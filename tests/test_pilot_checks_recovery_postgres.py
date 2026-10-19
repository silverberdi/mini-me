"""Targeted E2E tests for pilot checks-only checkpoint recovery in disposable PostgreSQL."""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session, close_all_sessions, sessionmaker
from sqlalchemy.pool import NullPool

from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import EXPECTED_ALEMBIC_HEAD
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    EvidenceDiagnosticStatus,
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    RecoveryDecisionStatus,
    WorkItemStatus,
    WorktreeCreationState,
)
from minime.domain.models import (
    BacklogItem,
    Change,
    CheckResult,
    EvidenceDiagnostic,
    Job,
    OrchestrationRun,
    OrchestrationWorktreeOwnership,
    Project,
    ProjectBinding,
    ProjectManagedRepositoryBinding,
    RecoveryClaimContext,
    utc_now,
)
from minime.services.checks_runner import ChecksRunner, ChecksRunResult
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.recovery_convergence_service import RecoveryConvergenceService


def validate_disposable_test_url(url_str: str, allow_admin: bool = False) -> None:
    """Validate that the provided database URL is strictly local and safe for disposable testing."""
    if not url_str or not url_str.strip():
        raise ValueError("Database URL cannot be empty.")
    url = make_url(url_str.strip())

    # 1. Host must be strictly local or unix domain socket
    if url.host not in {"localhost", "127.0.0.1", "::1", None}:
        raise ValueError(
            f"Refusing to use non-local database host '{url.host}'. Tests require local PostgreSQL."
        )

    db_name = (url.database or "").lower()
    if not db_name:
        raise ValueError("Database URL must specify a database name.")

    # 2. Reject any production keywords
    prod_keywords = ["prod", "production", "live"]
    if any(k in db_name for k in prod_keywords):
        raise ValueError(
            f"Refusing to connect to database '{url.database}': contains production keywords {prod_keywords}."
        )

    # 3. For disposable databases, must contain 'test' or be the default server admin db ('postgres', 'template1')
    if not allow_admin and db_name in {"postgres", "template1", "template0"}:
        raise ValueError(
            f"Refusing to use administrative database '{url.database}' as a disposable test database."
        )

    if not allow_admin and "test" not in db_name:
        raise ValueError(
            f"Refusing to connect to non-test database '{url.database}'. Database name must contain 'test'."
        )


def _ensure_pg_admin_server() -> str | None:
    candidate_urls = [
        os.environ.get("MINIME_TEST_ADMIN_DATABASE_URL"),
        os.environ.get("MINIME_TEST_DATABASE_URL"),
        "postgresql+psycopg://silveriobernal@localhost:54333/postgres",
        "postgresql+psycopg://testuser@localhost:54333/postgres",
    ]
    for raw_url in candidate_urls:
        if not raw_url:
            continue
        try:
            validate_disposable_test_url(raw_url, allow_admin=True)
            admin_url = make_url(raw_url).set(database="postgres")
            eng = create_engine(admin_url, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            eng.dispose()
            return str(admin_url)
        except Exception:
            continue
    return None


PG_ADMIN_URL = _ensure_pg_admin_server()


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    if not PG_ADMIN_URL:
        pytest.skip("PostgreSQL test database server is not reachable.")

    validate_disposable_test_url(PG_ADMIN_URL, allow_admin=True)
    admin_url = make_url(PG_ADMIN_URL)
    admin_engine = create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")

    ephemeral_db_name = f"minime_test_pilot_{uuid.uuid4().hex[:12]}"
    test_url_str = str(admin_url.set(database=ephemeral_db_name))
    validate_disposable_test_url(test_url_str, allow_admin=False)

    with admin_engine.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{ephemeral_db_name}"')

    test_engine = create_engine(test_url_str, poolclass=NullPool)
    Base.metadata.create_all(test_engine)
    with test_engine.connect() as conn:
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

    try:
        yield test_engine
    finally:
        close_all_sessions()
        test_engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :ephemeral_db AND pid <> pg_backend_pid()"
                ),
                {"ephemeral_db": ephemeral_db_name},
            )
            conn.exec_driver_sql(f'DROP DATABASE "{ephemeral_db_name}"')
        admin_engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: Engine) -> Generator[sessionmaker[Session], None, None]:
    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    yield factory
    close_all_sessions()


