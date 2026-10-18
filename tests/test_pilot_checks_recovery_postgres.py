"""Targeted E2E tests for pilot checks-only checkpoint recovery in disposable PostgreSQL."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    ChangeStatus,
    EvidenceDiagnosticStatus,
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    RecoveryClassification,
    RecoveryDecisionStatus,
    WorkItemStatus,
)
from minime.domain.models import (
    BacklogItem,
    Change,
    CheckResult,
    EvidenceDiagnostic,
    Job,
    OrchestrationRun,
    Project,
    ProjectBinding,
    ProjectManagedRepositoryBinding,
)
from minime.services.checks_runner import ChecksRunResult
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.recovery_convergence_service import RecoveryConvergenceService


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
    return None


PG_TEST_URL = _ensure_pg_server()


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    if not PG_TEST_URL:
        pytest.skip("PostgreSQL test database server is not reachable.")
    engine = create_engine(PG_TEST_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)

    with engine.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();"
            )
        )
        conn.commit()
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    Base.metadata.create_all(engine)
    from minime.db.session import EXPECTED_ALEMBIC_HEAD

    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) PRIMARY KEY);"
            )
        )
        conn.execute(text("DELETE FROM alembic_version;"))
        conn.execute(
            text(f"INSERT INTO alembic_version (version_num) VALUES ('{EXPECTED_ALEMBIC_HEAD}');")
        )
        conn.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


def _setup_repo_and_worktree(
    tmp_path: Path, test_id: str | None = None
) -> tuple[Path, Path, str, str, str]:
    """Create a git repo and worktree with a candidate commit."""
    import uuid

    if test_id is None:
        test_id = uuid.uuid4().hex[:8]

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"], cwd=str(repo_dir), check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_dir), check=True)

    (repo_dir / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_dir), check=True, capture_output=True, text=True
    ).stdout.strip()

    # Create worktree
    worktrees_parent = tmp_path / "worktrees"
    worktrees_parent.mkdir(parents=True)
    wt_dir = worktrees_parent / f"job-pilot-{test_id}"
    subprocess.run(
        ["git", "worktree", "add", "-b", f"minime/pilot-change-{test_id}", str(wt_dir), "main"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )

    # Make candidate commit
    (wt_dir / "feature.py").write_text("def sanitize(token): return token.strip()\n")
    subprocess.run(["git", "add", "feature.py"], cwd=str(wt_dir), check=True)
    subprocess.run(["git", "commit", "-m", "Implement sanitize token"], cwd=str(wt_dir), check=True)
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(wt_dir), check=True, capture_output=True, text=True
    ).stdout.strip()

    return repo_dir, wt_dir, base_sha, candidate_sha, test_id


def _seed_pilot_state(
    session: Session,
    repo_dir: Path,
    wt_dir: Path,
    base_sha: str,
    candidate_sha: str,
    test_id: str,
    diagnostic_reason: str = "PermissionError: [Errno 13] Permission denied: '/dev/null'",
) -> tuple[Project, OrchestrationRun, Job]:
    uow = PostgresPersistenceUnitOfWork(session)
    project_id = f"pilot-prj-{test_id}"
    change_name = f"pilot-ch-{test_id}"
    run_id = f"run-pilot-{test_id}"
    job_id = wt_dir.name

    project = Project(
        project_id=project_id,
        display_name="Pilot Project",
        repository=str(repo_dir),
        base_branch="main",
        checks=[
            {"name": "pytest", "command": "pytest tests/ -v"},
            {"name": "ruff", "command": "ruff check ."},
        ],
    )
    uow.projects.save(project)

    binding = ProjectManagedRepositoryBinding(
        project_id=project_id,
        canonical_repository_identity=str(repo_dir),
        managed_repository_root=str(repo_dir),
        worktree_parent_dir=str(wt_dir.parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    uow.bindings.save(
        ProjectBinding(
            binding_id=f"bind-{change_name}",
            project_id=project_id,
            openspec_change_name=change_name,
            repository=str(repo_dir),
            is_valid=True,
        )
    )

    uow.changes.save(
        Change(
            change_id=f"ch-{change_name}",
            project_id=project_id,
            name=change_name,
            status=ChangeStatus.READY,
        )
    )

    uow.backlog_items.save(
        BacklogItem(
            project_id=project_id,
            item_key=change_name,
            title="Pilot Change Item",
            status=WorkItemStatus.RUNNING,
            openspec_change_name=change_name,
        )
    )

    job = Job(
        job_id=job_id,
        project_id=project_id,
        change_name=change_name,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        status=JobStatus.CHECKS_FAILED,
        implementer_role="codex",
        current_executor="codex",
    )
    uow.jobs.save(job)

    run = OrchestrationRun(
        run_id=run_id,
        project_id=project_id,
        change_name=change_name,
        base_sha=base_sha,
        current_stage=OrchestrationStage.IMPLEMENTING,
        active_job_id=job_id,
        current_generation=1,
        is_active=True,
    )
    uow.orchestration_runs.save(run)

    # Save historical diagnostic evidence
    diag = EvidenceDiagnostic(
        job_id=job_id,
        stage_type="CHECKS",
        check_name="pytest",
        diagnostic_status=EvidenceDiagnosticStatus.FAIL,
        environment_identity=str(wt_dir)[-128:],
        candidate_sha=candidate_sha,
        reason=diagnostic_reason,
        evidence_reference={"snippet": diagnostic_reason},
    )
    uow.evidence_diagnostics.save(diag)

    # Save prior check results (failed due to runner fault)
    cr = CheckResult(
        job_id=job_id,
        check_name="pytest",
        command="pytest tests/ -v",
        exit_code=1,
        duration_ms=120,
        output_snippet=diagnostic_reason,
        candidate_sha=candidate_sha,
        candidate_generation=1,
    )
    uow.check_results.save(cr)

    session.commit()
    return project, run, job


# ============================================================================
# 5.1 Happy path: checks-only recovery executes, freezes candidate & halts at review hold
# ============================================================================
def test_pilot_checks_recovery_happy_path(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    project, run, job = _seed_pilot_state(
        session, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    uow = PostgresPersistenceUnitOfWork(session)
    rec_svc = RecoveryConvergenceService(uow, project_root=repo_dir)

    # Mock ChecksRunner to simulate passing checks without executing Bubblewrap under macOS
    mock_passing_results = [
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest tests/ -v",
            exit_code=0,
            duration_ms=100,
            output_snippet="2 passed in 0.05s",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
        CheckResult(
            job_id=job.job_id,
            check_name="ruff",
            command="ruff check .",
            exit_code=0,
            duration_ms=50,
            output_snippet="All checks passed!",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
    ]

    with (
        patch.object(
            ExecutionPipelineService,
            "execute_queued_job",
            new=AsyncMock(
                side_effect=AssertionError(
                    "execute_queued_job must NEVER be called in checks-only recovery!"
                )
            ),
        ),
        patch(
            "minime.services.checks_runner.ChecksRunner.run",
            new=AsyncMock(
                return_value=ChecksRunResult(
                    passed=True, results=mock_passing_results, diagnostics=[]
                )
            ),
        ),
        patch(
            "minime.services.deepseek_code_review_service.DeepSeekCodeReviewService.review_candidate",
            new=AsyncMock(side_effect=AssertionError("Review model must NEVER be dispatched!")),
        ),
    ):
        decision = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)

    assert decision.status == RecoveryDecisionStatus.COMPLETED

    # Assert durable PostgreSQL state
    refreshed_run = uow.orchestration_runs.get_by_id(run.run_id)
    assert refreshed_run is not None
    assert refreshed_run.is_active is False
    assert refreshed_run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
    assert refreshed_run.human_gate == HumanGate.NEEDS_HUMAN
    assert refreshed_run.stop_details.get("code") == "REVIEW_AUTHORIZATION_PENDING"

    refreshed_job = uow.jobs.get_by_id(job.job_id)
    assert refreshed_job is not None
    assert refreshed_job.status == JobStatus.CHECKS_PASSED

    # Candidate record exists and is frozen
    frozen_cand = uow.orchestration_candidates.get_latest_for_run(run.run_id)
    assert frozen_cand is not None
    assert frozen_cand.candidate_sha == candidate_sha
    assert frozen_cand.is_frozen is True

    # Check that BacklogItem was updated to NEEDS_HUMAN
    bk_item = uow.backlog_items.get_by_project_and_key(project.project_id, run.change_name)
    assert bk_item is not None
    assert bk_item.status == WorkItemStatus.NEEDS_HUMAN

    # Ensure claim was released
    claim = uow.claims.get_by_key(f"run:{run.run_id}")
    assert claim is None or claim.released_at is not None


# ============================================================================
# 5.2 Negative: Authority tuple mismatches fail closed
# ============================================================================
def test_pilot_checks_recovery_authority_mismatch(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    uow = PostgresPersistenceUnitOfWork(session)
    rec_svc = RecoveryConvergenceService(uow, project_root=repo_dir)

    # Mutate run base_sha to mismatch job
    run.base_sha = "0000000000000000000000000000000000000000"
    uow.orchestration_runs.save(run)
    session.commit()

    decision = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert decision.status == RecoveryDecisionStatus.BLOCKED
    assert "does not match job base_sha" in decision.reason_code


# ============================================================================
# 5.3 Negative: Non-environmental fault rejects checks-only bypass
# ============================================================================
def test_pilot_checks_recovery_non_environmental_fault_rejected(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    # Seed with application assertion failure rather than /dev/null runner fault
    _project, run, _job = _seed_pilot_state(
        session,
        repo_dir,
        wt_dir,
        base_sha,
        candidate_sha,
        test_id,
        diagnostic_reason="AssertionError: sanitize('abc') == 'def' failed",
    )

    uow = PostgresPersistenceUnitOfWork(session)
    rec_svc = RecoveryConvergenceService(uow, project_root=repo_dir)

    decision = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert decision.status == RecoveryDecisionStatus.BLOCKED
    assert (
        "Prior check failure does not substantiate a proven runner environmental fault"
        in decision.reason_code
    )


# ============================================================================
# 5.4 Negative: Incomplete check batch fails and does not inherit old evidence
# ============================================================================
def test_pilot_checks_recovery_incomplete_batch(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    uow = PostgresPersistenceUnitOfWork(session)
    rec_svc = RecoveryConvergenceService(uow, project_root=repo_dir)

    # Return only pytest, omitting configured ruff check
    incomplete_results = [
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest tests/ -v",
            exit_code=0,
            duration_ms=100,
            output_snippet="Passed",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        )
    ]

    with patch(
        "minime.services.checks_runner.ChecksRunner.run",
        new=AsyncMock(
            return_value=ChecksRunResult(passed=True, results=incomplete_results, diagnostics=[])
        ),
    ):
        decision = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)

    assert decision.status == RecoveryDecisionStatus.COMPLETED

    # Check that job transitioned to CHECKS_FAILED due to incomplete batch
    refreshed_job = uow.jobs.get_by_id(job.job_id)
    assert refreshed_job is not None
    assert refreshed_job.status == JobStatus.CHECKS_FAILED

    # Run stopped fail-closed at NEEDS_HUMAN
    refreshed_run = uow.orchestration_runs.get_by_id(run.run_id)
    assert refreshed_run is not None
    assert refreshed_run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN


# ============================================================================
# 5.5 Negative: Claim fence loss or contention aborts recovery
# ============================================================================
def test_pilot_checks_recovery_claim_contention(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    session1 = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, _job = _seed_pilot_state(
        session1, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )
    session2 = pg_session_factory()

    uow1 = PostgresPersistenceUnitOfWork(session1)
    uow2 = PostgresPersistenceUnitOfWork(session2)

    # Worker 1 acquires claim on the run
    rec_svc1 = RecoveryConvergenceService(uow1, project_root=repo_dir, owner_instance_id="worker-1")
    claim = rec_svc1.acquire_claim(f"run:{run.run_id}")
    assert claim is not None
    session1.commit()

    # Worker 2 attempts checks recovery while claim is held elsewhere
    rec_svc2 = RecoveryConvergenceService(uow2, project_root=repo_dir, owner_instance_id="worker-2")
    decision = rec_svc2.recover_checks_only(run.run_id, project_root=repo_dir)
    assert decision.status == RecoveryDecisionStatus.NO_ACTION
    assert decision.classification == RecoveryClassification.CLAIMED_ELSEWHERE


# ============================================================================
# 5.6 Idempotency: Repeated recovery invocations do not duplicate records
# ============================================================================
def test_pilot_checks_recovery_idempotency(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    uow = PostgresPersistenceUnitOfWork(session)
    rec_svc = RecoveryConvergenceService(uow, project_root=repo_dir)

    mock_passing_results = [
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest tests/ -v",
            exit_code=0,
            duration_ms=100,
            output_snippet="2 passed in 0.05s",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
        CheckResult(
            job_id=job.job_id,
            check_name="ruff",
            command="ruff check .",
            exit_code=0,
            duration_ms=50,
            output_snippet="All checks passed!",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
    ]

    with patch(
        "minime.services.checks_runner.ChecksRunner.run",
        new=AsyncMock(
            return_value=ChecksRunResult(passed=True, results=mock_passing_results, diagnostics=[])
        ),
    ):
        decision1 = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
        assert decision1.status == RecoveryDecisionStatus.COMPLETED

        # Check manifest count for this candidate
        manifests_first = uow.candidate_manifests.get_by_candidate_sha(job.job_id, candidate_sha)
        assert manifests_first is not None

        # Re-invoke checks-only recovery with force=True on the now-stopped run
        decision2 = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir, force=True)
        assert decision2.status == RecoveryDecisionStatus.COMPLETED
        # Should not fail or corrupt state
        manifests_second = uow.candidate_manifests.get_by_candidate_sha(job.job_id, candidate_sha)
        assert manifests_second is not None
        assert manifests_second.manifest_hash == manifests_first.manifest_hash
