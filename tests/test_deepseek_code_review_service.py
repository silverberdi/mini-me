"""Operational, no-network tests for candidate-bound DeepSeek CODE_REVIEW."""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from minime.adapters import provider_adapter
from minime.adapters.provider_adapter import (
    CapacityObservation,
    DeepSeekProviderAdapter,
)
from minime.config import AppConfig, ProjectConfig, ProviderConfig
from minime.domain.enums import (
    CapacitySignalSource,
    JobStatus,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.models import (
    CandidateAuthorship,
    CheckResult,
    Job,
    OpenRouterPricingSnapshot,
    OperatorActionRequest,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
)
from minime.services import control_plane_service
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.contract_review_service import (
    DeepSeekResponseDiagnostics,
    DeepSeekReviewResponse,
)
from minime.services.deepseek_code_review_service import DeepSeekCodeReviewService
from minime.services.provider_health_service import ProviderHealthService


class _AccountAdapter(DeepSeekProviderAdapter):
    def __init__(self, *, available: bool = True):
        super().__init__()
        self.available = available
        self.capacity_reads = 0

    async def check_model_supported(self, model: str, effort=None, timeout_seconds=10.0):
        return (model == "deepseek-flash" and effort == "low", None)

    async def read_capacity_observation(self, timeout_seconds=10.0, selected_model=None):
        self.capacity_reads += 1
        now = datetime.now(UTC)
        return CapacityObservation(
            provider="deepseek",
            ordinary_usage_allowed=self.available,
            observed_at=now,
            expires_at=now + timedelta(seconds=60),
            source_signal=CapacitySignalSource.DEEPSEEK_ACCOUNT_BALANCE,
            account_id=self.account_fingerprint,
            model=selected_model,
            quota_scope="deepseek_direct_account_balance",
        )


class _ReviewRunner:
    model = "deepseek-flash"
    effort = "low"
    review_stage = "CODE_REVIEW"

    def __init__(self, *, content: str | None = None):
        self.calls = 0
        self.request: str | None = None
        self.content = content or json.dumps(
            {
                "verdict": "READY_TO_MERGE",
                "summary": "Candidate and checks reviewed.",
                "findings": [],
            }
        )

    async def review(self, request: str, timeout_seconds: int):
        self.calls += 1
        self.request = request
        assert timeout_seconds > 0
        return DeepSeekReviewResponse(
            0,
            self.content,
            self.model,
            20,
            9,
            response_diagnostics=DeepSeekResponseDiagnostics(
                http_status=200,
                returned_model=self.model,
                model_matches_request=True,
                choices_count=1,
                finish_reason="stop",
                content_present=True,
                content_type="str",
                content_length=len(self.content),
                usage_present=True,
                prompt_tokens=20,
                completion_tokens=9,
                total_tokens=29,
                usage_valid=True,
            ),
        )


async def _fixture(
    tmp_path: Path, monkeypatch, uow, *, available: bool = True, runner=None, authorize=True
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-direct-account-key")
    project_id = "code-review-project"
    change_name = "candidate-change"
    project = Project(
        project_id=project_id,
        display_name="Code review fixture",
        repository="owner/repo",
        openspec_path="openspec",
        external_providers_allowed=["codex", "antigravity", "deepseek"],
    )
    app_config = AppConfig(
        providers={
            "deepseek": ProviderConfig(
                type="api",
                enabled=True,
                # Test-only owner policy exercising optional bounded reservations.
                budget={
                    "maximum_contract_review_usd": "0.50",
                    "maximum_code_review_usd": "1.00",
                    "maximum_combined_review_usd": "1.50",
                },
            )
        },
        projects={
            project_id: ProjectConfig(
                repository="owner/repo",
                openspec_path="openspec",
                external_providers_allowed=["codex", "antigravity", "deepseek"],
            )
        },
    )
    repo = tmp_path / "candidate"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    source = repo / "slug.py"
    source.write_text("def normalize_slug(value):\n    return value.lower()\n", encoding="utf-8")
    readme = repo / "README.md"
    readme.write_text("# Candidate source context\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "slug.py", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "candidate"], check=True)
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    base_sha = "base-candidate-fixture"

    job = Job(
        project_id=project_id,
        change_name=change_name,
        status=JobStatus.CHECKS_PASSED,
        base_sha=base_sha,
        candidate_sha=sha,
        current_executor="codex",
        implementer_role="codex",
    )
    run = OrchestrationRun(
        project_id=project_id,
        change_name=change_name,
        base_sha=base_sha,
        active_job_id=job.job_id,
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        current_generation=1,
        current_candidate_sha=sha,
    )
    manifest = CandidateManifestService().generate_manifest(repo, sha, job.job_id)
    candidate = OrchestrationCandidate(
        run_id=run.run_id,
        generation=1,
        base_sha=base_sha,
        candidate_sha=sha,
        candidate_ref="refs/heads/minime/candidate",
        manifest_id=manifest.manifest_id,
        manifest_hash=manifest.manifest_hash,
        is_frozen=True,
    )
    uow.projects.save(project)
    uow.jobs.save(job)
    uow.orchestration_runs.save(run)
    uow.candidate_manifests.save(manifest)
    uow.orchestration_candidates.save(candidate)
    uow.check_results.save(
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest -q",
            exit_code=0,
            duration_ms=12,
            output_snippet="1 passed",
            candidate_sha=sha,
            candidate_generation=1,
        )
    )

    adapter = _AccountAdapter(available=available)
    monkeypatch.setitem(provider_adapter._ADAPTER_REGISTRY, "deepseek", adapter)
    pricing = OpenRouterPricingSnapshot(
        id="deepseek-code-review-price",
        canonical_model_identity="deepseek-flash",
        routed_model_identity="deepseek-flash",
        prompt_price_per_token=Decimal("0.000001"),
        output_price_per_token=Decimal("0.000001"),
        additional_cost_per_request=Decimal("0"),
        currency="USD",
        source="deepseek_official_pricing",
        provider="deepseek",
        account_fingerprint=adapter.account_fingerprint,
        billing_origin="deepseek_direct",
    )
    uow.pricing_snapshots.save(pricing)
    monkeypatch.setattr(control_plane_service, "load_config", lambda: app_config)
    monkeypatch.setenv("MINIME_TEST_DISABLE_REAL_PROVIDER", "1")
    request = OperatorActionRequest(
        action_request_id="authorize-code-review-001",
        project_id=project_id,
        change_name=change_name,
        run_id=run.run_id,
        action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
        parameters={
            "max_spend_usd": "0.50",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            "pricing_snapshot_id": pricing.snapshot_id,
        },
        actor_identity="test-operator",
        expected_stage=run.current_stage,
        expected_generation=run.current_generation,
        expected_candidate_sha=sha,
    )
    authorization = (
        await asyncio.to_thread(
            control_plane_service.ControlPlaneService(uow, project_root=tmp_path).execute_action,
            request,
        )
        if authorize
        else None
    )
    service = DeepSeekCodeReviewService(
        uow,
        health_service=ProviderHealthService(uow),
        app_config=app_config,
        runner=runner or _ReviewRunner(),
    )
    return project, run, job, candidate, manifest, repo, adapter, pricing, authorization, service


@pytest.mark.asyncio
async def test_code_review_owner_policy_dispatches_bound_candidate_without_per_call_auth(
    in_memory_uow, monkeypatch, tmp_path
):
    runner = _ReviewRunner()
    project, run, job, candidate, manifest, repo, adapter, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow, runner=runner, authorize=False
    )
    assert auth is None
    result = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={"is_mixed_authorship": False, "surviving_contributions": []},
    )
    assert result.accepted
    assert result.verdict and result.verdict.verdict == ReviewVerdict.READY_TO_MERGE
    assert runner.calls == 1
    payload = json.loads(runner.request or "{}")
    assert payload["candidate_sha"] == candidate.candidate_sha
    assert payload["manifest_hash"] == manifest.manifest_hash
    assert any("def normalize_slug" in item["content"] for item in payload["files"])
    review = in_memory_uow.reviews.get_by_id(result.review_id)
    assert review and review.review_stage == "CODE_REVIEW"
    assert review.provider == "deepseek" and review.billing_origin == "deepseek_direct"
    assert review.candidate_sha == candidate.candidate_sha
    reservation = in_memory_uow.budget_reservations.get_by_id(review.budget_reservation_id)
    assert reservation and reservation.stage == "REVIEW" and reservation.status == "SETTLED"
    assert reservation.authorization_id is None
    assert reservation.provider == "deepseek" and reservation.billing_origin == "deepseek_direct"
    assert adapter.capacity_reads == 1


