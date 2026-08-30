"""Regression coverage for fail-closed recovery transitions."""

import pytest

from minime.db.repository import PostgresJobRepository
from minime.domain.enums import JobStatus
from minime.domain.models import Job


@pytest.mark.parametrize("status", list(JobStatus))
def test_in_memory_jobs_can_record_recovery_blocked_from_any_cleanup_state(in_memory_uow, status):
    job = Job(
        job_id=f"recovery-{status.value.lower()}",
        project_id="mini-me",
        change_name="synthetic",
        implementer_role="codex",
        status=status,
    )
    in_memory_uow.jobs.save(job)

    updated = in_memory_uow.jobs.transition(
        job.job_id, JobStatus.RECOVERY_BLOCKED.value, "preservation failed"
    )

    assert updated.status == JobStatus.RECOVERY_BLOCKED


def test_postgres_job_transition_map_allows_recovery_blocked_from_every_status():
    for status in JobStatus:
        assert JobStatus.RECOVERY_BLOCKED in PostgresJobRepository.VALID_TRANSITIONS[status]
