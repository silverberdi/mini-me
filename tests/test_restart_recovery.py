"""Unit tests for RestartRecoveryService, concrete Git lock ownership evidence, and daemon restart/interruption tracking."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from minime.domain.enums import EventType, GitOperationStatus, JobStatus
from minime.domain.models import CheckResult, GitOperation, Job, Project
from minime.services.restart_recovery_service import RestartRecoveryService
from minime.services.worktree_manager import WorktreeManager


def test_daemon_startup_zero_jobs_emits_daemon_restarted(in_memory_uow, tmp_path):
    """Verify that daemon startup with 0 active jobs still persists DAEMON_RESTARTED event."""
    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 0
    events = in_memory_uow.events.list_events()
    restart_events = [e for e in events if e.event_type == EventType.DAEMON_RESTARTED]
    assert len(restart_events) == 1
    assert restart_events[0].payload["active_jobs_count"] == 0
    assert restart_events[0].payload["interrupted_jobs_count"] == 0


def test_daemon_startup_single_interrupted_job_emits_full_evidence(in_memory_uow, tmp_path):
    """Verify that startup with one non-terminal job persists DAEMON_RESTARTED, JOB_INTERRUPTED, and JOB_RECOVERED."""
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    job = Job(
        job_id="job-interrupted-1",
        project_id="mini-me",
        change_name="005-feature",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.QUEUED

    events = in_memory_uow.events.list_events()
    event_types = [e.event_type for e in events]
    assert EventType.DAEMON_RESTARTED in event_types
    assert EventType.JOB_INTERRUPTED in event_types
    assert EventType.JOB_RECOVERED in event_types

    interrupted_evt = next(e for e in events if e.event_type == EventType.JOB_INTERRUPTED)
    assert interrupted_evt.payload["job_id"] == "job-interrupted-1"
    assert interrupted_evt.payload["previous_status"] == JobStatus.RUNNING.value
    assert interrupted_evt.payload["interrupted_stage"] == "implementer"


def test_daemon_startup_multiple_interrupted_jobs(in_memory_uow, tmp_path):
    """Verify that multiple non-terminal jobs result in one DAEMON_RESTARTED event and per-job JOB_INTERRUPTED."""
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    for i in range(3):
        job = Job(
            job_id=f"job-multi-{i}",
            project_id="mini-me",
            change_name=f"005-feature-{i}",
            implementer_role="codex",
            status=JobStatus.RUNNING,
        )
        in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 3
    events = in_memory_uow.events.list_events()
    restart_events = [e for e in events if e.event_type == EventType.DAEMON_RESTARTED]
    assert len(restart_events) == 1
    assert restart_events[0].payload["active_jobs_count"] == 3
    assert restart_events[0].payload["interrupted_jobs_count"] == 3

    interrupted_events = [e for e in events if e.event_type == EventType.JOB_INTERRUPTED]
    assert len(interrupted_events) == 3


def test_terminal_jobs_never_emit_job_interrupted(in_memory_uow, tmp_path):
    """Verify that completed or failed terminal jobs never get JOB_INTERRUPTED events."""
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    job_completed = Job(
        job_id="job-terminal-1",
        project_id="mini-me",
        change_name="005-done",
        implementer_role="codex",
        status=JobStatus.READY_TO_MERGE,
    )
    job_failed = Job(
        job_id="job-terminal-2",
        project_id="mini-me",
        change_name="005-failed",
        implementer_role="codex",
        status=JobStatus.FAILED,
    )
    in_memory_uow.jobs.save(job_completed)
    in_memory_uow.jobs.save(job_failed)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 0
    events = in_memory_uow.events.list_events()
    interrupted_events = [e for e in events if e.event_type == EventType.JOB_INTERRUPTED]
    assert len(interrupted_events) == 0


def test_restart_recovery_preserves_completed_checkpoint(in_memory_uow, tmp_path):
    """Verify that a job that completed checks before crash retains its checkpoint at CHECKS_PASSED."""
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    job = Job(
        job_id="job-crash-1",
        project_id="mini-me",
        change_name="005-feature",
        implementer_role="codex",
        status=JobStatus.REVIEW_RUNNING,
        candidate_sha="abc1234",
        base_sha="def5678",
    )
    in_memory_uow.jobs.save(job)

    check = CheckResult(
        job_id="job-crash-1",
        check_name="unit_tests",
        command="pytest",
        exit_code=0,
        duration_ms=10,
        output_snippet="ok",
    )
    in_memory_uow.check_results.save(check)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    rec = reconciled[0]
    assert rec.status == JobStatus.CHECKS_PASSED
    assert rec.candidate_sha == "abc1234"

    events = in_memory_uow.events.list_events()
    interrupted_events = [e for e in events if e.event_type == EventType.JOB_INTERRUPTED]
    assert len(interrupted_events) == 1
    assert interrupted_events[0].payload["previous_status"] == JobStatus.REVIEW_RUNNING.value

    rec_events = [e for e in events if e.event_type == EventType.JOB_RECOVERED]
    assert len(rec_events) == 1
    assert rec_events[0].payload["new_status"] == JobStatus.CHECKS_PASSED.value


def test_interrupted_running_never_inferred_successful(in_memory_uow, tmp_path):
    """Verify that an interrupted RUNNING job without candidate SHA is re-queued, not marked completed."""
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    job = Job(
        job_id="job-crash-2",
        project_id="mini-me",
        change_name="005-feature-2",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.QUEUED
    assert reconciled[0].candidate_sha is None


# ==============================================================================
# SECTION A: Worktree Path Identity Regressions
# ==============================================================================


@pytest.mark.asyncio
async def test_worktree_add_records_managed_worktree_path_not_cwd(in_memory_uow, tmp_path):
    """A1. worktree_add runs with cwd=project_root but records GitOperation.worktree_path=<worktree_path>."""
    manager = WorktreeManager(project_root=tmp_path, uow=in_memory_uow)
    job_id = "job-wt-identity-1"
    target_worktree = (tmp_path / ".minime" / "worktrees" / job_id).resolve()

    # Mock git execution to succeed without creating full git repo
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = mock_exec.return_value
        mock_proc.pid = 4321
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"sha123\n", b""))

        await manager.create_worktree(
            job_id=job_id,
            change_name="test-change",
            base_branch="main",
            project_id="mini-me",
        )

    ops = in_memory_uow.git_operations.list_by_job(job_id)
    assert len(ops) >= 1
    add_op = next(op for op in ops if op.operation_type == "worktree_add")

    # Persisted worktree_path MUST be the exact target worktree, NOT the command cwd (project_root)
    assert add_op.worktree_path == str(target_worktree)
    assert add_op.worktree_path != str(tmp_path.resolve())
    assert add_op.pid == 4321
    assert add_op.status == GitOperationStatus.COMPLETED


@pytest.mark.asyncio
async def test_worktree_remove_records_managed_worktree_path(in_memory_uow, tmp_path):
    """A2. worktree_remove records the exact managed worktree path being removed."""
    manager = WorktreeManager(project_root=tmp_path, uow=in_memory_uow)
    job_id = "job-wt-remove-1"
    target_worktree = (tmp_path / ".minime" / "worktrees" / job_id).resolve()
    target_worktree.mkdir(parents=True, exist_ok=True)

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = mock_exec.return_value
        mock_proc.pid = 4322
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        await manager.cleanup_worktree(job_id=job_id, project_id="mini-me")

    ops = in_memory_uow.git_operations.list_by_job(job_id)
    assert len(ops) >= 1
    remove_op = next(op for op in ops if op.operation_type == "worktree_remove")
    assert remove_op.worktree_path == str(target_worktree)
    assert remove_op.worktree_path != str(tmp_path.resolve())


def test_restart_recovery_matches_real_worktree_path(in_memory_uow, tmp_path):
    """A3. Ownership record created with exact worktree path matches recovery lookup for that worktree."""
    job_id = "job-real-match"
    target_worktree = (tmp_path / ".minime" / "worktrees" / job_id).resolve()
    worktree_git_dir = target_worktree / ".git"
    worktree_git_dir.mkdir(parents=True, exist_ok=True)
    lock_file = worktree_git_dir / "index.lock"
    dead_pid = 99999999
    lock_file.write_text(f"{dead_pid}\n", encoding="utf-8")

    git_op = GitOperation(
        operation_id="op-real-match",
        job_id=job_id,
        project_id="mini-me",
        worktree_path=str(target_worktree),
        operation_type="worktree_add",
        pid=dead_pid,
        status=GitOperationStatus.RUNNING,
    )
    in_memory_uow.git_operations.save(git_op)

    job = Job(
        job_id=job_id,
        project_id="mini-me",
        change_name="005-match",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.QUEUED
    assert not lock_file.exists()


def test_ownership_record_for_different_target_worktree_fails_closed(in_memory_uow, tmp_path):
    """A4. Ownership record exists for a different target worktree -> retained."""
    job_id = "job-diff-wt"
    target_worktree = (tmp_path / ".minime" / "worktrees" / job_id).resolve()
    other_worktree = (tmp_path / ".minime" / "worktrees" / "other-job").resolve()

    worktree_git_dir = target_worktree / ".git"
    worktree_git_dir.mkdir(parents=True, exist_ok=True)
    lock_file = worktree_git_dir / "index.lock"
    dead_pid = 99999999
    lock_file.write_text(f"{dead_pid}\n", encoding="utf-8")

    git_op = GitOperation(
        operation_id="op-diff-wt",
        job_id=job_id,
        project_id="mini-me",
        worktree_path=str(other_worktree),
        operation_type="worktree_add",
        pid=dead_pid,
        status=GitOperationStatus.RUNNING,
    )
    in_memory_uow.git_operations.save(git_op)

    job = Job(
        job_id=job_id,
        project_id="mini-me",
        change_name="005-diff-wt",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.RECOVERY_BLOCKED
    assert lock_file.exists()


# ==============================================================================
# SECTION B: PID Consistency Regressions
# ==============================================================================


def test_matching_operation_with_null_pid_fails_closed(in_memory_uow, tmp_path):
    """B5. Matching GitOperation with pid=None + dead lock PID -> retain lock -> RECOVERY_BLOCKED."""
    job_id = "job-null-pid"
    worktree_dir = (tmp_path / ".minime" / "worktrees" / job_id).resolve()
    worktree_git_dir = worktree_dir / ".git"
    worktree_git_dir.mkdir(parents=True, exist_ok=True)
    lock_file = worktree_git_dir / "index.lock"
    lock_file.write_text("99999999\n", encoding="utf-8")

    # Record exists and is RUNNING, but pid is None (crashed before PID recorded)
    git_op = GitOperation(
        operation_id="op-null-pid",
        job_id=job_id,
        project_id="mini-me",
        worktree_path=str(worktree_dir),
        operation_type="worktree_add",
        pid=None,
        status=GitOperationStatus.RUNNING,
    )
    in_memory_uow.git_operations.save(git_op)

    job = Job(
        job_id=job_id,
        project_id="mini-me",
        change_name="005-null-pid",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.RECOVERY_BLOCKED
    assert "unrecorded pid" in reconciled[0].recovery_blocked_reason.lower()
    assert lock_file.exists()  # Retained!

    events = in_memory_uow.events.list_events()
    assert not any(e.event_type == EventType.WORKTREE_LOCK_RECOVERED for e in events)
    assert any(e.event_type == EventType.RECOVERY_BLOCKED for e in events)


def test_matching_operation_pid_mismatch_fails_closed(in_memory_uow, tmp_path):
    """B6. Matching operation pid=123 + lock PID=456 -> retain -> RECOVERY_BLOCKED."""
    job_id = "job-pid-mismatch"
    worktree_dir = (tmp_path / ".minime" / "worktrees" / job_id).resolve()
    worktree_git_dir = worktree_dir / ".git"
    worktree_git_dir.mkdir(parents=True, exist_ok=True)
    lock_file = worktree_git_dir / "index.lock"
    lock_file.write_text("456\n", encoding="utf-8")

    git_op = GitOperation(
        operation_id="op-pid-123",
        job_id=job_id,
        project_id="mini-me",
        worktree_path=str(worktree_dir),
        operation_type="worktree_add",
        pid=123,
        status=GitOperationStatus.RUNNING,
    )
    in_memory_uow.git_operations.save(git_op)

    job = Job(
        job_id=job_id,
        project_id="mini-me",
        change_name="005-pid-mismatch",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.RECOVERY_BLOCKED
    assert "does not match recorded mini me operation pid" in reconciled[0].recovery_blocked_reason.lower()
    assert lock_file.exists()


def test_matching_operation_with_living_pid_fails_closed(in_memory_uow, tmp_path):
    """B7. Matching operation pid=123 + lock PID=123 + PID alive -> retain -> RECOVERY_BLOCKED / ACTIVE_OWNER."""
    job_id = "job-living-pid"
    worktree_dir = (tmp_path / ".minime" / "worktrees" / job_id).resolve()
    worktree_git_dir = worktree_dir / ".git"
    worktree_git_dir.mkdir(parents=True, exist_ok=True)
    lock_file = worktree_git_dir / "index.lock"
    live_pid = os.getpid()
    lock_file.write_text(f"{live_pid}\n", encoding="utf-8")

    git_op = GitOperation(
        operation_id="op-living-pid",
        job_id=job_id,
        project_id="mini-me",
        worktree_path=str(worktree_dir),
        operation_type="worktree_add",
        pid=live_pid,
        status=GitOperationStatus.RUNNING,
    )
    in_memory_uow.git_operations.save(git_op)

    job = Job(
        job_id=job_id,
        project_id="mini-me",
        change_name="005-living-pid",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.RECOVERY_BLOCKED
    assert "owned by active process" in reconciled[0].recovery_blocked_reason.lower()
    assert lock_file.exists()


def test_matching_operation_with_dead_pid_eligible_for_safe_orphaned(in_memory_uow, tmp_path):
    """B8. Matching operation pid=123 + lock PID=123 + PID dead -> SAFE_ORPHANED."""
    job_id = "job-dead-pid-match"
    worktree_dir = (tmp_path / ".minime" / "worktrees" / job_id).resolve()
    worktree_git_dir = worktree_dir / ".git"
    worktree_git_dir.mkdir(parents=True, exist_ok=True)
    lock_file = worktree_git_dir / "index.lock"
    dead_pid = 99999999
    lock_file.write_text(f"{dead_pid}\n", encoding="utf-8")

    git_op = GitOperation(
        operation_id="op-dead-match",
        job_id=job_id,
        project_id="mini-me",
        worktree_path=str(worktree_dir),
        operation_type="worktree_add",
        pid=dead_pid,
        status=GitOperationStatus.RUNNING,
    )
    in_memory_uow.git_operations.save(git_op)

    job = Job(
        job_id=job_id,
        project_id="mini-me",
        change_name="005-dead-match",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.QUEUED
    assert not lock_file.exists()

    events = in_memory_uow.events.list_events()
    lock_evts = [e for e in events if e.event_type == EventType.WORKTREE_LOCK_RECOVERED]
    assert len(lock_evts) == 1
    assert lock_evts[0].payload["owning_pid"] == dead_pid


def test_random_dead_pid_without_ownership_record_retained(in_memory_uow, tmp_path):
    """B9. Random dead PID without ownership record -> retained."""
    job_id = "job-random-dead"
    worktree_dir = (tmp_path / ".minime" / "worktrees" / job_id).resolve()
    worktree_git_dir = worktree_dir / ".git"
    worktree_git_dir.mkdir(parents=True, exist_ok=True)
    lock_file = worktree_git_dir / "index.lock"
    lock_file.write_text("99999999\n", encoding="utf-8")

    job = Job(
        job_id=job_id,
        project_id="mini-me",
        change_name="005-random-dead",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.RECOVERY_BLOCKED
    assert lock_file.exists()


def test_malformed_or_empty_lock_retained(in_memory_uow, tmp_path):
    """B10. Malformed or empty lock -> retained."""
    job_id = "job-empty-lock"
    worktree_dir = (tmp_path / ".minime" / "worktrees" / job_id).resolve()
    worktree_git_dir = worktree_dir / ".git"
    worktree_git_dir.mkdir(parents=True, exist_ok=True)
    lock_file = worktree_git_dir / "index.lock"
    lock_file.write_text("", encoding="utf-8")

    git_op = GitOperation(
        operation_id="op-empty-lock",
        job_id=job_id,
        project_id="mini-me",
        worktree_path=str(worktree_dir),
        operation_type="worktree_add",
        pid=12345,
        status=GitOperationStatus.RUNNING,
    )
    in_memory_uow.git_operations.save(git_op)

    job = Job(
        job_id=job_id,
        project_id="mini-me",
        change_name="005-empty-lock",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.RECOVERY_BLOCKED
    assert "empty" in reconciled[0].recovery_blocked_reason.lower()
    assert lock_file.exists()


# ==============================================================================
# SECTION C: Persistence Ordering Regressions
# ==============================================================================


@pytest.mark.asyncio
async def test_git_operation_persistence_failure_prevents_subprocess_launch(tmp_path):
    """C11. GitOperation persistence failure before subprocess prevents subprocess launch."""
    class FailingGitOpRepo:
        def save(self, op):
            raise RuntimeError("Database connection failure")

    class FailingUoW:
        def __init__(self):
            self.git_operations = FailingGitOpRepo()
        def commit(self):
            pass

    manager = WorktreeManager(project_root=tmp_path, uow=FailingUoW())

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        with pytest.raises(RuntimeError, match="Database connection failure"):
            await manager._git(
                ["worktree", "add", "dummy"],
                job_id="job-fail-db",
                project_id="mini-me",
                operation_type="worktree_add",
                managed_worktree_path=tmp_path / ".minime" / "worktrees" / "job-fail-db",
            )
        # Subprocess MUST NOT be launched!
        mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_operation_created_with_exact_managed_worktree_path_before_launch(in_memory_uow, tmp_path):
    """C12. GitOperation is saved with exact managed worktree path prior to launching Git subprocess."""
    manager = WorktreeManager(project_root=tmp_path, uow=in_memory_uow)
    job_id = "job-persist-order"
    expected_worktree = (tmp_path / ".minime" / "worktrees" / job_id).resolve()

    saved_worktree_path = None
    orig_save = in_memory_uow.git_operations.save

    def capture_save(op):
        nonlocal saved_worktree_path
        saved_worktree_path = op.worktree_path
        orig_save(op)

    with patch.object(in_memory_uow.git_operations, "save", side_effect=capture_save):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = mock_exec.return_value
            mock_proc.pid = 5555
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"sha123\n", b""))

            await manager._git(
                ["worktree", "add", "-b", "branch", str(expected_worktree), "main"],
                job_id=job_id,
                project_id="mini-me",
                operation_type="worktree_add",
                managed_worktree_path=expected_worktree,
            )

    assert saved_worktree_path == str(expected_worktree)


def test_pid_none_crash_window_remains_fail_closed_on_restart(in_memory_uow, tmp_path):
    """C13. pid=None crash-window state remains strictly fail-closed during restart."""
    job_id = "job-crash-window"
    worktree_dir = (tmp_path / ".minime" / "worktrees" / job_id).resolve()
    worktree_git_dir = worktree_dir / ".git"
    worktree_git_dir.mkdir(parents=True, exist_ok=True)
    lock_file = worktree_git_dir / "index.lock"
    lock_file.write_text("7777\n", encoding="utf-8")

    git_op = GitOperation(
        operation_id="op-crash-window",
        job_id=job_id,
        project_id="mini-me",
        worktree_path=str(worktree_dir),
        operation_type="worktree_add",
        pid=None,  # Crash occurred before PID could be saved
        status=GitOperationStatus.RUNNING,
    )
    in_memory_uow.git_operations.save(git_op)

    job = Job(
        job_id=job_id,
        project_id="mini-me",
        change_name="005-crash-window",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    service = RestartRecoveryService(in_memory_uow, project_root=tmp_path)
    reconciled = service.reconcile_on_startup()

    assert len(reconciled) == 1
    assert reconciled[0].status == JobStatus.RECOVERY_BLOCKED
    assert lock_file.exists()