@pytest.mark.asyncio
async def test_code_review_without_optional_limit_records_idempotent_usage(
    in_memory_uow, monkeypatch, tmp_path
):
    runner = _ReviewRunner()
    project, run, job, candidate, manifest, repo, _, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow, runner=runner, authorize=False
    )
    service.app_config.providers["deepseek"].budget = {}
    result = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    assert auth is None and result.accepted and runner.calls == 1
    review = in_memory_uow.reviews.get_by_id(result.review_id)
    assert review.budget_reservation_id is None
    assert review.budget_authorization_id is None
    entries = in_memory_uow.budget_ledger.list_by_project(project.project_id)
    assert len(entries) == 1 and entries[0].entry_type == "USAGE"
    assert entries[0].stage == "REVIEW" and entries[0].billing_origin == "deepseek_direct"
    replay = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    assert replay.accepted and replay.review_id == result.review_id
    assert runner.calls == 1
    assert len(in_memory_uow.budget_ledger.list_by_project(project.project_id)) == 1


@pytest.mark.asyncio
async def test_contract_review_authorization_is_not_used_as_code_review_budget_authority(
    in_memory_uow, monkeypatch, tmp_path
):
    project, run, job, candidate, manifest, repo, _, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow
    )
    assert auth.status == OperatorActionStatus.COMPLETED
    code_auth = in_memory_uow.operator_actions.get_by_request_id(auth.action_request_id)
    code_auth.action_type = OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW
    in_memory_uow.operator_actions.save(code_auth)
    in_memory_uow.commit()
    result = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    assert result.accepted
    assert service.runner.calls == 1
    review = in_memory_uow.reviews.get_by_id(result.review_id)
    reservation = in_memory_uow.budget_reservations.get_by_id(review.budget_reservation_id)
    assert review.review_stage == "CODE_REVIEW"
    assert reservation.stage == "REVIEW"
    assert reservation.authorization_id is None


