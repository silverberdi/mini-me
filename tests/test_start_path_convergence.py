"""Start-path convergence: no executable work may start outside the scheduler policy."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import (
    InMemoryPersistenceUnitOfWork,
    ReadinessGitHubStub,
    init_git_repo,
)

from minime.domain.enums import (
    AdmissionDecisionKind,
    ProviderHealthStatus,
    WorkItemPriority,
)
from minime.domain.models import (
    BacklogItem,
    Project,
    ProviderHealth,
    WorkItemStatus,
)
from minime.services.intake_service import IntakeService


def _setup_ready_item(
    uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> IntakeService:
    repo_dir = tmp_path / "app-repo"
    repo_dir.mkdir()
    init_git_repo(repo_dir)

    project = Project(
        project_id="app-proj",
        display_name="App Project",
        repository="test-owner/app-repo",
        base_branch="main",
    )
    uow.projects.save(project)

    uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
    )
    uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE)
    )

    item = BacklogItem(
        project_id="app-proj",
        item_key="025-ready-task",
        title="Implement audit logging",
        priority=WorkItemPriority.NORMAL,
        status=WorkItemStatus.BACKLOG,
        description="Add audit log entry on all operator mutations.",
        acceptance_criteria=["Logs contain operator, timestamp, and action"],
    )
    uow.backlog_items.save(item)

    service = IntakeService(
        uow, project_root=repo_dir, github_adapter=ReadinessGitHubStub()
    )
    service.prepare_work_item("app-proj", "025-ready-task", operator_email="op@example.com")
    return service


def test_blocked_admission_cannot_start_through_intake(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
):
    service = _setup_ready_item(in_memory_uow, tmp_path)

    # Exhaust the canonically assigned implementer after preparation reached READY.
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
    )

    with pytest.raises(ValueError):
        service.start_work_item("app-proj", "025-ready-task", operator_email="op@example.com")


def test_ready_item_starts_through_scheduler_authority(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
):
    service = _setup_ready_item(in_memory_uow, tmp_path)

    started = service.start_work_item("app-proj", "025-ready-task", operator_email="op@example.com")

    assert started.is_admitted is True
    assert started.run_id is not None

    # A scheduler decision was recorded (authority exercised), not a raw orchestration admit.
    recent = in_memory_uow.scheduler_decisions.list_recent("app-proj", limit=1)
    assert recent
    assert recent[0].operational_decision == AdmissionDecisionKind.RUN
