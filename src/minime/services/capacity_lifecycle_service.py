"""Scheduler capacity lifecycle service managing RUN, DRAIN, and WAIT modes."""

from __future__ import annotations

import logging

from minime.domain.enums import (
    EventType,
    JobStatus,
    ProviderHealthStatus,
    SchedulerMode,
)
from minime.domain.interfaces import FallbackPolicyInterface, PersistenceUnitOfWork
from minime.domain.models import Event, Job, SchedulerStatus, utc_now
from minime.services.provider_health_service import ProviderHealthService

logger = logging.getLogger(__name__)


class DefaultFallbackPolicy(FallbackPolicyInterface):
    """Default fallback policy seam for 005 (returns False until 006 OpenRouter fallback)."""

    def is_fallback_eligible(self, project_id: str, job: Job, role: str) -> bool:
        del project_id, job, role
        return False


class CapacityLifecycleService:
    """Manages scheduler RUN / DRAIN / WAIT lifecycle and READY change admission gating."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        health_service: ProviderHealthService | None = None,
        fallback_policy: FallbackPolicyInterface | None = None,
    ):
        self.uow = uow
        self.health_service = health_service or ProviderHealthService(uow)
        self.fallback_policy = fallback_policy or DefaultFallbackPolicy()
        self._last_mode: SchedulerMode | None = None

    def get_scheduler_status(self, project_id: str | None = None) -> SchedulerStatus:
        """Evaluate current scheduler mode across primary providers and active jobs."""
        active_jobs = self.uow.jobs.list_active_jobs()
        if project_id:
            active_jobs = [j for j in active_jobs if j.project_id == project_id]

        # In-flight jobs currently progressing through stages (not paused at waiting/blocked)
        in_flight_jobs = [
            j
            for j in active_jobs
            if j.status
            in {
                JobStatus.RUNNING,
                JobStatus.CHECKS_RUNNING,
                JobStatus.CHECKS_PASSED,
                JobStatus.REVIEW_RUNNING,
                JobStatus.AUDIT_RUNNING,
            }
        ]

        # Determine primary capacity availability
        if project_id:
            project = self.uow.projects.get_by_id(project_id)
            if project:
                pair_avail, reason = self.health_service.is_pair_available(
                    project.implementer, project.reviewer
                )
            else:
                pair_avail, reason = False, f"Project '{project_id}' not found"
        else:
            # Check all primary health
            all_health = self.health_service.list_all_health()
            unavailable = [h for h in all_health if h.status != ProviderHealthStatus.AVAILABLE]
            if unavailable:
                pair_avail = False
                reasons = [f"{h.provider} is {h.status.value}" for h in unavailable]
                reason = "; ".join(reasons)
            else:
                pair_avail = True
                reason = None

        # Mode determination:
        # RUN: complete primary pair(s) are available -> admission allowed
        # DRAIN: primary shortage, but in-flight jobs can make progress -> no new admission
        # WAIT: primary shortage, and NO in-flight job can make safe progress -> wait for probe/reset
        if pair_avail:
            mode = SchedulerMode.RUN
            admission_allowed = True
            mode_reason = "All primary providers are available."
        else:
            admission_allowed = False
            if in_flight_jobs:
                mode = SchedulerMode.DRAIN
                mode_reason = f"Primary capacity unavailable ({reason}); draining in-flight work."
            else:
                mode = SchedulerMode.WAIT
                mode_reason = f"Primary capacity unavailable ({reason}); waiting for capacity recovery."

        # Emit mode change event if changed
        if self._last_mode is not None and self._last_mode != mode:
            self.uow.events.save(
                Event(
                    event_type=EventType.SCHEDULER_MODE_CHANGED,
                    payload={
                        "previous_mode": self._last_mode.value,
                        "new_mode": mode.value,
                        "reason": mode_reason,
                        "active_jobs_count": len(active_jobs),
                        "in_flight_jobs_count": len(in_flight_jobs),
                    },
                    timestamp=utc_now(),
                )
            )
            self.uow.commit()

        self._last_mode = mode

        return SchedulerStatus(
            mode=mode,
            admission_allowed=admission_allowed,
            active_jobs_count=len(active_jobs),
            primary_capacity_available=pair_avail,
            reason=mode_reason,
            updated_at=utc_now(),
        )

    def can_admit_change(self, project_id: str) -> tuple[bool, str | None]:
        """Verify whether a new READY change can be admitted for execution."""
        status = self.get_scheduler_status(project_id=project_id)
        if not status.admission_allowed:
            return (
                False,
                f"Scheduler is in {status.mode.value} mode: admission of new READY work is blocked ({status.reason}).",
            )
        return True, None
