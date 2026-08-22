"""Test fixtures and mock repositories for mini me tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from minime.domain.enums import (
    PRIMARY_PROVIDERS,
    AuditRiskLevel,
    AuditStatus,
    GitOperationStatus,
    JobStatus,
    ProviderHealthStatus,
    ProviderResultClass,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.interfaces import (
    AuditFindingRepositoryInterface,
    AuditRepositoryInterface,
    CapacityWindowRepositoryInterface,
    ChangeRepositoryInterface,
    CheckResultRepositoryInterface,
    EventRepositoryInterface,
    GitOperationRepositoryInterface,
    JobLogRepositoryInterface,
    JobRepositoryInterface,
    MetricFactRepositoryInterface,
    PersistenceUnitOfWork,
    ProjectBindingRepositoryInterface,
    ProjectRepositoryInterface,
    ProviderHealthRepositoryInterface,
    ReviewFindingRepositoryInterface,
    ReviewRepositoryInterface,
)
from minime.domain.models import (
    AUTHORITATIVE_PRICING_SOURCES,
    AuditFinding,
    AuditRecord,
    BudgetLedgerEntry,
    BudgetReservation,
    CapacityWindow,
    Change,
    CheckResult,
    Event,
    GitOperation,
    Job,
    JobLog,
    MetricFact,
    OpenRouterBudgetPolicy,
    OpenRouterPricingSnapshot,
    Project,
    ProjectBinding,
    ProviderHealth,
    Review,
    ReviewFinding,
    utc_now,
)


class InMemoryProjectRepository(ProjectRepositoryInterface):
    def __init__(self):
        self._store: dict[str, Project] = {}

    def save(self, project: Project) -> None:
        self._store[project.project_id] = project.model_copy(deep=True)

    def get_by_id(self, project_id: str) -> Project | None:
        p = self._store.get(project_id)
        return p.model_copy(deep=True) if p else None

    def list_all(self) -> list[Project]:
        return [p.model_copy(deep=True) for p in self._store.values()]


class InMemoryChangeRepository(ChangeRepositoryInterface):
    def __init__(self):
        self._store: dict[str, Change] = {}

    def save(self, change: Change) -> None:
        self._store[change.change_id] = change.model_copy(deep=True)

    def get_by_id(self, change_id: str) -> Change | None:
        c = self._store.get(change_id)
        return c.model_copy(deep=True) if c else None

    def get_by_name(self, project_id: str, name: str) -> Change | None:
        for c in self._store.values():
            if c.project_id == project_id and c.name == name:
                return c.model_copy(deep=True)
        return None

    def list_by_project(self, project_id: str) -> list[Change]:
        return [c.model_copy(deep=True) for c in self._store.values() if c.project_id == project_id]


class InMemoryProjectBindingRepository(ProjectBindingRepositoryInterface):
    def __init__(self):
        self._store: dict[str, ProjectBinding] = {}

    def save(self, binding: ProjectBinding) -> None:
        for existing in self._store.values():
            if (
                existing.project_id == binding.project_id
                and existing.openspec_change_name == binding.openspec_change_name
                and existing.binding_id != binding.binding_id
            ):
                raise ValueError(
                    f"Unique constraint violation: binding already exists for project '{binding.project_id}' "
                    f"and change '{binding.openspec_change_name}'."
                )
        self._store[binding.binding_id] = binding.model_copy(deep=True)

    def get_by_id(self, binding_id: str) -> ProjectBinding | None:
        b = self._store.get(binding_id)
        return b.model_copy(deep=True) if b else None

    def get_by_project_and_change(self, project_id: str, change_name: str) -> ProjectBinding | None:
        matches = [
            b
            for b in self._store.values()
            if b.project_id == project_id and b.openspec_change_name == change_name
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous bindings: {len(matches)} bindings found for project '{project_id}' "
                f"and change '{change_name}'."
            )
        return matches[0].model_copy(deep=True) if matches else None


class InMemoryEventRepository(EventRepositoryInterface):
    def __init__(self):
        self._store: list[Event] = []

    def save(self, event: Event) -> None:
        self._store.append(event.model_copy(deep=True))

    def list_events(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        res = self._store
        if project_id:
            res = [e for e in res if e.project_id == project_id]
        if change_id:
            res = [e for e in res if e.change_id == change_id]
        return [e.model_copy(deep=True) for e in reversed(res[-limit:])]


class InMemoryMetricFactRepository(MetricFactRepositoryInterface):
    def __init__(self):
        self._store: list[MetricFact] = []

    def save(self, fact: MetricFact) -> None:
        self._store.append(fact.model_copy(deep=True))

    def list_facts(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        metric_name: str | None = None,
        limit: int = 100,
    ) -> list[MetricFact]:
        res = self._store
        if project_id:
            res = [f for f in res if f.project_id == project_id]
        if change_id:
            res = [f for f in res if f.change_id == change_id]
        if metric_name:
            res = [f for f in res if f.metric_name == metric_name]
        return [f.model_copy(deep=True) for f in reversed(res[-limit:])]


class InMemoryJobRepository(JobRepositoryInterface):
    _valid_transitions: dict[JobStatus, set[JobStatus]] = {
        JobStatus.QUEUED: {
            JobStatus.RUNNING,
            JobStatus.WAITING_CAPACITY,
            JobStatus.CANCELLED,
            JobStatus.FAILED,
        },
        JobStatus.RUNNING: {
            JobStatus.CHECKS_RUNNING,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_RUNNING: {
            JobStatus.CHECKS_PASSED,
            JobStatus.CHECKS_FAILED,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_PASSED: {
            JobStatus.REVIEW_RUNNING,
            JobStatus.WAITING_CAPACITY,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_FAILED: set(),
        JobStatus.REVIEW_RUNNING: {
            JobStatus.AUDIT_RUNNING,
            JobStatus.CHANGES_REQUIRED,
            JobStatus.CHECKS_PASSED,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.AUDIT_RUNNING: {
            JobStatus.READY_TO_MERGE,
            JobStatus.AUDIT_BLOCKED,
            JobStatus.CHECKS_PASSED,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.WAITING_CAPACITY: {
            JobStatus.RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.REVIEW_RUNNING,
            JobStatus.AUDIT_RUNNING,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.RECOVERY_BLOCKED: {
            JobStatus.WAITING_CAPACITY,
            JobStatus.RUNNING,
            JobStatus.REVIEW_RUNNING,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.READY_TO_MERGE: set(),
        JobStatus.AUDIT_BLOCKED: set(),
        JobStatus.CHANGES_REQUIRED: set(),
        JobStatus.FAILED: set(),
        JobStatus.CANCELLED: set(),
    }

    def __init__(self):
        self._store: dict[str, Job] = {}

    def save(self, job: Job) -> None:
        self._store[job.job_id] = job.model_copy(deep=True)

    def get_by_id(self, job_id: str) -> Job | None:
        job = self._store.get(job_id)
        return job.model_copy(deep=True) if job else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[Job]:
        jobs = [j for j in self._store.values() if j.project_id == project_id]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [j.model_copy(deep=True) for j in jobs[:limit]]

    def list_active_jobs(self) -> list[Job]:
        active_statuses = {
            JobStatus.QUEUED,
            JobStatus.RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.CHECKS_PASSED,
            JobStatus.REVIEW_RUNNING,
            JobStatus.AUDIT_RUNNING,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
        }
        jobs = [j for j in self._store.values() if j.status in active_statuses]
        jobs.sort(key=lambda j: j.created_at)
        return [j.model_copy(deep=True) for j in jobs]

    def transition(self, job_id: str, new_status: str, error_message: str | None = None) -> Job:
        job = self._store.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found.")
        target = JobStatus(new_status)
        if target not in self._valid_transitions[job.status]:
            raise ValueError(f"Invalid job status transition: {job.status.value} -> {target.value}.")
        updated = job.model_copy(update={"status": target, "error_message": error_message})
        self._store[job_id] = updated
        return updated.model_copy(deep=True)

    def set_waiting_capacity(
        self,
        job_id: str,
        waiting_provider: str,
        reason: str,
        expected_reset_at: datetime | None = None,
    ) -> Job:
        job = self._store.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found.")
        target = JobStatus.WAITING_CAPACITY
        if target not in self._valid_transitions[job.status]:
            raise ValueError(f"Invalid job status transition: {job.status.value} -> {target.value}.")
        updated = job.model_copy(
            update={
                "status": target,
                "waiting_provider": waiting_provider,
                "capacity_block_reason": reason,
                "expected_reset_at": expected_reset_at,
            }
        )
        self._store[job_id] = updated
        return updated.model_copy(deep=True)

    def set_recovery_blocked(self, job_id: str, reason: str) -> Job:
        job = self._store.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found.")
        target = JobStatus.RECOVERY_BLOCKED
        if target not in self._valid_transitions[job.status]:
            raise ValueError(f"Invalid job status transition: {job.status.value} -> {target.value}.")
        updated = job.model_copy(
            update={
                "status": target,
                "recovery_blocked_reason": reason,
            }
        )
        self._store[job_id] = updated
        return updated.model_copy(deep=True)


class InMemoryJobLogRepository(JobLogRepositoryInterface):
    def __init__(self):
        self._store: list[JobLog] = []

    def save(self, log: JobLog) -> None:
        self._store.append(log.model_copy(deep=True))

    def list_by_job(self, job_id: str, limit: int = 500) -> list[JobLog]:
        logs = [log for log in self._store if log.job_id == job_id]
        return [log.model_copy(deep=True) for log in logs[:limit]]


class InMemoryCheckResultRepository(CheckResultRepositoryInterface):
    def __init__(self):
        self._store: list[CheckResult] = []

    def save(self, result: CheckResult) -> None:
        self._store.append(result.model_copy(deep=True))

    def list_by_job(self, job_id: str) -> list[CheckResult]:
        return [r.model_copy(deep=True) for r in self._store if r.job_id == job_id]


class InMemoryReviewRepository(ReviewRepositoryInterface):
    _valid_transitions: dict[ReviewStatus, set[ReviewStatus]] = {
        ReviewStatus.REVIEW_PENDING: {
            ReviewStatus.REVIEW_RUNNING,
            ReviewStatus.REVIEW_FAILED,
            ReviewStatus.REVIEW_TIMED_OUT,
        },
        ReviewStatus.REVIEW_RUNNING: {
            ReviewStatus.REVIEW_COMPLETED,
            ReviewStatus.REVIEW_FAILED,
            ReviewStatus.REVIEW_TIMED_OUT,
        },
        ReviewStatus.REVIEW_COMPLETED: set(),
        ReviewStatus.REVIEW_FAILED: set(),
        ReviewStatus.REVIEW_TIMED_OUT: set(),
    }

    def __init__(self):
        self._store: dict[str, Review] = {}

    def save(self, review: Review) -> None:
        self._store[review.review_id] = review.model_copy(deep=True)

    def get_by_id(self, review_id: str) -> Review | None:
        rev = self._store.get(review_id)
        return rev.model_copy(deep=True) if rev else None

    def get_by_job_id(self, job_id: str) -> Review | None:
        reviews = [r for r in self._store.values() if r.job_id == job_id]
        reviews.sort(key=lambda r: r.created_at, reverse=True)
        return reviews[0].model_copy(deep=True) if reviews else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[Review]:
        reviews = [r for r in self._store.values() if r.project_id == project_id]
        reviews.sort(key=lambda r: r.created_at, reverse=True)
        return [r.model_copy(deep=True) for r in reviews[:limit]]

    def transition(
        self,
        review_id: str,
        new_status: str,
        verdict: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> Review:
        rev = self._store.get(review_id)
        if not rev:
            raise ValueError(f"Review '{review_id}' not found.")
        target = ReviewStatus(new_status)
        if target not in self._valid_transitions[rev.status]:
            raise ValueError(
                f"Invalid review status transition: {rev.status.value} -> {target.value}."
            )
        update_dict: dict[str, object] = {"status": target}
        if verdict:
            update_dict["verdict"] = ReviewVerdict(verdict)
        if summary is not None:
            update_dict["summary"] = summary
        if error_message is not None:
            update_dict["error_message"] = error_message
        updated = rev.model_copy(update=update_dict)
        self._store[review_id] = updated
        return updated.model_copy(deep=True)


class InMemoryReviewFindingRepository(ReviewFindingRepositoryInterface):
    def __init__(self):
        self._store: list[ReviewFinding] = []

    def save(self, finding: ReviewFinding) -> None:
        self._store.append(finding.model_copy(deep=True))

    def list_by_review(self, review_id: str) -> list[ReviewFinding]:
        return [f.model_copy(deep=True) for f in self._store if f.review_id == review_id]


class InMemoryAuditRepository(AuditRepositoryInterface):
    _valid_transitions: dict[AuditStatus, set[AuditStatus]] = {
        AuditStatus.AUDIT_PENDING: {
            AuditStatus.AUDIT_RUNNING,
            AuditStatus.AUDIT_FAILED,
            AuditStatus.AUDIT_TIMED_OUT,
        },
        AuditStatus.AUDIT_RUNNING: {
            AuditStatus.AUDIT_COMPLETED,
            AuditStatus.AUDIT_BLOCKED,
            AuditStatus.AUDIT_FAILED,
            AuditStatus.AUDIT_TIMED_OUT,
        },
        AuditStatus.AUDIT_COMPLETED: set(),
        AuditStatus.AUDIT_BLOCKED: set(),
        AuditStatus.AUDIT_FAILED: set(),
        AuditStatus.AUDIT_TIMED_OUT: set(),
    }

    def __init__(self):
        self._store: dict[str, AuditRecord] = {}

    def save(self, audit: AuditRecord) -> None:
        self._store[audit.audit_id] = audit.model_copy(deep=True)

    def get_by_id(self, audit_id: str) -> AuditRecord | None:
        audit = self._store.get(audit_id)
        return audit.model_copy(deep=True) if audit else None

    def get_by_job_id(self, job_id: str) -> AuditRecord | None:
        audits = [a for a in self._store.values() if a.job_id == job_id]
        audits.sort(key=lambda a: a.created_at, reverse=True)
        return audits[0].model_copy(deep=True) if audits else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[AuditRecord]:
        audits = [a for a in self._store.values() if a.project_id == project_id]
        audits.sort(key=lambda a: a.created_at, reverse=True)
        return [a.model_copy(deep=True) for a in audits[:limit]]

    def transition(
        self,
        audit_id: str,
        new_status: str,
        risk: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> AuditRecord:
        audit = self._store.get(audit_id)
        if not audit:
            raise ValueError(f"Audit '{audit_id}' not found.")
        target = AuditStatus(new_status)
        if target not in self._valid_transitions[audit.status]:
            raise ValueError(
                f"Invalid audit status transition: {audit.status.value} -> {target.value}."
            )
        update_dict: dict[str, object] = {"status": target}
        if risk:
            update_dict["risk"] = AuditRiskLevel(risk)
        if summary is not None:
            update_dict["summary"] = summary
        if error_message is not None:
            update_dict["error_message"] = error_message
        updated = audit.model_copy(update=update_dict)
        self._store[audit_id] = updated
        return updated.model_copy(deep=True)


class InMemoryAuditFindingRepository(AuditFindingRepositoryInterface):
    def __init__(self):
        self._store: list[AuditFinding] = []

    def save(self, finding: AuditFinding) -> None:
        self._store.append(finding.model_copy(deep=True))

    def list_by_audit(self, audit_id: str) -> list[AuditFinding]:
        return [f.model_copy(deep=True) for f in self._store if f.audit_id == audit_id]


class InMemoryProviderHealthRepository(ProviderHealthRepositoryInterface):
    def __init__(self):
        self._store: dict[str, ProviderHealth] = {}

    def _validate_primary_provider(self, provider: str) -> None:
        if provider not in PRIMARY_PROVIDERS:
            raise ValueError(
                f"Invalid primary provider '{provider}'. "
                f"005 capacity tracking is restricted strictly to {PRIMARY_PROVIDERS}."
            )

    def save(self, health: ProviderHealth) -> None:
        health.validate_primary()
        self._store[health.provider] = health.model_copy(deep=True)

    def get_by_provider(self, provider: str) -> ProviderHealth | None:
        self._validate_primary_provider(provider)
        h = self._store.get(provider)
        return h.model_copy(deep=True) if h else None

    def list_all(self) -> list[ProviderHealth]:
        return [h.model_copy(deep=True) for h in self._store.values()]

    def update_health(
        self,
        provider: str,
        status: str,
        result_class: str | None = None,
        error_summary: str | None = None,
        consecutive_failures: int | None = None,
    ) -> ProviderHealth:
        self._validate_primary_provider(provider)
        now = utc_now()
        target_status = ProviderHealthStatus(status)
        target_result_class = ProviderResultClass(result_class) if result_class else None
        h = self._store.get(provider)

        if not h:
            init_failures = (
                consecutive_failures
                if consecutive_failures is not None
                else (0 if target_status == ProviderHealthStatus.AVAILABLE else 1)
            )
            h = ProviderHealth(
                health_id=f"ph-{provider}",
                provider=provider,
                status=target_status,
                consecutive_failures=init_failures,
                last_result_class=target_result_class,
                last_error_summary=error_summary,
                last_success_at=now if target_status == ProviderHealthStatus.AVAILABLE else None,
                last_failure_at=now if target_status != ProviderHealthStatus.AVAILABLE else None,
                updated_at=now,
            )
        else:
            if consecutive_failures is not None:
                consecutive = consecutive_failures
            elif target_status == ProviderHealthStatus.AVAILABLE:
                consecutive = 0
            else:
                consecutive = h.consecutive_failures + 1

            succ_at = h.last_success_at
            fail_at = h.last_failure_at
            if target_status == ProviderHealthStatus.AVAILABLE and target_result_class == ProviderResultClass.SUCCESS:
                succ_at = now
            elif target_result_class and target_result_class != ProviderResultClass.SUCCESS:
                fail_at = now

            h = h.model_copy(
                update={
                    "status": target_status,
                    "consecutive_failures": consecutive,
                    "last_result_class": target_result_class or h.last_result_class,
                    "last_error_summary": error_summary if error_summary is not None else h.last_error_summary,
                    "last_success_at": succ_at,
                    "last_failure_at": fail_at,
                    "updated_at": now,
                }
            )
        self._store[provider] = h
        return h.model_copy(deep=True)


class InMemoryCapacityWindowRepository(CapacityWindowRepositoryInterface):
    def __init__(self):
        self._store: list[CapacityWindow] = []

    def _validate_primary_provider(self, provider: str) -> None:
        if provider not in PRIMARY_PROVIDERS:
            raise ValueError(
                f"Invalid primary provider '{provider}'. "
                f"005 capacity windows are restricted strictly to {PRIMARY_PROVIDERS}."
            )

    def save(self, window: CapacityWindow) -> None:
        window.validate_primary()
        self._store.append(window.model_copy(deep=True))

    def get_latest_for_provider(self, provider: str) -> CapacityWindow | None:
        self._validate_primary_provider(provider)
        windows = [w for w in self._store if w.provider == provider]
        windows.sort(key=lambda w: w.quota_exhausted_at, reverse=True)
        return windows[0].model_copy(deep=True) if windows else None

    def list_by_provider(self, provider: str, limit: int = 50) -> list[CapacityWindow]:
        self._validate_primary_provider(provider)
        windows = [w for w in self._store if w.provider == provider]
        windows.sort(key=lambda w: w.quota_exhausted_at, reverse=True)
        return [w.model_copy(deep=True) for w in windows[:limit]]


class InMemoryGitOperationRepository(GitOperationRepositoryInterface):
    def __init__(self):
        self._store: dict[str, GitOperation] = {}

    def save(self, operation: GitOperation) -> None:
        self._store[operation.operation_id] = operation.model_copy(deep=True)

    def get_by_id(self, operation_id: str) -> GitOperation | None:
        op = self._store.get(operation_id)
        return op.model_copy(deep=True) if op else None

    def list_by_job(self, job_id: str) -> list[GitOperation]:
        ops = [op for op in self._store.values() if op.job_id == job_id]
        ops.sort(key=lambda op: op.started_at, reverse=True)
        return [op.model_copy(deep=True) for op in ops]

    def list_by_worktree(self, worktree_path: str) -> list[GitOperation]:
        ops = [op for op in self._store.values() if op.worktree_path == worktree_path]
        ops.sort(key=lambda op: op.started_at, reverse=True)
        return [op.model_copy(deep=True) for op in ops]

    def update_status(
        self,
        operation_id: str,
        status: GitOperationStatus,
        completed_at: datetime | None = None,
    ) -> GitOperation | None:
        op = self._store.get(operation_id)
        if not op:
            return None
        updated = op.model_copy(update={"status": status, "completed_at": completed_at})
        self._store[operation_id] = updated
        return updated.model_copy(deep=True)


class InMemoryOpenRouterBudgetPolicyRepository:
    def __init__(self):
        self._store: dict[str, OpenRouterBudgetPolicy] = {}

    def get_for_update(self, project_id: str) -> OpenRouterBudgetPolicy | None:
        policy = self._store.get(project_id)
        return policy.model_copy(deep=True) if policy else None

    def save(self, policy: OpenRouterBudgetPolicy) -> None:
        self._store[policy.project_id] = policy.model_copy(deep=True)


class InMemoryOpenRouterPricingSnapshotRepository:
    def __init__(self):
        self._store: dict[str, OpenRouterPricingSnapshot] = {}

    def save(self, snapshot: OpenRouterPricingSnapshot) -> None:
        self._store[snapshot.snapshot_id] = snapshot.model_copy(deep=True)

    def get_by_id(self, snapshot_id: str) -> OpenRouterPricingSnapshot | None:
        snapshot = self._store.get(snapshot_id)
        return snapshot.model_copy(deep=True) if snapshot else None

    def get_latest_verified_for_model(
        self, routed_model: str, canonical_name: str | None = None
    ) -> OpenRouterPricingSnapshot | None:
        matching = [
            s for s in self._store.values()
            if s.routed_model_identity == routed_model
            and s.source in AUTHORITATIVE_PRICING_SOURCES
            and (canonical_name is None or s.canonical_model_identity == canonical_name)
        ]
        if not matching:
            return None
        matching.sort(key=lambda x: (x.observed_at, x.created_at), reverse=True)
        return matching[0].model_copy(deep=True)

    def list_by_model(self, routed_model: str) -> list[OpenRouterPricingSnapshot]:
        return [
            s.model_copy(deep=True)
            for s in self._store.values()
            if s.routed_model_identity == routed_model
        ]


class InMemoryBudgetReservationRepository:
    def __init__(self):
        self._store: dict[str, BudgetReservation] = {}

    def save(self, reservation: BudgetReservation) -> None:
        self._store[reservation.reservation_id] = reservation.model_copy(deep=True)

    def get_by_id(self, reservation_id: str) -> BudgetReservation | None:
        reservation = self._store.get(reservation_id)
        return reservation.model_copy(deep=True) if reservation else None

    def list_by_project(self, project_id: str) -> list[BudgetReservation]:
        return [r.model_copy(deep=True) for r in self._store.values() if r.project_id == project_id]


class InMemoryBudgetLedgerRepository:
    def __init__(self):
        self._store: list[BudgetLedgerEntry] = []

    def save(self, entry: BudgetLedgerEntry) -> None:
        self._store.append(entry.model_copy(deep=True))

    def list_by_project(self, project_id: str) -> list[BudgetLedgerEntry]:
        return [e.model_copy(deep=True) for e in self._store if e.project_id == project_id]


class InMemoryPersistenceUnitOfWork(PersistenceUnitOfWork):
    def __init__(self):
        self.projects = InMemoryProjectRepository()
        self.changes = InMemoryChangeRepository()
        self.bindings = InMemoryProjectBindingRepository()
        self.events = InMemoryEventRepository()
        self.metrics = InMemoryMetricFactRepository()
        self.jobs = InMemoryJobRepository()
        self.job_logs = InMemoryJobLogRepository()
        self.check_results = InMemoryCheckResultRepository()
        self.reviews = InMemoryReviewRepository()
        self.review_findings = InMemoryReviewFindingRepository()
        self.audits = InMemoryAuditRepository()
        self.audit_findings = InMemoryAuditFindingRepository()
        self.provider_health = InMemoryProviderHealthRepository()
        self.capacity_windows = InMemoryCapacityWindowRepository()
        self.git_operations = InMemoryGitOperationRepository()
        self.budget_policies = InMemoryOpenRouterBudgetPolicyRepository()
        self.pricing_snapshots = InMemoryOpenRouterPricingSnapshotRepository()
        self.budget_reservations = InMemoryBudgetReservationRepository()
        self.budget_ledger = InMemoryBudgetLedgerRepository()
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True



@pytest.fixture
def in_memory_uow() -> InMemoryPersistenceUnitOfWork:
    return InMemoryPersistenceUnitOfWork()


def create_isolated_openspec_change(
    root: Path,
    change_name: str = "synthetic-change",
    proposal_content: str = "# Proposal\n",
    tasks_content: str = "# Tasks\n",
    design_content: str = "# Design\n",
    spec_content: str = "# Spec\n",
) -> Path:
    """Helper to create a fully isolated OpenSpec change directory with valid standard artifacts."""
    change_dir = root / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text(proposal_content, encoding="utf-8")
    (change_dir / "tasks.md").write_text(tasks_content, encoding="utf-8")
    (change_dir / "design.md").write_text(design_content, encoding="utf-8")
    specs_dir = change_dir / "specs" / "feature"
    specs_dir.mkdir(parents=True, exist_ok=True)
    (specs_dir / "spec.md").write_text(spec_content, encoding="utf-8")
    return change_dir
