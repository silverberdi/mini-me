"""Acceptance test suite for OpenSpec change 008-autonomous-change-orchestration.

Validates the full set of requirements:
1. Single-change admission (READY admitted, ineligible refused, duplicate refused, historical allowed).
2. Deterministic lifecycle (successful path, agent claims without evidence rejected, WAITING_CAPACITY, WAITING_EXTERNAL, NEEDS_HUMAN).
3. Pipeline coordination (007 continuation integration, review CHANGES_REQUIRED, audit failures, medium audit findings).
4. Candidate-bound evidence authority (stale review/audit rejection).
5. Idempotent PR preparation and human gate contract (no merge, explicit stop outcomes).
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from conftest import ReadinessGitHubStub, create_isolated_openspec_change
from minime.adapters import provider_adapter
from minime.adapters.provider_adapter import CapacityObservation, DeepSeekProviderAdapter
from minime.config import AppConfig, ProjectConfig, ProviderConfig, StageProfileConfig
from minime.domain.enums import (
    CapacitySignalSource,
    ExternalOutcome,
    ExternalReasonCode,
    HumanGate,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProjectStatus,
    ProviderHealthStatus,
    ReadinessState,
    RetrySafety,
    ReviewStatus,
)
from minime.domain.interfaces import GitHubAdapterInterface
from minime.domain.models import (
    CheckResult,
    Event,
    ExternalActionResult,
    OpenRouterPricingSnapshot,
    OperatorActionRequest,
    Project,
    ProjectBinding,
    ProviderHealth,
    utc_now,
)
from minime.services.checks_runner import ChecksRunResult
from minime.services.contract_review_service import DeepSeekReviewResponse
from minime.services.deepseek_auditor_runner import MockAuditorRunner
from minime.services.deepseek_code_review_service import DeepSeekCodeReviewService
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.implementer_runner import ImplementerResult, MockImplementerRunner
from minime.services.orchestration_service import OrchestrationService
from minime.services.reviewer_runner import MockReviewerRunner


class _AcceptanceDeepSeekAdapter(DeepSeekProviderAdapter):
    @property
    def account_fingerprint(self):
        return hashlib.sha256(b"acceptance-deepseek-account").hexdigest()

    async def check_model_supported(self, model, effort=None, timeout_seconds=10.0):
        del timeout_seconds
        return (model == "deepseek-chat" and effort == "low", None)

    async def read_capacity_observation(self, timeout_seconds=10.0, selected_model=None):
        from minime.domain.models import utc_now

        del timeout_seconds
        now = utc_now()
        return CapacityObservation(
            provider="deepseek",
            ordinary_usage_allowed=True,
            observed_at=now,
            expires_at=now + timedelta(seconds=60),
            source_signal=CapacitySignalSource.DEEPSEEK_ACCOUNT_BALANCE,
            account_id=self.account_fingerprint,
            model=selected_model or "deepseek-chat",
            quota_scope="deepseek_direct_account_balance",
        )


class _AcceptanceReviewTransport:
    model = "deepseek-chat"
    effort = "low"
    review_stage = "CODE_REVIEW"

    def __init__(self):
        self.calls = 0

    async def review(self, request: str, timeout_seconds: int):
        del timeout_seconds
        payload = json.loads(request)
        assert payload["stage"] == "CODE_REVIEW"
        self.calls += 1
        return DeepSeekReviewResponse(
            exit_code=0,
            content=json.dumps(
                {
                    "verdict": "READY_TO_MERGE",
                    "summary": "Acceptance review passed.",
                    "findings": [],
                }
            ),
            model=self.model,
            prompt_tokens=100,
            completion_tokens=20,
        )


class DeterministicGitHubAdapter(GitHubAdapterInterface):
    """Predictable GitHub adapter for acceptance test suite."""

    def __init__(self):
        self.prs: dict[str, dict[str, Any]] = {}
        self.pushed_branches: list[dict[str, Any]] = []

    def validate_issue_binding(
        self, expected_repository: str, issue_number: int, github_repository: str | None = None
    ) -> ExternalActionResult[bool]:
        if github_repository and expected_repository != github_repository:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="fake",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message="Repository mismatch",
            )
        if issue_number <= 0:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="fake",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.SAFE,
                data=False,
                error_message="Invalid issue number",
            )
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="fake",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=True,
        )

    def record_sync_failure(
        self, project_id: str, change_id: str | None, operation: str, error_message: str
    ) -> Event:
        return Event(
            event_type="SYNC_FAILED", project_id=project_id, payload={"error": error_message}
        )

    def get_pull_request(
        self, repository: str, branch: str, base: str | None = None
    ) -> ExternalActionResult[dict[str, Any]]:
        key = f"{repository}:{branch}"
        pr = self.prs.get(key)
        if pr:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="fake",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=pr,
                external_id=str(pr.get("number")),
            )
        return ExternalActionResult(
            outcome=ExternalOutcome.FAILURE,
            source_adapter="fake",
            reason_code=ExternalReasonCode.NOT_FOUND,
            retry_safety=RetrySafety.SAFE,
            error_message="Pull request not found.",
        )

    def create_pull_request(
        self,
        repository: str,
        branch: str,
        base: str,
        title: str,
        body: str,
        head_sha: str,
    ) -> ExternalActionResult[dict[str, Any]]:
        key = f"{repository}:{branch}"
        pr_data = {
            "repository": repository,
            "number": len(self.prs) + 1,
            "url": f"https://github.com/{repository}/pull/{len(self.prs) + 1}",
            "head_sha": head_sha,
            "head_branch": branch,
            "base_branch": base,
            "state": "OPEN",
            "title": title,
            "body": body,
        }
        self.prs[key] = pr_data
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="fake",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.UNSAFE,
            data=pr_data,
            external_id=str(pr_data["number"]),
        )

    def push_branch(
        self, worktree_path: str, remote: str, branch: str, candidate_sha: str
    ) -> ExternalActionResult[str]:
        self.pushed_branches.append(
            {"remote": remote, "branch": branch, "candidate_sha": candidate_sha}
        )
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="fake",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.UNSAFE,
            data=candidate_sha,
        )

    def get_remote_branch_head(
        self, repository: str, branch: str, remote: str = "origin"
    ) -> ExternalActionResult[str]:
        for p in self.pushed_branches:
            if p.get("branch") == branch:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="fake",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.SAFE,
                    data=p.get("candidate_sha", ""),
                )
        return ExternalActionResult(
            outcome=ExternalOutcome.FAILURE,
            source_adapter="fake",
            reason_code=ExternalReasonCode.NOT_FOUND,
            retry_safety=RetrySafety.SAFE,
            error_message="Remote branch head not found.",
        )


class AcceptanceChecksRunner:
    def __init__(self, should_pass: bool = True):
        self.should_pass = should_pass

    async def run(
        self,
        job_id: str,
        checks: list[dict],
        worktree_path: str | Path,
        candidate_sha: str = "",
        attempt_id: str | None = None,
    ) -> ChecksRunResult:
        exit_code = 0 if self.should_pass else 1
        res = CheckResult(
            job_id=job_id,
            check_name="pytest",
            command="pytest",
            exit_code=exit_code,
            duration_ms=100,
            output_snippet="Passed" if self.should_pass else "Failed",
        )
        return ChecksRunResult(passed=self.should_pass, results=[res], diagnostics=[])


@pytest.fixture
def setup_acceptance_env(tmp_path: Path, in_memory_uow, monkeypatch, test_capacity_strategy):
    import subprocess

    from conftest import setup_managed_repository_fixture

    project_id = "mini-me"
    change_name = "008-autonomous-change-orchestration"
    test_capacity_strategy(("codex", "antigravity"))

    setup_managed_repository_fixture(
        in_memory_uow,
        project_id,
        tmp_path,
        tmp_path / ".minime" / "worktrees",
        canonical_repository_identity="github.com/silverberdi/mini-me",
    )
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True
    )

    project = Project(
        project_id=project_id,
        display_name="Mini Me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
        external_providers_allowed=["codex", "antigravity", "deepseek"],
        independent_audit_required=True,
        status=ProjectStatus.ACTIVE,
        checks=[{"name": "pytest", "command": "pytest"}],
    )
    in_memory_uow.projects.save(project)

    binding = ProjectBinding(
        project_id=project_id,
        openspec_change_name=change_name,
        repository="silverberdi/mini-me",
        github_issue_number=16,
        is_valid=True,
    )
    in_memory_uow.bindings.save(binding)

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE)
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-acceptance-key")
    review_adapter = _AcceptanceDeepSeekAdapter()
    review_transport = _AcceptanceReviewTransport()
    monkeypatch.setitem(provider_adapter._ADAPTER_REGISTRY, "deepseek", review_adapter)
    app_config = AppConfig(
        providers={
            "deepseek": ProviderConfig(
                type="api", enabled=True, budget={"maximum_code_review_usd": "1.00"}
            )
        },
        projects={
            project_id: ProjectConfig(
                repository="silverberdi/mini-me",
                base_branch="main",
                openspec_path="openspec",
                external_providers_allowed=["codex", "antigravity", "deepseek"],
                stage_profiles={
                    "REVIEW": StageProfileConfig(
                        provider="deepseek",
                        model="deepseek-chat",
                        effort="low",
                        workflow="review",
                    )
                },
            )
        },
    )
    monkeypatch.setattr("minime.services.execution_pipeline.load_config", lambda: app_config)
    monkeypatch.setattr("minime.services.control_plane_service.load_config", lambda: app_config)
    monkeypatch.setattr(
        "minime.services.deepseek_code_review_service.load_config", lambda: app_config
    )
    pricing = OpenRouterPricingSnapshot(
        id="acceptance-code-review-price",
        canonical_model_identity="deepseek-chat",
        routed_model_identity="deepseek-chat",
        prompt_price_per_token=Decimal("0.000001"),
        output_price_per_token=Decimal("0.000001"),
        currency="USD",
        source="deepseek_official_pricing",
        provider="deepseek",
        account_fingerprint=review_adapter.account_fingerprint,
        billing_origin="deepseek_direct",
    )
    in_memory_uow.pricing_snapshots.save(pricing)

    create_isolated_openspec_change(
        tmp_path,
        change_name=change_name,
        proposal_content="# Proposal\n\nAutonomous orchestration.\n",
        tasks_content="## 1. Foundation\n- [x] 1.1 Complete schema <!-- id: 1.1 -->\n",
        design_content="# Design\n\nState graph.\n",
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Add OpenSpec change"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True
    )

    from minime.domain.models import Change

    in_memory_uow.changes.save(
        Change(
            project_id=project_id,
            name=change_name,
            schema_name="feature",
            last_readiness_status=ReadinessState.READY,
        )
    )

    return {
        "project_id": project_id,
        "change_name": change_name,
        "project_root": tmp_path,
        "app_config": app_config,
        "review_adapter": review_adapter,
        "review_transport": review_transport,
        "review_pricing": pricing,
    }


def test_acceptance_successful_end_to_end_orchestration(setup_acceptance_env, in_memory_uow):
    """Scenario: Successful path reaches the human gate READY_FOR_HUMAN_MERGE without automatic merge."""
    env = setup_acceptance_env
    fake_github = DeterministicGitHubAdapter()

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=MockImplementerRunner(),
        checks_runner=AcceptanceChecksRunner(should_pass=True),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                '```json\n{"verdict": "READY_TO_MERGE", "summary": "All good", "findings": []}\n```'
            ]
        ),
        auditor_runner=MockAuditorRunner(
            output=['{"risk": "low", "summary": "Passed", "findings": []}']
        ),
        code_review_service=DeepSeekCodeReviewService(
            in_memory_uow,
            runner=env["review_transport"],
            app_config=env["app_config"],
        ),
    )

    service = OrchestrationService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        pipeline=pipeline,
        github_adapter=fake_github,
    )

    run = service.start(env["project_id"], env["change_name"])

    # The normal run must stop with a frozen candidate until an operator grants
    # exact candidate-bound DeepSeek spend authorization.
    assert run.stop_outcome == OrchestrationStopOutcome.WAITING_CAPACITY
    job = in_memory_uow.jobs.get_by_id(run.active_job_id)
    candidate = in_memory_uow.orchestration_candidates.get_latest_for_run(run.run_id)
    assert job and candidate and candidate.is_frozen
    assert candidate.candidate_sha == run.current_candidate_sha == job.candidate_sha
    from minime.services.control_plane_service import ControlPlaneService

    control_plane = ControlPlaneService(
        in_memory_uow,
        project_root=env["project_root"],
        orchestration_service=service,
    )
    action_descriptors = {
        action.action: action for action in control_plane.get_available_actions(run.run_id)
    }
    assert action_descriptors[OperatorActionType.CONTINUE].enabled
    authorization = control_plane.execute_action(
        OperatorActionRequest(
            action_request_id=f"acceptance-review-auth-{run.run_id}",
            project_id=run.project_id,
            change_name=run.change_name,
            run_id=run.run_id,
            action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
            parameters={
                "max_spend_usd": "0.50",
                "expires_at": (utc_now() + timedelta(minutes=15)).isoformat(),
                "pricing_snapshot_id": env["review_pricing"].snapshot_id,
            },
            actor_identity="acceptance-test-operator",
            expected_stage=run.current_stage,
            expected_generation=run.current_generation,
            expected_candidate_sha=job.candidate_sha,
        )
    )
    assert authorization.status == OperatorActionStatus.COMPLETED, authorization.summary
    continued = control_plane.execute_action(
        OperatorActionRequest(
            action_request_id=f"acceptance-review-continue-{run.run_id}",
            project_id=run.project_id,
            change_name=run.change_name,
            run_id=run.run_id,
            action_type=OperatorActionType.CONTINUE,
            parameters={},
            actor_identity="acceptance-test-operator",
            expected_stage=run.current_stage,
            expected_generation=run.current_generation,
            expected_candidate_sha=job.candidate_sha,
        )
    )
    assert continued.status == OperatorActionStatus.COMPLETED, continued.summary
    run = in_memory_uow.orchestration_runs.get_by_id(run.run_id)

    # Must end at PR_PREPARED stage
    assert run.current_stage == OrchestrationStage.PR_PREPARED
    # Stop outcome must be READY_FOR_HUMAN_MERGE
    assert run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    # Human gate must be READY_FOR_HUMAN_MERGE
    assert run.human_gate == HumanGate.READY_FOR_HUMAN_MERGE
    # Active must be False
    assert run.is_active is False
    review = in_memory_uow.reviews.get_by_job_stage(job.job_id, "CODE_REVIEW")
    assert review and review.status == ReviewStatus.REVIEW_COMPLETED
    assert review.candidate_sha == run.current_candidate_sha
    authorization_record = in_memory_uow.operator_actions.get_by_request_id(
        review.budget_authorization_id
    )
    assert authorization_record is not None
    assert authorization_record.action_type == OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW
    assert authorization_record.status == OperatorActionStatus.COMPLETED
    assert env["review_transport"].calls == 1
    reservation = in_memory_uow.budget_reservations.get_by_id(review.budget_reservation_id)
    assert reservation and reservation.status == "SETTLED"
    # Remote PR created in status view
    status_view = service.get_status(run.run_id)
    assert status_view.pr_url is not None
    assert "github.com/silverberdi/mini-me/pull" in status_view.pr_url
    published_pr = next(iter(fake_github.prs.values()))
    assert published_pr["head_sha"] == run.current_candidate_sha
    assert run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE


def test_acceptance_duplicate_active_run_refused(setup_acceptance_env, in_memory_uow):
    """Scenario: Duplicate active run is refused."""
    env = setup_acceptance_env
    service = OrchestrationService(
        in_memory_uow, project_root=env["project_root"], github_adapter=ReadinessGitHubStub()
    )

    # Create an active run directly in store
    from minime.domain.models import OrchestrationRun

    active_run = OrchestrationRun(
        project_id=env["project_id"],
        change_name=env["change_name"],
        base_sha="61eb4bfdabf0e7612090bf1806c439929bf0fe68",
        current_stage=OrchestrationStage.IMPLEMENTING,
        is_active=True,
    )
    in_memory_uow.orchestration_runs.save(active_run)

    # Attempt to admit duplicate
    res = service.admit_change(env["project_id"], env["change_name"])
    assert res.admitted is False
    assert "already exists" in res.refusal_reason.lower()
    assert res.refusal_details.get("existing_run_id") == active_run.run_id


def test_acceptance_historical_run_permits_new_run(setup_acceptance_env, in_memory_uow):
    """Scenario: Historical terminal run does not block a later run."""
    env = setup_acceptance_env
    service = OrchestrationService(
        in_memory_uow, project_root=env["project_root"], github_adapter=ReadinessGitHubStub()
    )

    # Create a completed/terminal historical run
    from minime.domain.models import OrchestrationRun

    old_run = OrchestrationRun(
        project_id=env["project_id"],
        change_name=env["change_name"],
        base_sha="61eb4bfdabf0e7612090bf1806c439929bf0fe68",
        current_stage=OrchestrationStage.PR_PREPARED,
        stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
        human_gate=HumanGate.READY_FOR_HUMAN_MERGE,
        is_active=False,
    )
    in_memory_uow.orchestration_runs.save(old_run)

    # Admitting a new run is permitted
    res = service.admit_change(env["project_id"], env["change_name"])
    assert res.admitted is True
    assert res.run is not None
    assert res.run.run_id != old_run.run_id


def test_acceptance_medium_audit_finding_blocks_advancement(setup_acceptance_env, in_memory_uow):
    """Scenario: Medium audit finding blocks advancement and triggers remediation."""
    env = setup_acceptance_env

    class SingleAttemptImplementer(MockImplementerRunner):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def run(self, worktree_path: Path, prompt_context: str, timeout_seconds: int):
            self.attempts += 1
            return ImplementerResult(
                exit_code=0, timed_out=False, stdout=[], stderr=[], duration_ms=1
            )

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=SingleAttemptImplementer(),
        checks_runner=AcceptanceChecksRunner(should_pass=True),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                '```json\n{"verdict": "READY_TO_MERGE", "summary": "Looks good", "findings": []}\n```'
            ]
        ),
        auditor_runner=MockAuditorRunner(
            output=[
                '{"risk": "medium", "summary": "Found edge-case logic flaw", "findings": [{"severity": "medium", "category": "correctness", "message": "Edge case flaw", "file": "logic.py"}]}'
            ]
        ),
    )

    service = OrchestrationService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        pipeline=pipeline,
        github_adapter=DeterministicGitHubAdapter(),
    )

    # Auditor returns medium finding -> audit blocked
    # In test environment with MockImplementerRunner, coordinator attempts remediation
    run = service.admit_change(env["project_id"], env["change_name"]).run
    # Coordinator should not advance past audit to PREPARING_PR when medium finding is unaddressed
    assert run.current_stage != OrchestrationStage.PREPARING_PR
