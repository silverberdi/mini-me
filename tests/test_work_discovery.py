"""Unit and integration tests for WorkDiscoveryService."""

from pathlib import Path
from unittest.mock import MagicMock

from tests.conftest import InMemoryPersistenceUnitOfWork, create_isolated_openspec_change

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import (
    QueuePriority,
)
from minime.domain.models import (
    Project,
)
from minime.services.discovery_service import (
    WorkDiscoveryService,
    extract_priority_from_labels,
    extract_roadmap_stage,
)


def test_extract_roadmap_stage():
    assert extract_roadmap_stage("001-foundation") == 1
    assert extract_roadmap_stage("016-autonomous-queue-work-selection") == 16
    assert extract_roadmap_stage("017-pwa-control-center") == 17
    assert extract_roadmap_stage("non-numeric-change") is None


def test_extract_priority_from_labels():
    assert extract_priority_from_labels([{"name": "priority:critical"}]) == QueuePriority.CRITICAL
    assert extract_priority_from_labels(["P0"]) == QueuePriority.CRITICAL
    assert extract_priority_from_labels([{"name": "priority:high"}]) == QueuePriority.HIGH
    assert extract_priority_from_labels(["p1"]) == QueuePriority.HIGH
    assert extract_priority_from_labels([{"name": "priority:low"}]) == QueuePriority.LOW
    assert extract_priority_from_labels(["p3"]) == QueuePriority.LOW
    assert extract_priority_from_labels(["enhancement", "bug"]) == QueuePriority.NORMAL
    assert extract_priority_from_labels([]) == QueuePriority.NORMAL
    assert extract_priority_from_labels(None) == QueuePriority.NORMAL


def test_discover_work_creates_queue_items_and_reconciles_bindings(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    # Create local OpenSpec change
    create_isolated_openspec_change(
        tmp_path,
        change_name="016-autonomous-queue-work-selection",
        proposal_content="# Proposal\nWhy this change is needed.\n",
        tasks_content="# Tasks\n- [ ] Task 1\n",
        design_content="# Design\nArchitecture design.\n",
        spec_content="# Spec\nRequirement: Foo\n",
    )

    # Mock GitHub adapter returning matching issue
    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.list_issues.return_value = [
        {
            "number": 45,
            "title": "016-autonomous-queue-work-selection: Autonomous Queue + Work Selection",
            "body": "Implements autonomous work selection.",
            "labels": [{"name": "priority:high"}],
            "state": "open",
        }
    ]
    mock_gh.validate_issue_binding.return_value = (True, None)

    discovery_service = WorkDiscoveryService(
        uow=in_memory_uow,
        project_root=tmp_path,
        github_adapter=mock_gh,
    )

    items = discovery_service.discover_work("mini-me")
    assert len(items) == 1
    item = items[0]
    assert item.change_name == "016-autonomous-queue-work-selection"
    assert item.github_issue_number == 45
    assert item.priority == QueuePriority.HIGH
    assert item.roadmap_stage == 16

    # Verify durable binding was created
    binding = in_memory_uow.bindings.get_by_project_and_change(
        "mini-me", "016-autonomous-queue-work-selection"
    )
    assert binding is not None
    assert binding.github_issue_number == 45
    assert binding.repository == "silverberdi/mini-me"


def test_discover_work_is_idempotent(tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    create_isolated_openspec_change(tmp_path, change_name="016-test-change")

    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.list_issues.return_value = [
        {"number": 99, "title": "016-test-change", "labels": [], "state": "open"}
    ]
    mock_gh.validate_issue_binding.return_value = (True, None)

    discovery_service = WorkDiscoveryService(
        uow=in_memory_uow,
        project_root=tmp_path,
        github_adapter=mock_gh,
    )

    # First run
    items1 = discovery_service.discover_work("mini-me")
    assert len(items1) == 1
    discovered_at1 = items1[0].discovered_at

    # Second run
    items2 = discovery_service.discover_work("mini-me")
    assert len(items2) == 1
    assert items2[0].queue_item_id == items1[0].queue_item_id
    assert items2[0].discovered_at == discovered_at1
