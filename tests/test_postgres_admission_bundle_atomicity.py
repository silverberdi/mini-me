"""PostgreSQL adversarial tests for admission bundle atomicity (T05)."""

import os
import subprocess
import time
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
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
    yield engine
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


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
    cdir = tmp_path / "openspec" / "changes" / change_name
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "proposal.md").write_text("# Proposal")
    (cdir / "tasks.md").write_text("# Tasks")
    (cdir / "design.md").write_text("# Design")
    (cdir / "specs").mkdir(exist_ok=True)
    (cdir / "specs" / "test.md").write_text("# Spec")
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=False, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-b", "main"], check=False, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=False, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=False, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"], check=False, capture_output=True)

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
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
        mock_readiness.evaluate_change_readiness.return_value = ReadinessEvaluation(
            project_id=project_id,
            change_id=f"ch-{project_id}-{change_name}",
            change_name=change_name,
            is_ready=True,
            status=ReadinessState.READY,
            unmet_reasons=[],
            checks=[],
        )
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
