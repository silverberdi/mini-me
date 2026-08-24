"""Domain model and persistence tests for autonomous change orchestration."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import Base
from minime.db.repository import (
    PostgresOrchestrationCandidateRepository,
    PostgresOrchestrationExternalActionRepository,
    PostgresOrchestrationRunRepository,
    PostgresOrchestrationStageEventRepository,
    PostgresProjectRepository,
)
from minime.domain.enums import (
    ExternalActionStatus,
    ExternalActionType,
    HumanGate,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProjectStatus,
)
from minime.domain.models import (
    OrchestrationCandidate,
    OrchestrationExternalAction,
    OrchestrationRun,
    OrchestrationStageEvent,
    Project,
)


def test_orchestration_run_domain_and_in_memory_persistence(in_memory_uow):
    run = OrchestrationRun(
        run_id="run-101",
        project_id="mini-me",
        change_name="008-autonomous-change-orchestration",
        base_sha="61eb4bfdabf0e7612090bf1806c439929bf0fe68",
        current_stage=OrchestrationStage.ADMITTED,
        resumable_stage=OrchestrationStage.ADMITTED,
        human_gate=None,
        is_active=True,
        current_generation=1,
    )

    in_memory_uow.orchestration_runs.save(run)
    fetched = in_memory_uow.orchestration_runs.get_by_id("run-101")
    assert fetched is not None
    assert fetched.run_id == "run-101"
    assert fetched.current_stage == OrchestrationStage.ADMITTED
    assert fetched.is_active is True

    # Active run lookup
    active = in_memory_uow.orchestration_runs.get_active_run(
        "mini-me", "008-autonomous-change-orchestration"
    )
    assert active is not None
    assert active.run_id == "run-101"

    # Enforce active duplicate run rejection
    duplicate_run = OrchestrationRun(
        run_id="run-102",
        project_id="mini-me",
        change_name="008-autonomous-change-orchestration",
        base_sha="61eb4bfdabf0e7612090bf1806c439929bf0fe68",
        current_stage=OrchestrationStage.ADMITTED,
        resumable_stage=OrchestrationStage.ADMITTED,
        is_active=True,
    )
    with pytest.raises(ValueError, match="active orchestration run already exists"):
        in_memory_uow.orchestration_runs.save(duplicate_run)

    # Deactivating run-101 allows a new active run
    in_memory_uow.orchestration_runs.update_stop_outcome(
        "run-101",
        stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
        human_gate=HumanGate.READY_FOR_HUMAN_MERGE,
        stop_reason="Done",
        is_active=False,
    )
    in_memory_uow.orchestration_runs.save(duplicate_run)
    assert (
        in_memory_uow.orchestration_runs.get_active_run(
            "mini-me", "008-autonomous-change-orchestration"
        ).run_id
        == "run-102"
    )


def test_orchestration_candidate_generations_and_supersede(in_memory_uow):
    cand1 = OrchestrationCandidate(
        run_id="run-101",
        generation=1,
        base_sha="base-sha-1",
        candidate_sha="cand-sha-1",
        manifest_hash="hash-1",
        is_frozen=True,
    )
    in_memory_uow.orchestration_candidates.save(cand1)

    latest = in_memory_uow.orchestration_candidates.get_latest_for_run("run-101")
    assert latest is not None
    assert latest.generation == 1
    assert latest.candidate_sha == "cand-sha-1"

    # Save generation 2 and supersede generation 1
    cand2 = OrchestrationCandidate(
        run_id="run-101",
        generation=2,
        base_sha="base-sha-1",
        candidate_sha="cand-sha-2",
        manifest_hash="hash-2",
        is_frozen=True,
    )
    in_memory_uow.orchestration_candidates.save(cand2)
    in_memory_uow.orchestration_candidates.supersede(cand1.candidate_id, cand2.candidate_id)

    updated_cand1 = in_memory_uow.orchestration_candidates.get_by_id(cand1.candidate_id)
    assert updated_cand1.superseded_by_id == cand2.candidate_id

    latest2 = in_memory_uow.orchestration_candidates.get_latest_for_run("run-101")
    assert latest2.generation == 2
    assert latest2.candidate_sha == "cand-sha-2"


def test_orchestration_external_action_reservation(in_memory_uow):
    action = OrchestrationExternalAction(
        run_id="run-101",
        action_key="push:run-101:gen1:cand-sha-1",
        action_type=ExternalActionType.BRANCH_PUSH,
        target_identity="silverberdi/mini-me:minime/008-autonomous-change-orchestration",
        request_fingerprint="push:cand-sha-1",
        candidate_sha="cand-sha-1",
        generation=1,
        status=ExternalActionStatus.RESERVED,
    )
    in_memory_uow.orchestration_external_actions.reserve(action)

    fetched = in_memory_uow.orchestration_external_actions.get_by_action_key(
        "push:run-101:gen1:cand-sha-1"
    )
    assert fetched is not None
    assert fetched.status == ExternalActionStatus.RESERVED

    # Reject duplicate action key reservation
    with pytest.raises(ValueError, match="already exists"):
        in_memory_uow.orchestration_external_actions.reserve(action)

    # Update status to completed
    updated = in_memory_uow.orchestration_external_actions.update_status(
        "push:run-101:gen1:cand-sha-1",
        ExternalActionStatus.COMPLETED,
        remote_identifier="refs/heads/minime/008-autonomous-change-orchestration",
    )
    assert updated.status == ExternalActionStatus.COMPLETED
    assert updated.remote_identifier == "refs/heads/minime/008-autonomous-change-orchestration"
    assert updated.reconciled_at is not None


def test_sqlite_postgres_repositories_roundtrip():
    """Verify SQLAlchemy model mapping with SQLite in-memory engine for fast ORM tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        proj_repo = PostgresProjectRepository(session)
        proj_repo.save(
            Project(
                project_id="mini-me",
                display_name="Mini Me",
                repository="silverberdi/mini-me",
                base_branch="main",
                status=ProjectStatus.ACTIVE,
            )
        )
        session.commit()

        run_repo = PostgresOrchestrationRunRepository(session)
        cand_repo = PostgresOrchestrationCandidateRepository(session)
        action_repo = PostgresOrchestrationExternalActionRepository(session)
        event_repo = PostgresOrchestrationStageEventRepository(session)

        run = OrchestrationRun(
            run_id="run-pg-1",
            project_id="mini-me",
            change_name="008-orchestration",
            base_sha="base-1",
            current_stage=OrchestrationStage.ADMITTED,
            resumable_stage=OrchestrationStage.ADMITTED,
            is_active=True,
        )
        run_repo.save(run)
        session.commit()

        saved_run = run_repo.get_by_id("run-pg-1")
        assert saved_run is not None
        assert saved_run.current_stage == OrchestrationStage.ADMITTED

        cand = OrchestrationCandidate(
            run_id="run-pg-1",
            generation=1,
            base_sha="base-1",
            candidate_sha="sha-1",
            manifest_hash="hash-1",
            is_frozen=True,
        )
        cand_repo.save(cand)
        session.commit()

        saved_cand = cand_repo.get_latest_for_run("run-pg-1")
        assert saved_cand is not None
        assert saved_cand.candidate_sha == "sha-1"

        action = OrchestrationExternalAction(
            run_id="run-pg-1",
            action_key="pr:run-pg-1:gen1:sha-1",
            action_type=ExternalActionType.PR_CREATE,
            target_identity="silverberdi/mini-me:branch",
            request_fingerprint="pr:sha-1",
            candidate_sha="sha-1",
            generation=1,
            status=ExternalActionStatus.RESERVED,
        )
        action_repo.reserve(action)
        session.commit()

        saved_action = action_repo.get_by_action_key("pr:run-pg-1:gen1:sha-1")
        assert saved_action is not None
        assert saved_action.status == ExternalActionStatus.RESERVED

        event_repo.save(
            OrchestrationStageEvent(
                run_id="run-pg-1",
                from_stage=OrchestrationStage.ADMITTED,
                to_stage=OrchestrationStage.PREPARING_EXECUTION,
                event_type="STAGE_TRANSITION",
                transition_key="run-pg-1:ADMITTED:PREPARING_EXECUTION",
            )
        )
        session.commit()

        events = event_repo.list_by_run("run-pg-1")
        assert len(events) == 1
        assert events[0].to_stage == OrchestrationStage.PREPARING_EXECUTION
