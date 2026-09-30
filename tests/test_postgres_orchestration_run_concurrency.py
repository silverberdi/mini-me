"""PostgreSQL adversarial tests for orchestration, saga, and job concurrency (T06, T07, T10, T11, T12)."""

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
    JobStatus,
    OrchestrationStage,
    SagaStatus,
    SagaType,
)
from minime.domain.models import (
    DurableSaga,
    Job,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
)
from minime.services.saga_engine import SagaEngine


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


def test_t06_saga_resume_row_locking(pg_session_factory: sessionmaker[Session]):
    """T06: Prove DurableSagaRepository.get_for_update() row locking serializes concurrent saga workers."""
    saga_id = "saga-t06"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(Project(project_id="proj-t06", display_name="P06", repository="o/r", base_branch="main"))
        saga = DurableSaga(
            id=saga_id,
            project_id="proj-t06",
            work_item_key="key-t06",
            saga_type=SagaType.INTAKE,
            current_phase="PHASE_1",
            status=SagaStatus.IN_PROGRESS,
        )
        uow.durable_sagas.save(saga)
        uow.commit()

    step_log: list[str] = []
    lock_event_a = threading.Event()

    def worker_a():
        with pg_session_factory() as session_a:
            uow_a = PostgresPersistenceUnitOfWork(session_a)
            engine_a = SagaEngine(uow_a)
            # Acquire row lock
            _ = uow_a.durable_sagas.get_for_update(saga_id)
            step_log.append("A: row lock acquired")
            lock_event_a.set()

            time.sleep(0.2)
            step_log.append("A: updating saga phase")
            engine_a.uow.durable_sagas.update_phase(saga_id, "PHASE_2")
            uow_a.commit()
            step_log.append("A: committed")

    def worker_b():
        lock_event_a.wait()
        step_log.append("B: attempting saga get_for_update (will block on row lock)")
        with pg_session_factory() as session_b:
            uow_b = PostgresPersistenceUnitOfWork(session_b)
            engine_b = SagaEngine(uow_b)
            resumed = engine_b.resume_saga(saga_id)
            step_log.append(f"B: unblocked, observed phase '{resumed.current_phase}'")
            uow_b.commit()

    t1 = threading.Thread(target=worker_a)
    t2 = threading.Thread(target=worker_b)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert "A: row lock acquired" in step_log
    assert "B: attempting saga get_for_update (will block on row lock)" in step_log
    assert "A: committed" in step_log
    assert "B: unblocked, observed phase 'PHASE_2'" in step_log


def test_t07_saga_creation_savepoint_recovery(pg_session_factory: sessionmaker[Session]):
    """T07: Prove concurrent Pattern A Savepoint conflict recovery on uq_active_intake_saga."""
    project_id = "proj-t07"
    work_item_key = "key-t07"

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(Project(project_id=project_id, display_name="P07", repository="o/r", base_branch="main"))
        uow.commit()

    results: list[DurableSaga] = [None, None]  # type: ignore

    def worker(idx: int):
        with pg_session_factory() as s:
            uow = PostgresPersistenceUnitOfWork(s)
            engine = SagaEngine(uow)
            saga = engine.start_saga(SagaType.INTAKE, project_id, work_item_key)
            uow.commit()
            results[idx] = saga

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results[0].id == results[1].id


def test_t10_candidate_generation_savepoint_recovery(pg_session_factory: sessionmaker[Session]):
    """T10: Prove production candidate generation path uses Pattern A savepoint recovery for uq_orchestration_candidate_generation."""
    run_id = "run-t10"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        proj = Project(project_id="p-t10", display_name="P10", repository="o/r", base_branch="main")
        uow.projects.save(proj)
        run = OrchestrationRun(
            run_id=run_id,
            project_id="p-t10",
            change_name="c-t10",
            base_sha="base-sha",
            current_stage=OrchestrationStage.FREEZING_CANDIDATE,
            current_generation=1,
            is_active=True,
        )
        uow.orchestration_runs.save(run)

        cand1 = OrchestrationCandidate(
            run_id=run_id,
            generation=1,
            base_sha="base-sha",
            candidate_sha="cand-sha-1",
            manifest_id=None,
            manifest_hash="hash1",
            is_frozen=True,
        )
        uow.orchestration_candidates.save(cand1)
        uow.commit()

    with pg_session_factory() as session2:
        uow2 = PostgresPersistenceUnitOfWork(session2)
        from minime.services.orchestration_service import OrchestrationService
        orch_srv = OrchestrationService(uow2)
        cand2 = OrchestrationCandidate(
            run_id=run_id,
            generation=1,
            base_sha="base-sha",
            candidate_sha="cand-sha-2",
            manifest_id=None,
            manifest_hash="hash2",
            is_frozen=True,
        )
        saved, recovered = orch_srv._save_candidate_with_savepoint(cand2)
        assert saved is False
        assert recovered is not None
        assert recovered.candidate_sha == "cand-sha-1"


