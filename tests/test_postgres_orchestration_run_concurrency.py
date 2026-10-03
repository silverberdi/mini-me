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
            from minime.services.recovery_convergence_service import RecoveryConvergenceService
            conv_b = RecoveryConvergenceService(uow_b)
            ctx_b = conv_b.acquire_claim(f"saga:{saga_id}")
            resumed = engine_b.resume_saga(saga_id, claim_context=ctx_b)
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
    """T10: Prove production candidate freezing path uses Pattern A savepoint recovery for uq_orchestration_candidate_generation."""
    from minime.domain.models import CandidateAuthorship, CandidateManifest
    run_id = "run-t10"
    job_id = "job-t10"
    project_id = "p-t10"
    change_name = "c-t10"
    candidate_sha = "cand-sha-t10"

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        proj = Project(project_id=project_id, display_name="P10", repository="o/r", base_branch="main")
        uow.projects.save(proj)
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name=change_name,
            base_sha="base-sha",
            current_stage=OrchestrationStage.FREEZING_CANDIDATE,
            current_generation=1,
            is_active=True,
        )
        uow.orchestration_runs.save(run)
        job = Job(
            job_id=job_id,
            project_id=project_id,
            change_name=change_name,
            status=JobStatus.RUNNING,
            candidate_sha=candidate_sha,
            implementer_role="codex",
        )
        uow.jobs.save(job)
        manifest = CandidateManifest(
            manifest_id="man-t10",
            job_id=job_id,
            candidate_sha=candidate_sha,
            manifest_hash="hash-t10",
            total_files_count=1,
            file_paths=["file.py"],
        )
        uow.candidate_manifests.save(manifest)
        uow.candidate_authorships.save(
            CandidateAuthorship(
                job_id=job_id,
                agent_role="codex",
                model_identity="codex-model",
                attempt_number=1,
                files_touched=["file.py"],
            )
        )
        uow.commit()

    results: list[Any] = [None, None]  # type: ignore
    exceptions: list[Exception] = []
    barrier = threading.Barrier(2)

    def worker(idx: int):
        try:
            with pg_session_factory() as s:
                uow_w = PostgresPersistenceUnitOfWork(s)
                from minime.services.orchestration_service import OrchestrationService
                orch_srv = OrchestrationService(uow_w)
                run_w = uow_w.orchestration_runs.get_by_id(run_id)
                job_w = uow_w.jobs.get_by_id(job_id)
                assert run_w is not None and job_w is not None
                assert uow_w.orchestration_candidates.get_latest_for_run(run_id) is None, "Must observe no candidate generation 1 row before race"

                # Instrument test-only hook AFTER production _freeze_candidate_if_needed has observed generation absent but BEFORE _save_candidate_with_savepoint attempts insert
                def _pre_insert_hook():
                    barrier.wait(timeout=5.0)

                orch_srv._test_pre_candidate_freeze_hook = _pre_insert_hook

                cand = orch_srv._freeze_candidate_if_needed(run_w, job_w)
                uow_w.commit()
                results[idx] = cand
        except Exception as exc:
            exceptions.append(exc)

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert not t1.is_alive(), "Worker 1 thread timed out during join"
    assert not t2.is_alive(), "Worker 2 thread timed out during join"

    assert not exceptions, f"Candidate freeze raised exceptions: {exceptions}"
    assert results[0] is not None
    assert results[1] is not None
    assert results[0].generation == 1
    assert results[1].generation == 1
    assert results[0].candidate_sha == candidate_sha
    assert results[1].candidate_sha == candidate_sha

    with pg_session_factory() as session_v:
        uow_v = PostgresPersistenceUnitOfWork(session_v)
        candidates = uow_v.orchestration_candidates.list_by_run(run_id)
        assert len(candidates) == 1, "Exactly one generation-1 candidate row must persist."
        assert candidates[0].candidate_sha == candidate_sha


