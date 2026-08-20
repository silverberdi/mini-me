"""Test fixtures and mock repositories for mini me tests."""

from __future__ import annotations

import pytest

from minime.domain.interfaces import (
    ChangeRepositoryInterface,
    EventRepositoryInterface,
    MetricFactRepositoryInterface,
    PersistenceUnitOfWork,
    ProjectBindingRepositoryInterface,
    ProjectRepositoryInterface,
)
from minime.domain.models import (
    Change,
    Event,
    MetricFact,
    Project,
    ProjectBinding,
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


class InMemoryPersistenceUnitOfWork(PersistenceUnitOfWork):
    def __init__(self):
        self.projects = InMemoryProjectRepository()
        self.changes = InMemoryChangeRepository()
        self.bindings = InMemoryProjectBindingRepository()
        self.events = InMemoryEventRepository()
        self.metrics = InMemoryMetricFactRepository()
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


@pytest.fixture
def in_memory_uow() -> InMemoryPersistenceUnitOfWork:
    return InMemoryPersistenceUnitOfWork()
