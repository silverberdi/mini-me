"""Unit and integration tests for 021.3 Work Item Intake."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import WorkItemPriority
from minime.domain.models import Project, WorkItemCreateInput, WorkItemUpdateInput
from minime.services.intake_service import IntakeService


def test_create_and_update_work_item(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "work-repo"
    repo_dir.mkdir()

    project = Project(
        project_id="work-project",
        display_name="Work Project",
        repository=str(repo_dir),
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    service = IntakeService(in_memory_uow, project_root=repo_dir)

    # 1. Create work item
    item = service.create_work_item(
        "work-project",
        WorkItemCreateInput(
            title="Implement Rate Limiting",
            priority=WorkItemPriority.HIGH,
            description="Protect API endpoints from abuse.",
            acceptance_criteria=["Returns HTTP 429 when quota exceeded"],
        ),
        operator_email="operator@example.com",
    )

    assert item.project_id == "work-project"
    assert "rate-limiting" in item.item_key
    assert item.priority == WorkItemPriority.HIGH
    assert len(item.acceptance_criteria) == 1

    # 2. Update priority and description
    updated = service.update_work_item(
        "work-project",
        item.item_key,
        WorkItemUpdateInput(
            priority=WorkItemPriority.CRITICAL,
            description="Updated description with security rationale.",
        ),
        operator_email="operator@example.com",
    )

    assert updated.priority == WorkItemPriority.CRITICAL
    assert updated.description == "Updated description with security rationale."

    # 3. Delete work item
    service.delete_work_item("work-project", item.item_key, operator_email="operator@example.com")
    deleted = in_memory_uow.backlog_items.get_by_project_and_key("work-project", item.item_key)
    assert deleted is None


def test_create_duplicate_work_item_fails(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "work-repo"
    repo_dir.mkdir()

    project = Project(
        project_id="work-project",
        display_name="Work Project",
        repository=str(repo_dir),
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    service = IntakeService(in_memory_uow, project_root=repo_dir)

    service.create_work_item(
        "work-project",
        WorkItemCreateInput(
            item_key="022-unique-key",
            title="First task",
        ),
        operator_email="operator@example.com",
    )

    with pytest.raises(ValueError, match="already exists"):
        service.create_work_item(
            "work-project",
            WorkItemCreateInput(
                item_key="022-unique-key",
                title="Duplicate task",
            ),
            operator_email="operator@example.com",
        )
