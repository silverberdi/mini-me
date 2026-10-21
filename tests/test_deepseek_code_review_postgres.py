"""PostgreSQL integration for the governed, candidate-bound DeepSeek code review."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from minime.adapters import provider_adapter
from minime.adapters.provider_adapter import DeepSeekProviderAdapter
from minime.config import AppConfig, ProjectConfig, ProviderConfig, StageProfileConfig
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ExecutionOutcome,
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    ExternalReasonCode,
    HumanGate,
    JobStatus,
    OperatorActionErrorCode,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProgressClassification,
    ReviewVerdict,
    WorktreeCreationState,
)
from minime.domain.models import (
    BudgetReservation,
    Change,
    CheckResult,
    ExternalActionResult,
    Job,
    JobAttempt,
    OpenRouterPricingSnapshot,
    OperatorActionRecord,
    OperatorActionRequest,
    OrchestrationCandidate,
    OrchestrationExternalAction,
    OrchestrationRun,
    OrchestrationWorktreeOwnership,
    Project,
    ProjectBinding,
    ProjectManagedRepositoryBinding,
)
from minime.services import control_plane_service
from minime.services.budget_service import BudgetService
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.contract_review_service import (
    DeepSeekContractReviewRunner,
)
from minime.services.deepseek_auditor_runner import AuditorResult
from minime.services.deepseek_code_review_service import (
    MAX_REVIEW_OUTPUT_TOKENS,
    DeepSeekCodeReviewService,
)
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.orchestration_service import OrchestrationService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.worktree_manager import WorktreeManager

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must target the isolated R01 disposable PostgreSQL database",
)


class _NoInferenceAuditor:
    """Deterministic local auditor for exercising the existing downstream gate."""

    def __init__(self, risk="low"):
        self.calls = 0
        self.risk = risk

    async def run(self, worktree_path, prompt_context, timeout_seconds):
        self.calls += 1
        assert worktree_path.exists()
        assert "candidate" in prompt_context.lower()
        assert timeout_seconds > 0
        return AuditorResult(
            exit_code=0,
            timed_out=False,
            output=[
                json.dumps(
                    {"risk": self.risk, "summary": "Deterministic audit result", "findings": []}
                )
            ],
            duration_ms=8,
        )


class _DeterministicGitHubAdapter:
    """Local-only downstream GitHub authority; never contacts GitHub."""

    def __init__(self):
        self.pushed: dict[str, str] = {}
        self.created_prs: list[dict[str, str]] = []

    def get_remote_branch_head(self, repository, branch, remote="origin"):
        sha = self.pushed.get(branch)
        if sha:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="test",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                data=sha,
            )
        return ExternalActionResult(
            outcome=ExternalOutcome.FAILURE,
            source_adapter="test",
            reason_code=ExternalReasonCode.NOT_FOUND,
        )

    def push_branch(self, worktree_path, remote, branch, candidate_sha):
        self.pushed[branch] = candidate_sha
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="test",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            data=candidate_sha,
        )

    def get_pull_request(self, repository, branch, base="main"):
        return ExternalActionResult(
            outcome=ExternalOutcome.FAILURE,
            source_adapter="test",
            reason_code=ExternalReasonCode.NOT_FOUND,
        )

    def create_pull_request(self, repository, branch, base, title, body, head_sha):
        result = {
            "repository": repository,
            "number": 901,
            "url": f"https://github.com/{repository}/pull/901",
            "head_sha": head_sha,
            "head_branch": branch,
            "base_branch": base,
            "state": "OPEN",
            "title": title,
            "body": body,
        }
        self.created_prs.append(result)
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="test",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            data=result,
            external_id=result["url"],
        )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _control_plane_request(
    *, project_id, change_name, run, action_type, action_id, params, candidate_sha=None
):
    return OperatorActionRequest(
        action_request_id=action_id,
        project_id=project_id,
        change_name=change_name,
        run_id=run.run_id,
        action_type=action_type,
        parameters=params,
        actor_identity="isolated-postgres-test-operator",
        expected_stage=run.current_stage,
        expected_generation=run.current_generation,
        expected_candidate_sha=candidate_sha,
    )


def test_postgres_dispatch_intent_survives_worker_restart_and_blocks_replay():
    """A committed review dispatch checkpoint is still non-replayable in a fresh UOW."""
    from minime.domain.enums import ExternalActionType
    from minime.domain.models import OrchestrationExternalAction
    from minime.services.recovery_convergence_service import RecoveryConvergenceService

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id = f"r01-crash-recovery-{uuid4()}"
    run_id = str(uuid4())
    action_key = f"deepseek-code-review-crash:{uuid4()}"
    change_name = "crash-after-review-dispatch-intent"
    try:
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            project = Project(
                project_id=project_id,
                display_name="Disposable review-dispatch restart test",
                repository="silverberdi/isolated-r01-dispatch-recovery-test",
                openspec_path="openspec",
                checks=[{"name": "pytest", "command": "pytest -q"}],
                base_branch="main",
            )
            run = OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name=change_name,
                base_sha="base-sha",
                current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
            )
            uow.projects.save(project)
            uow.orchestration_runs.save(run)
            uow.orchestration_external_actions.reserve(
                OrchestrationExternalAction(
                    run_id=run_id,
                    action_key=action_key,
                    action_type=ExternalActionType.DEEPSEEK_CODE_REVIEW_DISPATCH,
                    target_identity="deepseek:isolated-account:deepseek-flash:REVIEW",
                    request_fingerprint=f"fingerprint-{uuid4()}",
                    candidate_sha="frozen-candidate-sha",
                    generation=1,
                )
            )
            uow.commit()
            original_recovery = RecoveryConvergenceService(
                uow, owner_instance_id="review-dispatch-worker-before-crash"
            )
            original_claim = original_recovery.acquire_claim(f"run:{run_id}", lease_seconds=1)
            assert original_claim is not None
            original_intent = uow.claims.commit_fenced_dispatch_intent(
                claim_key=original_claim.claim_key,
                owner_instance_id=original_claim.owner_instance_id,
                fence_token=original_claim.fence_token,
                action_key=action_key,
                attempt_number=1,
            )
            session.close()

        # Model process death by abandoning the first UOW after the durable intent
        # and constructing a new UOW after its lease expires.
        time.sleep(1.1)
        with sessionmaker(
            bind=engine, autoflush=False, expire_on_commit=False
        )() as recovery_session:
            recovery_uow = PostgresPersistenceUnitOfWork(recovery_session)
            recovered_action = recovery_uow.orchestration_external_actions.get_by_action_key(
                action_key
            )
            persisted_attempts = recovery_uow.external_action_attempts.list_by_action_key(
                action_key
            )
            assert recovered_action is not None
            assert recovered_action.status.value == "EXECUTING"
            assert recovered_action.last_dispatch_intent_id == original_intent.attempt_id
            assert len(persisted_attempts) == 1
            assert persisted_attempts[0].status == "EXECUTING"

            recovered_claim = RecoveryConvergenceService(
                recovery_uow, owner_instance_id="review-dispatch-recovery-worker"
            ).acquire_claim(f"run:{run_id}", lease_seconds=30)
            assert recovered_claim is not None
            with pytest.raises(ValueError, match="Stage B/D authorization not proven"):
                recovery_uow.claims.commit_fenced_dispatch_intent(
                    claim_key=recovered_claim.claim_key,
                    owner_instance_id=recovered_claim.owner_instance_id,
                    fence_token=recovered_claim.fence_token,
                    action_key=action_key,
                    attempt_number=1,
                )
            assert len(recovery_uow.external_action_attempts.list_by_action_key(action_key)) == 1
            assert (
                recovery_uow.orchestration_external_actions.get_by_action_key(
                    action_key
                ).last_dispatch_intent_id
                == original_intent.attempt_id
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("delete from external_action_attempts where action_key = :action_key"),
                {"action_key": action_key},
            )
            connection.execute(
                text("delete from orchestration_external_actions where action_key = :action_key"),
                {"action_key": action_key},
            )
            connection.execute(
                text("delete from recovery_claims where claim_key = :claim_key"),
                {"claim_key": f"run:{run_id}"},
            )
            connection.execute(
                text("delete from orchestration_runs where id = :run_id"),
                {"run_id": run_id},
            )
            connection.execute(
                text("delete from projects where id = :project_id"),
                {"project_id": project_id},
            )
        engine.dispose()


@pytest.mark.parametrize(
    (
        "review_verdict",
        "audit_risk",
        "mutate_candidate_during_review",
        "missing_reservation_case",
        "terminal_recovery_case",
    ),
    [
        (ReviewVerdict.READY_TO_MERGE, "low", False, False, False),
        (ReviewVerdict.CHANGES_REQUIRED, "low", False, False, False),
        (ReviewVerdict.READY_TO_MERGE, "high", False, False, False),
        (ReviewVerdict.READY_TO_MERGE, "low", True, False, False),
        (ReviewVerdict.READY_TO_MERGE, "low", False, True, False),
        (ReviewVerdict.READY_TO_MERGE, "low", False, False, True),
    ],
    ids=[
        "ready",
        "changes-required",
        "audit-high",
        "candidate-mutated",
        "missing-reservation",
        "terminal-recovery",
    ],
)
def test_code_review_authorization_reservation_settlement_and_idempotency_in_postgres(
    tmp_path,
    monkeypatch,
    review_verdict,
    audit_risk,
    mutate_candidate_during_review,
    missing_reservation_case,
    terminal_recovery_case,
):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id = f"r01-code-review-{uuid4()}"
    change_name = "budgeted-review-candidate"
    account_key = "isolated-test-key-not-a-provider-credential"
    run_id = str(uuid4())
    job_id = str(uuid4())
    snapshot_id = str(uuid4())
    capacity_state_touched = False
    review_started = threading.Event()
    release_review = threading.Event()
    review_http_calls: list[dict[str, object]] = []
    terminal_response_sent = False

    # Exercise the production adapter and HTTP parsing, while every request is
    # answered by an in-process transport. No DeepSeek inference/network call occurs.
    def response_for(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == f"Bearer {account_key}"
        if request.url.path == "/models":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "deepseek-flash",
                            "effort": {"supported_levels": ["low", "medium", "high"]},
                        }
                    ]
                },
            )
        if request.url.path == "/user/balance":
            return httpx.Response(
                200,
                json={
                    "is_available": True,
                    "balance_infos": [{"currency": "USD", "total_balance": "100.00"}],
                },
            )
        if request.url.path == "/chat/completions":
            nonlocal terminal_response_sent
            payload = json.loads(request.content)
            assert payload["model"] == "deepseek-flash"
            assert payload["reasoning_effort"] == "low"
            assert payload["max_tokens"] == MAX_REVIEW_OUTPUT_TOKENS == 16384
            assert payload["response_format"] == {"type": "json_object"}
            assert any(
                message.get("role") == "user"
                and json.loads(message["content"])["stage"] == "CODE_REVIEW"
                for message in payload["messages"]
            )
            review_http_calls.append(payload)
            review_started.set()
            assert release_review.wait(timeout=10)
            if terminal_recovery_case and not terminal_response_sent:
                terminal_response_sent = True
                return httpx.Response(
                    200,
                    json={
                        "id": "intercepted-terminal-truncation",
                        "object": "chat.completion",
                        "model": "deepseek-flash",
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "reasoning_content": "private reasoning excluded from evidence",
                                },
                                "finish_reason": "length",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 2000,
                            "completion_tokens": MAX_REVIEW_OUTPUT_TOKENS,
                            "total_tokens": 2000 + MAX_REVIEW_OUTPUT_TOKENS,
                        },
                    },
                )
            if mutate_candidate_during_review:
                # Adversarially mutate the real registered Git worktree while
                # the intercepted provider response is in flight.
                (repo / "slug.py").write_text(
                    "def normalize_slug(value):\n    return 'mutated'\n", encoding="utf-8"
                )
            content = json.dumps(
                {
                    "verdict": review_verdict.value,
                    "summary": "Deterministic intercepted HTTP review",
                    "findings": []
                    if review_verdict == ReviewVerdict.READY_TO_MERGE
                    else [
                        {
                            "severity": "MAJOR",
                            "location": "src/module.py:1",
                            "violated_requirement": (
                                "The output must preserve the accepted input contract."
                            ),
                            "expected_correction": (
                                "Restore the accepted input validation before release."
                            ),
                        }
                    ],
                }
            )
            return httpx.Response(
                200,
                json={
                    "id": "disposable-intercepted-code-review",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 25,
                        "completion_tokens": 20,
                        "total_tokens": 45,
                    },
                },
            )
        return httpx.Response(404)

    original_async_client = httpx.AsyncClient

    def intercepted_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(response_for)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", intercepted_async_client)
    monkeypatch.setenv("DEEPSEEK_API_KEY", account_key)

    adapter = DeepSeekProviderAdapter()
    runner = DeepSeekContractReviewRunner(
        api_key=account_key,
        model="deepseek-flash",
        effort="low",
        review_stage="CODE_REVIEW",
        max_output_tokens=MAX_REVIEW_OUTPUT_TOKENS,
    )
    monkeypatch.setitem(provider_adapter._ADAPTER_REGISTRY, "deepseek", adapter)
    profile_common = {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "effort": "low",
    }
    project_config = ProjectConfig(
        repository="silverberdi/isolated-r01-budget-test",
        openspec_path="openspec",
        external_providers_allowed=["codex", "antigravity", "deepseek"],
        stage_profiles={
            "CONTRACT_REVIEW": StageProfileConfig(**profile_common, workflow="openspec-explore"),
            "REVIEW": StageProfileConfig(**profile_common, workflow="review"),
        },
    )
    budget_config = {
        "maximum_contract_review_usd": "0.50",
        "maximum_code_review_usd": "1.00",
        "maximum_combined_review_usd": "1.50",
    }
    app_config = AppConfig(
        providers={
            "deepseek": ProviderConfig(
                type="api", enabled=True, api_key_env="DEEPSEEK_API_KEY", budget=budget_config
            )
        },
        projects={project_id: project_config},
    )
    monkeypatch.setattr(control_plane_service, "load_config", lambda: app_config)
    monkeypatch.setenv("MINIME_TEST_DISABLE_REAL_PROVIDER", "1")

    # Conservative official peak/cache-miss pricing for deepseek-flash.
    # The values are per token: $0.30/M input and $1.20/M output.
    snapshot = OpenRouterPricingSnapshot(
        id=snapshot_id,
        canonical_model_identity="deepseek-flash",
        routed_model_identity="deepseek-flash",
        prompt_price_per_token=Decimal("0.00000030"),
        output_price_per_token=Decimal("0.00000120"),
        additional_cost_per_request=Decimal("0"),
        currency="USD",
        source="deepseek_official_pricing",
        provider="deepseek",
        account_fingerprint=adapter.account_fingerprint,
        billing_origin="deepseek_direct",
    )
    repository_identity = "github.com/silverberdi/isolated-r01-budget-test"
    managed_repo = tmp_path / "managed-repository"
    managed_repo.mkdir()
    shutil.copytree(
        Path(__file__).parent / "fixtures" / "r01-reviewed-candidate" / "openspec",
        managed_repo / "openspec",
    )
    worktree_parent = managed_repo / ".minime" / "worktrees"
    worktree_parent.mkdir(parents=True)
    (managed_repo / ".minime-managed-project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "canonical_repository_identity": repository_identity,
            }
        ),
        encoding="utf-8",
    )

    try:
        with engine.connect() as connection:
            parsed_test_url = make_url(DATABASE_URL)
            assert parsed_test_url.database and parsed_test_url.database.startswith("minime_")
            assert not (
                parsed_test_url.host == "192.168.0.194"
                and parsed_test_url.port == 5432
                and parsed_test_url.database == "minime"
            )
            assert connection.execute(text("select current_database()")).scalar() == (
                parsed_test_url.database
            )
            assert connection.execute(text("select version_num from alembic_version")).scalar() == (
                "r02_contract_review_budget_identity"
            )
            assert (
                connection.execute(
                    text("select count(*) from provider_health where provider = 'deepseek'")
                ).scalar()
                == 0
            )
            assert (
                connection.execute(
                    text("select count(*) from capacity_windows where provider = 'deepseek'")
                ).scalar()
                == 0
            )
            unique_indexes = set(
                connection.execute(
                    text(
                        "select indexname from pg_indexes "
                        "where schemaname = current_schema() "
                        "and indexdef ilike 'create unique index%'"
                    )
                ).scalars()
            )
            assert {
                "uq_budget_reservations_authorization_id",
                "uq_budget_reservations_idempotency_key",
                "uq_external_action_dispatch_intent",
                "ix_operator_action_records_action_request_id",
            } <= unique_indexes
            capacity_state_touched = True

        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            project = Project(
                project_id=project_id,
                display_name="Disposable DeepSeek code-review budget test",
                repository=project_config.repository,
                openspec_path="openspec",
                external_providers_allowed=project_config.external_providers_allowed,
                checks=[{"name": "pytest", "command": "pytest -q"}],
                base_branch="main",
                independent_audit_required=True,
            )
            project_binding = ProjectManagedRepositoryBinding(
                project_id=project_id,
                canonical_repository_identity=repository_identity,
                managed_repository_root=str(managed_repo),
                worktree_parent_dir=str(worktree_parent),
                default_base_branch="main",
            )
            change = Change(
                project_id=project_id,
                name=change_name,
                status=ChangeStatus.IN_PROGRESS,
            )
            github_binding = ProjectBinding(
                project_id=project_id,
                repository=project.repository,
                github_issue_number=17,
                openspec_change_name=change_name,
                is_valid=True,
            )
            job = Job(
                job_id=job_id,
                project_id=project_id,
                change_name=change_name,
                implementer_role="codex",
                current_executor="codex",
                base_sha="pending-base",
            )
            run = OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name=change_name,
                base_sha="pending-base",
                active_job_id=job_id,
                current_stage=OrchestrationStage.ADMITTED,
                current_generation=1,
            )
            uow.projects.save(project)
            uow.project_managed_repository_bindings.save(project_binding)
            uow.changes.save(change)
            uow.bindings.save(github_binding)
            uow.jobs.save(job)
            uow.orchestration_runs.save(run)
            uow.pricing_snapshots.save(snapshot)
            uow.commit()

            expiry = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
            contract_auth = control_plane_service.ControlPlaneService(
                uow, project_root=tmp_path
            ).execute_action(
                _control_plane_request(
                    project_id=project_id,
                    change_name=change_name,
                    run=run,
                    action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW,
                    action_id=f"contract-auth-{uuid4()}",
                    params={
                        "max_spend_usd": "0.50",
                        "expires_at": expiry,
                        "pricing_snapshot_id": snapshot_id,
                    },
                )
            )
            assert contract_auth.status == OperatorActionStatus.COMPLETED, contract_auth.summary

            _git(managed_repo, "init", "-q", "-b", "main")
            _git(managed_repo, "config", "user.email", "review-test@example.invalid")
            _git(managed_repo, "config", "user.name", "R01 budget integration")
            remote_url = "https://github.com/silverberdi/isolated-r01-budget-test.git"
            _git(
                managed_repo,
                "remote",
                "add",
                "origin",
                remote_url,
            )
            (managed_repo / "README.md").write_text("# isolated base\n", encoding="utf-8")
            _git(managed_repo, "add", "README.md")
            _git(managed_repo, "commit", "-qm", "base")
            base_sha = _git(managed_repo, "rev-parse", "HEAD")
            # A local remote-tracking ref makes the base observation deterministic
            # without contacting GitHub or rewriting the canonical remote binding.
            _git(managed_repo, "update-ref", "refs/remotes/origin/main", base_sha)
            branch = f"minime/{change_name}-{job_id}"
            _git(managed_repo, "branch", branch)
            repo = worktree_parent / job_id
            _git(managed_repo, "worktree", "add", str(repo), branch)
            (repo / "slug.py").write_text(
                "def normalize_slug(value):\n    return value.lower()\n", encoding="utf-8"
            )
            _git(repo, "add", "slug.py")
            _git(repo, "commit", "-qm", "frozen candidate")
            candidate_sha = _git(repo, "rev-parse", "HEAD")

            job = uow.jobs.get_by_id(job_id)
            run = uow.orchestration_runs.get_by_id(run_id)
            job.base_sha = base_sha
            job.candidate_sha = candidate_sha
            job.status = JobStatus.CHECKS_PASSED
            run.base_sha = base_sha
            run.current_candidate_sha = candidate_sha
            run.current_stage = OrchestrationStage.COMPLEMENTARY_REVIEW
            attempt_id = str(uuid4())
            manifest = CandidateManifestService().generate_manifest(
                repo, candidate_sha, job_id, attempt_id=attempt_id
            )
            candidate = OrchestrationCandidate(
                run_id=run_id,
                generation=1,
                base_sha=base_sha,
                candidate_sha=candidate_sha,
                candidate_ref=f"refs/heads/{branch}",
                manifest_id=manifest.manifest_id,
                manifest_hash=manifest.manifest_hash,
                is_frozen=True,
            )
            job.candidate_sha = candidate_sha
            job.base_sha = base_sha
            run.current_candidate_sha = candidate_sha
            run.base_sha = base_sha
            run.resumable_stage = OrchestrationStage.COMPLEMENTARY_REVIEW
            run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
            run.human_gate = HumanGate.NEEDS_HUMAN
            run.stop_reason = "Frozen candidate awaits one-shot review authorization."
            run.stop_details = {
                "code": "REVIEW_AUTHORIZATION_PENDING",
                "candidate_sha": candidate_sha,
                "generation": 1,
            }
            run.is_active = False
            attempt = JobAttempt(
                attempt_id=attempt_id,
                job_id=job_id,
                attempt_number=1,
                executor_role="codex",
                model_identity="codex-test-runner",
                start_sha=base_sha,
                end_sha=candidate_sha,
                normalized_outcome=ExecutionOutcome.COMPLETED,
                progress_classification=ProgressClassification.GOOD_PROGRESS,
                started_at=datetime.now(UTC) - timedelta(seconds=2),
                completed_at=datetime.now(UTC),
                duration_ms=10,
            )
            ownership = OrchestrationWorktreeOwnership(
                project_id=project_id,
                job_id=job_id,
                run_id=run_id,
                change_name=change_name,
                canonical_worktree_path=str(repo),
                source_repository_identity=repository_identity,
                source_base_sha=base_sha,
                branch=branch,
                creation_state=WorktreeCreationState.CREATED,
            )
            uow.jobs.save(job)
            uow.orchestration_runs.save(run)
            uow.job_attempts.save(attempt)
            # The manifest has a durable FK to the attempt; commit its
            # identity before persisting the candidate-bound manifest.
            uow.commit()
            uow.orchestration_worktree_ownerships.save(ownership)
            uow.candidate_manifests.save(manifest)
            uow.orchestration_candidates.save(candidate)
            historical_check_failure = CheckResult(
                job_id=job_id,
                check_name="pytest",
                command="pytest -q",
                exit_code=1,
                duration_ms=6,
                output_snippet="historical fixture failure",
                candidate_sha=candidate_sha,
                candidate_generation=1,
                created_at=datetime.now(UTC) - timedelta(days=1),
            )
            uow.check_results.save(historical_check_failure)
            uow.check_results.save(
                CheckResult(
                    job_id=job_id,
                    check_name="pytest",
                    command="pytest -q",
                    exit_code=0,
                    duration_ms=5,
                    output_snippet="deterministic fixture checks passed",
                    candidate_sha=candidate_sha,
                    candidate_generation=1,
                )
            )
            uow.commit()
            manager = WorktreeManager(managed_repo, uow=uow)
            manager._write_ownership_marker(repo, ownership)
            uow.commit()

            # The service process root is deliberately unrelated to the
            # managed repository. The validated durable binding remains the
            # only authority for review worktree adoption.
            root_mismatch_control_plane = control_plane_service.ControlPlaneService(
                uow, project_root=tmp_path
            )
            assert root_mismatch_control_plane.project_root == tmp_path.resolve()
            assert root_mismatch_control_plane.project_root != managed_repo.resolve()
            bound_manager = root_mismatch_control_plane._worktree_manager_for_bound_project(
                project_id, project
            )
            assert bound_manager.project_root == managed_repo.resolve()
            contradictory_project = project.model_copy(
                update={"repository": "silverberdi/contradictory-repository"}
            )
            with pytest.raises(RuntimeError, match="binding is missing or contradictory"):
                root_mismatch_control_plane._worktree_manager_for_bound_project(
                    project_id, contradictory_project
                )

            app_config.providers["deepseek"].budget["maximum_combined_review_usd"] = "1.49"
            over_limit = control_plane_service.ControlPlaneService(
                uow, project_root=tmp_path
            ).execute_action(
                _control_plane_request(
                    project_id=project_id,
                    change_name=change_name,
                    run=run,
                    action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
                    action_id=f"code-auth-over-limit-{uuid4()}",
                    params={
                        "max_spend_usd": "1.00",
                        "expires_at": expiry,
                        "pricing_snapshot_id": snapshot_id,
                    },
                    candidate_sha=candidate_sha,
                )
            )
            assert over_limit.status != OperatorActionStatus.COMPLETED
            assert "combined" in over_limit.summary.lower()

            app_config.providers["deepseek"].budget["maximum_combined_review_usd"] = "1.50"
            expired_auth_id = f"expired-unused-code-auth-{uuid4()}"
            expired_at = datetime.now(UTC) - timedelta(minutes=5)
            prior_auth_payload = {
                "provider": "deepseek",
                "account_fingerprint": adapter.account_fingerprint,
                "model": "deepseek-flash",
                "effort": "low",
                "stage": "REVIEW",
                "billing_origin": "deepseek_direct",
                "pricing_snapshot_id": snapshot_id,
                "run_id": run_id,
                "job_id": job_id,
                "candidate_sha": candidate_sha,
                "base_sha": base_sha,
                "generation": 1,
                "manifest_id": manifest.manifest_id,
                "manifest_hash": manifest.manifest_hash,
                "max_spend_usd": "0.05",
                "expires_at": expired_at.isoformat(),
                "authorized_by": "operator-test",
                "action_request_id": expired_auth_id,
            }
            expired_auth_record = OperatorActionRecord(
                action_request_id=expired_auth_id,
                project_id=project_id,
                change_name=change_name,
                run_id=run_id,
                job_id=job_id,
                action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
                status=OperatorActionStatus.COMPLETED,
                created_at=expired_at - timedelta(minutes=1),
                summary="Prior exact-candidate authorization expired unused.",
                result_payload_json={"authorization": prior_auth_payload},
            )
            root_rejection = OperatorActionRecord(
                action_request_id=f"expired-auth-root-rejection-{uuid4()}",
                project_id=project_id,
                change_name=change_name,
                run_id=run_id,
                job_id=job_id,
                action_type=OperatorActionType.EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW,
                status=OperatorActionStatus.REJECTED,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Frozen candidate worktree adoption proof failed: RuntimeError.",
                parameters_json={"authorization_id": expired_auth_id},
                created_at=expired_at + timedelta(seconds=1),
            )
            uow.operator_actions.save(expired_auth_record)
            uow.operator_actions.save(root_rejection)
            uow.commit()
            assert root_mismatch_control_plane._expired_unused_code_review_authorization(
                expired_auth_record, run, job, candidate
            )
            unexpired_auth_record = expired_auth_record.model_copy(
                update={
                    "result_payload_json": {
                        "authorization": {
                            **prior_auth_payload,
                            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                        }
                    }
                }
            )
            assert not root_mismatch_control_plane._expired_unused_code_review_authorization(
                unexpired_auth_record, run, job, candidate
            )

            consumed_reservation = BudgetReservation(
                project_id=project_id,
                job_id=job_id,
                run_id=run_id,
                change_id=change_name,
                role="reviewer",
                canonical_model_identity="deepseek-flash",
                reserved_amount_usd=Decimal("0.05"),
                status="RESERVED",
                pricing_snapshot_id=snapshot_id,
                provider="deepseek",
                account_fingerprint=adapter.account_fingerprint,
                stage="REVIEW",
                billing_origin="deepseek_direct",
                authorization_id=expired_auth_id,
                idempotency_key=f"expired-auth-consumed-{uuid4()}",
            )
            uow.budget_reservations.save(consumed_reservation)
            uow.commit()
            assert not root_mismatch_control_plane._expired_unused_code_review_authorization(
                expired_auth_record, run, job, candidate
            )
            with engine.begin() as connection:
                connection.execute(
                    text("delete from budget_reservations where id = :reservation_id"),
                    {"reservation_id": consumed_reservation.reservation_id},
                )

            ambiguous_dispatch = OrchestrationExternalAction(
                run_id=run_id,
                action_key=f"deepseek-code-review:{expired_auth_id}",
                action_type=ExternalActionType.DEEPSEEK_CODE_REVIEW_DISPATCH,
                target_identity=f"{project_id}:{candidate_sha}",
                request_fingerprint=f"ambiguous-review-dispatch-{uuid4()}",
                candidate_sha=candidate_sha,
                generation=1,
            )
            uow.orchestration_external_actions.reserve(ambiguous_dispatch)
            uow.commit()
            assert not root_mismatch_control_plane._expired_unused_code_review_authorization(
                expired_auth_record, run, job, candidate
            )
            with engine.begin() as connection:
                connection.execute(
                    text("delete from orchestration_external_actions where action_key = :key"),
                    {"key": f"deepseek-code-review:{expired_auth_id}"},
                )

            ambiguous_execute_record = OperatorActionRecord(
                action_request_id=str(uuid4()),
                project_id=project_id,
                change_name=change_name,
                run_id=run_id,
                job_id=job_id,
                action_type=OperatorActionType.EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW,
                status=OperatorActionStatus.BLOCKED,
                parameters_json={"authorization_id": expired_auth_id},
            )
            uow.operator_actions.save(ambiguous_execute_record)
            uow.commit()
            assert not root_mismatch_control_plane._expired_unused_code_review_authorization(
                expired_auth_record, run, job, candidate
            )
            with engine.begin() as connection:
                connection.execute(
                    text("delete from operator_action_records where id = :action_id"),
                    {"action_id": ambiguous_execute_record.id},
                )
            first_authorization_check = threading.Event()
            release_first_authorization = threading.Event()
            second_authorization_check = threading.Event()
            call_lock = threading.Lock()
            authorization_check_count = 0
            original_total = (
                control_plane_service.ControlPlaneService._deepseek_review_authorized_total
            )

            def synchronized_total(service, current_run):
                nonlocal authorization_check_count
                with call_lock:
                    authorization_check_count += 1
                    call_number = authorization_check_count
                if call_number == 1:
                    first_authorization_check.set()
                    assert release_first_authorization.wait(timeout=10)
                elif call_number == 2:
                    second_authorization_check.set()
                return original_total(service, current_run)

            monkeypatch.setattr(
                control_plane_service.ControlPlaneService,
                "_deepseek_review_authorized_total",
                synchronized_total,
            )

            def authorize_code(action_id):
                with sessionmaker(
                    bind=engine, autoflush=False, expire_on_commit=False
                )() as other_session:
                    other_uow = PostgresPersistenceUnitOfWork(other_session)
                    current_run = other_uow.orchestration_runs.get_by_id(run_id)
                    return control_plane_service.ControlPlaneService(
                        other_uow, project_root=tmp_path
                    ).execute_action(
                        _control_plane_request(
                            project_id=project_id,
                            change_name=change_name,
                            run=current_run,
                            action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
                            action_id=action_id,
                            params={
                                "max_spend_usd": "1.00",
                                "expires_at": expiry,
                                "pricing_snapshot_id": snapshot_id,
                            },
                            candidate_sha=candidate_sha,
                        )
                    )

            with ThreadPoolExecutor(max_workers=2) as pool:
                first_future = pool.submit(authorize_code, f"code-auth-{uuid4()}")
                assert first_authorization_check.wait(timeout=10)
                second_future = pool.submit(authorize_code, f"code-auth-{uuid4()}")
                # The second Control Plane request must wait on the PostgreSQL
                # Run row lock and cannot evaluate a stale authorization total.
                assert not second_authorization_check.wait(timeout=0.2)
                release_first_authorization.set()
                code_auth, duplicate_code_auth = (
                    first_future.result(timeout=15),
                    second_future.result(timeout=15),
                )
            assert code_auth.status == OperatorActionStatus.COMPLETED, code_auth.summary
            assert duplicate_code_auth.status != OperatorActionStatus.COMPLETED
            assert code_auth.payload["candidate_sha"] == candidate_sha
            preserved_expired_auth = uow.operator_actions.get_by_request_id(expired_auth_id)
            assert preserved_expired_auth is not None
            assert preserved_expired_auth.created_at == expired_auth_record.created_at
            assert preserved_expired_auth.result_payload_json == {
                "authorization": prior_auth_payload
            }
            original_code_authorization = uow.operator_actions.get_by_request_id(
                code_auth.action_request_id
            ).result_payload_json.copy()

            github = _DeterministicGitHubAdapter()
            dispatch_key = f"deepseek-code-review:{code_auth.action_request_id}"

            def dispatch_review(action_id, authorization_id=None):
                effective_authorization_id = authorization_id or code_auth.action_request_id
                with sessionmaker(
                    bind=engine, autoflush=False, expire_on_commit=False
                )() as review_session:
                    review_uow = PostgresPersistenceUnitOfWork(review_session)
                    current_run = review_uow.orchestration_runs.get_by_id(run_id)
                    review_runner = runner
                    review_service = DeepSeekCodeReviewService(
                        review_uow,
                        health_service=ProviderHealthService(review_uow),
                        app_config=app_config,
                        runner=review_runner,
                    )
                    review_github = _DeterministicGitHubAdapter()
                    review_orchestration = OrchestrationService(
                        review_uow,
                        project_root=managed_repo,
                        github_adapter=review_github,
                    )
                    review_control_plane = control_plane_service.ControlPlaneService(
                        review_uow,
                        orchestration_service=review_orchestration,
                        deepseek_code_review_service=review_service,
                    )
                    action_request = _control_plane_request(
                        project_id=project_id,
                        change_name=change_name,
                        run=current_run,
                        action_type=OperatorActionType.EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW,
                        action_id=action_id,
                        params={"authorization_id": effective_authorization_id},
                        candidate_sha=candidate_sha,
                    )
                    if (
                        review_verdict == ReviewVerdict.READY_TO_MERGE
                        and audit_risk == "low"
                        and not mutate_candidate_during_review
                        and not missing_reservation_case
                    ):
                        # Exercise the real `minime action execute` entrypoint
                        # with its default process root, using only this isolated
                        # PostgreSQL engine and intercepted provider HTTP.
                        from typer.testing import CliRunner

                        from minime.cli import main as cli_main

                        @contextmanager
                        def isolated_cli_session():
                            with sessionmaker(
                                bind=engine, autoflush=False, expire_on_commit=False
                            )() as cli_session:
                                yield cli_session

                        monkeypatch.setattr(cli_main.db_manager, "session", isolated_cli_session)
                        cli_result = CliRunner().invoke(
                            cli_main.app,
                            [
                                "action",
                                "execute",
                                run_id,
                                OperatorActionType.EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW.value,
                                "--params",
                                json.dumps({"authorization_id": effective_authorization_id}),
                                "--actor",
                                "isolated-test-operator",
                                "--expected-stage",
                                OrchestrationStage.COMPLEMENTARY_REVIEW.value,
                                "--expected-gen",
                                "1",
                                "--expected-sha",
                                candidate_sha,
                                "--json",
                            ],
                        )
                        if cli_result.exit_code != 0:
                            review_started.set()
                        assert cli_result.exit_code == 0, cli_result.output
                        return control_plane_service.OperatorActionResult.model_validate(
                            json.loads(cli_result.stdout)
                        )
                    if review_verdict == ReviewVerdict.CHANGES_REQUIRED:
                        # Exercise the API action endpoint against the same
                        # exact database/Git fixture; no external HTTP or model.
                        from minime.api import app as api_app

                        return api_app.execute_action_generic_endpoint(
                            run_id, action_request, review_uow
                        )
                    return review_control_plane.execute_action(action_request)

            with ThreadPoolExecutor(max_workers=2) as pool:
                first_review = pool.submit(dispatch_review, f"code-review-dispatch-{uuid4()}")
                if not review_started.wait(timeout=10):
                    release_review.set()
                    assert False, first_review.result(timeout=10).summary
                competing_review = pool.submit(dispatch_review, str(uuid4()))
                competing_result = competing_review.result(timeout=10)
                assert competing_result.status != OperatorActionStatus.COMPLETED
                release_review.set()
                review_action = first_review.result(timeout=15)
            assert not root_mismatch_control_plane._expired_unused_code_review_authorization(
                expired_auth_record, run, job, candidate
            )
            if terminal_recovery_case:
                assert review_action.status == OperatorActionStatus.BLOCKED
                assert review_action.payload["reason"] == (
                    "DEEPSEEK_CODE_REVIEW_TERMINAL_TRUNCATED"
                ), [
                    event.payload.get("response")
                    for event in uow.events.list_events(
                        project_id=project_id, change_id=change_name, limit=10000
                    )
                    if event.event_type == EventType.EVIDENCE_DIAGNOSTIC_RECORDED
                ]
                assert len(review_http_calls) == 1
                failed_review = uow.reviews.get_by_id(review_action.payload["review_id"])
                assert (
                    failed_review
                    and failed_review.status.value == "REVIEW_FAILED"
                    and failed_review.verdict is None
                )
                failed_reservation = uow.budget_reservations.get_by_id(
                    failed_review.budget_reservation_id
                )
                assert failed_reservation and failed_reservation.status == "SETTLED"
                failed_dispatch_key = f"deepseek-code-review:{code_auth.action_request_id}"
                failed_dispatch = uow.orchestration_external_actions.get_by_action_key(
                    failed_dispatch_key
                )
                failed_dispatch_attempts = uow.external_action_attempts.list_by_action_key(
                    failed_dispatch_key
                )
                assert failed_dispatch and failed_dispatch.status.value == "FAILED"
                assert len(failed_dispatch_attempts) == 1
                assert failed_dispatch_attempts[0].status == "FAILED"
                assert failed_dispatch_attempts[0].attempt_number == 1
                failed_run = uow.orchestration_runs.get_by_id(run_id)
                failed_job = uow.jobs.get_by_id(job_id)
                assert failed_run.stop_details["code"] == ("CODE_REVIEW_TERMINAL_FAILURE_SETTLED")
                assert failed_run.is_active is False
                assert failed_job.status == JobStatus.NEEDS_HUMAN
                terminal_actions = {
                    item.action: item
                    for item in control_plane_service.ControlPlaneService(
                        uow, project_root=tmp_path
                    ).get_available_actions(run_id)
                }
                assert terminal_actions[OperatorActionType.CONTINUE].enabled is False
                assert _git(repo, "rev-parse", "HEAD") == candidate_sha
                assert _git(repo, "status", "--porcelain") == ""
                check_results_before_retry = uow.check_results.list_by_job(job_id)
                attempts_before_retry = uow.job_attempts.list_by_job(job_id)
                old_review_snapshot = failed_review.model_copy(deep=True)
                old_ledger = uow.budget_ledger.list_by_project(project_id)
                assert len(old_ledger) == 1  # settled CODE_REVIEW; no contract spend occurred

                diagnostic_event = next(
                    event
                    for event in uow.events.list_events(
                        project_id=project_id, change_id=change_name, limit=10000
                    )
                    if event.event_type == EventType.EVIDENCE_DIAGNOSTIC_RECORDED
                    and event.payload.get("review_id") == failed_review.review_id
                )
                assert diagnostic_event.payload["response"]["finish_reason"] == "length"
                assert diagnostic_event.payload["response"]["reasoning_content_present"] is True
                assert diagnostic_event.payload["response"]["reasoning_content_length"] == len(
                    "private reasoning excluded from evidence"
                )
                assert "reasoning_content" not in diagnostic_event.payload["response"]
                assert "private reasoning" not in json.dumps(diagnostic_event.payload)
                from minime.services.deepseek_code_review_service import (
                    terminal_settled_code_review_recovery_allowed,
                )

                contradictory_run = failed_run.model_copy(
                    update={
                        "stop_details": {
                            **failed_run.stop_details,
                            "manifest_hash": "contradictory-manifest",
                        }
                    }
                )
                assert not terminal_settled_code_review_recovery_allowed(
                    uow,
                    run=contradictory_run,
                    job=failed_job,
                    candidate=candidate,
                    manifest=manifest,
                )
                failed_reservation.status = "UNRESOLVED"
                uow.budget_reservations.save(failed_reservation)
                uow.commit()
                assert not terminal_settled_code_review_recovery_allowed(
                    uow,
                    run=failed_run,
                    job=failed_job,
                    candidate=candidate,
                    manifest=manifest,
                )
                failed_reservation.status = "SETTLED"
                uow.budget_reservations.save(failed_reservation)
                uow.commit()
                failed_dispatch.status = ExternalActionStatus.EXECUTING
                uow.session.execute(
                    text(
                        "update orchestration_external_actions set status = 'EXECUTING' where action_key = :key"
                    ),
                    {"key": failed_dispatch_key},
                )
                uow.session.execute(
                    text("update external_action_attempts set status = 'EXECUTING' where id = :id"),
                    {"id": failed_dispatch_attempts[0].attempt_id},
                )
                uow.commit()
                assert not terminal_settled_code_review_recovery_allowed(
                    uow,
                    run=failed_run,
                    job=failed_job,
                    candidate=candidate,
                    manifest=manifest,
                )
                failed_dispatch.status = ExternalActionStatus.FAILED
                uow.session.execute(
                    text(
                        "update orchestration_external_actions set status = 'FAILED' where action_key = :key"
                    ),
                    {"key": failed_dispatch_key},
                )
                uow.session.execute(
                    text("update external_action_attempts set status = 'FAILED' where id = :id"),
                    {"id": failed_dispatch_attempts[0].attempt_id},
                )
                uow.commit()
                recovery_proven = terminal_settled_code_review_recovery_allowed(
                    uow,
                    run=failed_run,
                    job=failed_job,
                    candidate=candidate,
                    manifest=manifest,
                )
                assert recovery_proven
                renewal_allowed = (
                    root_mismatch_control_plane._code_review_authorization_renewal_allowed(
                        failed_run, failed_job, candidate
                    )
                )
                assert renewal_allowed

                over_limit_retry = control_plane_service.ControlPlaneService(
                    uow, project_root=tmp_path
                ).execute_action(
                    _control_plane_request(
                        project_id=project_id,
                        change_name=change_name,
                        run=failed_run,
                        action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
                        action_id=f"terminal-over-limit-{uuid4()}",
                        params={
                            "max_spend_usd": "1.00",
                            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
                            "pricing_snapshot_id": snapshot_id,
                        },
                        candidate_sha=candidate_sha,
                    )
                )
                assert over_limit_retry.status != OperatorActionStatus.COMPLETED

                uow.session.expire_all()
                retry_run = uow.orchestration_runs.get_by_id(run_id)
                new_auth_id = f"terminal-recovery-auth-{uuid4()}"
                new_auth = control_plane_service.ControlPlaneService(
                    uow, project_root=tmp_path
                ).execute_action(
                    _control_plane_request(
                        project_id=project_id,
                        change_name=change_name,
                        run=retry_run,
                        action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
                        action_id=new_auth_id,
                        params={
                            "max_spend_usd": "0.50",
                            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
                            "pricing_snapshot_id": snapshot_id,
                        },
                        candidate_sha=candidate_sha,
                    )
                )
                assert new_auth.status == OperatorActionStatus.COMPLETED, new_auth.summary
                assert new_auth.action_request_id != code_auth.action_request_id
                assert (
                    uow.operator_actions.get_by_request_id(
                        code_auth.action_request_id
                    ).result_payload_json
                    == original_code_authorization
                )
                second_review_action = dispatch_review(
                    f"terminal-recovery-dispatch-{uuid4()}", new_auth.action_request_id
                )
                assert second_review_action.status == OperatorActionStatus.COMPLETED, (
                    second_review_action.summary,
                    second_review_action.payload.get("reason"),
                )
                assert second_review_action.payload["review_id"] != failed_review.review_id
                assert len(review_http_calls) == 2
                duplicate_retry = dispatch_review(
                    f"terminal-recovery-duplicate-{uuid4()}", new_auth.action_request_id
                )
                assert duplicate_retry.status != OperatorActionStatus.COMPLETED
                assert len(review_http_calls) == 2
                assert uow.reviews.get_by_id(failed_review.review_id) == old_review_snapshot
                assert _git(repo, "rev-parse", "HEAD") == candidate_sha
                assert _git(repo, "status", "--porcelain") == ""
                assert uow.check_results.list_by_job(job_id) == check_results_before_retry
                assert uow.job_attempts.list_by_job(job_id) == attempts_before_retry
                assert len(uow.budget_reservations.list_by_project(project_id)) == 2
                ledger_after_retry = uow.budget_ledger.list_by_project(project_id)
                assert len(ledger_after_retry) == len(old_ledger) + 1
                assert {item.entry_id for item in old_ledger} <= {
                    item.entry_id for item in ledger_after_retry
                }
                retry_reservation = next(
                    item
                    for item in uow.budget_reservations.list_by_project(project_id)
                    if item.authorization_id == new_auth.action_request_id
                )
                assert retry_reservation.status == "SETTLED"
                assert retry_reservation.reservation_id != failed_reservation.reservation_id
                assert retry_reservation.idempotency_key != failed_reservation.idempotency_key
                assert len(retry_reservation.idempotency_key) <= 128
                assert (
                    uow.orchestration_external_actions.get_by_action_key(
                        f"deepseek-code-review:{new_auth.action_request_id}"
                    ).status.value
                    == "COMPLETED"
                )
                assert (
                    uow.orchestration_external_actions.get_by_action_key(
                        failed_dispatch_key
                    ).status.value
                    == "FAILED"
                )
                assert _git(managed_repo, "rev-parse", "refs/remotes/origin/main") == base_sha
                return
            if mutate_candidate_during_review:
                assert review_action.status == OperatorActionStatus.BLOCKED
                assert review_action.payload["reason"] == (
                    "CODE_REVIEW_POST_REVIEW_INTEGRITY_FAILED"
                )
                blocked_review = uow.reviews.get_by_id(review_action.payload["review_id"])
                assert blocked_review and blocked_review.status.value == "REVIEW_FAILED"
                assert blocked_review.verdict is None
                assert len(review_http_calls) == 1
                assert len(uow.budget_ledger.list_by_project(project_id)) == 1
                assert len(uow.budget_reservations.list_by_project(project_id)) == 1
                failed_dispatch = uow.orchestration_external_actions.get_by_action_key(dispatch_key)
                assert failed_dispatch and failed_dispatch.status.value == "FAILED"
                failed_attempts = uow.external_action_attempts.list_by_action_key(dispatch_key)
                assert len(failed_attempts) == 1 and failed_attempts[0].status == "FAILED"
                assert not any(
                    event.event_type == EventType.CODE_REVIEW_COMPLETED
                    and event.payload.get("review_id") == blocked_review.review_id
                    for event in uow.events.list_events(
                        project_id=project_id, change_id=change_name, limit=10000
                    )
                )
                assert any(
                    event.event_type == EventType.EVIDENCE_DIAGNOSTIC_RECORDED
                    and event.payload.get("review_id") == blocked_review.review_id
                    for event in uow.events.list_events(
                        project_id=project_id, change_id=change_name, limit=10000
                    )
                )
                assert github.pushed == {} and github.created_prs == []
                assert candidate_sha == uow.jobs.get_by_id(job_id).candidate_sha
                assert (
                    uow.orchestration_runs.get_by_id(run_id).current_candidate_sha == candidate_sha
                )
                return
            assert review_action.status == OperatorActionStatus.COMPLETED, review_action.summary
            review_id = review_action.payload["review_id"]
            assert _git(repo, "rev-parse", "HEAD") == candidate_sha
            assert _git(repo, "status", "--porcelain") == ""
            downstream_auditor = _NoInferenceAuditor(risk=audit_risk)
            downstream_pipeline = ExecutionPipelineService(
                uow,
                project_root=managed_repo,
                auditor_runner=downstream_auditor,
            )
            control_plane = control_plane_service.ControlPlaneService(
                uow,
                orchestration_service=OrchestrationService(
                    uow,
                    project_root=managed_repo,
                    pipeline=downstream_pipeline,
                    github_adapter=github,
                ),
            )
            held_run = uow.orchestration_runs.get_by_id(run_id)
            held_job = uow.jobs.get_by_id(job_id)
            assert held_run.current_stage == OrchestrationStage.COMPLEMENTARY_REVIEW
            assert held_run.resumable_stage == OrchestrationStage.COMPLEMENTARY_REVIEW
            expected_gate = (
                "CODE_REVIEW_COMPLETED_REQUIRES_SEPARATE_AUTHORIZED_CONTINUATION"
                if review_verdict == ReviewVerdict.READY_TO_MERGE
                else "CODE_REVIEW_COMPLETED_CHANGES_REQUIRED"
            )
            assert held_run.stop_details["code"] == expected_gate
            assert held_run.is_active is False
            assert held_job.status == JobStatus.CHECKS_PASSED
            assert len(review_http_calls) == 1
            current_candidate = uow.orchestration_candidates.get_latest_for_run(run_id)
            review_authority_before_continue = (
                control_plane.orchestration_service._validate_review_authority(
                    held_run, held_job, current_candidate
                )
            )
            assert github.pushed == {}
            assert github.created_prs == []
            review_events = [
                event
                for event in uow.events.list_events(
                    project_id=project_id, change_id=change_name, limit=10000
                )
                if event.event_type == EventType.CODE_REVIEW_COMPLETED
                and event.payload.get("review_id") == review_id
            ]
            assert len(review_events) == 1
            assert review_events[0].payload["candidate_sha"] == candidate_sha
            assert review_events[0].payload["manifest_hash"] == manifest.manifest_hash
            review_metrics = uow.metrics.list_facts(
                project_id=project_id,
                change_id=change_name,
                metric_name="review_duration_ms",
                limit=10,
            )
            assert len(review_metrics) == 1
            assert review_metrics[0].stage == "CODE_REVIEW"
            assert review_metrics[0].details["candidate_sha"] == candidate_sha
            reservations = uow.budget_reservations.list_by_project(project_id)
            assert len(reservations) == 1
            reservation = reservations[0]
            assert reservation.status == "SETTLED"
            assert reservation.provider == "deepseek"
            assert reservation.account_fingerprint == adapter.account_fingerprint
            assert reservation.canonical_model_identity == "deepseek-flash"
            assert reservation.stage == "REVIEW"
            assert reservation.billing_origin == "deepseek_direct"
            assert reservation.authorization_id == code_auth.action_request_id
            assert Decimal("0") < reservation.reserved_amount_usd < Decimal("1.00")
            assert reservation.reserved_amount_usd <= Decimal("0.50") + Decimal("1.00")

            if review_verdict == ReviewVerdict.CHANGES_REQUIRED:
                findings = uow.review_findings.list_by_review(review_id)
                assert len(findings) == 1
                assert findings[0].severity.value == "MAJOR"
                assert findings[0].violated_requirement == (
                    "The output must preserve the accepted input contract."
                )
                remediation_required = control_plane.execute_action(
                    _control_plane_request(
                        project_id=project_id,
                        change_name=change_name,
                        run=held_run,
                        action_type=OperatorActionType.CONTINUE_AFTER_CODE_REVIEW,
                        action_id=str(uuid4()),
                        params={
                            "review_id": review_id,
                            "candidate_sha": candidate_sha,
                            "manifest_hash": manifest.manifest_hash,
                        },
                        candidate_sha=candidate_sha,
                    )
                )
                assert remediation_required.status == OperatorActionStatus.REJECTED
                assert (
                    uow.orchestration_runs.get_by_id(run_id).stop_details == held_run.stop_details
                )
                assert uow.jobs.get_by_id(job_id).candidate_sha == candidate_sha
                assert uow.jobs.get_by_id(job_id).status == JobStatus.CHECKS_PASSED
                assert len(review_http_calls) == 1
                assert downstream_auditor.calls == 0
                assert github.pushed == {} and github.created_prs == []
                assert len(uow.budget_reservations.list_by_project(project_id)) == 1
                assert len(uow.external_action_attempts.list_by_action_key(dispatch_key)) == 1
                return

            ledger = uow.budget_ledger.list_by_project(project_id)
            assert len(ledger) == 1
            assert ledger[0].entry_type == "SETTLEMENT"
            assert ledger[0].provider == "deepseek"
            assert ledger[0].stage == "REVIEW"
            assert ledger[0].billing_origin == "deepseek_direct"
            # PostgreSQL's durable NUMERIC scale rounds the sub-cent computed
            # token cost upward to its six-decimal representation.
            assert ledger[0].amount_usd == Decimal("0.000032")

            invalid_identity_cases = [
                (str(uuid4()), candidate_sha, manifest.manifest_hash),
                (review_id, "stale-candidate-sha", manifest.manifest_hash),
                (review_id, candidate_sha, "stale-manifest-hash"),
            ]
            for invalid_review_id, invalid_sha, invalid_manifest_hash in invalid_identity_cases:
                invalid_continuation = control_plane.execute_action(
                    _control_plane_request(
                        project_id=project_id,
                        change_name=change_name,
                        run=held_run,
                        action_type=OperatorActionType.CONTINUE_AFTER_CODE_REVIEW,
                        action_id=f"post-review-invalid-{uuid4()}",
                        params={
                            "review_id": invalid_review_id,
                            "candidate_sha": invalid_sha,
                            "manifest_hash": invalid_manifest_hash,
                        },
                        candidate_sha=invalid_sha,
                    )
                )
                assert invalid_continuation.status == OperatorActionStatus.REJECTED
                assert (
                    uow.orchestration_runs.get_by_id(run_id).stop_details == held_run.stop_details
                )
                assert uow.jobs.get_by_id(job_id).status == JobStatus.CHECKS_PASSED
                assert len(review_http_calls) == 1
                assert github.pushed == {}
                assert github.created_prs == []

            if missing_reservation_case:
                # A completed review with a dangling reservation identity is not
                # continuation authority. This exercises the real PostgreSQL read
                # returning None and must reject before audit, push, or PR effects.
                review_record = uow.reviews.get_by_id(review_id)
                assert (
                    review_record
                    and review_record.budget_reservation_id == reservation.reservation_id
                )
                saved_run = uow.orchestration_runs.get_by_id(run_id)
                saved_job = uow.jobs.get_by_id(job_id)
                external_actions_before = uow.orchestration_external_actions.list_by_run(run_id)
                attempts_before = uow.external_action_attempts.list_by_action_key(dispatch_key)
                review_record.budget_reservation_id = str(uuid4())
                uow.reviews.save(review_record)
                uow.commit()
                missing_reservation = control_plane.execute_action(
                    _control_plane_request(
                        project_id=project_id,
                        change_name=change_name,
                        run=held_run,
                        action_type=OperatorActionType.CONTINUE_AFTER_CODE_REVIEW,
                        action_id=f"missing-reservation-{uuid4()}",
                        params={
                            "review_id": review_id,
                            "candidate_sha": candidate_sha,
                            "manifest_hash": manifest.manifest_hash,
                        },
                        candidate_sha=candidate_sha,
                    )
                )
                assert missing_reservation.status == OperatorActionStatus.REJECTED
                assert uow.orchestration_runs.get_by_id(run_id) == saved_run
                assert uow.jobs.get_by_id(job_id) == saved_job
                assert (
                    uow.orchestration_external_actions.list_by_run(run_id)
                    == external_actions_before
                )
                assert (
                    uow.external_action_attempts.list_by_action_key(dispatch_key) == attempts_before
                )
                assert len(review_http_calls) == 1
                assert downstream_auditor.calls == 0
                assert github.pushed == {} and github.created_prs == []

                # Restore only the disposable test fixture so test cleanup sees
                # the original link; no production records are involved.
                review_record.budget_reservation_id = reservation.reservation_id
                uow.reviews.save(review_record)
                uow.commit()
                return

            # A competing live claim blocks before downstream audit or PR work.
            from minime.services.recovery_convergence_service import RecoveryConvergenceService

            competing_recovery = RecoveryConvergenceService(
                uow, owner_instance_id="post-review-competing-owner"
            )
            competing_claim = competing_recovery.acquire_claim(f"run:{run_id}")
            assert competing_claim is not None
            blocked_by_claim = control_plane.execute_action(
                _control_plane_request(
                    project_id=project_id,
                    change_name=change_name,
                    run=held_run,
                    action_type=OperatorActionType.CONTINUE_AFTER_CODE_REVIEW,
                    action_id=f"post-review-live-claim-{uuid4()}",
                    params={
                        "review_id": review_id,
                        "candidate_sha": candidate_sha,
                        "manifest_hash": manifest.manifest_hash,
                    },
                    candidate_sha=candidate_sha,
                )
            )
            assert blocked_by_claim.status == OperatorActionStatus.REJECTED
            assert uow.orchestration_runs.get_by_id(run_id).stop_details == held_run.stop_details
            assert len(review_http_calls) == 1
            assert downstream_auditor.calls == 0
            assert github.pushed == {} and github.created_prs == []
            competing_recovery.release_claim(competing_claim)

            # Generic CONTINUE cannot turn a review hold back into APPLY.
            generic_continue = control_plane.execute_action(
                _control_plane_request(
                    project_id=project_id,
                    change_name=change_name,
                    run=held_run,
                    action_type=OperatorActionType.CONTINUE,
                    action_id=f"generic-review-continue-{uuid4()}",
                    params={},
                    candidate_sha=candidate_sha,
                )
            )
            assert generic_continue.status != OperatorActionStatus.COMPLETED
            assert uow.orchestration_runs.get_by_id(run_id).current_stage == (
                OrchestrationStage.COMPLEMENTARY_REVIEW
            )

            # A distinct action is required to resume after the completed review.
            continuation = control_plane.execute_action(
                _control_plane_request(
                    project_id=project_id,
                    change_name=change_name,
                    run=held_run,
                    action_type=OperatorActionType.CONTINUE_AFTER_CODE_REVIEW,
                    action_id=f"post-review-continue-{uuid4()}",
                    params={
                        "review_id": review_id,
                        "candidate_sha": candidate_sha,
                        "manifest_hash": manifest.manifest_hash,
                    },
                    candidate_sha=candidate_sha,
                )
            )
            assert continuation.status == OperatorActionStatus.COMPLETED, (
                f"{continuation.summary}: {continuation.payload}"
            )
            if audit_risk == "high":
                assert continuation.resulting_stage == OrchestrationStage.INDEPENDENT_AUDIT
                assert continuation.resulting_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
                assert continuation.resulting_gate == HumanGate.NEEDS_HUMAN
                assert downstream_auditor.calls == 1
                assert github.pushed == {} and github.created_prs == []
                assert len(review_http_calls) == 1
                assert uow.jobs.get_by_id(job_id).status == JobStatus.AUDIT_BLOCKED
                assert (
                    uow.orchestration_runs.get_by_id(run_id).current_candidate_sha == candidate_sha
                )
                assert len(uow.job_attempts.list_by_job(job_id)) == 1
                check_history = uow.check_results.list_by_job(job_id)
                assert len(check_history) == 2
                assert (
                    next(
                        result
                        for result in check_history
                        if result.result_id == historical_check_failure.result_id
                    ).exit_code
                    == 1
                )
                assert len(uow.budget_reservations.list_by_project(project_id)) == 1
                assert len(uow.external_action_attempts.list_by_action_key(dispatch_key)) == 1
                audit = uow.audits.get_by_job_id(job_id)
                assert audit and audit.status.value == "AUDIT_BLOCKED"
                assert audit.candidate_sha == candidate_sha
                return
            assert continuation.resulting_stage == OrchestrationStage.PR_PREPARED, (
                continuation.summary,
                continuation.payload,
                downstream_auditor.calls,
                uow.audits.get_by_job_id(job_id),
                review_authority_before_continue,
            )
            persisted_continuation_run = uow.orchestration_runs.get_by_id(run_id)
            assert continuation.resulting_gate == HumanGate.READY_FOR_HUMAN_MERGE, (
                f"stage={continuation.resulting_stage!r}, "
                f"outcome={continuation.resulting_outcome!r}, "
                f"gate={continuation.resulting_gate!r}, "
                f"stop_details={persisted_continuation_run.stop_details!r}"
            )
            assert continuation.resulting_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
            assert persisted_continuation_run.current_stage == OrchestrationStage.PR_PREPARED
            assert (
                persisted_continuation_run.stop_outcome
                == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
            )
            assert persisted_continuation_run.human_gate == HumanGate.READY_FOR_HUMAN_MERGE
            assert persisted_continuation_run.stop_details == {"code": "READY_FOR_HUMAN_MERGE"}
            assert downstream_auditor.calls == 1
            assert github.pushed == {branch: candidate_sha}
            assert len(github.created_prs) == 1
            assert github.created_prs[0]["head_sha"] == candidate_sha
            assert github.created_prs[0]["state"] == "OPEN"
            persisted_audit = uow.audits.get_by_job_id(job_id)
            assert persisted_audit is not None
            assert persisted_audit.status.value == "AUDIT_COMPLETED"
            assert persisted_audit.candidate_sha == candidate_sha
            final_run = uow.orchestration_runs.get_by_id(run_id)
            final_job = uow.jobs.get_by_id(job_id)
            assert final_run.current_stage != OrchestrationStage.IMPLEMENTING
            assert final_run.current_candidate_sha == candidate_sha
            assert final_job.candidate_sha == candidate_sha
            assert uow.job_attempts.get_by_id(attempt_id).end_sha == candidate_sha
            check_history = uow.check_results.list_by_job(job_id)
            assert len(check_history) == 2
            assert (
                next(
                    result
                    for result in check_history
                    if result.result_id == historical_check_failure.result_id
                ).exit_code
                == 1
            )
            assert len(review_http_calls) == 1
            assert len(uow.budget_reservations.list_by_project(project_id)) == 1
            assert len(uow.budget_ledger.list_by_project(project_id)) == 1
            dispatch = uow.orchestration_external_actions.get_by_action_key(dispatch_key)
            assert dispatch and dispatch.status.value == "COMPLETED"
            dispatch_attempts = uow.external_action_attempts.list_by_action_key(dispatch_key)
            assert len(dispatch_attempts) == 1
            assert dispatch_attempts[0].status == "COMPLETED"
            assert (
                BudgetService(uow).settle_reservation(
                    reservation.reservation_id,
                    Decimal("0.0000315"),
                    prompt_tokens=25,
                    completion_tokens=20,
                    total_tokens=45,
                )
                is None
            )
            uow.commit()

            persisted = uow.operator_actions.list_by_run(run_id)
            completed = [
                item for item in persisted if item.status == OperatorActionStatus.COMPLETED
            ]
            assert {
                item.action_type
                for item in completed
                if item.action_type
                in {
                    OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW,
                    OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
                    OperatorActionType.EXECUTE_AUTHORIZED_DEEPSEEK_CODE_REVIEW,
                    OperatorActionType.CONTINUE_AFTER_CODE_REVIEW,
                }
            }
            assert len(completed) >= 4
    finally:
        release_review.set()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "delete from review_findings where review_id in "
                    "(select id from reviews where project_id = :project_id)"
                ),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from reviews where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from budget_ledger where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from budget_reservations where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from check_results where job_id = :job_id"), {"job_id": job_id}
            )
            connection.execute(
                text("delete from orchestration_candidates where run_id = :run_id"),
                {"run_id": run_id},
            )
            connection.execute(
                text("delete from candidate_manifests where job_id = :job_id"),
                {"job_id": job_id},
            )
            connection.execute(
                text("delete from operator_action_records where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from events where project_id = :project_id"),
                {"project_id": project_id},
            )
            if capacity_state_touched:
                connection.execute(
                    text(
                        "delete from events where payload->>'provider' = 'deepseek' "
                        "and payload->>'account_fingerprint' = :account_fingerprint"
                    ),
                    {"account_fingerprint": adapter.account_fingerprint},
                )
                connection.execute(text("delete from capacity_windows where provider = 'deepseek'"))
                connection.execute(text("delete from provider_health where provider = 'deepseek'"))
            connection.execute(
                text("delete from orchestration_runs where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from jobs where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from openrouter_pricing_snapshots where id = :snapshot_id"),
                {"snapshot_id": snapshot_id},
            )
            connection.execute(
                text("delete from projects where id = :project_id"),
                {"project_id": project_id},
            )
        engine.dispose()
