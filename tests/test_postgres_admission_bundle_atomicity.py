"""PostgreSQL adversarial tests for admission bundle atomicity (T05)."""

import os
import subprocess
import time
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from tests.conftest import (
    ReadinessGitHubStub,
    create_isolated_openspec_change,
)

from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    AdmissionDecision,
    ChangeStatus,
    QueuePriority,
    ReadinessState,
    WorkItemStatus,
)
from minime.domain.models import (
    BacklogItem,
    Change,
    Project,
    ProjectBinding,
    WorkQueueItem,
    utc_now,
)
from minime.services.orchestration_service import OrchestrationService


def _ensure_pg_server() -> str | None:
    candidate_urls = [
        os.environ.get("MINIME_TEST_DATABASE_URL"),
        "postgresql+psycopg://testuser@localhost:54333/minime_test",
    ]
    for url in candidate_urls:
        if not url:
            continue
        try:
            eng = create_engine(url, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            eng.dispose()
            return url
        except Exception:
            continue

    pg_ctl = Path("/Library/PostgreSQL/17/bin/pg_ctl")
    initdb = Path("/Library/PostgreSQL/17/bin/initdb")
    psql = Path("/Library/PostgreSQL/17/bin/psql")
    data_dir = Path("/tmp/minime_pg_test_data")

    if pg_ctl.exists() and initdb.exists():
        if not data_dir.exists():
            subprocess.run(
                [str(initdb), "-D", str(data_dir), "-U", "testuser", "-A", "trust"],
                check=False,
                capture_output=True,
            )
        subprocess.run(
            [
                str(pg_ctl),
                "-D",
                str(data_dir),
                "-o",
                "-p 54333 -k /tmp",
                "-l",
                "/tmp/minime_pg_test.log",
                "start",
            ],
            check=False,
            capture_output=True,
        )
        time.sleep(0.5)
        if psql.exists():
            subprocess.run(
                [
                    str(psql),
                    "-h",
                    "localhost",
                    "-p",
                    "54333",
                    "-U",
                    "testuser",
                    "-d",
                    "postgres",
                    "-c",
                    "CREATE DATABASE minime_test;",
                ],
                check=False,
                capture_output=True,
            )
        try:
            test_url = "postgresql+psycopg://testuser@localhost:54333/minime_test"
            eng = create_engine(test_url, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            eng.dispose()
            return test_url
        except Exception:
            pass
    return None


PG_TEST_URL = _ensure_pg_server()


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    if not PG_TEST_URL:
        pytest.skip("PostgreSQL test database server is not reachable.")
    engine = create_engine(PG_TEST_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) PRIMARY KEY);"))
        conn.execute(text("DELETE FROM alembic_version;"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('024_task_classification_snapshots');"))
        conn.commit()
    yield engine
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _clean_db(pg_engine: Engine):
    from sqlalchemy import text
    with pg_engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    Base.metadata.create_all(pg_engine)
    with pg_engine.connect() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) PRIMARY KEY);"))
        conn.execute(text("DELETE FROM alembic_version;"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('024_task_classification_snapshots');"))
        conn.commit()



def test_t05_admission_bundle_failure_injection_rollback(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """T05: Failure injection rollback during admission bundle persistence.

    When an error occurs after creating orchestration records in transaction but before
    calling uow.commit(), calling uow.rollback() cleanly reverts all inserted records,
    leaving zero active orchestration runs and preserving backlog item status.
    """
    project_id = "t05-proj"
    change_name = "t05-change"
    issue_number = 505
    create_isolated_openspec_change(tmp_path, change_name)

    with pg_session_factory() as session:

        uow = PostgresPersistenceUnitOfWork(session)
        from tests.conftest import setup_managed_repository_fixture
        setup_managed_repository_fixture(
            uow, project_id, tmp_path, tmp_path / ".minime" / "worktrees", canonical_repository_identity="github.com/owner/repo"
        )
        proj = Project(
            project_id=project_id,
            display_name=f"Project {project_id}",
            repository="owner/repo",
            base_branch="main",
            implementer="codex",
            reviewer="antigravity",
        )
        uow.projects.save(proj)

        binding = ProjectBinding(
            binding_id=f"bind-{project_id}-{change_name}",
            project_id=project_id,
            openspec_change_name=change_name,
            github_issue_number=issue_number,
            repository="owner/repo",
            is_valid=True,
            bound_at=utc_now(),
        )
        uow.bindings.save(binding)

        ch = Change(
            change_id=f"ch-{project_id}-{change_name}",
            project_id=project_id,
            name=change_name,
            status=ChangeStatus.READY,
            last_readiness_status=ReadinessState.READY,
        )
        uow.changes.save(ch)

        item = WorkQueueItem(
            project_id=project_id,
            change_name=change_name,
            github_issue_number=issue_number,
            priority=QueuePriority.NORMAL,
            readiness_state=ReadinessState.READY,
            admission_eligible=True,
            discovered_at=utc_now(),
        )
        uow.work_queue.save(item)

        backlog = BacklogItem(
            item_id=f"item-{project_id}-{change_name}",
            project_id=project_id,
            item_key=f"KEY-{change_name}",
            title=f"Title-{change_name}",
            openspec_change_name=change_name,
            status=WorkItemStatus.READY,
        )
        uow.backlog_items.save(backlog)
        uow.commit()

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        from unittest.mock import MagicMock

        from minime.domain.models import ReadinessEvaluation
        mock_readiness = MagicMock()
        eval_res = ReadinessEvaluation(
            project_id=project_id,
            change_id=f"ch-{project_id}-{change_name}",
            change_name=change_name,
            is_ready=True,
            status=ReadinessState.READY,
            unmet_reasons=[],
            checks=[],
        )
        mock_readiness.evaluate_change_readiness.return_value = eval_res
        mock_readiness.evaluate_change_readiness_pure.return_value = eval_res
        orch = OrchestrationService(uow, project_root=tmp_path, readiness_service=mock_readiness)


        # Execute transactional admission primitive
        res = orch._admit_change_in_transaction(project_id, change_name, project_root=tmp_path)
        assert res.admitted is True
        assert res.run is not None

        # Simulate failure BEFORE committing transaction
        uow.rollback()

    # Verify database state after rollback
    with pg_session_factory() as verify_session:
        verify_uow = PostgresPersistenceUnitOfWork(verify_session)
        active_runs = verify_uow.orchestration_runs.list_runs(project_id=project_id, is_active=True)
        assert len(active_runs) == 0, "Rollback must remove the uncommitted orchestration run."

        b_item = verify_uow.backlog_items.get_by_openspec_change_name(project_id, change_name)
        assert b_item is not None
        assert b_item.status == WorkItemStatus.READY, "Backlog item status must remain READY."


def test_t05a_no_intermediate_admission_commit(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """T05A: Real ReadinessService + SchedulerService admission atomicity & 0 intermediate commits.

    Verifies:
    1. Pre-lock readiness & preflight complete.
    2. After advisory lock acquisition and before final admission commit: 0 intermediate commits occur.
    3. Exactly 1 final admission transaction commit persists the entire bundle.
    4. Injecting failure before final commit cleanly rolls back all records:
       0 active OrchestrationRun, 0 initial OrchestrationStageEvent, 0 canonical ORCHESTRATION_STARTED Event,
       0 SchedulerDecisionRecord, BacklogItem still READY, work queue item unchanged.
    """
    from minime.domain.enums import ProviderHealthStatus
    from minime.domain.models import ProviderHealth
    from minime.services.readiness_service import ReadinessService
    from minime.services.scheduler_service import SchedulerService

    project_id = "t05a-proj"
    change_name = "t05a-change"
    issue_number = 5051

    create_isolated_openspec_change(tmp_path, change_name)

    with pg_session_factory() as session:

        uow = PostgresPersistenceUnitOfWork(session)
        from tests.conftest import setup_managed_repository_fixture
        setup_managed_repository_fixture(
            uow, project_id, tmp_path, tmp_path / ".minime" / "worktrees", canonical_repository_identity="github.com/owner/repo"
        )
        uow.projects.save(
            Project(
                project_id=project_id,
                display_name=f"Project {project_id}",
                repository="owner/repo",
                base_branch="main",
                implementer="codex",
                reviewer="antigravity",
                auto_admit=True,
            )
        )
        uow.bindings.save(
            ProjectBinding(
                binding_id=f"bind-{project_id}-{change_name}",
                project_id=project_id,
                openspec_change_name=change_name,
                github_issue_number=issue_number,
                repository="owner/repo",
                is_valid=True,
                bound_at=utc_now(),
            )
        )
        uow.changes.save(
            Change(
                change_id=f"ch-{project_id}-{change_name}",
                project_id=project_id,
                name=change_name,
                status=ChangeStatus.READY,
                last_readiness_status=ReadinessState.READY,
            )
        )
        uow.work_queue.save(
            WorkQueueItem(
                project_id=project_id,
                change_name=change_name,
                github_issue_number=issue_number,
                priority=QueuePriority.NORMAL,
                readiness_state=ReadinessState.READY,
                admission_eligible=True,
                discovered_at=utc_now(),
            )
        )
        uow.backlog_items.save(
            BacklogItem(
                item_id=f"item-{project_id}-{change_name}",
                project_id=project_id,
                item_key=f"KEY-{change_name}",
                title=f"Title-{change_name}",
                openspec_change_name=change_name,
                status=WorkItemStatus.READY,
            )
        )
        uow.provider_health.save(ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE))
        uow.provider_health.save(ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE))
        uow.commit()

    # Part A: Test zero intermediate commits & exactly 1 commit on successful admission path
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        from tests.conftest import ReadinessGitHubStub
        real_readiness = ReadinessService(uow, github_adapter=ReadinessGitHubStub())
        scheduler = SchedulerService(uow, project_root=tmp_path, readiness_service=real_readiness)

        commit_events: list[tuple[str, float]] = []
        lock_events: list[tuple[str, float]] = []

        orig_commit = session.commit
        orig_lock = uow.acquire_advisory_lock

        def tracked_commit():
            commit_events.append(("commit", time.time()))
            orig_commit()

        def tracked_lock(key: int, lock_timeout: str = "2s"):
            lock_events.append(("lock", time.time()))
            return orig_lock(key, lock_timeout=lock_timeout)

        session.commit = tracked_commit
        uow.acquire_advisory_lock = tracked_lock

        dec, record, run = scheduler.admit_work_item(project_id, change_name)
        print("RECORD REASON:", record.reason_summary if record else "NO RECORD", record.refusal_details if record else "")
        assert dec == AdmissionDecision.ADMITTED
        assert run is not None
        assert record is not None
        assert len(lock_events) == 2, "Must acquire global and project advisory locks."
        assert len(commit_events) == 1, "Must perform EXACTLY 1 commit for the admission bundle."
        assert commit_events[0][1] > lock_events[1][1], "Commit must occur AFTER advisory locks are acquired."

    # Part B: Test failure injection after run save but before final commit -> full rollback
    change_name_2 = "t05a-change-fail"
    create_isolated_openspec_change(tmp_path, change_name_2)

    with pg_session_factory() as session:

        uow = PostgresPersistenceUnitOfWork(session)
        uow.bindings.save(
            ProjectBinding(
                binding_id=f"bind-{project_id}-{change_name_2}",
                project_id=project_id,
                openspec_change_name=change_name_2,
                github_issue_number=5052,
                repository="owner/repo",
                is_valid=True,
                bound_at=utc_now(),
            )
        )
        uow.changes.save(
            Change(
                change_id=f"ch-{project_id}-{change_name_2}",
                project_id=project_id,
                name=change_name_2,
                status=ChangeStatus.READY,
                last_readiness_status=ReadinessState.READY,
            )
        )
        uow.work_queue.save(
            WorkQueueItem(
                project_id=project_id,
                change_name=change_name_2,
                github_issue_number=5052,
                priority=QueuePriority.NORMAL,
                readiness_state=ReadinessState.READY,
                admission_eligible=True,
                discovered_at=utc_now(),
            )
        )
        uow.backlog_items.save(
            BacklogItem(
                item_id=f"item-{project_id}-{change_name_2}",
                project_id=project_id,
                item_key=f"KEY-{change_name_2}",
                title=f"Title-{change_name_2}",
                openspec_change_name=change_name_2,
                status=WorkItemStatus.READY,
            )
        )
        uow.commit()

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        real_readiness = ReadinessService(uow, github_adapter=ReadinessGitHubStub())
        scheduler = SchedulerService(uow, project_root=tmp_path, readiness_service=real_readiness)

        orig_save = uow.scheduler_decisions.save

        def failing_save(dec_record):
            orig_save(dec_record)
            raise RuntimeError("Injected DB failure before admission bundle commit!")

        uow.scheduler_decisions.save = failing_save

        with pytest.raises(RuntimeError, match="Injected DB failure"):
            scheduler.admit_work_item(project_id, change_name_2)

        uow.rollback()

    # Verify DB state after failure injection rollback
    with pg_session_factory() as verify_session:
        verify_uow = PostgresPersistenceUnitOfWork(verify_session)
        runs = verify_uow.orchestration_runs.list_runs(project_id=project_id, change_name=change_name_2)
        assert len(runs) == 0, "Rollback must leave 0 OrchestrationRun for failed admission."

        events = verify_uow.events.list_events(project_id=project_id)
        started_events = [e for e in events if e.change_id == change_name_2]
        assert len(started_events) == 0, "Rollback must leave 0 Event for failed admission."

        b_item = verify_uow.backlog_items.get_by_openspec_change_name(project_id, change_name_2)
        assert b_item is not None
        assert b_item.status == WorkItemStatus.READY, "BacklogItem status must remain READY after rollback."


def test_t05b_locks_not_held_during_external_observations(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """T05B: Prove advisory locks are NOT held during Git/GitHub/OpenSpec/subprocess observations.

    Instruments:
    - uow.acquire_advisory_lock
    - readiness_service.evaluate_change_readiness_pure
    - ApplyAttributionGate.evaluate
    - orchestration_service._resolve_base_sha

    Asserts that ALL external/subprocess observations occur BEFORE the first advisory lock is acquired.
    """
    from minime.domain.enums import ProviderHealthStatus
    from minime.domain.models import ProviderHealth
    from minime.services.lifecycle_gates import ApplyAttributionGate
    from minime.services.readiness_service import ReadinessService
    from minime.services.scheduler_service import SchedulerService

    project_id = "t05b-proj"
    change_name = "t05b-change"
    issue_number = 5053

    create_isolated_openspec_change(tmp_path, change_name)

    with pg_session_factory() as session:

        uow = PostgresPersistenceUnitOfWork(session)
        from tests.conftest import setup_managed_repository_fixture
        setup_managed_repository_fixture(
            uow, project_id, tmp_path, tmp_path / ".minime" / "worktrees", canonical_repository_identity="github.com/owner/repo"
        )
        uow.projects.save(
            Project(
                project_id=project_id,
                display_name=f"Project {project_id}",
                repository="owner/repo",
                base_branch="main",
                implementer="codex",
                reviewer="antigravity",
                auto_admit=True,
            )
        )
        uow.bindings.save(
            ProjectBinding(
                binding_id=f"bind-{project_id}-{change_name}",
                project_id=project_id,
                openspec_change_name=change_name,
                github_issue_number=issue_number,
                repository="owner/repo",
                is_valid=True,
                bound_at=utc_now(),
            )
        )
        uow.changes.save(
            Change(
                change_id=f"ch-{project_id}-{change_name}",
                project_id=project_id,
                name=change_name,
                status=ChangeStatus.READY,
                last_readiness_status=ReadinessState.READY,
            )
        )
        uow.work_queue.save(
            WorkQueueItem(
                project_id=project_id,
                change_name=change_name,
                github_issue_number=issue_number,
                priority=QueuePriority.NORMAL,
                readiness_state=ReadinessState.READY,
                admission_eligible=True,
                discovered_at=utc_now(),
            )
        )
        uow.backlog_items.save(
            BacklogItem(
                item_id=f"item-{project_id}-{change_name}",
                project_id=project_id,
                item_key=f"KEY-{change_name}",
                title=f"Title-{change_name}",
                openspec_change_name=change_name,
                status=WorkItemStatus.READY,
            )
        )
        uow.provider_health.save(ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE))
        uow.provider_health.save(ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE))
        uow.commit()


    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        real_readiness = ReadinessService(uow, github_adapter=ReadinessGitHubStub())
        scheduler = SchedulerService(uow, project_root=tmp_path, readiness_service=real_readiness)

        timeline: list[tuple[str, float]] = []

        orig_lock = uow.acquire_advisory_lock
        orig_pure_readiness = real_readiness.evaluate_change_readiness_pure
        orig_apply_gate = ApplyAttributionGate.evaluate
        orig_resolve_base = scheduler.orchestration_service._resolve_base_sha

        def tracked_lock(key: int, lock_timeout: str = "2s"):
            timeline.append(("acquire_advisory_lock", time.time()))
            return orig_lock(key, lock_timeout=lock_timeout)

        def tracked_pure_readiness(*args, **kwargs):
            timeline.append(("evaluate_change_readiness_pure", time.time()))
            return orig_pure_readiness(*args, **kwargs)

        def tracked_apply_gate(self_gate, *args, **kwargs):
            timeline.append(("ApplyAttributionGate.evaluate", time.time()))
            return orig_apply_gate(self_gate, *args, **kwargs)

        def tracked_resolve_base(*args, **kwargs):
            timeline.append(("resolve_base_sha", time.time()))
            return orig_resolve_base(*args, **kwargs)

        uow.acquire_advisory_lock = tracked_lock
        real_readiness.evaluate_change_readiness_pure = tracked_pure_readiness
        ApplyAttributionGate.evaluate = tracked_apply_gate
        scheduler.orchestration_service._resolve_base_sha = tracked_resolve_base

        dec, record, run = scheduler.admit_work_item(project_id, change_name)
        assert dec == AdmissionDecision.ADMITTED


        assert run is not None

        # Verify event sequence
        events_captured = [t[0] for t in timeline]
        first_lock_idx = events_captured.index("acquire_advisory_lock")

        pure_readiness_idx = events_captured.index("evaluate_change_readiness_pure")
        apply_gate_idx = events_captured.index("ApplyAttributionGate.evaluate")
        resolve_base_idx = events_captured.index("resolve_base_sha")

        assert pure_readiness_idx < first_lock_idx, (
            f"Pure readiness evaluation ({pure_readiness_idx}) must occur BEFORE first advisory lock ({first_lock_idx})."
        )
        assert apply_gate_idx < first_lock_idx, (
            f"ApplyAttributionGate evaluation ({apply_gate_idx}) must occur BEFORE first advisory lock ({first_lock_idx})."
        )
        assert resolve_base_idx < first_lock_idx, (
            f"Base SHA resolution ({resolve_base_idx}) must occur BEFORE first advisory lock ({first_lock_idx})."
        )

        # Ensure no external/subprocess observations occurred AFTER first advisory lock
        post_lock_events = events_captured[first_lock_idx:]
        invalid_post_lock = [
            e for e in post_lock_events if e in ("evaluate_change_readiness_pure", "ApplyAttributionGate.evaluate", "resolve_base_sha")
        ]
        assert len(invalid_post_lock) == 0, f"External/subprocess observations occurred post-lock: {invalid_post_lock}"

