"""Domain interfaces for repositories and external adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from minime.domain.models import (
    Change,
    Event,
    MetricFact,
    Project,
    ProjectBinding,
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


class PersistenceUnitOfWork(ABC):
    """Transactional persistence boundary: atomically persists state changes and emitted events."""

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