@pytest.mark.asyncio
async def test_unavailable_capacity_and_dirty_candidate_wait_without_dispatch(
    in_memory_uow, monkeypatch, tmp_path
):
    runner = _ReviewRunner()
    project, run, job, candidate, manifest, repo, _, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow, available=False, runner=runner
    )
    assert auth.status == OperatorActionStatus.COMPLETED
    result = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    assert not result.accepted and result.waiting
    assert result.reason == "DEEPSEEK_CODE_REVIEW_CAPACITY_UNKNOWN_OR_EXHAUSTED"
    assert runner.calls == 0

    # Candidate integrity is checked before provider capacity or any reservation.
    (repo / "slug.py").write_text("# changed after freeze\n", encoding="utf-8")
    denied = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    assert not denied.accepted and not denied.waiting
    assert denied.reason.startswith("CODE_REVIEW_PREFLIGHT_BLOCKED:")
    assert runner.calls == 0


@pytest.mark.asyncio
async def test_candidate_bound_review_checkpoint_is_not_dispatched_twice(
    in_memory_uow, monkeypatch, tmp_path
):
    runner = _ReviewRunner()
    project, run, job, candidate, manifest, repo, _, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow, runner=runner
    )
    assert auth.status == OperatorActionStatus.COMPLETED
    kwargs = dict(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    first = await service.review_candidate(**kwargs)
    assert first.accepted and runner.calls == 1
    review = in_memory_uow.reviews.get_by_id(first.review_id)
    assert review.status == ReviewStatus.REVIEW_RUNNING
    assert review.verdict == ReviewVerdict.READY_TO_MERGE
    second = await service.review_candidate(**kwargs)
    assert second.accepted and second.review_id == first.review_id
    assert runner.calls == 1

    from minime.services.authorship_service import AuthorshipService
    from minime.services.review_evidence import validate_review_authority

    in_memory_uow.reviews.transition(
        first.review_id,
        ReviewStatus.REVIEW_COMPLETED.value,
        verdict=ReviewVerdict.READY_TO_MERGE.value,
        summary=first.verdict.summary,
    )
    in_memory_uow.commit()
    valid, verdict, reason = validate_review_authority(
        in_memory_uow, run, job, candidate, AuthorshipService()
    )
    assert valid and verdict == ReviewVerdict.READY_TO_MERGE and reason is None


@pytest.mark.asyncio
async def test_incomplete_manifest_and_reviewer_authorship_are_rejected_before_reservation(
    in_memory_uow, monkeypatch, tmp_path
):
    project, run, job, candidate, manifest, repo, _, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow
    )
    assert auth.status == OperatorActionStatus.COMPLETED
    incomplete = manifest.model_copy(
        update={
            "tracked_files": manifest.tracked_files[:1],
            "manifest_hash": "e" * 64,
        }
    )
    forged_candidate = candidate.model_copy(update={"manifest_hash": incomplete.manifest_hash})
    denied = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=forged_candidate,
        manifest=incomplete,
        candidate_worktree=repo,
        authorship_evidence={"is_mixed_authorship": False},
    )
    assert not denied.accepted and denied.reason.startswith("CODE_REVIEW_PREFLIGHT_BLOCKED:")
    assert service.runner.calls == 0
    assert in_memory_uow.budget_reservations.list_by_project(project.project_id) == []

    in_memory_uow.candidate_authorships.save(
        CandidateAuthorship(
            job_id=job.job_id,
            agent_role="deepseek",
            model_identity="deepseek-flash",
            attempt_number=1,
            files_touched=["slug.py"],
            is_primary_author=False,
        )
    )
    denied = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        # Caller-provided evidence is ignored; independence comes from durable authorship.
        authorship_evidence={"is_mixed_authorship": False, "surviving_contributions": []},
    )
    assert not denied.accepted and "REVIEWER_NOT_INDEPENDENT" in denied.reason
    assert service.runner.calls == 0
    assert in_memory_uow.budget_reservations.list_by_project(project.project_id) == []


