"""Unit and integration tests for WorkDiscoveryService."""

from pathlib import Path
from unittest.mock import MagicMock

from tests.conftest import InMemoryPersistenceUnitOfWork, create_isolated_openspec_change

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import (
    ChangeStatus,
    ExternalOutcome,
    ExternalReasonCode,
    QueuePriority,
    RetrySafety,
)
from minime.domain.models import (
    Change,
    ExternalActionResult,
    Project,
    WorkQueueItem,
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
    mock_gh.list_issues.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="fake",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=[
            {
                "number": 45,
                "title": "016-autonomous-queue-work-selection: Autonomous Queue + Work Selection",
                "body": "Implements autonomous work selection.",
                "labels": [{"name": "priority:high"}],
                "state": "open",
            }
        ],
    )
    mock_gh.validate_issue_binding.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="fake",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=True,
    )

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
    mock_gh.list_issues.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="fake",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=[{"number": 99, "title": "016-test-change", "labels": [], "state": "open"}],
    )
    mock_gh.validate_issue_binding.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="fake",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=True,
    )

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


def test_reconcile_active_archived_and_missing_changes(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    # 1. ACTIVE ON DISK change
    create_isolated_openspec_change(tmp_path, change_name="001-active-change")
    in_memory_uow.changes.save(
        Change(project_id="mini-me", name="001-active-change", status=ChangeStatus.IN_PROGRESS)
    )

    # 2. ARCHIVED ON DISK change
    archive_dir = tmp_path / "openspec" / "changes" / "archive" / "002-archived-change"
    archive_dir.mkdir(parents=True, exist_ok=True)
    in_memory_uow.changes.save(
        Change(project_id="mini-me", name="002-archived-change", status=ChangeStatus.IN_PROGRESS)
    )
    in_memory_uow.work_queue.save(
        WorkQueueItem(project_id="mini-me", change_name="002-archived-change")
    )

    # 3. MISSING FROM DISK change
    in_memory_uow.changes.save(
        Change(project_id="mini-me", name="003-missing-change", status=ChangeStatus.DISCOVERED)
    )
    in_memory_uow.work_queue.save(
        WorkQueueItem(project_id="mini-me", change_name="003-missing-change")
    )

    discovery_service = WorkDiscoveryService(
        uow=in_memory_uow,
        project_root=tmp_path,
    )

    items = discovery_service.discover_work("mini-me")

    # Queue should contain ONLY the active change item
    assert len(items) == 1
    assert items[0].change_name == "001-active-change"

    # Archived change in DB should be marked DONE
    archived_change = in_memory_uow.changes.get_by_name("mini-me", "002-archived-change")
    assert archived_change is not None
    assert archived_change.status == ChangeStatus.DONE

    # Archived queue item removed
    assert in_memory_uow.work_queue.get_by_project_and_change("mini-me", "002-archived-change") is None

    # Missing change in DB retains its historical status (NOT DONE)
    missing_change = in_memory_uow.changes.get_by_name("mini-me", "003-missing-change")
    assert missing_change is not None
    assert missing_change.status == ChangeStatus.DISCOVERED

    # Missing queue item removed from active work queue
    assert in_memory_uow.work_queue.get_by_project_and_change("mini-me", "003-missing-change") is None


def test_stale_queue_cleanup_multi_project_isolation(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    project1 = Project(
        project_id="mini-me", display_name="mini me", repository="repo1", base_branch="main"
    )
    project2 = Project(
        project_id="other-project", display_name="other", repository="repo2", base_branch="main"
    )
    in_memory_uow.projects.save(project1)
    in_memory_uow.projects.save(project2)

    # Missing queue items for both projects
    in_memory_uow.work_queue.save(
        WorkQueueItem(project_id="mini-me", change_name="001-stale-p1")
    )
    in_memory_uow.work_queue.save(
        WorkQueueItem(project_id="other-project", change_name="001-stale-p2")
    )

    discovery_service = WorkDiscoveryService(uow=in_memory_uow, project_root=tmp_path)

    # Run discovery only for project1 ("mini-me")
    items_p1 = discovery_service.discover_work("mini-me")
    assert len(items_p1) == 0

    # project1 stale queue item was removed
    assert in_memory_uow.work_queue.get_by_project_and_change("mini-me", "001-stale-p1") is None

    # project2 stale queue item remains untouched
    assert (
        in_memory_uow.work_queue.get_by_project_and_change("other-project", "001-stale-p2")
        is not None
    )
