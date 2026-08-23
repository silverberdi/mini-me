"""Unit tests for provider resilience persistence models, repositories, and primary boundaries."""

from datetime import UTC, datetime, timedelta

import pytest

from minime.domain.enums import (
    CapacitySignalSource,
    JobStatus,
    ProviderHealthStatus,
    ProviderResultClass,
)
from minime.domain.models import CapacityWindow, Job, ProviderHealth, utc_now


def test_provider_health_primary_validation():
    """Verify that ProviderHealth only accepts primary providers (codex, antigravity)."""
    valid_codex = ProviderHealth(
        provider="codex",
        status=ProviderHealthStatus.AVAILABLE,
    )
    valid_codex.validate_primary()

    valid_antigravity = ProviderHealth(
        provider="antigravity",
        status=ProviderHealthStatus.AVAILABLE,
    )
    valid_antigravity.validate_primary()

    invalid_deepseek = ProviderHealth(
        provider="deepseek",
        status=ProviderHealthStatus.AVAILABLE,
    )
    with pytest.raises(ValueError, match="Invalid primary provider 'deepseek'"):
        invalid_deepseek.validate_primary()

    invalid_openrouter = ProviderHealth(
        provider="openrouter",
        status=ProviderHealthStatus.AVAILABLE,
    )
    with pytest.raises(ValueError, match="Invalid primary provider 'openrouter'"):
        invalid_openrouter.validate_primary()


def test_capacity_window_primary_validation():
    """Verify that CapacityWindow only accepts primary providers."""
    valid_window = CapacityWindow(
        provider="codex",
        source_signal=CapacitySignalSource.HEADER_RETRY_AFTER,
    )
    valid_window.validate_primary()

    invalid_window = CapacityWindow(
        provider="deepseek",
        source_signal=CapacitySignalSource.UNKNOWN,
    )
    with pytest.raises(ValueError, match="Invalid primary provider 'deepseek'"):
        invalid_window.validate_primary()


def test_provider_health_repository_operations(in_memory_uow):
    """Test saving, retrieving, and updating provider health records."""
    # 1. Update health for codex
    health = in_memory_uow.provider_health.update_health(
        provider="codex",
        status="temporarily_unavailable",
        result_class="transient_error",
        error_summary="Connection reset by peer",
    )
    assert health.provider == "codex"
    assert health.status == ProviderHealthStatus.TEMPORARILY_UNAVAILABLE
    assert health.consecutive_failures == 1
    assert health.last_result_class == ProviderResultClass.TRANSIENT_ERROR
    assert health.last_error_summary == "Connection reset by peer"

    # 2. Retrieve
    retrieved = in_memory_uow.provider_health.get_by_provider("codex")
    assert retrieved is not None
    assert retrieved.status == ProviderHealthStatus.TEMPORARILY_UNAVAILABLE

    # 3. Update to available resets consecutive failures
    updated = in_memory_uow.provider_health.update_health(
        provider="codex",
        status="available",
        result_class="success",
    )
    assert updated.status == ProviderHealthStatus.AVAILABLE
    assert updated.consecutive_failures == 0
    assert updated.last_success_at is not None

    # 4. Reject non-primary provider query
    with pytest.raises(ValueError, match="Invalid primary provider 'deepseek'"):
        in_memory_uow.provider_health.get_by_provider("deepseek")


def test_capacity_window_repository_operations(in_memory_uow):
    """Test saving and querying capacity windows."""
    now = utc_now()
    reset_time = now + timedelta(hours=1)

    window1 = CapacityWindow(
        provider="antigravity",
        quota_exhausted_at=now,
        capacity_reset_at=reset_time,
        retry_after_seconds=3600,
        source_signal=CapacitySignalSource.RESPONSE_BODY_TIMESTAMP,
    )
    in_memory_uow.capacity_windows.save(window1)

    latest = in_memory_uow.capacity_windows.get_latest_for_provider("antigravity")
    assert latest is not None
    assert latest.provider == "antigravity"
    assert latest.retry_after_seconds == 3600
    assert latest.capacity_reset_at == reset_time

    # Reject non-primary query
    with pytest.raises(ValueError, match="Invalid primary provider 'deepseek'"):
        in_memory_uow.capacity_windows.get_latest_for_provider("deepseek")


def test_job_waiting_capacity_and_recovery_blocked_transitions(in_memory_uow):
    """Verify job transitions into WAITING_CAPACITY and RECOVERY_BLOCKED."""
    job = Job(
        job_id="job-100",
        project_id="mini-me",
        change_name="005-resilience",
        status=JobStatus.RUNNING,
        implementer_role="codex",
    )
    in_memory_uow.jobs.save(job)

    # Transition to WAITING_CAPACITY
    reset_at = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
    waiting_job = in_memory_uow.jobs.set_waiting_capacity(
        job_id="job-100",
        waiting_provider="codex",
        reason="Quota exhausted on primary implementer",
        expected_reset_at=reset_at,
    )
    assert waiting_job.status == JobStatus.WAITING_CAPACITY
    assert waiting_job.waiting_provider == "codex"
    assert waiting_job.capacity_block_reason == "Quota exhausted on primary implementer"
    assert waiting_job.expected_reset_at == reset_at

    # Check list_active_jobs includes WAITING_CAPACITY
    active_jobs = in_memory_uow.jobs.list_active_jobs()
    assert len(active_jobs) == 1
    assert active_jobs[0].job_id == "job-100"

    # Transition from WAITING_CAPACITY to RECOVERY_BLOCKED
    blocked_job = in_memory_uow.jobs.set_recovery_blocked(
        job_id="job-100",
        reason="Ambiguous lock on worktree",
    )
    assert blocked_job.status == JobStatus.RECOVERY_BLOCKED
    assert blocked_job.recovery_blocked_reason == "Ambiguous lock on worktree"

    # Transition back to RUNNING upon unblocking
    resumed_job = in_memory_uow.jobs.transition("job-100", JobStatus.RUNNING.value)
    assert resumed_job.status == JobStatus.RUNNING


def test_git_operation_repository_operations(in_memory_uow):
    """Test saving, retrieving, querying, and updating GitOperation records."""
    from minime.domain.enums import GitOperationStatus
    from minime.domain.models import GitOperation

    op1 = GitOperation(
        operation_id="op-101",
        job_id="job-100",
        project_id="mini-me",
        worktree_path="/path/to/worktree/job-100",
        operation_type="worktree_add",
        pid=12345,
        status=GitOperationStatus.RUNNING,
    )
    in_memory_uow.git_operations.save(op1)

    # Retrieve by ID
    retrieved = in_memory_uow.git_operations.get_by_id("op-101")
    assert retrieved is not None
    assert retrieved.job_id == "job-100"
    assert retrieved.operation_type == "worktree_add"
    assert retrieved.pid == 12345
    assert retrieved.status == GitOperationStatus.RUNNING

    # Query by job and worktree
    job_ops = in_memory_uow.git_operations.list_by_job("job-100")
    assert len(job_ops) == 1
    assert job_ops[0].operation_id == "op-101"

    wt_ops = in_memory_uow.git_operations.list_by_worktree("/path/to/worktree/job-100")
    assert len(wt_ops) == 1

    # Update status
    updated = in_memory_uow.git_operations.update_status(
        "op-101",
        GitOperationStatus.COMPLETED,
        completed_at=utc_now(),
    )
    assert updated is not None
    assert updated.status == GitOperationStatus.COMPLETED
    assert updated.completed_at is not None