@pytest.mark.asyncio
async def test_ambiguous_dispatch_is_not_replayed_or_reserved_twice(
    in_memory_uow, monkeypatch, tmp_path
):
    class AmbiguousRunner(_ReviewRunner):
        async def review(self, request: str, timeout_seconds: int):
            self.calls += 1
            raise TimeoutError("response lost after request dispatch")

    runner = AmbiguousRunner()
    project, run, job, candidate, manifest, repo, _, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow, runner=runner
    )
    assert auth.status == OperatorActionStatus.COMPLETED
    kwargs = dict(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    first = await service.review_candidate(**kwargs)
    assert not first.accepted and first.reason == "CODE_REVIEW_OUTCOME_AMBIGUOUS:TimeoutError"
    reservations = in_memory_uow.budget_reservations.list_by_project(project.project_id)
    assert len(reservations) == 1 and reservations[0].status == "UNRESOLVED"
    second = await service.review_candidate(**kwargs)
    assert not second.accepted and "CHECKPOINT_EXISTS" in second.reason
    assert runner.calls == 1
    assert in_memory_uow.budget_reservations.list_by_project(project.project_id) == reservations


@pytest.mark.asyncio
async def test_code_review_excludes_unchanged_static_documentation_and_reduces_tokens(
    in_memory_uow, monkeypatch, tmp_path
):
    runner = _ReviewRunner()
    project, run, job, candidate, manifest, repo, _, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow, runner=runner
    )

    # Commit large static documentation in base branch
    docs_dir = repo / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    for i in range(10):
        (docs_dir / f"manual_{i}.md").write_text("# Extensive Manual\n" + ("Lorem ipsum dolor sit amet. " * 300), encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "docs"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "add docs"], check=True)
    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    # Now make small functional change in candidate
    (repo / "feature.py").write_text("def my_feature():\n    return 42\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "feature.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "feat: my feature"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    # Generate new manifest and update candidate/run/job
    manifest = CandidateManifestService().generate_manifest(repo, candidate_sha, job.job_id)
    candidate.base_sha = base_sha
    candidate.candidate_sha = candidate_sha
    candidate.manifest_id = manifest.manifest_id
    candidate.manifest_hash = manifest.manifest_hash
    run.base_sha = base_sha
    run.current_candidate_sha = candidate_sha
    job.base_sha = base_sha
    job.candidate_sha = candidate_sha
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.candidate_manifests.save(manifest)
    in_memory_uow.orchestration_candidates.save(candidate)
    in_memory_uow.check_results.save(
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest -q",
            exit_code=0,
            duration_ms=12,
            output_snippet="1 passed",
            candidate_sha=candidate_sha,
            candidate_generation=candidate.generation,
        )
    )

    result = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    assert result.accepted
    payload = json.loads(runner.request or "{}")

    # The payload MUST include the modified feature.py and git diff
    paths_in_payload = {item["path"] for item in payload.get("files", [])}
    assert "feature.py" in paths_in_payload
    assert "git_diff" in payload
    assert "def my_feature" in payload["git_diff"]

    # Large unchanged docs MUST be excluded from the review files payload
    for i in range(10):
        assert f"docs/manual_{i}.md" not in paths_in_payload

    # Manifest hash remains full-tree bound
    assert payload["manifest_hash"] == manifest.manifest_hash
    # Prompt payload is compact (under 5,000 tokens ≈ under 20,000 characters)
    assert len(runner.request or "") < 20000


