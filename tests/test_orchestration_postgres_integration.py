"""PostgreSQL evidence for 008 orchestration durability and reconciliation."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    AuditStatus,
    ExternalActionStatus,
    ExternalActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.models import (
    AuditRecord,
    CandidateManifest,
    Job,
    OrchestrationCandidate,
    OrchestrationExternalAction,
    OrchestrationRun,
    OrchestrationStageEvent,
    Project,
    Review,
)
from minime.services.orchestration_service import OrchestrationService
from minime.services.restart_recovery_service import RestartRecoveryService

PG_URL = os.environ.get("MINIME_DATABASE_URL")
EXPECTED_DATABASE = os.environ.get("MINIME_EXPECTED_DATABASE", "minime_010_verify")
pytestmark = pytest.mark.skipif(
    not PG_URL, reason="MINIME_DATABASE_URL must point to the migrated disposable PostgreSQL DB"
)


@pytest.fixture(scope="module")
def session_factory() -> sessionmaker[Session]:
    assert PG_URL
    engine = create_engine(PG_URL, pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.execute(text("select current_database()")).scalar() == EXPECTED_DATABASE
        assert connection.execute(text("select version_num from alembic_version")).scalar() == (
            "011_governance_hardening"
        )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def project_id(session_factory: sessionmaker[Session]):
    value = f"pg008-{uuid4().hex[:12]}"
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(
            Project(
                project_id=value,
                display_name="PostgreSQL 008 evidence",
                repository="silverberdi/mini-me",
                base_branch="main",
            )
        )
        uow.commit()
    yield value
    with session_factory() as session:
        session.execute(text("delete from projects where id = :project_id"), {"project_id": value})
        session.commit()


def _run(project_id: str, change_name: str = "change-a", **overrides) -> OrchestrationRun:
    return OrchestrationRun(
        run_id=f"run-{uuid4().hex}",
        project_id=project_id,
        change_name=change_name,
        base_sha="base-sha",
        current_stage=OrchestrationStage.PREPARING_PR,
        resumable_stage=OrchestrationStage.PREPARING_PR,
        current_generation=3,
        current_candidate_sha="candidate-sha",
        **overrides,
    )


def test_active_run_partial_unique_index_allows_history_and_independent_changes(
    session_factory: sessionmaker[Session], project_id: str
):
    first = _run(project_id)
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.orchestration_runs.save(first)
        uow.commit()

    duplicate = _run(project_id)
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.orchestration_runs.save(duplicate)
        with pytest.raises(IntegrityError):
            uow.commit()
            session.rollback()

    terminal = _run(project_id, is_active=False, stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN)
    independent = _run(project_id, change_name="change-b")
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.orchestration_runs.save(terminal)
        uow.orchestration_runs.save(independent)
        uow.commit()
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        assert uow.orchestration_runs.get_active_run(project_id, "change-a").run_id == first.run_id
        assert (
            uow.orchestration_runs.get_active_run(project_id, "change-b").run_id
            == independent.run_id
        )


def test_postgres_job_transitions_use_the_canonical_transition_map(
    session_factory: sessionmaker[Session], project_id: str
):
    """Exercise the real PostgreSQL job repository against the disposable database."""
    queued_job = Job(
        project_id=project_id,
        change_name=f"job-{uuid4().hex}",
        implementer_role="codex",
    )
    waiting_job = queued_job.model_copy(
        deep=True, update={"job_id": f"{queued_job.job_id}-waiting"}
    )
    recovery_job = queued_job.model_copy(
        deep=True, update={"job_id": f"{queued_job.job_id}-recovery"}
    )

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        for job in (queued_job, waiting_job, recovery_job):
            uow.jobs.save(job)
        uow.commit()

        assert uow.jobs.transition(queued_job.job_id, "RUNNING").status.value == "RUNNING"
        uow.jobs.transition(waiting_job.job_id, "RUNNING")
        assert (
            uow.jobs.set_waiting_capacity(
                waiting_job.job_id, "codex", "subscription exhausted"
            ).status.value
            == "WAITING_CAPACITY"
        )
        uow.jobs.transition(recovery_job.job_id, "RUNNING")
        assert (
            uow.jobs.set_recovery_blocked(
                recovery_job.job_id, "runtime identity unavailable"
            ).status.value
            == "RECOVERY_BLOCKED"
        )
        with pytest.raises(ValueError, match="Invalid job status transition"):
            uow.jobs.transition(queued_job.job_id, "READY_TO_MERGE")

        session.rollback()


def test_transition_and_external_action_keys_survive_new_sessions(
    session_factory: sessionmaker[Session], project_id: str
):
    run = _run(project_id)
    transition_key = f"transition-{uuid4().hex}"
    action_key = f"action-{uuid4().hex}"
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.orchestration_runs.save(run)
        uow.orchestration_stage_events.save(
            OrchestrationStageEvent(
                run_id=run.run_id,
                from_stage=OrchestrationStage.ADMITTED,
                to_stage=OrchestrationStage.PREPARING_EXECUTION,
                transition_key=transition_key,
            )
        )
        uow.orchestration_external_actions.reserve(
            OrchestrationExternalAction(
                run_id=run.run_id,
                action_key=action_key,
                action_type=ExternalActionType.BRANCH_PUSH,
                target_identity="silverberdi/mini-me:branch",
                request_fingerprint="fingerprint",
                candidate_sha="candidate-sha",
                generation=3,
            )
        )
        uow.commit()

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        assert uow.orchestration_stage_events.get_by_transition_key(transition_key) is not None
        assert uow.orchestration_external_actions.get_by_action_key(action_key) is not None
        uow.orchestration_stage_events.save(
            OrchestrationStageEvent(
                run_id=run.run_id,
                from_stage=OrchestrationStage.ADMITTED,
                to_stage=OrchestrationStage.PREPARING_EXECUTION,
                transition_key=transition_key,
            )
        )
        with pytest.raises(IntegrityError):
            uow.commit()
            session.rollback()

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.orchestration_external_actions.reserve(
            OrchestrationExternalAction(
                run_id=run.run_id,
                action_key=action_key,
                action_type=ExternalActionType.BRANCH_PUSH,
                target_identity="silverberdi/mini-me:branch",
                request_fingerprint="fingerprint",
                candidate_sha="candidate-sha",
                generation=3,
            )
        )
        with pytest.raises(IntegrityError):
            uow.commit()
            session.rollback()


def test_candidate_review_audit_and_run_state_persist_exactly_across_sessions(
    session_factory: sessionmaker[Session], project_id: str
):
    run = _run(project_id, stop_outcome=OrchestrationStopOutcome.WAITING_EXTERNAL)
    job = Job(
        job_id=f"job-{uuid4().hex}",
        project_id=project_id,
        change_name=run.change_name,
        implementer_role="codex",
        reviewer_role="antigravity",
    )
    run.active_job_id = job.job_id
    candidate = OrchestrationCandidate(
        run_id=run.run_id,
        generation=3,
        base_sha="base-sha",
        candidate_sha="candidate-sha",
        manifest_id="manifest-id",
        manifest_hash="manifest-hash",
    )
    review = Review(
        job_id=job.job_id,
        project_id=project_id,
        change_name=run.change_name,
        reviewer_role="antigravity",
        orchestration_run_id=run.run_id,
        candidate_generation=3,
        candidate_sha="candidate-sha",
        base_sha="base-sha",
        manifest_id="manifest-id",
        manifest_hash="manifest-hash",
        status=ReviewStatus.REVIEW_COMPLETED,
        verdict=ReviewVerdict.READY_TO_MERGE,
    )
    audit = AuditRecord(
        job_id=job.job_id,
        project_id=project_id,
        change_name=run.change_name,
        provider="deepseek_direct",
        orchestration_run_id=run.run_id,
        candidate_generation=3,
        candidate_sha="candidate-sha",
        base_sha="base-sha",
        manifest_id="manifest-id",
        manifest_hash="manifest-hash",
        is_full_candidate=True,
        status=AuditStatus.AUDIT_COMPLETED,
    )
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.jobs.save(job)
        uow.candidate_manifests.save(
            CandidateManifest(
                manifest_id="manifest-id",
                job_id=job.job_id,
                candidate_sha="candidate-sha",
                manifest_hash="manifest-hash",
            )
        )
        uow.orchestration_runs.save(run)
        uow.orchestration_candidates.save(candidate)
        uow.reviews.save(review)
        uow.audits.save(audit)
        uow.commit()

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        restored_run = uow.orchestration_runs.get_by_id(run.run_id)
        restored_candidate = uow.orchestration_candidates.get_latest_for_run(run.run_id)
        restored_review = uow.reviews.get_by_id(review.review_id)
        restored_audit = uow.audits.get_by_id(audit.audit_id)
        assert restored_run.current_stage == run.current_stage
        assert restored_run.resumable_stage == run.resumable_stage
        assert restored_run.stop_outcome == run.stop_outcome
        assert restored_run.active_job_id == job.job_id
        assert restored_run.current_generation == 3
        assert restored_candidate.manifest_id == "manifest-id"
        assert restored_candidate.manifest_hash == "manifest-hash"
        assert restored_review.orchestration_run_id == run.run_id
        assert restored_review.candidate_generation == 3
        assert restored_review.candidate_sha == "candidate-sha"
        assert restored_review.base_sha == "base-sha"
        assert restored_review.manifest_id == "manifest-id"
        assert restored_review.manifest_hash == "manifest-hash"
        assert restored_audit.orchestration_run_id == run.run_id
        assert restored_audit.candidate_generation == 3
        assert restored_audit.is_full_candidate is True


def test_real_postgres_coordinator_status_and_restart_reconciliation(
    session_factory: sessionmaker[Session], project_id: str, tmp_path
):
    run = _run(project_id)
    action = OrchestrationExternalAction(
        run_id=run.run_id,
        action_key=f"restart-action-{uuid4().hex}",
        action_type=ExternalActionType.BRANCH_PUSH,
        target_identity="silverberdi/mini-me:branch",
        request_fingerprint="restart-fingerprint",
        candidate_sha="candidate-sha",
        generation=3,
        status=ExternalActionStatus.RESERVED,
    )
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.orchestration_runs.save(run)
        uow.orchestration_external_actions.reserve(action)
        uow.commit()

    class RecordingCoordinator:
        def __init__(self):
            self.resumed: list[str] = []

        def resume(self, run_id: str):
            self.resumed.append(run_id)

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        coordinator = RecordingCoordinator()
        recovery = RestartRecoveryService(uow, project_root=tmp_path)
        recovered = recovery.reconcile_orchestration_runs(coordinator)
        assert recovered[0].run_id == run.run_id
        assert coordinator.resumed == [run.run_id]

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        service = OrchestrationService(uow, project_root=tmp_path)
        status = service.get_status(run.run_id)
        assert status.run_id == run.run_id
        assert status.current_generation == 3
        assert status.current_stage == OrchestrationStage.PREPARING_PR
