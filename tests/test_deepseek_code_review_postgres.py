"""PostgreSQL integration for the governed, candidate-bound DeepSeek code review."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from minime.adapters import provider_adapter
from minime.adapters.provider_adapter import DeepSeekProviderAdapter
from minime.config import AppConfig, ProjectConfig, ProviderConfig, StageProfileConfig
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    JobStatus,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
)
from minime.domain.models import (
    CheckResult,
    Job,
    OpenRouterPricingSnapshot,
    OperatorActionRequest,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
)
from minime.services import control_plane_service
from minime.services.budget_service import BudgetService
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.contract_review_service import DeepSeekReviewResponse
from minime.services.deepseek_code_review_service import DeepSeekCodeReviewService
from minime.services.provider_health_service import ProviderHealthService

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must target the isolated R01 disposable PostgreSQL database",
)


class _NoInferenceReviewRunner:
    model = "deepseek-flash"
    effort = "low"
    review_stage = "CODE_REVIEW"

    def __init__(self):
        self.calls = 0

    async def review(self, request: str, timeout_seconds: int):
        self.calls += 1
        assert timeout_seconds > 0
        payload = json.loads(request)
        assert payload["stage"] == "CODE_REVIEW"
        return DeepSeekReviewResponse(
            0,
            json.dumps(
                {
                    "verdict": "READY_TO_MERGE",
                    "summary": "Deterministic fixture review",
                    "findings": [],
                }
            ),
            self.model,
            25,
            20,
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


def test_code_review_authorization_reservation_settlement_and_idempotency_in_postgres(
    tmp_path, monkeypatch
):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id = f"r01-code-review-{uuid4()}"
    change_name = "budgeted-review-candidate"
    account_key = "isolated-test-key-not-a-provider-credential"
    run_id = str(uuid4())
    job_id = str(uuid4())
    snapshot_id = str(uuid4())
    capacity_state_touched = False
    runner = _NoInferenceReviewRunner()

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
        return httpx.Response(404)

    original_async_client = httpx.AsyncClient

    def intercepted_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(response_for)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", intercepted_async_client)
    monkeypatch.setenv("DEEPSEEK_API_KEY", account_key)

    adapter = DeepSeekProviderAdapter()
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

    try:
        with engine.connect() as connection:
            assert connection.execute(text("select current_database()")).scalar() == (
                "minime_contract_review_test"
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
            capacity_state_touched = True

        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            project = Project(
                project_id=project_id,
                display_name="Disposable DeepSeek code-review budget test",
                repository=project_config.repository,
                openspec_path="openspec",
                external_providers_allowed=project_config.external_providers_allowed,
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

            repo = tmp_path / "candidate"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "review-test@example.invalid")
            _git(repo, "config", "user.name", "R01 budget integration")
            (repo / "README.md").write_text("# isolated base\n", encoding="utf-8")
            _git(repo, "add", "README.md")
            _git(repo, "commit", "-qm", "base")
            base_sha = _git(repo, "rev-parse", "HEAD")
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
            manifest = CandidateManifestService().generate_manifest(repo, candidate_sha, job_id)
            candidate = OrchestrationCandidate(
                run_id=run_id,
                generation=1,
                base_sha=base_sha,
                candidate_sha=candidate_sha,
                candidate_ref="refs/heads/minime/budget-test",
                manifest_id=manifest.manifest_id,
                manifest_hash=manifest.manifest_hash,
                is_frozen=True,
            )
            job.candidate_sha = candidate_sha
            job.base_sha = base_sha
            run.current_candidate_sha = candidate_sha
            run.base_sha = base_sha
            uow.jobs.save(job)
            uow.orchestration_runs.save(run)
            uow.candidate_manifests.save(manifest)
            uow.orchestration_candidates.save(candidate)
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

            service = DeepSeekCodeReviewService(
                uow,
                health_service=ProviderHealthService(uow),
                app_config=app_config,
                runner=runner,
            )
            result = asyncio.run(
                service.review_candidate(
                    project=project,
                    run=run,
                    job=job,
                    candidate=candidate,
                    manifest=manifest,
                    candidate_worktree=repo,
                    authorship_evidence={},
                )
            )
            assert result.accepted, result.reason
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

            ledger = uow.budget_ledger.list_by_project(project_id)
            assert len(ledger) == 1
            assert ledger[0].entry_type == "SETTLEMENT"
            assert ledger[0].provider == "deepseek"
            assert ledger[0].stage == "REVIEW"
            assert ledger[0].billing_origin == "deepseek_direct"
            # PostgreSQL's durable NUMERIC scale rounds the sub-cent computed
            # token cost upward to its six-decimal representation.
            assert ledger[0].amount_usd == Decimal("0.000032")

            # A retry returns the same durable checkpoint; it does not dispatch,
            # reserve again, or add another ledger settlement.
            replay = asyncio.run(
                service.review_candidate(
                    project=project,
                    run=run,
                    job=job,
                    candidate=candidate,
                    manifest=manifest,
                    candidate_worktree=repo,
                    authorship_evidence={},
                )
            )
            assert replay.accepted and replay.review_id == result.review_id
            assert runner.calls == 1
            assert len(uow.budget_reservations.list_by_project(project_id)) == 1
            assert len(uow.budget_ledger.list_by_project(project_id)) == 1
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
            assert {item.action_type for item in completed} == {
                OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW,
                OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
            }
            assert len(completed) == 2
    finally:
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