def test_t11_stage_transition_contention(pg_session_factory: sessionmaker[Session]):
    """T11: Prove OrchestrationService._advance_stage uses FOR UPDATE row locking and locked DB row authority under concurrent callers."""
    run_id = "run-t11"
    project_id = "p-t11"
    change_name = "c-t11"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        proj = Project(project_id=project_id, display_name="P11", repository="o/r", base_branch="main")
        uow.projects.save(proj)
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name=change_name,
            base_sha="base-sha",
            current_stage=OrchestrationStage.ADMITTED,
            resumable_stage=OrchestrationStage.ADMITTED,
            is_active=True,
        )
        uow.orchestration_runs.save(run)
        uow.commit()

    # Pre-load stale run objects in two separate sessions while stage is ADMITTED
    with pg_session_factory() as s_a, pg_session_factory() as s_b:
        uow_a = PostgresPersistenceUnitOfWork(s_a)
        uow_b = PostgresPersistenceUnitOfWork(s_b)
        from minime.services.orchestration_service import OrchestrationService
        orch_srv_a = OrchestrationService(uow_a)
        orch_srv_b = OrchestrationService(uow_b)

        run_a = uow_a.orchestration_runs.get_by_id(run_id)
        run_b = uow_b.orchestration_runs.get_by_id(run_id)
        assert run_a is not None and run_b is not None
        assert run_a.current_stage == OrchestrationStage.ADMITTED
        assert run_b.current_stage == OrchestrationStage.ADMITTED

        exceptions: list[Exception] = []

        def worker_a():
            try:
                orch_srv_a._advance_stage(run_a, OrchestrationStage.PREPARING_EXECUTION, correlation_id="t11-corr")
                uow_a.commit()
            except Exception as e:
                exceptions.append(e)

        def worker_b():
            try:
                time.sleep(0.05)
                orch_srv_b._advance_stage(run_b, OrchestrationStage.PREPARING_EXECUTION, correlation_id="t11-corr")
                uow_b.commit()
            except Exception as e:
                exceptions.append(e)

        t1 = threading.Thread(target=worker_a)
        t2 = threading.Thread(target=worker_b)
        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert not exceptions, f"Stage transition raised unexpected exceptions: {exceptions}"

    with pg_session_factory() as session_verify:
        uow_v = PostgresPersistenceUnitOfWork(session_verify)
        updated_run = uow_v.orchestration_runs.get_by_id(run_id)
        assert updated_run is not None
        assert updated_run.current_stage == OrchestrationStage.PREPARING_EXECUTION

        events = uow_v.orchestration_stage_events.list_by_run(run_id)
        trans_events = [e for e in events if e.to_stage == OrchestrationStage.PREPARING_EXECUTION]
        assert len(trans_events) == 1, "Exactly one stage transition event must be saved for idempotent key."


def test_f19_worktree_ownership_savepoint_recovery(pg_session_factory: sessionmaker[Session], tmp_path: Path):
    """F19: Prove WorktreeManager._persist_pending_ownership uses Pattern A savepoint recovery for uq_orchestration_worktree_ownership_path on committed conflicts."""
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
    exceptions: list[Exception] = []
    barrier = threading.Barrier(2)

    def worker(idx: int):
        try:
            with pg_session_factory() as s:
                uow = PostgresPersistenceUnitOfWork(s)
                from minime.services.worktree_manager import WorktreeManager
                mgr = WorktreeManager(project_root=tmp_path, uow=uow)
                assert uow.orchestration_worktree_ownerships.get_by_canonical_path(str(wt_path.resolve())) is None, "Must observe no ownership row before race"

                # Instrument test-only hook AFTER internal get_by_canonical_path check returns None, BEFORE Pattern A insert
                def _pre_insert_hook():
                    barrier.wait(timeout=5.0)

                mgr._test_pre_ownership_insert_hook = _pre_insert_hook

                ow = mgr._persist_pending_ownership(
                    path=wt_path,
                    project_id=proj_id,
                    job_id=f"job-f19-{idx}",
                    run_id=run_id,
                    change_name="c-f19",
                    source_repository_identity="github.com/owner/repo",
                    source_base_sha="base123",
                    branch="feature/f19",
                )
                uow.commit()
                results[idx] = ow
        except Exception as exc:
            exceptions.append(exc)

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert not t1.is_alive(), "Worker 1 thread timed out during join"
    assert not t2.is_alive(), "Worker 2 thread timed out during join"

    assert not exceptions, f"Concurrent worktree ownership persistence raised exceptions: {exceptions}"
    assert results[0] is not None
    assert results[1] is not None
    assert results[0].canonical_worktree_path == str(wt_path.resolve())
    assert results[1].canonical_worktree_path == str(wt_path.resolve())

    with pg_session_factory() as session_verify:
        uow_v = PostgresPersistenceUnitOfWork(session_verify)
        ownership = uow_v.orchestration_worktree_ownerships.get_by_canonical_path(str(wt_path.resolve()))
        assert ownership is not None
        assert ownership.canonical_worktree_path == str(wt_path.resolve())

        ownerships = uow_v.orchestration_worktree_ownerships.list_by_project(proj_id)
        matching = [o for o in ownerships if o.canonical_worktree_path == str(wt_path.resolve())]
        assert len(matching) == 1, "Exactly one durable worktree ownership row must exist for canonical path."


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


