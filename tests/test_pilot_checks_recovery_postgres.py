"""Targeted E2E tests for pilot checks-only checkpoint recovery in disposable PostgreSQL."""

from __future__ import annotations

import os
import subprocess
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
