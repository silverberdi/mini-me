"""PostgreSQL integration proof for real coordinator stage claims (mock-free dispatch boundary)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text, update
from sqlalchemy.orm import sessionmaker

from minime.db.models import RecoveryClaimModel
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import OrchestrationStage
from minime.domain.models import OrchestrationRun, Project, utc_now
from minime.services import orchestration_coordinator as coordinator_module
from minime.services.agent_confinement import process_identity
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)


@pytest.mark.asyncio
async def test_postgres_stage_claim_suppresses_concurrent_and_completed_verify_dispatch(tmp_path):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, run_id = str(uuid4()), str(uuid4())
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    first_session = second_session = None
    try:
        with engine.connect() as connection:
            name = connection.execute(text("select current_database()")).scalar_one()
            assert "test" in name.lower(), "Refusing to write outside a test database"
        first_session, second_session = sessions(), sessions()
        first_uow = PostgresPersistenceUnitOfWork(first_session)
        second_uow = PostgresPersistenceUnitOfWork(second_session)
        first_uow.projects.save(Project(
            project_id=project_id,
            display_name="Stage invocation integration",
            repository="org/stage-invocation-test",
        ))
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name="stage-invocation-test",
            base_sha="main",
            current_stage=OrchestrationStage.VERIFYING,
        )
        first_uow.orchestration_runs.save(run)
        first_uow.commit()

        candidate = tmp_path / "candidate"
        candidate.mkdir()
        subprocess.run(["git", "init", "-q", str(candidate)], check=True)
        subprocess.run(["git", "-C", str(candidate), "config", "user.name", "integration"], check=True)
        subprocess.run(["git", "-C", str(candidate), "config", "user.email", "integration@example.com"], check=True)
        (candidate / "README.md").write_text("candidate\n")
        subprocess.run(["git", "-C", str(candidate), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(candidate), "commit", "-qm", "candidate"], check=True)

        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: first_uow,
            github_adapter=object(),
            worktree_manager=object(),
            agent_runner=object(),
        )
        first = await coordinator._begin_stage_invocation(
            first_uow, run, candidate, "VERIFY"
        )
        concurrent = await coordinator._begin_stage_invocation(
            second_uow, run, candidate, "VERIFY"
        )
        assert first is not None
        assert concurrent is None

        initial_claim = first_uow.claims.get_by_key(first.claim_key)
        coordinator._claim_heartbeat_interval_seconds = 0.01
        observed_heartbeat = []

        async def observe_renewal():
            await asyncio.sleep(0.06)
            with sessions() as observer:
                observed_heartbeat.append(
                    PostgresPersistenceUnitOfWork(observer)
                    .claims.get_by_key(first.claim_key).heartbeat_at
                )

        await coordinator._run_claimed(first_uow, first.claim, observe_renewal)
        assert observed_heartbeat[0] > initial_claim.heartbeat_at

        await coordinator._finish_stage_invocation(
            first_uow, run, first, "COMPLETE", {"summary": "observed native result"}
        )
        reentry = await coordinator._begin_stage_invocation(
            first_uow, run, candidate, "VERIFY"
        )
        assert reentry is None
        events = first_uow.orchestration_stage_events.list_by_run(run_id)
        assert [event.event_type for event in events] == [
            "STAGE_INVOCATION_STARTED", "STAGE_INVOCATION_COMPLETED"
        ]
    finally:
        if first_session is not None:
            first_session.execute(text("delete from orchestration_runs where id = :id"), {"id": run_id})
            first_session.execute(text("delete from projects where id = :id"), {"id": project_id})
            first_session.commit()
            first_session.close()
        if second_session is not None:
            second_session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_postgres_expired_invocation_recovers_once_only_after_processes_are_gone(
    tmp_path, monkeypatch,
):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, run_id = str(uuid4()), str(uuid4())
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    sessions = []

    def exited_process_identity():
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        identity = process_identity(process.pid)
        assert identity.get("status") == "AVAILABLE"
        process.terminate()
        process.wait(timeout=5)
        return identity

    def expire_claim(session, claim_key):
        session.execute(
            update(RecoveryClaimModel)
            .where(RecoveryClaimModel.claim_key == claim_key)
            .values(lease_expires_at=utc_now() - timedelta(seconds=1))
        )
        session.commit()

    try:
        with engine.connect() as connection:
            assert connection.execute(text("select current_database()")).scalar_one().endswith("test")

        candidate = tmp_path / "candidate"
        candidate.mkdir()
        subprocess.run(["git", "init", "-q", str(candidate)], check=True)
        subprocess.run(["git", "-C", str(candidate), "config", "user.name", "integration"], check=True)
        subprocess.run(["git", "-C", str(candidate), "config", "user.email", "integration@example.com"], check=True)
        (candidate / "README.md").write_text("same candidate\n")
        subprocess.run(["git", "-C", str(candidate), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(candidate), "commit", "-qm", "candidate"], check=True)

        coordinator_identity = exited_process_identity()
        first_workflow_identity = exited_process_identity()
        identities = [coordinator_identity]
        real_identity = coordinator_module.process_identity

        def coordinator_identity_for_attempt(pid=None):
            if pid is None and identities:
                return identities.pop(0)
            return real_identity(pid)

        monkeypatch.setattr(coordinator_module, "process_identity", coordinator_identity_for_attempt)
        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: None,
            github_adapter=object(),
            worktree_manager=object(),
            agent_runner=object(),
        )

        first_session = session_factory()
        sessions.append(first_session)
        first_uow = PostgresPersistenceUnitOfWork(first_session)
        first_uow.projects.save(Project(
            project_id=project_id,
            display_name="Stage invocation recovery integration",
            repository="org/stage-invocation-recovery-test",
        ))
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name="stage-invocation-recovery-test",
            base_sha="main",
            current_stage=OrchestrationStage.VERIFYING,
        )
        first_uow.orchestration_runs.save(run)
        first_uow.commit()

        first = await coordinator._begin_stage_invocation(
            first_uow, run, candidate, "VERIFY"
        )
        assert first is not None
        coordinator._observe_stage_process(first_uow, run, first)(first_workflow_identity)
        expire_claim(first_session, first.claim_key)

        recovery_session = session_factory()
        sessions.append(recovery_session)
        recovery_uow = PostgresPersistenceUnitOfWork(recovery_session)
        recovered = await coordinator._begin_stage_invocation(
            recovery_uow, run, candidate, "VERIFY"
        )
        assert recovered is not None
        assert recovered.attempt_id != first.attempt_id
        assert recovered.claim.fence_token > first.claim.fence_token
        assert recovered.recovery_count == 1
        with pytest.raises(RuntimeError, match="stale fence"):
            await coordinator._finish_stage_invocation(
                first_uow, run, first, "COMPLETE", {"summary": "stale worker"}
            )

        second_workflow_identity = exited_process_identity()
        coordinator._observe_stage_process(recovery_uow, run, recovered)(second_workflow_identity)
        expire_claim(recovery_session, recovered.claim_key)

        final_session = session_factory()
        sessions.append(final_session)
        final_uow = PostgresPersistenceUnitOfWork(final_session)
        second_recovery = await coordinator._begin_stage_invocation(
            final_uow, run, candidate, "VERIFY"
        )
        assert second_recovery is None
        events = final_uow.orchestration_stage_events.list_by_run(run_id)
        assert [event.event_type for event in events].count("STAGE_INVOCATION_ABANDONED") == 1
        assert [event.event_type for event in events].count("STAGE_INVOCATION_STARTED") == 2
        assert all(
            event.evidence_references["candidate"] == first.candidate
            for event in events
            if event.event_type in {"STAGE_INVOCATION_STARTED", "STAGE_INVOCATION_ABANDONED"}
        )
    finally:
        cleanup = session_factory()
        try:
            cleanup.execute(
                text("delete from recovery_claims where claim_key like :key"),
                {"key": f"stage-invocation:{run_id}:VERIFY:%"},
            )
            cleanup.execute(text("delete from orchestration_runs where id = :id"), {"id": run_id})
            cleanup.execute(text("delete from projects where id = :id"), {"id": project_id})
            cleanup.commit()
        finally:
            cleanup.close()
            for session in sessions:
                session.close()
            engine.dispose()
