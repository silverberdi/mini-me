"""Scheduler capacity lifecycle service managing RUN, DRAIN, and WAIT modes."""

from __future__ import annotations

import logging
from datetime import timedelta

from minime.domain.enums import (
    EventType,
    JobStatus,
    OrchestrationStage,
    ProviderHealthStatus,
    ProviderResultClass,
    SchedulerMode,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import Event, Job, SchedulerStatus, utc_now
from minime.services.provider_health_service import ProviderHealthService

logger = logging.getLogger(__name__)


class CapacityLifecycleService:
    """Manages scheduler RUN / DRAIN / WAIT lifecycle and READY change admission gating."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        health_service: ProviderHealthService | None = None,
    ):
        self.uow = uow
        self.health_service = health_service or ProviderHealthService(uow)
        self._last_mode: SchedulerMode | None = None

    def get_scheduler_status_pure(self, project_id: str | None = None) -> SchedulerStatus:
        """Pure query: Evaluate current scheduler mode without side effects or event emission."""
        active_jobs = self.uow.jobs.list_active_jobs()
        if project_id:
            active_jobs = [j for j in active_jobs if j.project_id == project_id]

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

        if project_id:
            project = self.uow.projects.get_by_id(project_id)
            if project:
                pair_avail, reason = self.health_service.is_pair_available(
                    project.implementer, project.reviewer
                )
            else:
                pair_avail, reason = False, f"Project '{project_id}' not found"
        else:
            all_health = self.health_service.list_existing_health()
            unavailable = [h for h in all_health if h.status != ProviderHealthStatus.AVAILABLE]
            if unavailable:
                pair_avail = False
                reasons = [f"{h.provider} is {h.status.value}" for h in unavailable]
                reason = "; ".join(reasons)
            else:
                pair_avail = True
                reason = None

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
                mode_reason = (
                    f"Primary capacity unavailable ({reason}); waiting for capacity recovery."
                )

        return SchedulerStatus(
            mode=mode,
            admission_allowed=admission_allowed,
            active_jobs_count=len(active_jobs),
            primary_capacity_available=pair_avail,
            reason=mode_reason,
            updated_at=utc_now(),
        )

    def evaluate_and_record_scheduler_mode_change(
        self, project_id: str | None = None
    ) -> SchedulerStatus:
        """Command: Evaluate scheduler mode, recording SCHEDULER_MODE_CHANGED event if changed."""
        status = self.get_scheduler_status_pure(project_id=project_id)
        mode = status.mode
        active_jobs = self.uow.jobs.list_active_jobs()
        if project_id:
            active_jobs = [j for j in active_jobs if j.project_id == project_id]
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

        if self._last_mode is not None and self._last_mode != mode:
            self.uow.events.save(
                Event(
                    event_type=EventType.SCHEDULER_MODE_CHANGED,
                    payload={
                        "previous_mode": self._last_mode.value,
                        "new_mode": mode.value,
                        "reason": status.reason,
                        "active_jobs_count": len(active_jobs),
                        "in_flight_jobs_count": len(in_flight_jobs),
                    },
                    timestamp=utc_now(),
                )
            )
            self.uow.commit()

        self._last_mode = mode
        return status

    def get_scheduler_status(self, project_id: str | None = None) -> SchedulerStatus:
        """Evaluate current scheduler mode purely without side effects."""
        return self.get_scheduler_status_pure(project_id=project_id)

    def can_admit_change(self, project_id: str) -> tuple[bool, str | None]:
        """Verify whether a new READY change can be admitted for execution."""
        status = self.get_scheduler_status_pure(project_id=project_id)
        if not status.admission_allowed:
            return (
                False,
                f"Scheduler is in {status.mode.value} mode: admission of new READY work is blocked ({status.reason}).",
            )
        return True, None

    def can_execute_inflight_apply(
        self, project_id: str, run_id: str, primary_provider: str
    ) -> bool:
        """Allow an existing Apply to use a healthy primary despite its peer's outage."""
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if (
            run is None
            or run.project_id != project_id
            or not run.is_active
            or run.current_stage != OrchestrationStage.IMPLEMENTING
        ):
            return False
        health = self.health_service.get_existing_health(primary_provider)
        if (
            health is None
            or health.status != ProviderHealthStatus.AVAILABLE
            or health.last_result_class != ProviderResultClass.SUCCESS
            or health.last_success_at is None
        ):
            return False
        now = utc_now()
        last_success = health.last_success_at
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=now.tzinfo)
        age = now - last_success
        return timedelta(seconds=-5) <= age <= timedelta(seconds=60)

    def fallback_provider_for_inflight_apply(
        self, project_id: str, run_id: str, primary_provider: str
    ) -> str | None:
        """Return the configured rescue provider only for a verified dual-primary outage."""
        run = self.uow.orchestration_runs.get_by_id(run_id)
        project = self.uow.projects.get_by_id(project_id)
        if (
            run is None
            or project is None
            or run.project_id != project_id
            or not run.is_active
            or run.current_stage != OrchestrationStage.IMPLEMENTING
        ):
            return None

        primary_providers = {project.implementer, project.reviewer}
        if len(primary_providers) < 2:
            return None
        if primary_provider == "agy":
            primary_provider = "antigravity"
        if primary_provider not in primary_providers:
            return None
        now = utc_now()
        for provider in primary_providers:
            health = self.health_service.get_existing_health(provider)
            if health is None or health.status not in {
                ProviderHealthStatus.EXHAUSTED,
                ProviderHealthStatus.TEMPORARILY_UNAVAILABLE,
            }:
                return None
            if health.last_result_class not in {
                ProviderResultClass.QUOTA_LIMIT,
                ProviderResultClass.RATE_LIMIT,
            }:
                return None
            failed_at = health.last_failure_at
            if failed_at is None:
                return None
            if failed_at.tzinfo is None:
                failed_at = failed_at.replace(tzinfo=now.tzinfo)
            age = now - failed_at
            if age > timedelta(minutes=5) or age < timedelta(seconds=-5):
                return None

        profile = project.agent_profiles.get("fallback")
        if hasattr(profile, "model_dump"):
            profile = profile.model_dump()
        if not isinstance(profile, dict):
            return None
        provider = str(
            profile.get("harness_id") or profile.get("agent_id") or profile.get("provider_id") or ""
        ).strip().lower()
        if provider in {"agy", "antigravity"}:
            provider = "antigravity"
        if not provider or provider in primary_providers:
            return None
        return provider