@pytest.mark.asyncio
async def test_code_review_unconditionally_includes_security_policy_modifications(
    in_memory_uow, monkeypatch, tmp_path
):
    runner = _ReviewRunner()
    project, run, job, candidate, manifest, repo, _, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow, runner=runner
    )

    # Base commit with an agent skill policy
    agent_dir = repo / ".agent" / "skills" / "security"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "SKILL.md").write_text("# Safe Security Policy\nenforce_safe = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".agent"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base security policy"], check=True)
    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    # Adversarial change: modifies agent security policy
    (agent_dir / "SKILL.md").write_text("# Bypassed Security Policy\nenforce_safe = False\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".agent"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "evil security tweak"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    manifest = CandidateManifestService().generate_manifest(repo, candidate_sha, job.job_id)
    candidate.base_sha = base_sha
    candidate.candidate_sha = candidate_sha
    candidate.manifest_id = manifest.manifest_id
    candidate.manifest_hash = manifest.manifest_hash
    run.base_sha = base_sha
    run.current_candidate_sha = candidate_sha
    job.base_sha = base_sha
    job.candidate_sha = candidate_sha
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.candidate_manifests.save(manifest)
    in_memory_uow.orchestration_candidates.save(candidate)
    in_memory_uow.check_results.save(
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest -q",
            exit_code=0,
            duration_ms=12,
            output_snippet="1 passed",
            candidate_sha=candidate_sha,
            candidate_generation=candidate.generation,
        )
    )

    result = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    assert result.accepted
    payload = json.loads(runner.request or "{}")

    # .agent/skills/security/SKILL.md MUST be included unconditionally!
    paths_in_payload = {item["path"] for item in payload.get("files", [])}
    assert ".agent/skills/security/SKILL.md" in paths_in_payload
    assert "enforce_safe = False" in payload["git_diff"]


