"""PostgreSQL adversarial tests for Scheduler admission serialization & concurrency (T01-T04)."""

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Generator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    AdmissionDecision,
    AdmissionRefusalCode,
    ChangeStatus,
    ProviderHealthStatus,
    QueuePriority,
    ReadinessState,
    WorkItemStatus,
)
from minime.domain.models import (
    BacklogItem,
    Change,
    Project,
    ProjectBinding,
    ProviderHealth,
    WorkQueueItem,
    utc_now,
)
from minime.services.scheduler_service import SchedulerService


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


@pytest.fixture(autouse=True)
def _clean_db(pg_engine: Engine):
    from sqlalchemy import text
    with pg_engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    Base.metadata.create_all(pg_engine)


def _seed_project_and_change(
    session_factory: sessionmaker[Session],
    project_id: str = "proj-concurrency",
    change_name: str = "change-concurrency",
    issue_number: int = 101,
    max_concurrent_jobs: int = 1,
    project_root: Path | None = None,
) -> None:
    if project_root:
        cdir = project_root / "openspec" / "changes" / change_name
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "proposal.md").write_text("# Proposal")
        (cdir / "tasks.md").write_text("# Tasks")
        (cdir / "design.md").write_text("# Design")
        (cdir / "specs").mkdir(exist_ok=True)
        (cdir / "specs" / "test.md").write_text("# Spec")
        import subprocess
        if not (project_root / ".git").exists():
            subprocess.run(["git", "init", str(project_root)], check=False, capture_output=True)
            subprocess.run(["git", "-C", str(project_root), "checkout", "-b", "main"], check=False, capture_output=True)
            subprocess.run(["git", "-C", str(project_root), "config", "user.name", "Test"], check=False, capture_output=True)
            subprocess.run(["git", "-C", str(project_root), "config", "user.email", "test@example.com"], check=False, capture_output=True)
        subprocess.run(["git", "-C", str(project_root), "add", "."], check=False, capture_output=True)
        subprocess.run(["git", "-C", str(project_root), "commit", "--allow-empty", "-m", f"seed {change_name}"], check=False, capture_output=True)
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        proj = Project(
            project_id=project_id,
            display_name=f"Project {project_id}",
            repository="owner/repo",
            base_branch="main",
            implementer="codex",
            reviewer="antigravity",
            max_concurrent_jobs=max_concurrent_jobs,
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

        for provider in ["codex", "antigravity"]:
            uow.provider_health.save(
                ProviderHealth(
                    health_id=f"ph-{provider}",
                    provider=provider,
                    status=ProviderHealthStatus.AVAILABLE,
                )
            )
        uow.commit()


def _make_scheduler(
    uow: PostgresPersistenceUnitOfWork,
    tmp_path: Path,
    _test_global_max_jobs_override: int | None = None,
) -> SchedulerService:
    from unittest.mock import MagicMock

    from minime.domain.models import ReadinessEvaluation
    mock_readiness = MagicMock()
    eval_res = ReadinessEvaluation(
        project_id="proj",
        change_id="ch-1",
        change_name="change",
        is_ready=True,
        status=ReadinessState.READY,
        unmet_reasons=[],
        checks=[],
    )
    mock_readiness.evaluate_change_readiness.return_value = eval_res
    mock_readiness.evaluate_change_readiness_pure.return_value = eval_res
    return SchedulerService(
        uow,
        project_root=tmp_path,
        _test_global_max_jobs_override=_test_global_max_jobs_override,
        readiness_service=mock_readiness,
    )


def test_t01_same_change_savepoint_recovery(pg_session_factory: sessionmaker[Session], tmp_path: Path):
    """T01: Prove same-change Savepoint conflict recovery on uq_active_orchestration_run.

    Two concurrent threads attempt to admit the exact same change.
    One caller succeeds in creating active run, second caller hits uq_active_orchestration_run
    and recovers via Pattern A Savepoint to return REFUSED with CHANGE_ALREADY_ACTIVE.
    """
    project_id = "t01-proj"
    change_name = "t01-change"
    _seed_project_and_change(pg_session_factory, project_id, change_name, project_root=tmp_path)

    results: list[tuple[AdmissionDecision, Any, Any]] = [None, None]  # type: ignore

    def worker(idx: int):
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            scheduler = _make_scheduler(uow, tmp_path, _test_global_max_jobs_override=5)
            dec, rec, run = scheduler.admit_work_item(project_id, change_name)
            results[idx] = (dec, rec, run)

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    decisions = [r[0] for r in results]
    assert AdmissionDecision.ADMITTED in decisions
    assert AdmissionDecision.REFUSED in decisions

    refused_rec = [r[1] for r in results if r[0] == AdmissionDecision.REFUSED][0]
    assert refused_rec.reason_code == AdmissionRefusalCode.CHANGE_ALREADY_ACTIVE


def test_t02_project_concurrency_limit(pg_session_factory: sessionmaker[Session], tmp_path: Path):
    """T02: Prove project concurrency limit (max_concurrent_jobs=1) under advisory locks.

    Two different changes for the same project are admitted concurrently.
    The first change gets admitted; the second change is refused with PROJECT_CONCURRENCY_LIMIT.
    """
    project_id = "t02-proj"
    _seed_project_and_change(pg_session_factory, project_id, "c1", issue_number=1, max_concurrent_jobs=1, project_root=tmp_path)
    _seed_project_and_change(pg_session_factory, project_id, "c2", issue_number=2, max_concurrent_jobs=1, project_root=tmp_path)

    results: list[tuple[AdmissionDecision, Any, Any]] = [None, None]  # type: ignore

    def worker(idx: int, cname: str):
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            scheduler = _make_scheduler(uow, tmp_path, _test_global_max_jobs_override=5)
            dec, rec, run = scheduler.admit_work_item(project_id, cname)
            results[idx] = (dec, rec, run)

    t1 = threading.Thread(target=worker, args=(0, "c1"))
    t2 = threading.Thread(target=worker, args=(1, "c2"))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    decisions = [r[0] for r in results]
    assert AdmissionDecision.ADMITTED in decisions
    assert AdmissionDecision.REFUSED in decisions

    refused_rec = [r[1] for r in results if r[0] == AdmissionDecision.REFUSED][0]
    assert refused_rec.reason_code == AdmissionRefusalCode.PROJECT_CONCURRENCY_LIMIT


def test_t03_global_concurrency_limit(pg_session_factory: sessionmaker[Session], tmp_path: Path):
    """T03: Prove canonical global concurrency limit (max_global_jobs=1) under advisory locks without test override.

    Two changes in different projects are admitted concurrently under normal production construction.
    The first caller succeeds; the second receives GLOBAL_CONCURRENCY_LIMIT.
    """
    _seed_project_and_change(pg_session_factory, "t03-p1", "c1", issue_number=1, max_concurrent_jobs=5, project_root=tmp_path)
    _seed_project_and_change(pg_session_factory, "t03-p2", "c2", issue_number=2, max_concurrent_jobs=5, project_root=tmp_path)

    results: list[tuple[AdmissionDecision, Any, Any]] = [None, None]  # type: ignore

    def worker(idx: int, pid: str, cname: str):
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            # Production construction with no override -> enforces max_global_jobs = 1
            scheduler = _make_scheduler(uow, tmp_path)
            assert scheduler.max_global_jobs == 1
            dec, rec, run = scheduler.admit_work_item(pid, cname)
            results[idx] = (dec, rec, run)

    t1 = threading.Thread(target=worker, args=(0, "t03-p1", "c1"))
    t2 = threading.Thread(target=worker, args=(1, "t03-p2", "c2"))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    decisions = [r[0] for r in results]
    assert AdmissionDecision.ADMITTED in decisions
    assert AdmissionDecision.REFUSED in decisions

    refused_rec = [r[1] for r in results if r[0] == AdmissionDecision.REFUSED][0]
    assert refused_rec.reason_code == AdmissionRefusalCode.GLOBAL_CONCURRENCY_LIMIT


def test_t04_project_limit_multi_slot(pg_session_factory: sessionmaker[Session], tmp_path: Path):
    """T04: Prove project concurrency limit > 1 (max_concurrent_jobs=2) allows multi-slot admission when global limit is explicitly overridden.

    Two different changes for the same project with max_concurrent_jobs=2 and _test_global_max_jobs_override=5.
    Both changes are successfully admitted.
    """
    project_id = "t04-proj"
    _seed_project_and_change(pg_session_factory, project_id, "c1", issue_number=1, max_concurrent_jobs=2, project_root=tmp_path)
    _seed_project_and_change(pg_session_factory, project_id, "c2", issue_number=2, max_concurrent_jobs=2, project_root=tmp_path)

    results: list[tuple[AdmissionDecision, Any, Any]] = [None, None]  # type: ignore

    def worker(idx: int, cname: str):
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            scheduler = _make_scheduler(uow, tmp_path, _test_global_max_jobs_override=5)
            dec, rec, run = scheduler.admit_work_item(project_id, cname)
            results[idx] = (dec, rec, run)

    t1 = threading.Thread(target=worker, args=(0, "c1"))
    t2 = threading.Thread(target=worker, args=(1, "c2"))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results[0][0] == AdmissionDecision.ADMITTED
    assert results[1][0] == AdmissionDecision.ADMITTED


def test_f04_scheduler_global_concurrency_immutability_regression(pg_session_factory: sessionmaker[Session], tmp_path: Path):
    """F04: Prove max_global_jobs parameter is ignored in production construction and only _test_global_max_jobs_override can set >1."""
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        s1 = SchedulerService(uow, project_root=tmp_path, max_global_jobs=999)
        assert s1.max_global_jobs == 1

        s2 = SchedulerService(uow, project_root=tmp_path, _test_global_max_jobs_override=5)
        assert s2.max_global_jobs == 5
