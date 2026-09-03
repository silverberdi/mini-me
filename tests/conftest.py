"""Test fixtures and mock repositories for mini me tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from minime.domain.enums import (
    PRIMARY_PROVIDERS,
    AuditRiskLevel,
    AuditStatus,
    ExternalActionStatus,
    GitOperationStatus,
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProviderHealthStatus,
    ProviderResultClass,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.interfaces import (
    AuditFindingRepositoryInterface,
    AuditRepositoryInterface,
    BlockerClaimRepositoryInterface,
    CandidateAuthorshipRepositoryInterface,
    CandidateManifestRepositoryInterface,
    CapacityWindowRepositoryInterface,
    ChangeRepositoryInterface,
    CheckResultRepositoryInterface,
    EventRepositoryInterface,
    EvidenceDiagnosticRepositoryInterface,
    GitOperationRepositoryInterface,
    JobAttemptRepositoryInterface,
    JobHandoffRepositoryInterface,
    JobLogRepositoryInterface,
    JobRepositoryInterface,
    MetricFactRepositoryInterface,
    OperatorActionRepositoryInterface,
    OrchestrationCandidateRepositoryInterface,
    OrchestrationExternalActionRepositoryInterface,
    OrchestrationRunRepositoryInterface,
    OrchestrationStageEventRepositoryInterface,
    PersistenceUnitOfWork,
    PreviewSessionRepositoryInterface,
    ProjectBindingRepositoryInterface,
    ProjectRepositoryInterface,
    ProviderHealthRepositoryInterface,
    ReviewFindingRepositoryInterface,
    ReviewRepositoryInterface,
    SchedulerDecisionRepositoryInterface,
    ValidationRunRepositoryInterface,
    WorkQueueRepositoryInterface,
)
from minime.domain.models import (
    AUTHORITATIVE_PRICING_SOURCES,
    AuditFinding,
    AuditRecord,
    BlockerClaim,
    BudgetLedgerEntry,
    BudgetReservation,
    CandidateAuthorship,
    CandidateManifest,
    CapacityWindow,
    Change,
    CheckResult,
    Event,
    EvidenceDiagnostic,
    GitOperation,
    Job,
    JobAttempt,
    JobHandoff,
    JobLog,
    MetricFact,
    OpenRouterBudgetPolicy,
    OpenRouterPricingSnapshot,
    OperatorActionRecord,
    OrchestrationCandidate,
    OrchestrationExternalAction,
    OrchestrationRun,
    OrchestrationStageEvent,
    PreviewSession,
    Project,
    ProjectBinding,
    ProviderHealth,
    Review,
    ReviewFinding,
    SchedulerDecisionRecord,
    ValidationRun,
    WorkQueueItem,
    utc_now,
)


class ReadinessGitHubStub:
    """Explicit offline double for legacy readiness tests; live validation is tested separately."""

    def validate_issue_binding(self, expected_repository, issue_number, github_repository=None):
        return True, None


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
        logical_matches = [
            c
            for c in self._store.values()
            if c.project_id == change.project_id and c.name == change.name
        ]
        if len(logical_matches) > 1:
            raise ValueError(
                f"Ambiguous logical Change identity for project '{change.project_id}' and "
                f"change '{change.name}': {len(logical_matches)} rows found."
            )
        physical = self._store.get(change.change_id)
        if (
            physical is not None
            and logical_matches
            and logical_matches[0].change_id != physical.change_id
        ):
            raise ValueError(
                f"Conflicting Change identities for project '{change.project_id}' and "
                f"change '{change.name}'."
            )
        if physical is not None:
            updated = change.model_copy(deep=True)
            updated.change_id = physical.change_id
            updated.discovered_at = physical.discovered_at
            self._store[physical.change_id] = updated
            return
        if logical_matches:
            existing = logical_matches[0]
            updated = existing.model_copy(deep=True)
            updated.schema_name = change.schema_name
            updated.proposal_path = change.proposal_path
            updated.tasks_path = change.tasks_path
            updated.design_path = change.design_path
            updated.specs_paths = change.specs_paths
            updated.updated_at = change.updated_at
            self._store[existing.change_id] = updated
            return
        else:
            self._store[change.change_id] = change.model_copy(deep=True)

    def get_by_id(self, change_id: str) -> Change | None:
        c = self._store.get(change_id)
        return c.model_copy(deep=True) if c else None

    def get_by_name(self, project_id: str, name: str) -> Change | None:
        matches = [c for c in self._store.values() if c.project_id == project_id and c.name == name]
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous logical Change identity for project '{project_id}' and change "
                f"'{name}': {len(matches)} rows found."
            )
        return matches[0].model_copy(deep=True) if matches else None

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
            JobStatus.RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_RUNNING: {
            JobStatus.CHECKS_PASSED,
            JobStatus.CHECKS_FAILED,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_PASSED: {
            JobStatus.REVIEW_RUNNING,
            JobStatus.WAITING_CAPACITY,
            JobStatus.NEEDS_HUMAN,
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
            JobStatus.NEEDS_HUMAN,
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
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.WAITING_CAPACITY: {
            JobStatus.RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.REVIEW_RUNNING,
            JobStatus.AUDIT_RUNNING,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.RECOVERY_BLOCKED: {
            JobStatus.WAITING_CAPACITY,
            JobStatus.RUNNING,
            JobStatus.REVIEW_RUNNING,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.READY_TO_MERGE: {
            JobStatus.POST_MERGE_RECONCILING,
            JobStatus.COMPLETED,
        },
        JobStatus.POST_MERGE_RECONCILING: {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.COMPLETED: set(),
        JobStatus.AUDIT_BLOCKED: {
            JobStatus.RUNNING,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHANGES_REQUIRED: {
            JobStatus.RUNNING,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.NEEDS_HUMAN: {
            JobStatus.RUNNING,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.FAILED: set(),
        JobStatus.CANCELLED: set(),
    }

    for _status in JobStatus:
        _valid_transitions[_status].add(JobStatus.RECOVERY_BLOCKED)

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
            raise ValueError(
                f"Invalid job status transition: {job.status.value} -> {target.value}."
            )
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
            raise ValueError(
                f"Invalid job status transition: {job.status.value} -> {target.value}."
            )
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
            raise ValueError(
                f"Invalid job status transition: {job.status.value} -> {target.value}."
            )
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
        reviews.sort(key=lambda r: (r.updated_at, r.created_at), reverse=True)
        return reviews[0].model_copy(deep=True) if reviews else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[Review]:
        reviews = [r for r in self._store.values() if r.project_id == project_id]
        reviews.sort(key=lambda r: (r.updated_at, r.created_at), reverse=True)
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
        update_dict: dict[str, object] = {"status": target, "updated_at": utc_now()}
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
        audits.sort(key=lambda a: (a.updated_at, a.created_at), reverse=True)
        return audits[0].model_copy(deep=True) if audits else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[AuditRecord]:
        audits = [a for a in self._store.values() if a.project_id == project_id]
        audits.sort(key=lambda a: (a.updated_at, a.created_at), reverse=True)
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
            raise ValueError(f"Audit record '{audit_id}' not found.")
        target = AuditStatus(new_status)
        if target not in self._valid_transitions[audit.status]:
            raise ValueError(
                f"Invalid audit status transition: {audit.status.value} -> {target.value}."
            )
        update_dict: dict[str, object] = {"status": target, "updated_at": utc_now()}
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
            if (
                target_status == ProviderHealthStatus.AVAILABLE
                and target_result_class == ProviderResultClass.SUCCESS
            ):
                succ_at = now
            elif target_result_class and target_result_class != ProviderResultClass.SUCCESS:
                fail_at = now

            h = h.model_copy(
                update={
                    "status": target_status,
                    "consecutive_failures": consecutive,
                    "last_result_class": target_result_class or h.last_result_class,
                    "last_error_summary": error_summary
                    if error_summary is not None
                    else h.last_error_summary,
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
            s
            for s in self._store.values()
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


class InMemoryJobAttemptRepository(JobAttemptRepositoryInterface):
    def __init__(self):
        self._store: dict[str, JobAttempt] = {}

    def save(self, attempt: JobAttempt) -> None:
        self._store[attempt.attempt_id] = attempt.model_copy(deep=True)

    def get_by_id(self, attempt_id: str) -> JobAttempt | None:
        att = self._store.get(attempt_id)
        return att.model_copy(deep=True) if att else None

    def list_by_job(self, job_id: str) -> list[JobAttempt]:
        attempts = [a for a in self._store.values() if a.job_id == job_id]
        attempts.sort(key=lambda a: a.attempt_number)
        return [a.model_copy(deep=True) for a in attempts]

    def get_latest_attempt(self, job_id: str) -> JobAttempt | None:
        attempts = self.list_by_job(job_id)
        return attempts[-1] if attempts else None


class InMemoryBlockerClaimRepository(BlockerClaimRepositoryInterface):
    def __init__(self):
        self._store: dict[str, BlockerClaim] = {}

    def save(self, claim: BlockerClaim) -> None:
        self._store[claim.claim_id] = claim.model_copy(deep=True)

    def get_by_id(self, claim_id: str) -> BlockerClaim | None:
        c = self._store.get(claim_id)
        return c.model_copy(deep=True) if c else None

    def list_by_job(self, job_id: str) -> list[BlockerClaim]:
        return [c.model_copy(deep=True) for c in self._store.values() if c.job_id == job_id]

    def list_by_attempt(self, attempt_id: str) -> list[BlockerClaim]:
        return [c.model_copy(deep=True) for c in self._store.values() if c.attempt_id == attempt_id]


class InMemoryJobHandoffRepository(JobHandoffRepositoryInterface):
    def __init__(self):
        self._store: dict[str, JobHandoff] = {}

    def save(self, handoff: JobHandoff) -> None:
        self._store[handoff.handoff_id] = handoff.model_copy(deep=True)

    def get_by_id(self, handoff_id: str) -> JobHandoff | None:
        h = self._store.get(handoff_id)
        return h.model_copy(deep=True) if h else None

    def list_by_job(self, job_id: str) -> list[JobHandoff]:
        handoffs = [h for h in self._store.values() if h.job_id == job_id]
        handoffs.sort(key=lambda h: h.created_at)
        return [h.model_copy(deep=True) for h in handoffs]

    def get_latest_handoff(self, job_id: str) -> JobHandoff | None:
        handoffs = self.list_by_job(job_id)
        return handoffs[-1] if handoffs else None

    def get_pending_handoff_for_attempt(
        self, job_id: str, to_attempt_number: int
    ) -> JobHandoff | None:
        for h in self._store.values():
            if (
                h.job_id == job_id
                and h.to_attempt_number == to_attempt_number
                and not h.is_consumed
            ):
                return h.model_copy(deep=True)
        return None


class InMemoryCandidateManifestRepository(CandidateManifestRepositoryInterface):
    def __init__(self):
        self._store: dict[str, CandidateManifest] = {}

    def save(self, manifest: CandidateManifest) -> None:
        self._store[manifest.manifest_id] = manifest.model_copy(deep=True)

    def get_by_id(self, manifest_id: str) -> CandidateManifest | None:
        m = self._store.get(manifest_id)
        return m.model_copy(deep=True) if m else None

    def get_latest_manifest(self, job_id: str) -> CandidateManifest | None:
        manifests = [m for m in self._store.values() if m.job_id == job_id]
        if not manifests:
            return None
        manifests.sort(key=lambda m: m.created_at, reverse=True)
        return manifests[0].model_copy(deep=True)

    def get_by_candidate_sha(self, job_id: str, candidate_sha: str) -> CandidateManifest | None:
        for m in self._store.values():
            if m.job_id == job_id and m.candidate_sha == candidate_sha:
                return m.model_copy(deep=True)
        return None


class InMemoryCandidateAuthorshipRepository(CandidateAuthorshipRepositoryInterface):
    def __init__(self):
        self._store: dict[str, CandidateAuthorship] = {}

    def save(self, authorship: CandidateAuthorship) -> None:
        self._store[authorship.authorship_id] = authorship.model_copy(deep=True)

    def list_by_job(self, job_id: str) -> list[CandidateAuthorship]:
        return [a.model_copy(deep=True) for a in self._store.values() if a.job_id == job_id]

    def get_for_file(self, job_id: str, file_path: str) -> CandidateAuthorship | None:
        for a in self._store.values():
            if a.job_id == job_id and a.file_path == file_path:
                return a.model_copy(deep=True)
        return None


class InMemoryEvidenceDiagnosticRepository(EvidenceDiagnosticRepositoryInterface):
    def __init__(self):
        self._store: dict[str, EvidenceDiagnostic] = {}

    def save(self, diagnostic: EvidenceDiagnostic) -> None:
        self._store[diagnostic.diagnostic_id] = diagnostic.model_copy(deep=True)

    def get_by_id(self, diagnostic_id: str) -> EvidenceDiagnostic | None:
        d = self._store.get(diagnostic_id)
        return d.model_copy(deep=True) if d else None

    def list_by_job(self, job_id: str) -> list[EvidenceDiagnostic]:
        return [d.model_copy(deep=True) for d in self._store.values() if d.job_id == job_id]

    def list_by_attempt(self, attempt_id: str) -> list[EvidenceDiagnostic]:
        return [d.model_copy(deep=True) for d in self._store.values() if d.attempt_id == attempt_id]


class InMemoryOrchestrationRunRepository(OrchestrationRunRepositoryInterface):
    def __init__(self):
        self._store: dict[str, OrchestrationRun] = {}

    def save(self, run: OrchestrationRun) -> None:
        if run.is_active:
            for existing in self._store.values():
                if (
                    existing.run_id != run.run_id
                    and existing.project_id == run.project_id
                    and existing.change_name == run.change_name
                    and existing.is_active
                ):
                    raise ValueError(
                        "Unique constraint violation: active orchestration run already exists for this project and change"
                    )
        self._store[run.run_id] = run.model_copy(deep=True)

    def get_by_id(self, run_id: str) -> OrchestrationRun | None:
        r = self._store.get(run_id)
        return r.model_copy(deep=True) if r else None

    def get_active_run(self, project_id: str, change_name: str) -> OrchestrationRun | None:
        for r in self._store.values():
            if r.project_id == project_id and r.change_name == change_name and r.is_active:
                return r.model_copy(deep=True)
        return None

    def list_runs(
        self,
        project_id: str | None = None,
        change_name: str | None = None,
        is_active: bool | None = None,
    ) -> list[OrchestrationRun]:
        res = list(self._store.values())
        if project_id:
            res = [r for r in res if r.project_id == project_id]
        if change_name:
            res = [r for r in res if r.change_name == change_name]
        if is_active is not None:
            res = [r for r in res if r.is_active == is_active]
        res.sort(key=lambda r: r.created_at, reverse=True)
        return [r.model_copy(deep=True) for r in res]

    def update_stage(
        self,
        run_id: str,
        current_stage: OrchestrationStage,
        resumable_stage: OrchestrationStage,
    ) -> OrchestrationRun:
        r = self._store.get(run_id)
        if not r:
            raise ValueError(f"Orchestration run '{run_id}' not found")
        r.current_stage = current_stage
        r.resumable_stage = resumable_stage
        r.updated_at = utc_now()
        return r.model_copy(deep=True)

    def update_stop_outcome(
        self,
        run_id: str,
        stop_outcome: OrchestrationStopOutcome,
        human_gate: HumanGate | None = None,
        stop_reason: str | None = None,
        stop_details: dict | None = None,
        is_active: bool = False,
    ) -> OrchestrationRun:
        r = self._store.get(run_id)
        if not r:
            raise ValueError(f"Orchestration run '{run_id}' not found")
        r.stop_outcome = stop_outcome
        r.human_gate = human_gate
        r.stop_reason = stop_reason
        r.stop_details = stop_details or {}
        r.is_active = is_active
        r.updated_at = utc_now()
        return r.model_copy(deep=True)

    def update_candidate_binding(
        self,
        run_id: str,
        current_generation: int,
        current_candidate_sha: str | None,
    ) -> OrchestrationRun:
        r = self._store.get(run_id)
        if not r:
            raise ValueError(f"Orchestration run '{run_id}' not found")
        r.current_generation = current_generation
        r.current_candidate_sha = current_candidate_sha
        r.updated_at = utc_now()
        return r.model_copy(deep=True)

    def update_active_job(
        self,
        run_id: str,
        active_job_id: str | None,
    ) -> OrchestrationRun:
        r = self._store.get(run_id)
        if not r:
            raise ValueError(f"Orchestration run '{run_id}' not found")
        r.active_job_id = active_job_id
        r.updated_at = utc_now()
        return r.model_copy(deep=True)


class InMemoryOrchestrationStageEventRepository(OrchestrationStageEventRepositoryInterface):
    def __init__(self):
        self._store: list[OrchestrationStageEvent] = []

    def save(self, event: OrchestrationStageEvent) -> None:
        if event.transition_key:
            if any(e.transition_key == event.transition_key for e in self._store):
                raise ValueError(f"Duplicate transition key '{event.transition_key}'")
        self._store.append(event.model_copy(deep=True))

    def list_by_run(self, run_id: str) -> list[OrchestrationStageEvent]:
        events = [e.model_copy(deep=True) for e in self._store if e.run_id == run_id]
        events.sort(key=lambda e: e.created_at)
        return events

    def get_by_transition_key(self, transition_key: str) -> OrchestrationStageEvent | None:
        for e in self._store:
            if e.transition_key == transition_key:
                return e.model_copy(deep=True)
        return None


class InMemoryOrchestrationCandidateRepository(OrchestrationCandidateRepositoryInterface):
    def __init__(self):
        self._store: dict[str, OrchestrationCandidate] = {}

    def save(self, candidate: OrchestrationCandidate) -> None:
        for existing in self._store.values():
            if (
                existing.candidate_id != candidate.candidate_id
                and existing.run_id == candidate.run_id
                and existing.generation == candidate.generation
            ):
                raise ValueError(
                    f"Unique constraint violation: generation {candidate.generation} already exists for run '{candidate.run_id}'"
                )
        self._store[candidate.candidate_id] = candidate.model_copy(deep=True)

    def get_by_id(self, candidate_id: str) -> OrchestrationCandidate | None:
        c = self._store.get(candidate_id)
        return c.model_copy(deep=True) if c else None

    def get_by_generation(self, run_id: str, generation: int) -> OrchestrationCandidate | None:
        for c in self._store.values():
            if c.run_id == run_id and c.generation == generation:
                return c.model_copy(deep=True)
        return None

    def get_latest_for_run(self, run_id: str) -> OrchestrationCandidate | None:
        matching = [c for c in self._store.values() if c.run_id == run_id]
        if not matching:
            return None
        matching.sort(key=lambda c: c.generation, reverse=True)
        return matching[0].model_copy(deep=True)

    def list_by_run(self, run_id: str) -> list[OrchestrationCandidate]:
        matching = [c.model_copy(deep=True) for c in self._store.values() if c.run_id == run_id]
        matching.sort(key=lambda c: c.generation)
        return matching

    def supersede(self, candidate_id: str, superseded_by_id: str) -> None:
        if candidate_id in self._store:
            self._store[candidate_id].superseded_by_id = superseded_by_id


class InMemoryOrchestrationExternalActionRepository(OrchestrationExternalActionRepositoryInterface):
    def __init__(self):
        self._store: dict[str, OrchestrationExternalAction] = {}

    def reserve(self, action: OrchestrationExternalAction) -> None:
        for existing in self._store.values():
            if existing.action_key == action.action_key:
                raise ValueError(f"Action key '{action.action_key}' already exists")
        self._store[action.action_id] = action.model_copy(deep=True)

    def get_by_action_key(self, action_key: str) -> OrchestrationExternalAction | None:
        for a in self._store.values():
            if a.action_key == action_key:
                return a.model_copy(deep=True)
        return None

    def list_by_run(self, run_id: str) -> list[OrchestrationExternalAction]:
        actions = [a.model_copy(deep=True) for a in self._store.values() if a.run_id == run_id]
        actions.sort(key=lambda a: a.created_at)
        return actions

    def update_status(
        self,
        action_key: str,
        status: ExternalActionStatus,
        remote_identifier: str | None = None,
        result_payload: dict | None = None,
        error_message: str | None = None,
    ) -> OrchestrationExternalAction:
        target = None
        for a in self._store.values():
            if a.action_key == action_key:
                target = a
                break
        if not target:
            raise ValueError(f"External action '{action_key}' not found")
        target.status = status
        if remote_identifier is not None:
            target.remote_identifier = remote_identifier
        if result_payload is not None:
            target.result_payload = result_payload
        if error_message is not None:
            target.error_message = error_message
        if status in {
            ExternalActionStatus.COMPLETED,
            ExternalActionStatus.FAILED,
            ExternalActionStatus.AMBIGUOUS,
        }:
            target.reconciled_at = utc_now()
        target.updated_at = utc_now()
        return target.model_copy(deep=True)


class InMemoryPreviewSessionRepository(PreviewSessionRepositoryInterface):
    def __init__(self):
        self._store: dict[str, PreviewSession] = {}

    def save(self, session: PreviewSession) -> None:
        self._store[session.preview_id] = session.model_copy(deep=True)

    def get_by_id(self, preview_id: str) -> PreviewSession | None:
        s = self._store.get(preview_id)
        return s.model_copy(deep=True) if s else None

    def get_latest_for_run(self, run_id: str) -> PreviewSession | None:
        matches = [s for s in self._store.values() if s.run_id == run_id]
        if not matches:
            return None
        matches.sort(key=lambda s: s.created_at, reverse=True)
        return matches[0].model_copy(deep=True)

    def get_latest_for_candidate(
        self, project_id: str, change_name: str, head_sha: str
    ) -> PreviewSession | None:
        matches = [
            s
            for s in self._store.values()
            if s.project_id == project_id
            and s.change_name == change_name
            and s.head_sha == head_sha
        ]
        if not matches:
            return None
        matches.sort(key=lambda s: s.created_at, reverse=True)
        return matches[0].model_copy(deep=True)

    def list_by_change(self, project_id: str, change_name: str) -> list[PreviewSession]:
        matches = [
            s.model_copy(deep=True)
            for s in self._store.values()
            if s.project_id == project_id and s.change_name == change_name
        ]
        matches.sort(key=lambda s: s.created_at, reverse=True)
        return matches

    def list_active(self) -> list[PreviewSession]:
        active_statuses = {"REQUESTED", "BUILDING", "STARTING", "PROBING", "READY"}
        matches = [
            s.model_copy(deep=True)
            for s in self._store.values()
            if s.status.value in active_statuses
        ]
        matches.sort(key=lambda s: s.created_at, reverse=True)
        return matches

    def get_active_for_change(self, project_id: str, change_name: str) -> PreviewSession | None:
        active_statuses = {"REQUESTED", "BUILDING", "STARTING", "PROBING", "READY"}
        matches = [
            s
            for s in self._store.values()
            if s.project_id == project_id
            and s.change_name == change_name
            and s.status.value in active_statuses
        ]
        if not matches:
            return None
        matches.sort(key=lambda s: s.created_at, reverse=True)
        return matches[0].model_copy(deep=True)


class InMemoryValidationRunRepository(ValidationRunRepositoryInterface):
    def __init__(self):
        self._store: dict[str, ValidationRun] = {}

    def save(self, validation: ValidationRun) -> None:
        self._store[validation.validation_id] = validation.model_copy(deep=True)

    def get_by_id(self, validation_id: str) -> ValidationRun | None:
        v = self._store.get(validation_id)
        return v.model_copy(deep=True) if v else None

    def get_latest_for_candidate(
        self,
        project_id: str,
        change_name: str,
        head_sha: str,
        base_sha: str,
        image_digest: str,
    ) -> ValidationRun | None:
        matches = [
            v
            for v in self._store.values()
            if v.project_id == project_id
            and v.change_name == change_name
            and v.head_sha == head_sha
            and v.base_sha == base_sha
            and v.image_digest == image_digest
        ]
        if not matches:
            return None
        matches.sort(key=lambda v: v.created_at, reverse=True)
        return matches[0].model_copy(deep=True)

    def list_by_change(self, project_id: str, change_name: str) -> list[ValidationRun]:
        matches = [
            v.model_copy(deep=True)
            for v in self._store.values()
            if v.project_id == project_id and v.change_name == change_name
        ]
        matches.sort(key=lambda v: v.created_at, reverse=True)
        return matches

    def list_by_run(self, run_id: str) -> list[ValidationRun]:
        matches = [v.model_copy(deep=True) for v in self._store.values() if v.run_id == run_id]
        matches.sort(key=lambda v: v.created_at, reverse=True)
        return matches


class InMemoryOperatorActionRepository(OperatorActionRepositoryInterface):
    def __init__(self):
        self._store: dict[str, OperatorActionRecord] = {}

    def save(self, record: OperatorActionRecord) -> None:
        self._store[record.id] = record.model_copy(deep=True)

    def get_by_id(self, action_id: str) -> OperatorActionRecord | None:
        rec = self._store.get(action_id)
        return rec.model_copy(deep=True) if rec else None

    def get_by_request_id(self, action_request_id: str) -> OperatorActionRecord | None:
        for rec in self._store.values():
            if rec.action_request_id == action_request_id:
                return rec.model_copy(deep=True)
        return None

    def list_by_run(self, run_id: str, limit: int = 50) -> list[OperatorActionRecord]:
        matches = [r.model_copy(deep=True) for r in self._store.values() if r.run_id == run_id]
        matches.sort(key=lambda r: r.created_at, reverse=True)
        return matches[:limit]

    def list_by_project(self, project_id: str, limit: int = 50) -> list[OperatorActionRecord]:
        matches = [
            r.model_copy(deep=True) for r in self._store.values() if r.project_id == project_id
        ]
        matches.sort(key=lambda r: r.created_at, reverse=True)
        return matches[:limit]


class InMemoryWorkQueueRepository(WorkQueueRepositoryInterface):
    def __init__(self):
        self._store: dict[str, WorkQueueItem] = {}

    def save(self, item: WorkQueueItem) -> None:
        for existing in self._store.values():
            if existing.project_id == item.project_id and existing.change_name == item.change_name:
                updated = item.model_copy(deep=True)
                updated.queue_item_id = existing.queue_item_id
                updated.discovered_at = existing.discovered_at
                self._store[existing.queue_item_id] = updated
                return
        self._store[item.queue_item_id] = item.model_copy(deep=True)

    def get_by_id(self, queue_item_id: str) -> WorkQueueItem | None:
        item = self._store.get(queue_item_id)
        return item.model_copy(deep=True) if item else None

    def get_by_project_and_change(self, project_id: str, change_name: str) -> WorkQueueItem | None:
        matches = [
            item
            for item in self._store.values()
            if item.project_id == project_id and item.change_name == change_name
        ]
        return matches[0].model_copy(deep=True) if matches else None

    def list_all(self, project_id: str | None = None) -> list[WorkQueueItem]:
        items = list(self._store.values())
        if project_id:
            items = [item for item in items if item.project_id == project_id]
        items.sort(key=lambda i: (-i.priority_score, i.discovered_at))
        return [i.model_copy(deep=True) for i in items]

    def list_ready(self, project_id: str | None = None) -> list[WorkQueueItem]:
        items = [item for item in self._store.values() if item.admission_eligible]
        if project_id:
            items = [item for item in items if item.project_id == project_id]
        items.sort(key=lambda i: (-i.priority_score, i.discovered_at))
        return [i.model_copy(deep=True) for i in items]

    def delete(self, queue_item_id: str) -> None:
        self._store.pop(queue_item_id, None)


class InMemorySchedulerDecisionRepository(SchedulerDecisionRepositoryInterface):
    def __init__(self):
        self._store: list[SchedulerDecisionRecord] = []

    def save(self, decision: SchedulerDecisionRecord) -> None:
        self._store.append(decision.model_copy(deep=True))

    def get_by_id(self, decision_id: str) -> SchedulerDecisionRecord | None:
        for d in self._store:
            if d.decision_id == decision_id:
                return d.model_copy(deep=True)
        return None

    def list_by_change(
        self, project_id: str, change_name: str, limit: int = 50
    ) -> list[SchedulerDecisionRecord]:
        matches = [
            d for d in self._store if d.project_id == project_id and d.change_name == change_name
        ]
        matches.sort(key=lambda d: d.evaluated_at, reverse=True)
        return [d.model_copy(deep=True) for d in matches[:limit]]

    def list_recent(
        self, project_id: str | None = None, limit: int = 100
    ) -> list[SchedulerDecisionRecord]:
        items = self._store
        if project_id:
            items = [d for d in items if d.project_id == project_id]
        items.sort(key=lambda d: d.evaluated_at, reverse=True)
        return [d.model_copy(deep=True) for d in items[:limit]]


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
        self.job_attempts = InMemoryJobAttemptRepository()
        self.blocker_claims = InMemoryBlockerClaimRepository()
        self.job_handoffs = InMemoryJobHandoffRepository()
        self.candidate_manifests = InMemoryCandidateManifestRepository()
        self.candidate_authorships = InMemoryCandidateAuthorshipRepository()
        self.evidence_diagnostics = InMemoryEvidenceDiagnosticRepository()
        self.orchestration_runs = InMemoryOrchestrationRunRepository()
        self.orchestration_stage_events = InMemoryOrchestrationStageEventRepository()
        self.orchestration_candidates = InMemoryOrchestrationCandidateRepository()
        self.orchestration_external_actions = InMemoryOrchestrationExternalActionRepository()
        self.preview_sessions = InMemoryPreviewSessionRepository()
        self.validation_runs = InMemoryValidationRunRepository()
        self.operator_actions = InMemoryOperatorActionRepository()
        self.work_queue = InMemoryWorkQueueRepository()
        self.scheduler_decisions = InMemorySchedulerDecisionRepository()
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