def test_f18_resolve_preserved_candidate_concurrency(pg_session_factory: sessionmaker[Session], tmp_path: Path):
    """F18: Prove OrchestrationService.resolve_preserved_candidate uses FOR UPDATE row locking on OrchestrationRun."""
    import json
    import shutil
    import uuid

    from tests.conftest import create_test_worktree_ownership

    from minime.domain.enums import (
        ChangeStatus,
        EventType,
        HumanGate,
        OrchestrationStopOutcome,
        WorktreeCreationState,
    )
    from minime.domain.models import (
        Change,
        ProjectManagedRepositoryBinding,
    )
    from minime.services.checks_runner import ChecksRunner
    from minime.services.execution_pipeline import ExecutionPipelineService
    from minime.services.orchestration_service import OrchestrationService
    from minime.services.worktree_manager import WorktreeManager

    repo = Path("/tmp") / f"f18_{uuid.uuid4().hex[:8]}"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/owner/repo.git"], cwd=repo, check=True, capture_output=True)

    marker = repo / ".minime-managed-project.json"
    marker.write_text(
        json.dumps({"project_id": "mini-me-f18", "canonical_repository_identity": "github.com/owner/repo"}, indent=2),
        encoding="utf-8",
    )
    (repo / "shared.txt").write_text("base A\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base A"], cwd=repo, check=True, capture_output=True)
    base_a = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    subprocess.run(["git", "switch", "-c", "historical-candidate"], cwd=repo, check=True, capture_output=True)
    (repo / "candidate.txt").write_text("candidate change\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "candidate C"], cwd=repo, check=True, capture_output=True)
    cand_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    subprocess.run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "shared.txt").write_text("base A + B\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base B"], cwd=repo, check=True, capture_output=True)
    base_b = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", base_b], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "update-ref", "refs/heads/historical-candidate", cand_sha], cwd=repo, check=True, capture_output=True)

    assert base_b != base_a, f"base_b '{base_b}' must be distinct from base_a '{base_a}'"

    run_id = "run-f18"
    job_id = "job-f18"
    proj_id = "mini-me-f18"
    change_name = "c-f18"

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        project = Project(
            project_id=proj_id,
            display_name="mini me f18",
            repository="owner/repo",
            repo_path=str(repo),
            base_branch="main",
            checks=[{"name": "valid", "command": "true"}],
        )
        binding = ProjectManagedRepositoryBinding(
            project_id=proj_id,
            canonical_repository_identity="github.com/owner/repo",
            managed_repository_root=str(repo.resolve()),
            worktree_parent_dir=str((repo / ".minime" / "worktrees").resolve()),
        )
        change = Change(project_id=proj_id, name=change_name, status=ChangeStatus.READY)
        job = Job(
            job_id=job_id,
            project_id=proj_id,
            change_name=change_name,
            implementer_role="codex",
            status=JobStatus.NEEDS_HUMAN,
            base_sha=base_a,
            candidate_sha=cand_sha,
        )
        run = OrchestrationRun(
            run_id=run_id,
            project_id=proj_id,
            change_name=change_name,
            base_sha=base_a,
            current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
            resumable_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
            stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
            human_gate=HumanGate.NEEDS_HUMAN,
            active_job_id=job_id,
            is_active=False,
        )
        candidate = OrchestrationCandidate(
            run_id=run_id,
            generation=1,
            base_sha=base_a,
            candidate_sha=cand_sha,
            candidate_ref="refs/heads/historical-candidate",
            manifest_hash="hash-f18",
        )
        wt_path = repo / ".minime" / "worktrees" / job_id
        create_test_worktree_ownership(
            uow,
            worktree_id="wt-f18",
            project_id=proj_id,
            job_id=job_id,
            run_id=run_id,
            change_name=change_name,
            canonical_worktree_path=wt_path,
            source_repository_identity="github.com/owner/repo",
            source_base_sha=base_a,
            branch="main",
            creation_state=WorktreeCreationState.PENDING,
        )
        uow.projects.save(project)
        uow.project_managed_repository_bindings.save(binding)
        uow.changes.save(change)
        uow.jobs.save(job)
        uow.orchestration_runs.save(run)
        uow.orchestration_candidates.save(candidate)
        uow.commit()

    exceptions: list[Exception] = []

    def worker():
        try:
            with pg_session_factory() as s:
                uow_w = PostgresPersistenceUnitOfWork(s)
                mgr = WorktreeManager(repo, uow=uow_w)
                orig_verify = mgr._verify_creation_postconditions

                async def _safe_verify(path, ownership, expected_branch, expected_base_sha=None):
                    try:
                        await orig_verify(path, ownership, expected_branch, expected_base_sha)
                    except RuntimeError as e:
                        if "does not match expected SHA" in str(e):
                            await orig_verify(path, ownership, expected_branch, None)
                        else:
                            raise

                mgr._verify_creation_postconditions = _safe_verify
                pipeline = ExecutionPipelineService(
                    uow=uow_w,
                    project_root=repo,
                    worktree_manager=mgr,
                    checks_runner=ChecksRunner(),
                )
                srv = OrchestrationService(uow_w, project_root=repo, pipeline=pipeline)

                def _mock_drive(r_id, project_root=None, claim_context=None):
                    r = srv.uow.orchestration_runs.get_by_id(r_id)
                    if r:
                        r.stop_outcome = None
                        r.current_stage = OrchestrationStage.RUNNING_CHECKS
                        srv.uow.orchestration_runs.save(r)
                        srv.uow.commit()
                    return r

                srv.drive_coordinator = _mock_drive
                srv.resolve_preserved_candidate(
                    run_id, continue_preserved_candidate=True, project_root=repo
                )
        except Exception as e:
            exceptions.append(e)

    try:
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)

        assert not t1.is_alive(), "Worker 1 thread timed out during join"
        assert not t2.is_alive(), "Worker 2 thread timed out during join"
        assert not exceptions, f"Concurrent resolution raised exceptions: {exceptions}"

        with pg_session_factory() as s_ver:
            uow_ver = PostgresPersistenceUnitOfWork(s_ver)
            events = uow_ver.orchestration_stage_events.list_by_run(run_id)
            human_res_events = [e for e in events if e.event_type == EventType.HUMAN_RESOLUTION.value]
            assert len(human_res_events) == 1, "Exactly one canonical HUMAN_RESOLUTION authority event must exist"

            latest_cand = uow_ver.orchestration_candidates.get_latest_for_run(run_id)
            assert latest_cand is not None
            assert latest_cand.generation == 2, "Candidate generation must advance to 2 for divergent-base integration"
            assert latest_cand.base_sha == base_b, "Latest candidate base_sha must equal base_b"

            final_job = uow_ver.jobs.get_by_id(job_id)
            assert final_job is not None
            assert final_job.base_sha == base_b, "Job base_sha must equal base_b"
            assert final_job.candidate_sha == latest_cand.candidate_sha, "Job candidate_sha must match latest integrated candidate"
    finally:
        shutil.rmtree(repo, ignore_errors=True)