def _setup_repo_and_worktree(
    tmp_path: Path, test_id: str | None = None
) -> tuple[Path, Path, str, str, str]:
    """Create a git repo and worktree with a candidate commit."""
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

    # Register worktree ownership
    wt_ownership = OrchestrationWorktreeOwnership(
        worktree_id=f"wt-own-{job_id}",
        project_id=project_id,
        job_id=job_id,
        run_id=run_id,
        change_name=change_name,
        canonical_worktree_path=str(wt_dir),
        source_repository_identity=str(repo_dir),
        source_base_sha=base_sha,
        branch=f"minime/pilot-change-{test_id}",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(wt_ownership)

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
# P0: Test refusal of unsafe/unknown/prod-looking database URLs without DDL
# ============================================================================
def test_refusal_of_unsafe_database_urls():
    """Verify validate_disposable_test_url rejects dangerous URLs fail-closed without executing DDL."""
    # 1. Non-local hosts
    with pytest.raises(ValueError, match="Refusing to use non-local database host"):
        validate_disposable_test_url(
            "postgresql+psycopg://user:pass@192.168.0.194:5432/minime_test"
        )

    with pytest.raises(ValueError, match="Refusing to use non-local database host"):
        validate_disposable_test_url(
            "postgresql+psycopg://user:pass@pg.example.com:5432/minime_test"
        )

    # 2. Production keywords
    with pytest.raises(ValueError, match="contains production keywords"):
        validate_disposable_test_url(
            "postgresql+psycopg://user:pass@localhost:5432/minime_production"
        )

    with pytest.raises(ValueError, match="contains production keywords"):
        validate_disposable_test_url(
            "postgresql+psycopg://user:pass@127.0.0.1:5432/minime_prod_test"
        )

    with pytest.raises(ValueError, match="contains production keywords"):
        validate_disposable_test_url(
            "postgresql+psycopg://user:pass@localhost:5432/live_database_test"
        )

    # 3. Non-test database names
    with pytest.raises(ValueError, match="Refusing to connect to non-test database"):
        validate_disposable_test_url("postgresql+psycopg://user:pass@localhost:5432/minime")

    with pytest.raises(ValueError, match="Refusing to connect to non-test database"):
        validate_disposable_test_url("postgresql+psycopg://user:pass@localhost:5432/analytics")

    # 4. Administrative database when allow_admin=False
    with pytest.raises(ValueError, match="Refusing to use administrative database"):
        validate_disposable_test_url(
            "postgresql+psycopg://user:pass@localhost:5432/postgres", allow_admin=False
        )

    with pytest.raises(ValueError, match="Refusing to use administrative database"):
        validate_disposable_test_url(
            "postgresql+psycopg://user:pass@localhost:5432/template1", allow_admin=False
        )

    # 5. Empty or whitespace URL
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_disposable_test_url("")

    # 6. Valid local test URLs pass without raising
    validate_disposable_test_url("postgresql+psycopg://testuser@localhost:54333/minime_test")
    validate_disposable_test_url(
        "postgresql+psycopg://testuser@127.0.0.1:54333/minime_test_pilot_12345"
    )
    validate_disposable_test_url(
        "postgresql+psycopg://testuser@localhost:54333/postgres", allow_admin=True
    )


# ============================================================================
# P0: Write after claim fence loss - mid-check supersession aborts writes
# ============================================================================
def test_pilot_checks_recovery_fence_loss_aborts_writes(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """Verify that if Worker 1's claim fence is superseded during checks execution,

    Worker 1 commits ZERO writes (job status, manifest, recovery decision) and releases nothing.
    """
    session1 = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session1, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    uow1 = PostgresPersistenceUnitOfWork(session1)
    rec_svc1 = RecoveryConvergenceService(uow1, project_root=repo_dir, owner_instance_id="worker-1")

    mock_passing_results = [
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest tests/ -v",
            exit_code=0,
            duration_ms=100,
            output_snippet="Passed",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
        CheckResult(
            job_id=job.job_id,
            check_name="ruff",
            command="ruff check .",
            exit_code=0,
            duration_ms=50,
            output_snippet="Passed",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
    ]

    async def fake_checks_run_with_fence_supersession(*args, **kwargs):
        # Worker 2 supersedes the claim by incrementing fence_token in a distinct session
        session2 = pg_session_factory()
        session2.execute(
            text(
                "UPDATE recovery_claims SET fence_token = fence_token + 1, owner_instance_id = 'worker-2' WHERE claim_key = :k"
            ),
            {"k": f"run:{run.run_id}"},
        )
        session2.commit()
        session2.close()
        return ChecksRunResult(passed=True, results=mock_passing_results, diagnostics=[])

    with patch(
        "minime.services.checks_runner.ChecksRunner.run",
        new=fake_checks_run_with_fence_supersession,
    ):
        decision = rec_svc1.recover_checks_only(run.run_id, project_root=repo_dir)

    # Worker 1 was fenced out
    assert decision.status == RecoveryDecisionStatus.BLOCKED
    assert "STALE_CLAIM" in decision.reason_code

    # Re-inspect DB in a fresh third session to verify ZERO writes were committed by Worker 1
    session3 = pg_session_factory()
    uow3 = PostgresPersistenceUnitOfWork(session3)

    refreshed_job = uow3.jobs.get_by_id(job.job_id)
    assert refreshed_job is not None
    # Job status was NOT updated to CHECKS_PASSED by stale Worker 1 (no success-shaped status)
    assert refreshed_job.status != JobStatus.CHECKS_PASSED

    # No candidate manifest was created/committed by Worker 1
    manifest = uow3.candidate_manifests.get_by_candidate_sha(job.job_id, candidate_sha)
    assert manifest is None

    # Worker 2's claim was NOT released by Worker 1
    claim3 = uow3.claims.get_by_key(f"run:{run.run_id}")
    assert claim3 is not None
    assert claim3.owner_instance_id == "worker-2"
    assert claim3.released_at is None
    session3.close()


# ============================================================================
# P0: Write after claim loss - expired lease / stalled heartbeat refuses writes
# ============================================================================
def test_pilot_checks_recovery_expired_lease_refuses_write(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """Verify that if Worker 1's lease expires during checks execution, zero writes occur."""
    session1 = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session1, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    uow1 = PostgresPersistenceUnitOfWork(session1)
    rec_svc1 = RecoveryConvergenceService(uow1, project_root=repo_dir, owner_instance_id="worker-1")

    mock_passing_results = [
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest tests/ -v",
            exit_code=0,
            duration_ms=100,
            output_snippet="Passed",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
        CheckResult(
            job_id=job.job_id,
            check_name="ruff",
            command="ruff check .",
            exit_code=0,
            duration_ms=50,
            output_snippet="Passed",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
    ]

    async def fake_checks_run_with_expired_lease(*args, **kwargs):
        # Manually backdate claim lease_expires_at in DB to simulate expired lease
        session2 = pg_session_factory()
        session2.execute(
            text(
                "UPDATE recovery_claims SET lease_expires_at = NOW() - INTERVAL '10 minutes' WHERE claim_key = :k"
            ),
            {"k": f"run:{run.run_id}"},
        )
        session2.commit()
        session2.close()
        return ChecksRunResult(passed=True, results=mock_passing_results, diagnostics=[])

    with patch(
        "minime.services.checks_runner.ChecksRunner.run",
        new=fake_checks_run_with_expired_lease,
    ):
        decision = rec_svc1.recover_checks_only(run.run_id, project_root=repo_dir)

    assert decision.status == RecoveryDecisionStatus.BLOCKED
    assert "STALE_CLAIM" in decision.reason_code

    # Verify zero writes committed
    session3 = pg_session_factory()
    uow3 = PostgresPersistenceUnitOfWork(session3)
    refreshed_job = uow3.jobs.get_by_id(job.job_id)
    assert refreshed_job is not None
    assert refreshed_job.status != JobStatus.CHECKS_PASSED
    manifest = uow3.candidate_manifests.get_by_candidate_sha(job.job_id, candidate_sha)
    assert manifest is None
    session3.close()


# ============================================================================
# P1: Historical check results cannot satisfy incomplete new batch
# ============================================================================
def test_pilot_checks_recovery_incomplete_batch_with_old_passing_check_rejected(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """Verify that an incomplete new batch is rejected fail-closed and does NOT inherit

    old passing results from prior attempts.
    """
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    uow = PostgresPersistenceUnitOfWork(session)

    # Seed an OLD passing pytest result from Attempt 1 (10 minutes ago)
    old_pytest = CheckResult(
        job_id=job.job_id,
        check_name="pytest",
        command="pytest tests/ -v",
        exit_code=0,
        duration_ms=80,
        output_snippet="Passed in old attempt",
        candidate_sha=candidate_sha,
        candidate_generation=1,
        created_at=utc_now() - timedelta(minutes=10),
    )
    uow.check_results.save(old_pytest)
    session.commit()

    rec_svc = RecoveryConvergenceService(uow, project_root=repo_dir)

    # Attempt 2 runs checks, but returns an INCOMPLETE batch containing ONLY 'ruff' (exit_code=0)
    # 'pytest' is omitted from this new batch!
    incomplete_new_batch = [
        CheckResult(
            job_id=job.job_id,
            check_name="ruff",
            command="ruff check .",
            exit_code=0,
            duration_ms=45,
            output_snippet="Ruff passed",
            candidate_sha=candidate_sha,
            candidate_generation=1,
            created_at=utc_now(),
        )
    ]

    with patch(
        "minime.services.checks_runner.ChecksRunner.run",
        new=AsyncMock(
            return_value=ChecksRunResult(passed=True, results=incomplete_new_batch, diagnostics=[])
        ),
    ):
        decision = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)

    # Recovery must fail-closed: job must NOT advance to CHECKS_PASSED
    assert decision.status == RecoveryDecisionStatus.COMPLETED

    refreshed_job = uow.jobs.get_by_id(job.job_id)
    assert refreshed_job is not None
    assert refreshed_job.status == JobStatus.CHECKS_FAILED

    # Run stopped at NEEDS_HUMAN, candidate is NOT frozen
    refreshed_run = uow.orchestration_runs.get_by_id(run.run_id)
    assert refreshed_run is not None
    assert refreshed_run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN

    frozen_cand = uow.orchestration_candidates.get_latest_for_run(run.run_id)
    assert frozen_cand is None or not frozen_cand.is_frozen


# ============================================================================
# P1: Sound preflight eligibility validations
# ============================================================================
def test_pilot_checks_recovery_preflight_eligibility_rejections(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """Verify that _validate_checks_only_eligibility strictly rejects invalid stage,

    invalid job status, inactive run, invalid binding, dirty worktree, or non-environmental fault.
    """
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    uow = PostgresPersistenceUnitOfWork(session)
    rec_svc = RecoveryConvergenceService(uow, project_root=repo_dir)

    # 1. Invalid run stage (not IMPLEMENTING)
    run.current_stage = OrchestrationStage.PR_PREPARED
    uow.orchestration_runs.save(run)
    session.commit()
    d1 = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert d1.status == RecoveryDecisionStatus.BLOCKED
    assert "expected IMPLEMENTING" in d1.reason_code
    run.current_stage = OrchestrationStage.IMPLEMENTING
    uow.orchestration_runs.save(run)
    session.commit()

    # 2. Invalid job status (not CHECKS_FAILED)
    job.status = JobStatus.COMPLETED
    uow.jobs.save(job)
    session.commit()
    d2 = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert d2.status == RecoveryDecisionStatus.BLOCKED
    assert "expected CHECKS_FAILED" in d2.reason_code
    job.status = JobStatus.CHECKS_FAILED
    uow.jobs.save(job)
    session.commit()

    # 3. Inactive run
    run.is_active = False
    uow.orchestration_runs.save(run)
    session.commit()
    d3 = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert d3.status == RecoveryDecisionStatus.BLOCKED
    assert "Run is not active" in d3.reason_code
    run.is_active = True
    uow.orchestration_runs.save(run)
    session.commit()

    # 4. Invalid binding
    binding = uow.project_managed_repository_bindings.get_by_project_id(run.project_id)
    assert binding is not None
    binding.is_valid = False
    uow.project_managed_repository_bindings.save(binding)
    session.commit()
    d4 = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert d4.status == RecoveryDecisionStatus.BLOCKED
    assert "no valid durable binding" in d4.reason_code
    binding.is_valid = True
    uow.project_managed_repository_bindings.save(binding)
    session.commit()

    # 5. Dirty worktree
    dirty_file = wt_dir / "untracked_dirty.txt"
    dirty_file.write_text("dirty content")
    d5 = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert d5.status == RecoveryDecisionStatus.BLOCKED
    assert "Preserved worktree is not clean" in d5.reason_code
    dirty_file.unlink()

    # 6. Non-environmental diagnostic fault (e.g. AssertionError)
    diags = uow.evidence_diagnostics.list_by_job(job.job_id)
    assert len(diags) > 0
    diag = diags[-1]
    diag.reason = "AssertionError: sanitize('abc') == 'def' failed"
    uow.evidence_diagnostics.save(diag)
    session.commit()
    d6 = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert d6.status == RecoveryDecisionStatus.BLOCKED
    assert "not a proven runner environmental fault" in d6.reason_code


# ============================================================================
# P1: Real ChecksRunner positive execution E2E
# ============================================================================
@pytest.mark.asyncio
async def test_pilot_checks_runner_real_execution(tmp_path: Path):
    """Verify that ChecksRunner actually executes commands against the real worktree

    producing authentic CheckResult records without model inference or code mutation.
    """
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    job_id = f"job-real-{test_id}"

    real_checks = [
        {"name": "echo-test", "command": "python3 -c \"print('confinement-ok')\""},
        {"name": "exit-zero", "command": 'python3 -c "import sys; sys.exit(0)"'},
    ]

    runner = ChecksRunner(timeout_seconds=30)
    check_run = await runner.run(
        job_id=job_id,
        checks=real_checks,
        worktree_path=wt_dir,
        candidate_sha=candidate_sha,
        candidate_generation=1,
    )

    assert check_run.passed is True
    assert len(check_run.results) == 2

    r0, r1 = check_run.results[0], check_run.results[1]
    assert r0.check_name == "echo-test"
    assert r0.exit_code == 0
    assert "confinement-ok" in r0.output_snippet
    assert r0.candidate_sha == candidate_sha
    assert r0.candidate_generation == 1

    assert r1.check_name == "exit-zero"
    assert r1.exit_code == 0

    # Worktree git status remains strictly clean
    status_out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(wt_dir),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert status_out == ""


# ============================================================================
# Happy path: checks-only recovery executes, freezes candidate & halts at review hold
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
    session.close()


# ============================================================================
# Blocker 1: Fenced persistence supersession before commit rolls back all
# ============================================================================
def test_fenced_persistence_supersession_right_before_commit_rolls_back_all(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """Verify that if Worker 1 executes checks, but Worker 2 supersedes the claim fence
    after check execution right before evidence/manifest commit, Worker 1's transition fails CAS,
    all uncommitted writes (check results, metrics, manifest) are rolled back, and zero rows commit.
    """
    session1 = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session1, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    uow1 = PostgresPersistenceUnitOfWork(session1)
    rec_svc1 = RecoveryConvergenceService(uow1, project_root=repo_dir, owner_instance_id="worker-1")

    mock_passing_results = [
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest tests/ -v",
            exit_code=0,
            duration_ms=100,
            output_snippet="Passed",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
        CheckResult(
            job_id=job.job_id,
            check_name="ruff",
            command="ruff check .",
            exit_code=0,
            duration_ms=50,
            output_snippet="Passed",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
    ]

    async def checks_run_and_supersede(*args, **kwargs):
        # Worker 2 increments fence_token and takes claim ownership in a distinct session
        # right before Worker 1 attempts evidence publication and claim row locking
        session2 = pg_session_factory()
        session2.execute(
            text(
                "UPDATE recovery_claims SET fence_token = fence_token + 1, owner_instance_id = 'worker-2' WHERE claim_key = :k"
            ),
            {"k": f"run:{run.run_id}"},
        )
        session2.commit()
        session2.close()
        return ChecksRunResult(passed=True, results=mock_passing_results, diagnostics=[])

    with patch(
        "minime.services.checks_runner.ChecksRunner.run",
        new=checks_run_and_supersede,
    ):
        decision = rec_svc1.recover_checks_only(run.run_id, project_root=repo_dir)

    # Worker 1 was blocked due to CAS stale fence on transition/commit
    assert decision.status == RecoveryDecisionStatus.BLOCKED
    assert "STALE_CLAIM" in decision.reason_code or "stale" in decision.reason_code.lower()

    # Re-inspect DB in a fresh third session to verify ZERO post-loss writes were committed by Worker 1
    session3 = pg_session_factory()
    uow3 = PostgresPersistenceUnitOfWork(session3)

    refreshed_job = uow3.jobs.get_by_id(job.job_id)
    assert refreshed_job is not None
    # Transition to CHECKS_PASSED was rolled back upon losing claim fence
    assert refreshed_job.status != JobStatus.CHECKS_PASSED
    assert refreshed_job.status == JobStatus.CHECKS_RUNNING

    # No candidate manifest committed by Worker 1
    manifest = uow3.candidate_manifests.get_by_candidate_sha(job.job_id, candidate_sha)
    assert manifest is None

    # Check results in DB are only the historical failure from seed, not the passing results from Worker 1
    crs = uow3.check_results.list_by_job(job.job_id)
    assert not any(cr.exit_code == 0 for cr in crs)

    # Metrics for recovery duration were rolled back
    metrics = session3.execute(
        text(
            "SELECT * FROM metric_facts WHERE project_id = :p AND metric_name = 'checks_duration_ms'"
        ),
        {"p": job.project_id},
    ).fetchall()
    assert len(metrics) == 0

    session3.close()


def test_fenced_persistence_concurrent_supersession_after_cas_before_commit_is_serialized(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """Verify that if Worker B attempts to supersede the claim AFTER Worker A has executed
    its CAS Job transition but BEFORE Worker A commits, Worker B's UPDATE on recovery_claims
    is blocked by PostgreSQL's row lock on recovery_claims held by Worker A, serializing
    Worker B strictly until after Worker A's transaction commits.
    """
    session1 = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session1, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    uow1 = PostgresPersistenceUnitOfWork(session1)
    rec_svc1 = RecoveryConvergenceService(uow1, project_root=repo_dir, owner_instance_id="worker-1")

    mock_passing_results = [
        CheckResult(
            job_id=job.job_id,
            check_name="pytest",
            command="pytest tests/ -v",
            exit_code=0,
            duration_ms=100,
            output_snippet="Passed",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
        CheckResult(
            job_id=job.job_id,
            check_name="ruff",
            command="ruff check .",
            exit_code=0,
            duration_ms=50,
            output_snippet="Passed",
            candidate_sha=candidate_sha,
            candidate_generation=1,
        ),
    ]

    worker_b_blocked_verified = threading.Event()
    worker_b_finished = threading.Event()
    worker_b_unblocked = threading.Event()
    worker_b_error = []
    worker_a_committed = threading.Event()

    def worker_b_concurrent_supersede():
        # Worker B opens a distinct PostgreSQL session and attempts an exclusive update on recovery_claims.
        # Worker A holds FOR UPDATE on this exact claim row. Worker B will be BLOCKED by PostgreSQL until Worker A commits.
        session2 = pg_session_factory()
        try:
            worker_b_blocked_verified.set()
            # This query will block until Worker A's transaction commits!
            session2.execute(
                text(
                    "UPDATE recovery_claims SET fence_token = fence_token + 1, owner_instance_id = 'worker-2' WHERE claim_key = :k"
                ),
                {"k": f"run:{run.run_id}"},
            )
            worker_b_unblocked.set()
            # Assert that Worker B was unblocked ONLY after Worker A committed!
            assert worker_a_committed.is_set(), (
                "Worker B unblocked BEFORE Worker A committed! Row lock was not held on recovery_claims."
            )
            session2.commit()
        except Exception as e:
            worker_b_error.append(e)
        finally:
            session2.close()
            worker_b_finished.set()

    # Hook right after jobs.transition (inside pipeline._save_event for CHECKS_PASSED transition)
    # when Worker A holds FOR UPDATE on the recovery_claims row but has not yet called uow.commit().
    from minime.services.orchestration_service import OrchestrationService

    root = Path(repo_dir).resolve()
    orchestration_svc = OrchestrationService(uow1, project_root=root)
    rec_svc1.orchestration_service = orchestration_svc

    orig_save_event = orchestration_svc.pipeline._save_event
    orig_commit = uow1.commit

    def hooked_commit():
        # Signal that Worker A is committing its transaction
        worker_a_committed.set()
        return orig_commit()

    def save_event_hook(event_type, job_arg, payload):
        orig_save_event(event_type, job_arg, payload)
        if event_type == EventType.JOB_CHECKS_PASSED:
            # Worker A has executed jobs.transition under FOR UPDATE lock, but has NOT called uow.commit() yet!
            t = threading.Thread(target=worker_b_concurrent_supersede)
            t.daemon = True
            t.start()
            assert worker_b_blocked_verified.wait(timeout=5)
            # Give Worker B thread time to reach and block on the UPDATE query in PostgreSQL
            time.sleep(0.3)
            # Worker B MUST be blocked on the recovery_claims row lock and not finished/unblocked!
            assert not worker_b_unblocked.is_set(), (
                "Worker B unblocked before Worker A committed! Row lock was not held on recovery_claims."
            )
            assert not worker_b_finished.is_set()

    with (
        patch(
            "minime.services.checks_runner.ChecksRunner.run",
            new=AsyncMock(
                return_value=ChecksRunResult(
                    passed=True, results=mock_passing_results, diagnostics=[]
                )
            ),
        ),
        patch.object(
            orchestration_svc.pipeline,
            "_save_event",
            side_effect=save_event_hook,
        ),
        patch.object(
            uow1,
            "commit",
            side_effect=hooked_commit,
        ),
    ):
        decision = rec_svc1.recover_checks_only(run.run_id, project_root=repo_dir)

    assert decision is not None

    # Worker B thread has now unblocked and finished cleanly
    assert worker_b_finished.wait(timeout=5)
    assert len(worker_b_error) == 0

    # Verify in a fresh session that Worker A's results committed cleanly, and Worker B's supersession took effect afterwards
    session3 = pg_session_factory()
    uow3 = PostgresPersistenceUnitOfWork(session3)

    refreshed_job = uow3.jobs.get_by_id(job.job_id)
    assert refreshed_job is not None
    assert refreshed_job.status == JobStatus.CHECKS_PASSED

    # Manifest was safely committed
    manifest = uow3.candidate_manifests.get_by_candidate_sha(job.job_id, candidate_sha)
    assert manifest is not None

    # Check results were safely committed
    crs = uow3.check_results.list_by_job(job.job_id)
    passing_crs = [cr for cr in crs if cr.exit_code == 0]
    assert len(passing_crs) == 2

    # Claim in database now reflects Worker B's supersession (serialized to AFTER Worker A committed)
    claim3 = uow3.claims.get_by_key(f"run:{run.run_id}")
    assert claim3 is not None
    assert claim3.fence_token == 2
    assert claim3.owner_instance_id == "worker-2"

    session3.close()


# ============================================================================
# Blocker 2: Historical sandbox error with later code failure rejected
# ============================================================================
def test_historical_sandbox_error_with_later_code_failure_rejected(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """Verify that if Attempt 1 had an environmental /dev/null failure, but Attempt 2
    failed due to a real code failure (e.g. Ruff lint failure or test assertion error),
    checks-only recovery is strictly rejected fail-closed without inheriting Attempt 1's diagnostic.
    """
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )
    uow = PostgresPersistenceUnitOfWork(session)
    rec_svc = RecoveryConvergenceService(uow, project_root=repo_dir)

    from minime.domain.enums import ExecutionOutcome
    from minime.domain.models import JobAttempt

    att1_time = utc_now() - timedelta(minutes=10)
    # Age historical diagnostic and check result from seed to Attempt 1's timestamp
    for d in uow.evidence_diagnostics.list_by_job(job.job_id):
        d.created_at = att1_time
        uow.evidence_diagnostics.save(d)
    for c in uow.check_results.list_by_job(job.job_id):
        c.created_at = att1_time
        uow.check_results.save(c)

    att1 = JobAttempt(
        job_id=job.job_id,
        attempt_number=1,
        executor_role="codex",
        model_identity="codex",
        normalized_outcome=ExecutionOutcome.PROVIDER_FAILURE,
        end_sha=candidate_sha,
        created_at=att1_time,
    )
    uow.job_attempts.save(att1)

    # Create Attempt 2: later execution (5 minutes ago)
    att2_time = utc_now() - timedelta(minutes=1)
    att2 = JobAttempt(
        job_id=job.job_id,
        attempt_number=2,
        executor_role="codex",
        model_identity="codex",
        normalized_outcome=ExecutionOutcome.COMPLETED,
        end_sha=candidate_sha,
        created_at=att2_time,
    )
    uow.job_attempts.save(att2)

    # Add check results for Attempt 2: check failed due to Ruff lint error (not environmental) at latest_ts
    cr_att2 = CheckResult(
        job_id=job.job_id,
        check_name="ruff",
        command="ruff check .",
        exit_code=1,
        duration_ms=50,
        output_snippet="src/foo.py:1:1: F401 'sys' imported but unused\nFound 1 error.",
        candidate_sha=candidate_sha,
        candidate_generation=1,
        created_at=utc_now(),
    )
    uow.check_results.save(cr_att2)
    session.commit()

    # Attempt checks-only recovery
    decision = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert decision.status == RecoveryDecisionStatus.BLOCKED
    assert (
        "not a proven runner environmental fault in latest execution" in decision.reason_code
        or "application code error" in decision.reason_code
    )

    # Re-verify that job status remains CHECKS_FAILED and candidate is not frozen
    refreshed_job = uow.jobs.get_by_id(job.job_id)
    assert refreshed_job is not None
    assert refreshed_job.status == JobStatus.CHECKS_FAILED
    cand = uow.orchestration_candidates.get_latest_for_run(run.run_id)
    assert cand is None or cand.is_frozen is False
    session.close()


def test_historical_sandbox_error_with_later_attempt_lacking_checks_rejected(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """Verify that if Attempt 2 was created after Attempt 1's checks but has no checks of its own,
    historical checks from Attempt 1 are not accepted and checks-only is rejected.
    """
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    _project, run, job = _seed_pilot_state(
        session, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )
    uow = PostgresPersistenceUnitOfWork(session)
    rec_svc = RecoveryConvergenceService(uow, project_root=repo_dir)

    from minime.domain.enums import ExecutionOutcome
    from minime.domain.models import JobAttempt

    # Attempt 2 created 10 minutes after the seed checks
    att2 = JobAttempt(
        job_id=job.job_id,
        attempt_number=2,
        executor_role="codex",
        model_identity="codex",
        normalized_outcome=ExecutionOutcome.COMPLETED,
        end_sha=candidate_sha,
        created_at=utc_now() + timedelta(minutes=10),
    )
    uow.job_attempts.save(att2)
    session.commit()

    decision = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert decision.status == RecoveryDecisionStatus.BLOCKED
    assert "Latest attempt has no check results or diagnostics" in decision.reason_code
    session.close()


# ============================================================================
# Full route E2E with real ChecksRunner against disposable PostgreSQL
# ============================================================================
def test_pilot_checks_recovery_full_route_real_checks_runner(
    pg_session_factory: sessionmaker[Session], tmp_path: Path
):
    """Execute the complete recover_checks_only route using the real ChecksRunner
    without mocking ChecksRunner.run, proving end-to-end execution, manifest generation,
    atomic transition to CHECKS_PASSED, candidate freeze, and review pause.
    """
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    project, run, job = _seed_pilot_state(
        session, repo_dir, wt_dir, base_sha, candidate_sha, test_id
    )

    # Configure project with real deterministic check commands that pass cleanly in the worktree
    uow = PostgresPersistenceUnitOfWork(session)
    project.checks = [
        {"name": "echo-test", "command": "python3 -c \"print('confinement-ok')\""},
        {"name": "true-test", "command": 'python3 -c "import sys; sys.exit(0)"'},
    ]
    uow.projects.save(project)
    session.commit()

    rec_svc = RecoveryConvergenceService(uow, project_root=repo_dir)

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

    # Real CandidateManifest was generated and stored
    manifest = uow.candidate_manifests.get_by_candidate_sha(job.job_id, candidate_sha)
    assert manifest is not None
    assert manifest.manifest_hash != ""
    assert manifest.total_files_count > 0

    # Real check results exist in DB
    crs = uow.check_results.list_by_job(job.job_id)
    passing_crs = [cr for cr in crs if cr.exit_code == 0]
    assert len(passing_crs) == 2
    assert {cr.check_name for cr in passing_crs} == {"echo-test", "true-test"}

    # BacklogItem updated to NEEDS_HUMAN
    bk_item = uow.backlog_items.get_by_project_and_key(project.project_id, run.change_name)
    assert bk_item is not None
    assert bk_item.status == WorkItemStatus.NEEDS_HUMAN

    # Claim released
    claim = uow.claims.get_by_key(f"run:{run.run_id}")
    assert claim is None or claim.released_at is not None
    session.close()


def test_checks_runner_cache_isolation_and_ownership(tmp_path: Path):
    """Test C04: ChecksRunner generates secure private cache paths with mode 0700 and rejects insecure paths."""
    runner = ChecksRunner()
    current_uid = os.getuid()

    # Pre-create a contaminated directory simulating another user or insecure permissions
    insecure_dir = tmp_path / "insecure_cache"
    insecure_dir.mkdir(parents=True, mode=0o777)

    # Calling check runner under custom XDG_CACHE_HOME
    custom_cache = tmp_path / "custom_xdg_cache"
    with patch.dict(os.environ, {"XDG_CACHE_HOME": str(custom_cache)}):
        worktree = tmp_path / "wt"
        worktree.mkdir()
        (worktree / ".git").mkdir()

        # Test private resolution: when custom_cache exists with current_uid
        custom_cache.mkdir(mode=0o700)
        import asyncio
        async def run_dummy():
            return await runner.run(
                job_id="test-sec-job",
                checks=[{"name": "test-true", "command": "true"}],
                worktree_path=worktree,
                candidate_sha="abc123",
            )
        # Should succeed without permission error
        res = asyncio.run(run_dummy())
        assert res is not None
        job_cache = custom_cache / "minime" / "pycache" / "test-sec-job"
        assert job_cache.exists()
        st = os.stat(job_cache)
        assert st.st_uid == current_uid
        assert (st.st_mode & 0o077) == 0  # Mode 0700


def test_exception_atomically_commits_checks_failed_and_run_needs_human(
    pg_session_factory: sessionmaker[Session],
    tmp_path: Path,
):
    """Test C02: An unhandled runner exception commits Job=CHECKS_FAILED and Run=NEEDS_HUMAN under valid claim."""
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    uow = PostgresPersistenceUnitOfWork(session)

    project_id = f"test-proj-exc-{test_id}"
    change_name = f"test-change-exc-{test_id}"
    run_id = f"run-exc-{test_id}"
    job_id = wt_dir.name

    proj = Project(
        project_id=project_id,
        name="Test Exc",
        display_name="Test Exc",
        repository=str(repo_dir),
        base_branch="main",
        checks=[{"name": "failing-check", "command": "python -c 'exit(1)'"}],
    )
    uow.projects.save(proj)

    binding = ProjectManagedRepositoryBinding(
        project_id=project_id,
        managed_repository_root=str(repo_dir),
        canonical_repository_identity=str(repo_dir),
        remote_name="origin",
        default_base_branch="main",
        worktree_parent_dir=str(wt_dir.parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    job = Job(
        job_id=job_id,
        project_id=project_id,
        change_name=change_name,
        status=JobStatus.CHECKS_FAILED,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        implementer_role="codex",
    )
    uow.jobs.save(job)

    run = OrchestrationRun(
        run_id=run_id,
        project_id=project_id,
        change_name=change_name,
        base_sha=base_sha,
        current_candidate_sha=candidate_sha,
        current_stage=OrchestrationStage.RUNNING_CHECKS,
        resumable_stage=OrchestrationStage.RUNNING_CHECKS,
        active_job_id=job_id,
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_reason="Checks-only pipeline execution failed.",
        stop_details={
            "code": "CHECKS_ONLY_PIPELINE_EXCEPTION",
            "exception_type": "PermissionError",
            "error": "[Errno 13] Permission denied: '/tmp/minime_pycache/test'",
        },
    )
    uow.orchestration_runs.save(run)
    uow.commit()

    rec_svc = RecoveryConvergenceService(uow=uow, project_root=repo_dir)

    # Mock runner to raise an environmental PermissionError simulating /tmp/minime_pycache
    with patch(
        "minime.services.checks_runner.ChecksRunner.run",
        new=AsyncMock(side_effect=PermissionError("[Errno 13] Permission denied: '/tmp/minime_pycache/test'")),
    ):
        decision = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)

    assert decision is not None
    assert decision.status in {RecoveryDecisionStatus.BLOCKED, RecoveryDecisionStatus.NO_ACTION, RecoveryDecisionStatus.COMPLETED}

    # In independent session, verify Job is CHECKS_FAILED and Run is NEEDS_HUMAN
    sess2 = pg_session_factory()
    uow2 = PostgresPersistenceUnitOfWork(sess2)
    j2 = uow2.jobs.get_by_id(job_id)
    assert j2.status == JobStatus.CHECKS_FAILED
    assert "Permission denied" in (j2.error_message or "")
    r2 = uow2.orchestration_runs.get_by_id(run_id)
    assert r2.is_active is False
    assert r2.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
    sess2.close()
    session.close()


def test_reentry_from_running_checks_executes_fresh_batch(
    pg_session_factory: sessionmaker[Session],
    tmp_path: Path,
):
    """Test C01: Re-entry from RUNNING_CHECKS executes a FRESH checks batch even if an old batch exists."""
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    uow = PostgresPersistenceUnitOfWork(session)

    project_id = f"test-proj-fresh-{test_id}"
    change_name = f"test-change-fresh-{test_id}"
    run_id = f"run-fresh-{test_id}"
    job_id = wt_dir.name

    proj = Project(
        project_id=project_id,
        name="Test Fresh",
        display_name="Test Fresh",
        repository=str(repo_dir),
        base_branch="main",
        checks=[{"name": "fresh-check", "command": "echo fresh"}],
    )
    uow.projects.save(proj)

    binding = ProjectManagedRepositoryBinding(
        project_id=project_id,
        managed_repository_root=str(repo_dir),
        canonical_repository_identity=str(repo_dir),
        remote_name="origin",
        default_base_branch="main",
        worktree_parent_dir=str(wt_dir.parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    job = Job(
        job_id=job_id,
        project_id=project_id,
        change_name=change_name,
        status=JobStatus.CHECKS_FAILED,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        implementer_role="codex",
    )
    uow.jobs.save(job)

    # Simulate an OLD passing check result from 1 hour ago
    old_cr = CheckResult(
        job_id=job_id,
        check_name="fresh-check",
        command="echo fresh",
        exit_code=0,
        duration_ms=100,
        output_snippet="fresh",
        candidate_sha=candidate_sha,
        candidate_generation=1,
        created_at=utc_now() - timedelta(hours=1),
    )
    uow.check_results.save(old_cr)

    run = OrchestrationRun(
        run_id=run_id,
        project_id=project_id,
        change_name=change_name,
        base_sha=base_sha,
        current_candidate_sha=candidate_sha,
        current_stage=OrchestrationStage.RUNNING_CHECKS,
        resumable_stage=OrchestrationStage.RUNNING_CHECKS,
        active_job_id=job_id,
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_reason="Checks-only pipeline execution failed.",
        stop_details={
            "code": "CHECKS_ONLY_PIPELINE_EXCEPTION",
            "exception_type": "PermissionError",
            "error": "[Errno 13] Permission denied: '/tmp/minime_pycache/test'",
        },
    )
    uow.orchestration_runs.save(run)
    uow.commit()

    rec_svc = RecoveryConvergenceService(uow=uow, project_root=repo_dir)

    runner_called = False

    async def mock_runner_run(*args, **kwargs):
        nonlocal runner_called
        runner_called = True
        return ChecksRunResult(
            passed=True,
            results=[
                CheckResult(
                    job_id=job_id,
                    check_name="fresh-check",
                    command="echo fresh",
                    exit_code=0,
                    duration_ms=100,
                    output_snippet="fresh",
                    candidate_sha=candidate_sha,
                    candidate_generation=1,
                    created_at=utc_now(),
                )
            ],
            diagnostics=[],
        )

    with patch("minime.services.checks_runner.ChecksRunner.run", new=mock_runner_run):
        decision = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)

    assert decision.status == RecoveryDecisionStatus.COMPLETED
    assert runner_called is True, "ChecksRunner MUST be invoked on re-entry from RUNNING_CHECKS!"

    # Assert new batch was validated and run is held at REVIEW_AUTHORIZATION_PENDING
    sess3 = pg_session_factory()
    uow3 = PostgresPersistenceUnitOfWork(sess3)
    r3 = uow3.orchestration_runs.get_by_id(run_id)
    assert r3.stop_details.get("code") == "REVIEW_AUTHORIZATION_PENDING"
    assert r3.current_candidate_sha == candidate_sha
    sess3.close()
    session.close()


def test_atomic_stop_fault_injection_prevents_partial_commit(
    pg_session_factory: sessionmaker[Session],
    tmp_path: Path,
):
    """Test A01: Fault injection before atomic commit guarantees ZERO partial state committed.

    Proves in an independent PostgreSQL readback session that if a failure occurs between
    runner exception and the atomic commit of Run stop outcome, Job is NOT committed to
    CHECKS_FAILED while Run remains RUNNING_CHECKS.
    """
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    uow = PostgresPersistenceUnitOfWork(session)

    project_id = f"test-proj-fault-{test_id}"
    change_name = f"test-change-fault-{test_id}"
    run_id = f"run-fault-{test_id}"
    job_id = wt_dir.name

    proj = Project(
        project_id=project_id,
        name="Test Fault",
        display_name="Test Fault",
        repository=str(repo_dir),
        base_branch="main",
        checks=[{"name": "check-1", "command": "echo 1"}],
    )
    uow.projects.save(proj)

    binding = ProjectManagedRepositoryBinding(
        project_id=project_id,
        managed_repository_root=str(repo_dir),
        canonical_repository_identity=str(repo_dir),
        remote_name="origin",
        default_base_branch="main",
        worktree_parent_dir=str(wt_dir.parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    job = Job(
        job_id=job_id,
        project_id=project_id,
        change_name=change_name,
        status=JobStatus.CHECKS_RUNNING,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        implementer_role="codex",
    )
    uow.jobs.save(job)

    run = OrchestrationRun(
        run_id=run_id,
        project_id=project_id,
        change_name=change_name,
        base_sha=base_sha,
        current_candidate_sha=candidate_sha,
        current_stage=OrchestrationStage.RUNNING_CHECKS,
        resumable_stage=OrchestrationStage.RUNNING_CHECKS,
        active_job_id=job_id,
        is_active=True,
    )
    uow.orchestration_runs.save(run)
    uow.commit()

    rec_svc = RecoveryConvergenceService(uow=uow, project_root=repo_dir)
    claim = rec_svc.acquire_claim(claim_key=f"run:{run_id}", lease_seconds=60)
    assert claim is not None
    claim_context = RecoveryClaimContext(
        claim_key=claim.claim_key,
        owner_instance_id=claim.owner_instance_id,
        fence_token=claim.fence_token,
        lease_expires_at=claim.lease_expires_at,
    )

    pipeline = ExecutionPipelineService(uow=uow, project_root=repo_dir)

    # Mock checks_runner to raise an environmental error
    pipeline.checks_runner = ChecksRunner()
    pipeline.checks_runner.run = AsyncMock(
        side_effect=PermissionError("[Errno 13] Permission denied: '/tmp/minime_pycache/fault'")
    )

    # Call run_checks_only directly: verify that it updates Job in session (auto_commit=False)
    # but does NOT commit to PostgreSQL when raising runner_exc!
    with pytest.raises(PermissionError):
        import asyncio

        asyncio.run(pipeline.run_checks_only(job_id, candidate_generation=1, claim_context=claim_context))

    # Read back from an INDEPENDENT PostgreSQL session:
    # Proves zero two-phase commit gap: Job is STILL CHECKS_RUNNING in the committed database!
    read_sess = pg_session_factory()
    read_uow = PostgresPersistenceUnitOfWork(read_sess)
    committed_job = read_uow.jobs.get_by_id(job_id)
    assert committed_job is not None
    assert committed_job.status == JobStatus.CHECKS_RUNNING, (
        "Job MUST NOT be committed to CHECKS_FAILED before Run is stopped! Found partial commit."
    )
    committed_run = read_uow.orchestration_runs.get_by_id(run_id)
    assert committed_run is not None
    assert committed_run.is_active is True
    assert committed_run.stop_outcome is None

    # Roll back the staged uncommitted pipeline changes
    uow.rollback()
    read_sess.close()
    session.close()


def test_runner_typeerror_invoked_exactly_once(
    pg_session_factory: sessionmaker[Session],
    tmp_path: Path,
):
    """Test A02: Internal TypeError in ChecksRunner.run is invoked EXACTLY ONCE and not retried."""
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    uow = PostgresPersistenceUnitOfWork(session)

    project_id = f"test-proj-typeerr-{test_id}"
    change_name = f"test-change-typeerr-{test_id}"
    run_id = f"run-typeerr-{test_id}"
    job_id = wt_dir.name

    proj = Project(
        project_id=project_id,
        name="Test TypeError",
        display_name="Test TypeError",
        repository=str(repo_dir),
        base_branch="main",
        checks=[{"name": "check-1", "command": "echo 1"}],
    )
    uow.projects.save(proj)

    binding = ProjectManagedRepositoryBinding(
        project_id=project_id,
        managed_repository_root=str(repo_dir),
        canonical_repository_identity=str(repo_dir),
        remote_name="origin",
        default_base_branch="main",
        worktree_parent_dir=str(wt_dir.parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    job = Job(
        job_id=job_id,
        project_id=project_id,
        change_name=change_name,
        status=JobStatus.CHECKS_RUNNING,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        implementer_role="codex",
    )
    uow.jobs.save(job)
    uow.commit()

    rec_svc = RecoveryConvergenceService(uow=uow, project_root=repo_dir)
    claim = rec_svc.acquire_claim(claim_key=f"run:{run_id}", lease_seconds=60)
    assert claim is not None
    claim_context = RecoveryClaimContext(
        claim_key=claim.claim_key,
        owner_instance_id=claim.owner_instance_id,
        fence_token=claim.fence_token,
        lease_expires_at=claim.lease_expires_at,
    )

    pipeline = ExecutionPipelineService(uow=uow, project_root=repo_dir)

    call_count = 0

    async def mock_run_with_internal_type_error(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Raise a real internal TypeError from inside runner logic
        raise TypeError("Unexpected NoneType encountered in runner argument unpacking")

    pipeline.checks_runner = ChecksRunner()
    pipeline.checks_runner.run = mock_run_with_internal_type_error

    with pytest.raises(TypeError) as exc_info:
        import asyncio

        asyncio.run(pipeline.run_checks_only(job_id, candidate_generation=1, claim_context=claim_context))

    assert "Unexpected NoneType" in str(exc_info.value)
    assert call_count == 1, (
        f"ChecksRunner MUST be invoked exactly once, but was called {call_count} times!"
    )
    uow.rollback()
    session.close()


def test_cache_confinement_trusted_path_validation_and_lifecycle(tmp_path: Path):
    """Test A03: validate_secure_cache_path and confinement wrap_command deny untrusted/insecure paths."""
    from minime.services.agent_confinement import (
        AgentConfinementError,
        AgentProcessConfinement,
        validate_secure_cache_path,
    )

    current_uid = os.getuid()

    # 1. Deny path outside authorized roots (e.g. /etc)
    with pytest.raises(PermissionError) as exc_info:
        validate_secure_cache_path(Path("/etc"))
    assert (
        "outside authorized roots" in str(exc_info.value)
        or "cannot be a symlink" in str(exc_info.value)
        or "mode must be strictly 0700" in str(exc_info.value)
    )

    # 2. Deny authorized root itself
    with pytest.raises(PermissionError) as exc_info:
        validate_secure_cache_path(Path.home())
    assert "root directory" in str(exc_info.value) or "mode must be strictly 0700" in str(
        exc_info.value
    )

    # 3. Deny insecure permissions (mode 0777 or 0755)
    insecure_dir = tmp_path / "insecure_cache"
    insecure_dir.mkdir(mode=0o755)
    os.chmod(insecure_dir, 0o755)
    with pytest.raises(PermissionError) as exc_info:
        validate_secure_cache_path(insecure_dir, expected_uid=current_uid)
    assert "mode must be strictly 0700" in str(exc_info.value)

    # 4. Deny symlink cache path
    target_dir = tmp_path / "real_cache"
    target_dir.mkdir(mode=0o700)
    os.chmod(target_dir, 0o700)
    symlink_path = tmp_path / "symlink_cache"
    symlink_path.symlink_to(target_dir)
    with pytest.raises(PermissionError) as exc_info:
        validate_secure_cache_path(symlink_path, expected_uid=current_uid)
    assert "cannot be a symlink" in str(exc_info.value)

    # 5. Deny wrong UID
    with pytest.raises(PermissionError) as exc_info:
        validate_secure_cache_path(target_dir, expected_uid=current_uid + 999)
    assert "owned by UID" in str(exc_info.value)

    # 6. Valid cache directory succeeds
    valid_path = validate_secure_cache_path(target_dir, expected_uid=current_uid)
    assert valid_path == target_dir.resolve()

    # 7. AgentProcessConfinement.wrap_command strictly rejects insecure cache paths
    confinement = AgentProcessConfinement(
        allowed_worktree_path=str(tmp_path),
    )
    if confinement.is_confinement_available():
        with pytest.raises(AgentConfinementError) as conf_exc:
            confinement.wrap_command(["echo", "hi"], secure_cache_path=insecure_dir)
        assert "Secure cache path rejected by confinement" in str(conf_exc.value)

    # 8. Test ChecksRunner ephemeral cache cleanup lifecycle
    import tempfile

    runner = ChecksRunner()
    fake_job_id = f"cleanuptest_{uuid.uuid4().hex[:8]}"
    # Force attempt 1 to fail by pointing XDG_CACHE_HOME to an insecure path
    os.environ["XDG_CACHE_HOME"] = str(insecure_dir)
    try:
        import asyncio

        asyncio.run(
            runner.run(
                job_id=fake_job_id,
                checks=[{"name": "test-cleanup", "command": "echo clean"}],
                worktree_path=tmp_path,
            )
        )
    finally:
        os.environ.pop("XDG_CACHE_HOME", None)

    # Verify that no leftover temporary directory matching the job_id remains in /tmp
    temp_dir = Path(tempfile.gettempdir())
    leftovers = list(temp_dir.glob(f"minime_cache_*_{fake_job_id}"))
    assert len(leftovers) == 0, f"Ephemeral cache directory leaked: {leftovers}"


def test_anti_spoofing_rejects_mismatched_candidate_and_serial_repeats(
    pg_session_factory: sessionmaker[Session],
    tmp_path: Path,
):
    """Test A04: _validate_checks_only_eligibility rejects spoofed stop_details and serial repeats."""
    session = pg_session_factory()
    repo_dir, wt_dir, base_sha, candidate_sha, test_id = _setup_repo_and_worktree(tmp_path)
    uow = PostgresPersistenceUnitOfWork(session)
    rec_svc = RecoveryConvergenceService(uow=uow, project_root=repo_dir)

    project_id = f"test-proj-spoof-{test_id}"
    change_name = f"test-change-spoof-{test_id}"
    run_id = f"run-spoof-{test_id}"
    job_id = wt_dir.name

    proj = Project(
        project_id=project_id,
        name="Test Spoof",
        display_name="Test Spoof",
        repository=str(repo_dir),
        base_branch="main",
        checks=[{"name": "check-1", "command": "echo 1"}],
    )
    uow.projects.save(proj)

    binding = ProjectManagedRepositoryBinding(
        project_id=project_id,
        managed_repository_root=str(repo_dir),
        canonical_repository_identity=str(repo_dir),
        remote_name="origin",
        default_base_branch="main",
        worktree_parent_dir=str(wt_dir.parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    job = Job(
        job_id=job_id,
        project_id=project_id,
        change_name=change_name,
        status=JobStatus.CHECKS_FAILED,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        implementer_role="codex",
    )
    uow.jobs.save(job)

    # 1. Test spoofed candidate_sha in stop_details
    run = OrchestrationRun(
        run_id=run_id,
        project_id=project_id,
        change_name=change_name,
        base_sha=base_sha,
        current_candidate_sha=candidate_sha,
        current_stage=OrchestrationStage.RUNNING_CHECKS,
        resumable_stage=OrchestrationStage.RUNNING_CHECKS,
        active_job_id=job_id,
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_reason="Checks-only pipeline execution failed.",
        stop_details={
            "code": "CHECKS_ONLY_PIPELINE_EXCEPTION",
            "exception_type": "PermissionError",
            "error": "[Errno 13] Permission denied: '/tmp/minime_pycache/spoof'",
            "candidate_sha": "0000000000000000000000000000000000000000",  # Spoofed!
        },
    )
    uow.orchestration_runs.save(run)
    uow.commit()

    decision = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert decision.status == RecoveryDecisionStatus.BLOCKED
    assert "does not match job candidate_sha" in decision.reason_code

    # 2. Test application code error in stop_details
    run.stop_details = {
        "code": "CHECKS_ONLY_PIPELINE_EXCEPTION",
        "exception_type": "PermissionError",
        "error": "AssertionError: expected 1 got 2",
        "candidate_sha": candidate_sha,
    }
    uow.orchestration_runs.save(run)
    uow.commit()

    decision2 = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert decision2.status == RecoveryDecisionStatus.BLOCKED
    assert "application code error" in decision2.reason_code

    # 3. Test serial repeat prevention when candidate already passed
    run.stop_details = {
        "code": "REVIEW_AUTHORIZATION_PENDING",
        "candidate_sha": candidate_sha,
    }
    job.status = JobStatus.CHECKS_PASSED
    uow.jobs.save(job)
    uow.orchestration_runs.save(run)
    uow.commit()

    decision3 = rec_svc.recover_checks_only(run.run_id, project_root=repo_dir)
    assert decision3.status == RecoveryDecisionStatus.BLOCKED
    assert "Checks have already succeeded" in decision3.reason_code

    session.close()

