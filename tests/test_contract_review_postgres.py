"""Disposable-PostgreSQL persistence and uniqueness evidence for contract review."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from minime.adapters.provider_adapter import (
    DeepSeekProviderAdapter,
)
from minime.config import AppConfig, ProjectConfig, ProviderConfig, StageProfileConfig
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    EventType,
    JobStatus,
    OrchestrationStage,
    ProviderHealthStatus,
    RecoveryClassification,
    RecoveryDecisionStatus,
    RecoverySource,
    ReviewStatus,
    ReviewVerdict,
    WorktreeCreationState,
)
from minime.domain.models import (
    BudgetReservation,
    Event,
    Job,
    OpenRouterPricingSnapshot,
    OrchestrationRun,
    OrchestrationWorktreeOwnership,
    Project,
    ProviderHealth,
    RecoveryClaimContext,
    RecoveryDecision,
    Review,
)
from minime.services.budget_service import BudgetService
from minime.services.contract_review_service import (
    ContractReviewService,
    DeepSeekResponseDiagnostics,
    DeepSeekReviewResponse,
    _review_reservation_key,
    persist_deepseek_response_diagnostic,
)

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)


def test_contract_review_owner_policy_usage_and_identity_persist_in_postgres():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    # Several durable identities use UUID-sized VARCHAR columns.
    project_id = str(uuid4())
    job_id = str(uuid4())
    run_id = str(uuid4())
    snapshot_id = str(uuid4())
    review_id = str(uuid4())
    reservation_id = str(uuid4())
    contract_hash = "a" * 64
    account_fingerprint = "b" * 64
    reservation_key = _review_reservation_key(
        run_id=run_id,
        job_id=job_id,
        stage="CONTRACT_REVIEW",
        contract_hash=contract_hash,
    )

    try:
        with engine.connect() as connection:
            assert (
                connection.execute(text("select current_database()")).scalar()
                == "minime_contract_review_test"
            )
            assert (
                connection.execute(text("select version_num from alembic_version")).scalar()
                == "r02_contract_review_budget_identity"
            )

        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            project = Project(
                project_id=project_id,
                display_name="Disposable contract review persistence test",
                repository="test/contract-review",
            )
            job = Job(
                job_id=job_id,
                project_id=project_id,
                change_name="review-change",
                implementer_role="codex",
            )
            run = OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name="review-change",
                base_sha="base-test-sha",
                active_job_id=job_id,
                current_stage=OrchestrationStage.ADMITTED,
            )
            snapshot = OpenRouterPricingSnapshot(
                id=snapshot_id,
                canonical_model_identity="deepseek-chat",
                routed_model_identity="deepseek-chat",
                prompt_price_per_token=Decimal("0.000001"),
                output_price_per_token=Decimal("0.000001"),
                source="deepseek_official_pricing",
                provider="deepseek",
                account_fingerprint=account_fingerprint,
                billing_origin="deepseek_direct",
            )
            uow.projects.save(project)
            uow.jobs.save(job)
            uow.orchestration_runs.save(run)
            uow.pricing_snapshots.save(snapshot)
            uow.flush()
            reservation, denial = BudgetService(uow).reserve_review_budget(
                project_id=project_id,
                run_id=run_id,
                job_id=job_id,
                change_id=run.change_name,
                provider="deepseek",
                account_fingerprint=account_fingerprint,
                model="deepseek-chat",
                stage="CONTRACT_REVIEW",
                billing_origin="deepseek_direct",
                pricing_snapshot_id=snapshot_id,
                prompt_token_upper_bound=100,
                max_output_tokens=100,
                idempotency_key=reservation_key,
                maximum_stage_usd=Decimal("0.50"),
                maximum_combined_usd=Decimal("1.50"),
            )
            assert denial is None and reservation is not None
            review = Review(
                review_id=review_id,
                job_id=job_id,
                project_id=project_id,
                change_name=run.change_name,
                reviewer_role="deepseek",
                reviewer_model="deepseek-chat",
                review_stage="CONTRACT_REVIEW",
                contract_hash=contract_hash,
                provider="deepseek",
                account_fingerprint=account_fingerprint,
                budget_authorization_id=None,
                budget_reservation_id=reservation_id,
                billing_origin="deepseek_direct",
                orchestration_run_id=run_id,
                candidate_generation=1,
                candidate_sha=contract_hash,
                base_sha=run.base_sha,
                manifest_id=contract_hash,
                manifest_hash=contract_hash,
                status=ReviewStatus.REVIEW_COMPLETED,
                verdict=ReviewVerdict.CONTRACT_ACCEPTED,
            )
            uow.reviews.save(review)
            uow.commit()
            settled = BudgetService(uow).settle_reservation(
                reservation.reservation_id,
                Decimal("0.000019"),
                prompt_tokens=12,
                completion_tokens=7,
                total_tokens=19,
            )
            assert settled is not None
            uow.commit()
            persist_deepseek_response_diagnostic(
                uow,
                review,
                DeepSeekReviewResponse(
                    0,
                    None,
                    "deepseek-chat",
                    12,
                    7,
                    "incomplete generation (length)",
                    DeepSeekResponseDiagnostics(
                        http_status=200,
                        response_id="response-id-safe",
                        returned_model="deepseek-chat",
                        model_matches_request=True,
                        choices_count=1,
                        finish_reason="length",
                        content_present=True,
                        content_type="str",
                        content_length=2,
                        reasoning_content_present=True,
                        reasoning_content_type="str",
                        reasoning_content_length=48,
                        usage_present=True,
                        prompt_tokens=12,
                        completion_tokens=7,
                        total_tokens=19,
                        usage_valid=True,
                    ),
                ),
            )

        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            persisted_review = uow.reviews.get_by_job_stage(job_id, "CONTRACT_REVIEW")
            persisted_reservation = uow.budget_reservations.get_by_idempotency_key(reservation_key)
            assert persisted_review is not None
            assert persisted_review.contract_hash == contract_hash
            assert persisted_review.provider == "deepseek"
            assert persisted_review.account_fingerprint == account_fingerprint
            assert persisted_review.budget_authorization_id is None
            assert persisted_reservation is not None
            assert persisted_reservation.stage == "CONTRACT_REVIEW"
            assert persisted_reservation.billing_origin == "deepseek_direct"
            assert persisted_reservation.authorization_id is None
            assert persisted_reservation.status == "SETTLED"
            usage = uow.budget_ledger.list_by_project(project_id)
            assert len(usage) == 1 and usage[0].total_tokens == 19
            diagnostics = [
                event
                for event in uow.events.list_events(project_id, "review-change")
                if event.event_type == EventType.EVIDENCE_DIAGNOSTIC_RECORDED
            ]
            assert len(diagnostics) == 1
            persisted_diagnostic = diagnostics[0].payload["response"]
            assert persisted_diagnostic["finish_reason"] == "length"
            assert persisted_diagnostic["usage_valid"] is True
            assert "reasoning_content" not in diagnostics[0].payload

        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            uow.budget_reservations.save(
                BudgetReservation(
                    project_id=project_id,
                    job_id=job_id,
                    run_id=run_id,
                    change_id="review-change",
                    role="reviewer",
                    canonical_model_identity="deepseek-chat",
                    reserved_amount_usd=Decimal("0.01"),
                    status="RESERVED",
                    pricing_snapshot_id=snapshot_id,
                    provider="deepseek",
                    account_fingerprint=account_fingerprint,
                    stage="CONTRACT_REVIEW",
                    billing_origin="deepseek_direct",
                    authorization_id=None,
                    idempotency_key=reservation_key,
                )
            )
            with pytest.raises(IntegrityError):
                uow.commit()
            session.rollback()
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("delete from events where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from reviews where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from budget_reservations where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from operator_action_records where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from orchestration_runs where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from jobs where project_id = :project_id"), {"project_id": project_id}
            )
            connection.execute(
                text("delete from openrouter_pricing_snapshots where id = :snapshot_id"),
                {"snapshot_id": snapshot_id},
            )
            connection.execute(
                text("delete from projects where id = :project_id"), {"project_id": project_id}
            )
        engine.dispose()


class _PostgresRecoveryAdapter(DeepSeekProviderAdapter):
    async def check_model_supported(self, model, effort=None, timeout_seconds=10.0):
        return (model == "deepseek-flash" and effort == "low", None)


class _PostgresCapacityEvidence:
    async def refresh_capacity_from_read_only_source(self, provider, model=None):
        return provider == "deepseek" and model == "deepseek-flash"

    def get_existing_health(self, provider):
        return ProviderHealth(
            provider=provider,
            model="deepseek-flash",
            status=ProviderHealthStatus.AVAILABLE,
        )

    def has_fresh_capacity_evidence(self, provider, *, model, account_fingerprint, quota_scope):
        return (
            provider == "deepseek"
            and model == "deepseek-flash"
            and bool(account_fingerprint)
            and quota_scope == "deepseek_direct_account_balance"
        )


class _PostgresReviewer:
    model = "deepseek-flash"
    effort = "low"

    def __init__(self, *, malformed_usage=False):
        self.malformed_usage = malformed_usage
        self.calls = 0

    async def review(self, contract_json, timeout_seconds):
        self.calls += 1
        payload = json.dumps(
            {"verdict": "CONTRACT_ACCEPTED", "summary": "Accepted", "findings": []}
        )
        if self.malformed_usage:
            return DeepSeekReviewResponse(0, payload, self.model, True, 7)
        return DeepSeekReviewResponse(
            0,
            payload,
            self.model,
            12,
            7,
            response_diagnostics=DeepSeekResponseDiagnostics(
                http_status=200,
                returned_model=self.model,
                model_matches_request=True,
                choices_count=1,
                finish_reason="stop",
                content_present=True,
                content_type="str",
                content_length=len(payload),
                usage_present=True,
                prompt_tokens=12,
                completion_tokens=7,
                total_tokens=19,
                usage_valid=True,
            ),
        )


@pytest.mark.asyncio
async def test_postgres_contract_review_recovery_uses_distinct_fenced_operation(
    monkeypatch, tmp_path
):
    from minime.adapters import provider_adapter

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, job_id, run_id, snapshot_id = (str(uuid4()) for _ in range(4))
    claim_key = f"run:{run_id}"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "disposable-test-account-key")
    adapter = _PostgresRecoveryAdapter()
    monkeypatch.setitem(provider_adapter._ADAPTER_REGISTRY, "deepseek", adapter)
    project_config = ProjectConfig(
        repository="test/contract-recovery",
        openspec_path="openspec",
        external_providers_allowed=["codex", "antigravity", "deepseek"],
        stage_profiles={
            "CONTRACT_REVIEW": StageProfileConfig(
                provider="deepseek",
                model="deepseek-flash",
                effort="low",
                workflow="openspec-explore",
            )
        },
    )
    app_config = AppConfig(
        providers={
            "deepseek": ProviderConfig(
                type="api",
                enabled=True,
                budget={
                    "maximum_contract_review_usd": "0.50",
                    "maximum_code_review_usd": "1.00",
                    "maximum_combined_review_usd": "1.50",
                },
            )
        },
        projects={project_id: project_config},
    )
    change_name = "recovery-change"
    change_dir = tmp_path / "openspec" / "changes" / change_name
    (change_dir / "specs" / "contract").mkdir(parents=True)
    (change_dir / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
    (change_dir / "tasks.md").write_text("- [ ] Keep the recovery fenced.\n", encoding="utf-8")
    (change_dir / "specs" / "contract" / "spec.md").write_text(
        "## Requirements\n", encoding="utf-8"
    )

    try:
        with engine.connect() as connection:
            assert connection.execute(text("select current_database()")).scalar() == (
                "minime_contract_review_test"
            )
            assert connection.execute(text("select version_num from alembic_version")).scalar() == (
                "r02_contract_review_budget_identity"
            )
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            project = Project(
                project_id=project_id,
                display_name="Disposable review recovery",
                repository="test/contract-recovery",
                openspec_path="openspec",
                external_providers_allowed=["codex", "antigravity", "deepseek"],
            )
            job = Job(
                job_id=job_id,
                project_id=project_id,
                change_name=change_name,
                implementer_role="codex",
                status=JobStatus.RUNNING,
                base_sha="base-test-sha",
            )
            run = OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name=change_name,
                base_sha="base-test-sha",
                active_job_id=job_id,
                current_stage=OrchestrationStage.IMPLEMENTING,
                is_active=True,
            )
            fingerprint = adapter.account_fingerprint
            uow.projects.save(project)
            uow.jobs.save(job)
            uow.orchestration_runs.save(run)
            uow.pricing_snapshots.save(
                OpenRouterPricingSnapshot(
                    id=snapshot_id,
                    canonical_model_identity="deepseek-flash",
                    routed_model_identity="deepseek-flash",
                    prompt_price_per_token=Decimal("0.000001"),
                    output_price_per_token=Decimal("0.000001"),
                    source="deepseek_official_pricing",
                    provider="deepseek",
                    account_fingerprint=fingerprint,
                    billing_origin="deepseek_direct",
                )
            )
            uow.commit()
            health = _PostgresCapacityEvidence()
            failed_runner = _PostgresReviewer(malformed_usage=True)
            failed = await ContractReviewService(
                uow, health_service=health, app_config=app_config, runner=failed_runner
            ).review_before_apply(project, run, job, tmp_path)
            assert not failed.accepted
            old_review = uow.reviews.get_by_id(failed.review_id)
            old_reservation = uow.budget_reservations.get_by_id(old_review.budget_reservation_id)
            assert old_review.status == ReviewStatus.REVIEW_FAILED
            assert old_reservation.status == "UNRESOLVED"
            old_key = old_reservation.idempotency_key

            claim = uow.claims.acquire_or_reacquire(
                claim_key, "postgres-control-plane-owner", lease_seconds=300
            )
            claim_context = RecoveryClaimContext(
                claim_key=claim.claim_key,
                owner_instance_id=claim.owner_instance_id,
                fence_token=claim.fence_token,
                lease_expires_at=claim.lease_expires_at,
            )
            decision = RecoveryDecision(
                cycle_id=str(uuid4()),
                claim_key=claim_key,
                identity_type="RUN",
                identity_id=run_id,
                project_id=project_id,
                change_name=change_name,
                source=RecoverySource.CONTROL_PLANE,
                classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
                planned_action="DRIVE_CONTINUATION",
                fence_token=claim.fence_token,
                status=RecoveryDecisionStatus.EXECUTING,
            )
            uow.recovery_decisions.create_decision(decision)
            uow.commit()

            success_runner = _PostgresReviewer()
            resumed = await ContractReviewService(
                uow, health_service=health, app_config=app_config, runner=success_runner
            ).review_before_apply(project, run, job, tmp_path, claim_context=claim_context)
            assert resumed.accepted and resumed.review_id != failed.review_id
            assert success_runner.calls == 1
            assert uow.reviews.get_by_id(failed.review_id).status == ReviewStatus.REVIEW_FAILED
            assert uow.budget_reservations.get_by_id(old_reservation.reservation_id).status == (
                "UNRESOLVED"
            )
            new_review = uow.reviews.get_by_id(resumed.review_id)
            new_reservation = uow.budget_reservations.get_by_id(new_review.budget_reservation_id)
            assert new_reservation.idempotency_key != old_key
            assert len(uow.reviews.list_by_job(job_id)) == 2
            started = [
                event
                for event in uow.events.list_events(project_id, change_name)
                if event.event_type == EventType.CONTRACT_REVIEW_OPERATION_STARTED
            ]
            assert len(started) == 2
            assert (
                next(event for event in started if event.operation_id == resumed.review_id).payload[
                    "supersedes_review_id"
                ]
                == failed.review_id
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "delete from review_findings where review_id in (select id from reviews where project_id = :project_id)"
                ),
                {"project_id": project_id},
            )
            for table in (
                "events",
                "budget_ledger",
                "reviews",
                "budget_reservations",
                "recovery_decisions",
            ):
                connection.execute(
                    text(f"delete from {table} where project_id = :project_id"),
                    {"project_id": project_id},
                )
            connection.execute(
                text("delete from recovery_claims where claim_key = :claim_key"),
                {"claim_key": claim_key},
            )
            connection.execute(
                text("delete from orchestration_runs where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from jobs where project_id = :project_id"), {"project_id": project_id}
            )
            connection.execute(
                text("delete from openrouter_pricing_snapshots where id = :snapshot_id"),
                {"snapshot_id": snapshot_id},
            )
            connection.execute(
                text("delete from projects where id = :project_id"), {"project_id": project_id}
            )
        engine.dispose()


def test_postgres_failed_read_only_review_authorizes_only_exact_snapshot_recovery(tmp_path):
    from minime.services.worktree_manager import WorktreeManager

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, job_id, run_id, snapshot_id = (str(uuid4()) for _ in range(4))
    change_name = "review-only-recovery"
    base_sha = "b" * 40
    contract_hash = "c" * 64
    fingerprint = "d" * 64
    branch = f"minime/{change_name}-{job_id}"
    worktree_path = tmp_path / ".minime" / "worktrees" / job_id
    claim_key = f"run:{run_id}"
    try:
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            project = Project(
                project_id=project_id,
                display_name="Disposable read-only review recovery",
                repository="test/review-only-recovery",
            )
            job = Job(
                job_id=job_id,
                project_id=project_id,
                change_name=change_name,
                implementer_role="codex",
                status=JobStatus.RUNNING,
                base_sha=base_sha,
                attempt_count=1,
            )
            run = OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name=change_name,
                base_sha=base_sha,
                active_job_id=job_id,
                current_stage=OrchestrationStage.IMPLEMENTING,
                is_active=True,
            )
            ownership = OrchestrationWorktreeOwnership(
                project_id=project_id,
                job_id=job_id,
                run_id=run_id,
                change_name=change_name,
                canonical_worktree_path=str(worktree_path),
                source_repository_identity="github.com/test/review-only-recovery",
                source_base_sha=base_sha,
                branch=branch,
                creation_state=WorktreeCreationState.DELETED,
            )
            reservation = BudgetReservation(
                reservation_id=str(uuid4()),
                project_id=project_id,
                job_id=job_id,
                run_id=run_id,
                change_id=change_name,
                role="reviewer",
                canonical_model_identity="deepseek-flash",
                reserved_amount_usd=Decimal("0.004735"),
                status="UNRESOLVED",
                pricing_snapshot_id=snapshot_id,
                provider="deepseek",
                account_fingerprint=fingerprint,
                stage="CONTRACT_REVIEW",
                billing_origin="deepseek_direct",
                idempotency_key=str(uuid4()),
            )
            review = Review(
                review_id=str(uuid4()),
                job_id=job_id,
                project_id=project_id,
                change_name=change_name,
                reviewer_role="deepseek",
                reviewer_model="deepseek-flash",
                review_stage="CONTRACT_REVIEW",
                contract_hash=contract_hash,
                provider="deepseek",
                account_fingerprint=fingerprint,
                budget_reservation_id=reservation.reservation_id,
                billing_origin="deepseek_direct",
                orchestration_run_id=run_id,
                candidate_generation=1,
                candidate_sha=contract_hash,
                base_sha=base_sha,
                status=ReviewStatus.REVIEW_FAILED,
                error_message="Provider response was not valid; usage remains unresolved.",
                created_at=(review_time := datetime.now(UTC) - timedelta(seconds=10)),
                updated_at=review_time + timedelta(seconds=1),
            )
            later_review_id = str(uuid4())
            later_reservation = BudgetReservation(
                reservation_id=str(uuid4()),
                project_id=project_id,
                job_id=job_id,
                run_id=run_id,
                change_id=change_name,
                role="reviewer",
                canonical_model_identity="deepseek-flash",
                reserved_amount_usd=Decimal("0.004753"),
                status="SETTLED",
                pricing_snapshot_id=snapshot_id,
                provider="deepseek",
                account_fingerprint=fingerprint,
                stage="CONTRACT_REVIEW",
                billing_origin="deepseek_direct",
                idempotency_key=str(uuid4()),
            )
            uow.projects.save(project)
            uow.commit()
            uow.jobs.save(job)
            uow.orchestration_runs.save(run)
            uow.orchestration_worktree_ownerships.save(ownership)
            uow.commit()
            uow.pricing_snapshots.save(
                OpenRouterPricingSnapshot(
                    id=snapshot_id,
                    canonical_model_identity="deepseek-flash",
                    routed_model_identity="deepseek-flash",
                    prompt_price_per_token=Decimal("0.0000003"),
                    output_price_per_token=Decimal("0.0000012"),
                    source="deepseek_official_pricing",
                    provider="deepseek",
                    account_fingerprint=fingerprint,
                    billing_origin="deepseek_direct",
                )
            )
            uow.commit()
            uow.budget_reservations.save(reservation)
            uow.commit()
            uow.reviews.save(review)
            uow.budget_reservations.save(later_reservation)
            uow.reviews.save(
                Review(
                    review_id=later_review_id,
                    job_id=job_id,
                    project_id=project_id,
                    change_name=change_name,
                    reviewer_role="deepseek",
                    reviewer_model="deepseek-flash",
                    review_stage="CONTRACT_REVIEW",
                    contract_hash=contract_hash,
                    provider="deepseek",
                    account_fingerprint=fingerprint,
                    budget_reservation_id=later_reservation.reservation_id,
                    billing_origin="deepseek_direct",
                    orchestration_run_id=run_id,
                    candidate_generation=1,
                    candidate_sha=contract_hash,
                    base_sha=base_sha,
                    status=ReviewStatus.REVIEW_FAILED,
                    error_message="Incomplete generation (length); usage was settled.",
                    created_at=review.created_at + timedelta(seconds=3),
                    updated_at=review.updated_at + timedelta(seconds=3),
                )
            )
            uow.events.save(
                Event(
                    event_type=EventType.WORKTREE_RECOVERY_SNAPSHOT,
                    project_id=project_id,
                    change_id=change_name,
                    operation_id=job_id,
                    payload={
                        "job_id": job_id,
                        "branch": branch,
                        "recovery_sha": "e" * 40,
                        "worktree_path": str(worktree_path),
                        "authoritative_candidate": False,
                    },
                    timestamp=review.updated_at + timedelta(seconds=1),
                )
            )
            uow.commit()
            claim = uow.claims.acquire_or_reacquire(
                claim_key, "review-only-recovery-test", lease_seconds=300
            )
            decision = RecoveryDecision(
                cycle_id=str(uuid4()),
                claim_key=claim_key,
                identity_type="RUN",
                identity_id=run_id,
                project_id=project_id,
                change_name=change_name,
                source=RecoverySource.CONTROL_PLANE,
                classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
                planned_action="DRIVE_CONTINUATION",
                fence_token=claim.fence_token,
                status=RecoveryDecisionStatus.EXECUTING,
            )
            uow.recovery_decisions.create_decision(decision)
            uow.commit()

            manager = WorktreeManager(tmp_path, uow)
            assert manager._has_durable_failed_contract_review_recovery(
                job=job,
                run=run,
                ownership=ownership,
                project_id=project_id,
                run_id=run_id,
                change_name=change_name,
                path=worktree_path,
                branch=branch,
                source_base=base_sha,
                attempts=[],
            )

            # Neither the existing Job.attempt_count metadata nor the unresolved
            # historical reservation is rewritten to make this checkpoint pass.
            assert uow.jobs.get_by_id(job_id).attempt_count == 1
            assert uow.budget_reservations.get_by_id(reservation.reservation_id).status == (
                "UNRESOLVED"
            )
            job.candidate_sha = "unexpected-candidate"
            assert not manager._has_durable_failed_contract_review_recovery(
                job=job,
                run=run,
                ownership=ownership,
                project_id=project_id,
                run_id=run_id,
                change_name=change_name,
                path=worktree_path,
                branch=branch,
                source_base=base_sha,
                attempts=[],
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("delete from events where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from budget_reservations where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from openrouter_pricing_snapshots where id = :snapshot_id"),
                {"snapshot_id": snapshot_id},
            )
            connection.execute(
                text("delete from reviews where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from recovery_decisions where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from recovery_claims where claim_key = :claim_key"),
                {"claim_key": claim_key},
            )
            connection.execute(
                text(
                    "delete from orchestration_worktree_ownerships where project_id = :project_id"
                ),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from orchestration_runs where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from jobs where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from projects where id = :project_id"),
                {"project_id": project_id},
            )
        engine.dispose()
