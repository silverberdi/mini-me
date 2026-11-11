from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import sessionmaker

from minime.db.models import (
    OperatorActionRecordModel,
    OrchestrationRunModel,
    OrchestrationStageEventModel,
    ProjectModel,
)
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import HumanGate, OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import OrchestrationRun, OrchestrationWorktreeOwnership, Project
from minime.services.run_cancellation_service import RunCancellationService

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)


def test_postgres_cancellation_releases_only_target_run_and_preserves_details():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, unrelated_project_id = str(uuid4()), str(uuid4())
    run_id, unrelated_run_id, action_key = str(uuid4()), str(uuid4()), str(uuid4())
    owner = OrchestrationWorktreeOwnership(
        project_id=project_id,
        job_id=f"cancel-job-{uuid4()}",
        run_id=run_id,
        change_name="issue-298-cancel-e2e",
        canonical_worktree_path=f"/tmp/unverified-cancel-e2e-{uuid4()}",
        source_repository_identity="github.com/test/cancel",
        source_base_sha="base-sha",
        branch="issue-298-cancel-e2e",
    )
    session = None
    try:
        with engine.connect() as connection:
            database_name = connection.execute(text("select current_database()")).scalar_one()
            assert "test" in database_name.lower(), "Refusing to write outside a test database"

        session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        session = session_factory()
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(
            Project(project_id=project_id, display_name="Cancellation E2E", repository="test/cancel")
        )
        uow.projects.save(
            Project(
                project_id=unrelated_project_id,
                display_name="Unrelated active project",
                repository="test/unrelated",
            )
        )
        uow.orchestration_runs.save(
            OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name="issue-298-cancel-e2e",
                base_sha="base-sha",
                current_stage=OrchestrationStage.IMPLEMENTING,
                stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                human_gate=HumanGate.NEEDS_HUMAN,
                stop_details={"issue_number": 298, "prior_evidence": {"kept": True}},
                is_active=True,
            )
        )
        uow.orchestration_runs.save(
            OrchestrationRun(
                run_id=unrelated_run_id,
                project_id=unrelated_project_id,
                change_name="unrelated-change",
                base_sha="other-base",
                is_active=True,
            )
        )
        uow.orchestration_worktree_ownerships.save(owner)
        uow.commit()

        result = asyncio.run(
            RunCancellationService(uow).cancel(
                project_id=project_id,
                run_id=run_id,
                reason="Release the stuck project slot",
                actor_identity="operator@example.test",
                source_interface="postgres-e2e",
                idempotency_key=action_key,
            )
        )

        assert result["status"] == "CANCELLED"
        assert result["workspace_cleanup"] == "PENDING"
        cancelled = uow.orchestration_runs.get_by_id(run_id)
        assert cancelled is not None and cancelled.is_active is False
        assert cancelled.stop_outcome == OrchestrationStopOutcome.CANCELLED
        assert cancelled.human_gate is None
        assert cancelled.stop_details["issue_number"] == 298
        assert cancelled.stop_details["prior_evidence"] == {"kept": True}
        assert cancelled.stop_details["cancellation"]["actor"] == "operator@example.test"
        assert uow.orchestration_runs.list_runs(project_id=project_id, is_active=True) == []
        assert [run.run_id for run in uow.orchestration_runs.list_runs(
            project_id=unrelated_project_id, is_active=True
        )] == [unrelated_run_id]

        events = uow.orchestration_stage_events.list_by_run(run_id)
        assert [event.event_type for event in events] == ["RUN_CANCELLED"]
        action = uow.operator_actions.get_by_request_id(action_key)
        assert action is not None
        assert action.result_payload_json["status"] == "CANCELLED"
        assert uow.orchestration_worktree_ownerships.get_by_id(owner.worktree_id) is not None

        repeated = asyncio.run(
            RunCancellationService(uow).cancel(
                project_id=project_id,
                run_id=run_id,
                reason="Release the stuck project slot",
                actor_identity="operator@example.test",
                source_interface="postgres-e2e",
                idempotency_key=action_key,
            )
        )
        assert repeated == result
        assert [event.event_type for event in uow.orchestration_stage_events.list_by_run(run_id)] == [
            "RUN_CANCELLED"
        ]

    finally:
        if session is not None:
            session.rollback()
            session.execute(
                delete(OperatorActionRecordModel).where(
                    OperatorActionRecordModel.action_request_id == action_key
                )
            )
            session.execute(
                delete(OrchestrationStageEventModel).where(
                    OrchestrationStageEventModel.run_id == run_id
                )
            )
            session.execute(delete(OrchestrationRunModel).where(
                OrchestrationRunModel.id.in_([run_id, unrelated_run_id])
            ))
            session.execute(delete(ProjectModel).where(
                ProjectModel.id.in_([project_id, unrelated_project_id])
            ))
            session.commit()
            session.close()
        engine.dispose()