@pytest.mark.asyncio
async def test_code_review_redacts_secrets_in_git_diff(
    in_memory_uow, monkeypatch, tmp_path
):
    runner = _ReviewRunner()
    project, run, job, candidate, manifest, repo, _, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow, runner=runner
    )

    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    # Commit with a secret token in diff
    secret_line = 'API_SECRET = "sk-ant-api03-1234567890abcdef1234567890abcdef12345678"\n'
    (repo / "client.py").write_text(secret_line, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "client.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "add client"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    manifest = CandidateManifestService().generate_manifest(repo, candidate_sha, job.job_id)
    candidate.base_sha = base_sha
    candidate.candidate_sha = candidate_sha
    candidate.manifest_id = manifest.manifest_id
    candidate.manifest_hash = manifest.manifest_hash
    run.base_sha = base_sha
    run.current_candidate_sha = candidate_sha
    job.base_sha = base_sha
    job.candidate_sha = candidate_sha
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.candidate_manifests.save(manifest)
    in_memory_uow.orchestration_candidates.save(candidate)
    in_memory_uow.check_results.save(
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest -q",
            exit_code=0,
            duration_ms=10,
            output_snippet="1 passed",
            candidate_sha=candidate_sha,
            candidate_generation=candidate.generation,
        )
    )

    result = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    assert result.accepted
    payload = json.loads(runner.request or "{}")

    # The raw secret token MUST be redacted from git_diff
    diff_text = payload.get("git_diff", "")
    assert "sk-ant-api03-1234567890abcdef1234567890abcdef12345678" not in diff_text
    assert "[REDACTED" in diff_text
    # But structural modification remains intact
    assert "API_SECRET" in diff_text


@pytest.mark.asyncio
async def test_code_review_fails_closed_when_git_diff_exceeds_bound(
    in_memory_uow, monkeypatch, tmp_path
):
    import minime.services.deepseek_code_review_service as dcrs

    runner = _ReviewRunner()
    project, run, job, candidate, manifest, repo, _, _, auth, service = await _fixture(
        tmp_path, monkeypatch, in_memory_uow, runner=runner
    )

    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    (repo / "large.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "large.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "add large"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    manifest = CandidateManifestService().generate_manifest(repo, candidate_sha, job.job_id)
    candidate.base_sha = base_sha
    candidate.candidate_sha = candidate_sha
    candidate.manifest_id = manifest.manifest_id
    candidate.manifest_hash = manifest.manifest_hash
    run.base_sha = base_sha
    run.current_candidate_sha = candidate_sha
    job.base_sha = base_sha
    job.candidate_sha = candidate_sha
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.candidate_manifests.save(manifest)
    in_memory_uow.orchestration_candidates.save(candidate)
    in_memory_uow.check_results.save(
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest -q",
            exit_code=0,
            duration_ms=10,
            output_snippet="1 passed",
            candidate_sha=candidate_sha,
            candidate_generation=candidate.generation,
        )
    )

    # Set diff bound artificially low to trigger fail-closed behavior
    monkeypatch.setattr(dcrs, "MAX_REVIEW_DIFF_BYTES", 10)

    result = await service.review_candidate(
        project=project,
        run=run,
        job=job,
        candidate=candidate,
        manifest=manifest,
        candidate_worktree=repo,
        authorship_evidence={},
    )
    # Must fail closed without silent truncation
    assert result.accepted is False
    assert result.reason == "CODE_REVIEW_PREFLIGHT_BLOCKED:ValueError"


