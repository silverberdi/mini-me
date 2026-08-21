"""Domain interfaces for repositories and external adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from minime.domain.enums import GitOperationStatus
from minime.domain.models import (
    AuditFinding,
    AuditRecord,
    CapacityWindow,
    Change,
    CheckResult,
    Event,
    GitOperation,
    Job,
    JobLog,
    MetricFact,
    Project,
    ProjectBinding,
    ProviderHealth,
    Review,
    ReviewFinding,
)


class ProjectRepositoryInterface(ABC):
    @abstractmethod
    def save(self, project: Project) -> None: ...

    @abstractmethod
    def get_by_id(self, project_id: str) -> Project | None: ...

    @abstractmethod
    def list_all(self) -> list[Project]: ...


class ChangeRepositoryInterface(ABC):
    @abstractmethod
    def save(self, change: Change) -> None: ...

    @abstractmethod
    def get_by_id(self, change_id: str) -> Change | None: ...

    @abstractmethod
    def get_by_name(self, project_id: str, name: str) -> Change | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str) -> list[Change]: ...


class ProjectBindingRepositoryInterface(ABC):
    @abstractmethod
    def save(self, binding: ProjectBinding) -> None: ...

    @abstractmethod
    def get_by_id(self, binding_id: str) -> ProjectBinding | None: ...

    @abstractmethod
    def get_by_project_and_change(
        self, project_id: str, change_name: str
    ) -> ProjectBinding | None: ...


class EventRepositoryInterface(ABC):
    @abstractmethod
    def save(self, event: Event) -> None: ...

    @abstractmethod
    def list_events(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        limit: int = 100,
    ) -> list[Event]: ...


class MetricFactRepositoryInterface(ABC):
    @abstractmethod
    def save(self, fact: MetricFact) -> None: ...

    @abstractmethod
    def list_facts(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        metric_name: str | None = None,
        limit: int = 100,
    ) -> list[MetricFact]: ...


class JobRepositoryInterface(ABC):
    @abstractmethod
    def save(self, job: Job) -> None: ...

    @abstractmethod
    def get_by_id(self, job_id: str) -> Job | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str, limit: int = 100) -> list[Job]: ...

    @abstractmethod
    def list_active_jobs(self) -> list[Job]: ...

    @abstractmethod
    def transition(self, job_id: str, new_status: str, error_message: str | None = None) -> Job: ...

    @abstractmethod
    def set_waiting_capacity(
        self,
        job_id: str,
        waiting_provider: str,
        reason: str,
        expected_reset_at: datetime | None = None,
    ) -> Job: ...

    @abstractmethod
    def set_recovery_blocked(self, job_id: str, reason: str) -> Job: ...


class JobLogRepositoryInterface(ABC):
    @abstractmethod
    def save(self, log: JobLog) -> None: ...

    @abstractmethod
    def list_by_job(self, job_id: str, limit: int = 500) -> list[JobLog]: ...


class CheckResultRepositoryInterface(ABC):
    @abstractmethod
    def save(self, result: CheckResult) -> None: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[CheckResult]: ...


class ReviewRepositoryInterface(ABC):
    @abstractmethod
    def save(self, review: Review) -> None: ...

    @abstractmethod
    def get_by_id(self, review_id: str) -> Review | None: ...

    @abstractmethod
    def get_by_job_id(self, job_id: str) -> Review | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str, limit: int = 100) -> list[Review]: ...

    @abstractmethod
    def transition(
        self,
        review_id: str,
        new_status: str,
        verdict: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> Review: ...


class ReviewFindingRepositoryInterface(ABC):
    @abstractmethod
    def save(self, finding: ReviewFinding) -> None: ...

    @abstractmethod
    def list_by_review(self, review_id: str) -> list[ReviewFinding]: ...


class AuditRepositoryInterface(ABC):
    @abstractmethod
    def save(self, audit: AuditRecord) -> None: ...

    @abstractmethod
    def get_by_id(self, audit_id: str) -> AuditRecord | None: ...

    @abstractmethod
    def get_by_job_id(self, job_id: str) -> AuditRecord | None: ...

    @abstractmethod
    def list_by_project(self, project_id: str, limit: int = 100) -> list[AuditRecord]: ...

    @abstractmethod
    def transition(
        self,
        audit_id: str,
        new_status: str,
        risk: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> AuditRecord: ...


class AuditFindingRepositoryInterface(ABC):
    @abstractmethod
    def save(self, finding: AuditFinding) -> None: ...

    @abstractmethod
    def list_by_audit(self, audit_id: str) -> list[AuditFinding]: ...


class ProviderHealthRepositoryInterface(ABC):
    @abstractmethod
    def save(self, health: ProviderHealth) -> None: ...

    @abstractmethod
    def get_by_provider(self, provider: str) -> ProviderHealth | None: ...

    @abstractmethod
    def list_all(self) -> list[ProviderHealth]: ...

    @abstractmethod
    def update_health(
        self,
        provider: str,
        status: str,
        result_class: str | None = None,
        error_summary: str | None = None,
        consecutive_failures: int | None = None,
    ) -> ProviderHealth: ...


class CapacityWindowRepositoryInterface(ABC):
    @abstractmethod
    def save(self, window: CapacityWindow) -> None: ...

    @abstractmethod
    def get_latest_for_provider(self, provider: str) -> CapacityWindow | None: ...

    @abstractmethod
    def list_by_provider(self, provider: str, limit: int = 50) -> list[CapacityWindow]: ...


class GitOperationRepositoryInterface(ABC):
    @abstractmethod
    def save(self, operation: GitOperation) -> None: ...

    @abstractmethod
    def get_by_id(self, operation_id: str) -> GitOperation | None: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[GitOperation]: ...

    @abstractmethod
    def list_by_worktree(self, worktree_path: str) -> list[GitOperation]: ...

    @abstractmethod
    def update_status(
        self,
        operation_id: str,
        status: GitOperationStatus,
        completed_at: datetime | None = None,
    ) -> GitOperation | None: ...


class FallbackPolicyInterface(ABC):
    """Abstract fallback policy seam for future drain provider execution (006)."""

    @abstractmethod
    def is_fallback_eligible(self, project_id: str, job: Job, role: str) -> bool: ...


class PersistenceUnitOfWork(ABC):
    """Transactional persistence boundary: atomically persists state changes and emitted events."""

    projects: ProjectRepositoryInterface
    changes: ChangeRepositoryInterface
    bindings: ProjectBindingRepositoryInterface
    events: EventRepositoryInterface
    metrics: MetricFactRepositoryInterface
    jobs: JobRepositoryInterface
    job_logs: JobLogRepositoryInterface
    check_results: CheckResultRepositoryInterface
    reviews: ReviewRepositoryInterface
    review_findings: ReviewFindingRepositoryInterface
    audits: AuditRepositoryInterface
    audit_findings: AuditFindingRepositoryInterface
    provider_health: ProviderHealthRepositoryInterface
    capacity_windows: CapacityWindowRepositoryInterface
    git_operations: GitOperationRepositoryInterface

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...



class OpenSpecAdapterInterface(ABC):
    @abstractmethod
    def discover_changes(self, project: Project, project_root: str) -> list[Change]: ...

    @abstractmethod
    def evaluate_artifacts(
        self, project: Project, change_name: str, project_root: str
    ) -> dict[str, Any]: ...


class GitHubAdapterInterface(ABC):
    @abstractmethod
    def validate_issue_binding(
        self,
        expected_repository: str,
        issue_number: int,
        github_repository: str | None = None,
    ) -> tuple[bool, str | None]: ...

    @abstractmethod
    def record_sync_failure(
        self,
        project_id: str,
        change_id: str | None,
        operation: str,
        error_message: str,
    ) -> Event: ...