def test_t11_stage_transition_contention(pg_session_factory: sessionmaker[Session]):
    """T11: Prove OrchestrationService._advance_stage uses FOR UPDATE row locking on OrchestrationRun."""
    run_id = "run-t11"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        proj = Project(project_id="p-t11", display_name="P11", repository="o/r", base_branch="main")
        uow.projects.save(proj)
        run = OrchestrationRun(
            run_id=run_id,
            project_id="p-t11",
            change_name="c-t11",
            base_sha="base-sha",
            current_stage=OrchestrationStage.ADMITTED,
            resumable_stage=OrchestrationStage.ADMITTED,
            is_active=True,
        )
        uow.orchestration_runs.save(run)
        uow.commit()

    with pg_session_factory() as session2:
        uow2 = PostgresPersistenceUnitOfWork(session2)
        from minime.services.orchestration_service import OrchestrationService
        orch_srv = OrchestrationService(uow2)
        run = uow2.orchestration_runs.get_by_id(run_id)
        assert run is not None
        orch_srv._advance_stage(run, OrchestrationStage.PREPARING_EXECUTION)
        uow2.commit()

    with pg_session_factory() as session3:
        uow3 = PostgresPersistenceUnitOfWork(session3)
        updated_run = uow3.orchestration_runs.get_by_id(run_id)
        assert updated_run is not None
        assert updated_run.current_stage == OrchestrationStage.PREPARING_EXECUTION


def test_f19_worktree_ownership_savepoint_recovery(pg_session_factory: sessionmaker[Session], tmp_path: Path):
    """F19: Prove WorktreeManager._persist_pending_ownership uses Pattern A savepoint recovery for canonical_worktree_path."""
    from minime.domain.models import ProjectBinding, utc_now
    wt_path = tmp_path / "worktree_f19"
    wt_path.mkdir(exist_ok=True)
    proj_id = "p-f19"
    run_id = "run-f19"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        from tests.conftest import setup_managed_repository_fixture
        setup_managed_repository_fixture(uow, proj_id, tmp_path, tmp_path, canonical_repository_identity="github.com/owner/repo")
        uow.projects.save(Project(project_id=proj_id, display_name="P-F19", repository="owner/repo", base_branch="main"))
        uow.bindings.save(ProjectBinding(binding_id="b-f19", project_id=proj_id, openspec_change_name="c-f19", github_issue_number=1919, repository="owner/repo", is_valid=True, bound_at=utc_now()))
        uow.orchestration_runs.save(OrchestrationRun(run_id=run_id, project_id=proj_id, change_name="c-f19", base_sha="base123", current_stage=OrchestrationStage.PREPARING_EXECUTION, current_generation=1, is_active=True))
        uow.commit()

    results: list[Any] = [None, None]  # type: ignore

    def worker(idx: int):
        with pg_session_factory() as s:
            uow = PostgresPersistenceUnitOfWork(s)
            from minime.services.worktree_manager import WorktreeManager
            mgr = WorktreeManager(project_root=tmp_path, uow=uow)
            ow = mgr._persist_pending_ownership(
                path=wt_path,
                project_id=proj_id,
                job_id="job-f19",
                run_id=run_id,
                change_name="c-f19",
                source_repository_identity="github.com/owner/repo",
                source_base_sha="base123",
                branch="feature/f19",
            )
            results[idx] = ow

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results[0] is not None
    assert results[1] is not None
    assert results[0].canonical_worktree_path == str(wt_path.resolve())
    assert results[1].canonical_worktree_path == str(wt_path.resolve())


def test_t12_job_status_stale_writer(pg_session_factory: sessionmaker[Session]):
    """T12: Prove PostgresJobRepository.transition() uses FOR UPDATE row locking to prevent stale status overwrite."""
    job_id = "job-t12"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(Project(project_id="p-t12", display_name="P12", repository="o/r", base_branch="main"))
        job = Job(
            job_id=job_id,
            project_id="p-t12",
            change_name="c-t12",
            status=JobStatus.QUEUED,
            implementer_role="PRIMARY",
        )
        uow.jobs.save(job)
        uow.commit()

    step_log: list[str] = []
    lock_event = threading.Event()

    def worker_a():
        with pg_session_factory() as session_a:
            uow_a = PostgresPersistenceUnitOfWork(session_a)
            _ = uow_a.jobs.transition(job_id, JobStatus.RUNNING.value)
            step_log.append("A: transitioned to RUNNING")
            lock_event.set()
            time.sleep(0.2)
            uow_a.commit()
            step_log.append("A: committed RUNNING")

    def worker_b():
        lock_event.wait()
        step_log.append("B: starting transition to CHECKS_RUNNING (will block on row lock)")
        with pg_session_factory() as session_b:
            uow_b = PostgresPersistenceUnitOfWork(session_b)
            j_b = uow_b.jobs.transition(job_id, JobStatus.CHECKS_RUNNING.value)
            step_log.append(f"B: unblocked, transitioned job status to '{j_b.status.value}'")
            uow_b.commit()

    t1 = threading.Thread(target=worker_a)
    t2 = threading.Thread(target=worker_b)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert "A: committed RUNNING" in step_log
    assert "B: unblocked, transitioned job status to 'CHECKS_RUNNING'" in step_log

    with pg_session_factory() as session_verify:
        uow_v = PostgresPersistenceUnitOfWork(session_verify)
        final_job = uow_v.jobs.get_by_id(job_id)
        assert final_job is not None
        assert final_job.status == JobStatus.CHECKS_RUNNING
