"""Unit tests for CapacityLifecycleService and scheduler RUN/DRAIN/WAIT modes."""

from minime.domain.enums import (
    AuditStatus,
    JobStatus,
    ProviderHealthStatus,
    ProviderResultClass,
    SchedulerMode,
)
from minime.domain.models import AuditRecord, Job, NormalizedProviderResult, Project
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.provider_health_service import ProviderHealthService


def test_scheduler_mode_run_when_all_primaries_available(in_memory_uow):
    """Verify scheduler is in RUN mode and allows admission when primaries are available."""
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    lifecycle = CapacityLifecycleService(in_memory_uow)
    status = lifecycle.get_scheduler_status(project_id="mini-me")

    assert status.mode == SchedulerMode.RUN
    assert status.admission_allowed is True
    assert status.primary_capacity_available is True

    can_admit, reason = lifecycle.can_admit_change("mini-me")
    assert can_admit is True
    assert reason is None


def test_scheduler_mode_drain_when_primary_exhausted_and_inflight_jobs_exist(in_memory_uow):
    """Verify scheduler enters DRAIN when primary capacity is exhausted and in-flight work exists."""
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    # In-flight job running checks
    job = Job(
        job_id="job-drain-1",
        project_id="mini-me",
        change_name="005-change",
        status=JobStatus.CHECKS_RUNNING,
        implementer_role="codex",
    )
    in_memory_uow.jobs.save(job)

    # Codex becomes exhausted
    health_service = ProviderHealthService(in_memory_uow)
    health_service.record_outcome(
        NormalizedProviderResult(
            result_class=ProviderResultClass.QUOTA_LIMIT,
            provider="codex",
            role="implementer",
            summary="Monthly quota exceeded",
        )
    )

    lifecycle = CapacityLifecycleService(in_memory_uow, health_service=health_service)
    status = lifecycle.get_scheduler_status(project_id="mini-me")

    assert status.mode == SchedulerMode.DRAIN
    assert status.admission_allowed is False
    assert status.primary_capacity_available is False
    assert status.active_jobs_count == 1

    can_admit, reason = lifecycle.can_admit_change("mini-me")
    assert can_admit is False
    assert "DRAIN" in reason


def test_scheduler_mode_wait_when_primary_exhausted_and_no_inflight_jobs(in_memory_uow):
    """Verify scheduler enters WAIT when primary capacity is exhausted and all jobs are waiting or empty."""
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    # Job is paused at WAITING_CAPACITY
    job = Job(
        job_id="job-wait-1",
        project_id="mini-me",
        change_name="005-change",
        status=JobStatus.WAITING_CAPACITY,
        implementer_role="codex",
        waiting_provider="codex",
    )
    in_memory_uow.jobs.save(job)

    # Codex is exhausted
    health_service = ProviderHealthService(in_memory_uow)
    health_service.record_outcome(
        NormalizedProviderResult(
            result_class=ProviderResultClass.QUOTA_LIMIT,
            provider="codex",
            role="implementer",
            summary="Monthly quota exceeded",
        )
    )

    lifecycle = CapacityLifecycleService(in_memory_uow, health_service=health_service)
    status = lifecycle.get_scheduler_status(project_id="mini-me")

    assert status.mode == SchedulerMode.WAIT
    assert status.admission_allowed is False
    assert status.primary_capacity_available is False

    can_admit, reason = lifecycle.can_admit_change("mini-me")
    assert can_admit is False
    assert "WAIT" in reason


def test_deepseek_audit_failure_never_affects_scheduler_mode(in_memory_uow):
    """Verify that DeepSeek Direct audit failures are isolated to 004 lifecycle and do not alter scheduler RUN mode."""
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    # Both Codex and Antigravity are available
    health_service = ProviderHealthService(in_memory_uow)
    assert health_service.get_health("codex").status == ProviderHealthStatus.AVAILABLE
    assert health_service.get_health("antigravity").status == ProviderHealthStatus.AVAILABLE

    # DeepSeek audit record fails or is blocked
    audit = AuditRecord(
        audit_id="aud-001",
        job_id="job-001",
        project_id="mini-me",
        change_name="005-change",
        candidate_sha="abc1234",
        base_sha="def5678",
        status=AuditStatus.AUDIT_FAILED,
        error_message="DeepSeek API timed out",
    )
    in_memory_uow.audits.save(audit)

    lifecycle = CapacityLifecycleService(in_memory_uow, health_service=health_service)
    status = lifecycle.get_scheduler_status(project_id="mini-me")

    # Scheduler remains in RUN mode
    assert status.mode == SchedulerMode.RUN
    assert status.admission_allowed is True
    assert status.primary_capacity_available is True
