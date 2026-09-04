"""Unit and integration tests for 021.2 Context & Backlog Discovery."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import WorkItemPriority, WorkItemSource, WorkItemStatus
from minime.domain.models import BacklogItem, Project
from minime.services.context_discovery_service import ContextDiscoveryService


def test_discover_context_facts_inferences_and_gaps(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "app-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text(
        "# App Repo\nPrimary web application with React and FastAPI.\n"
    )
    (repo_dir / "docs").mkdir()
    (repo_dir / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n- 010-auth: Authentication flow (READY)\n"
    )

    project = Project(
        project_id="app-project",
        display_name="App Project",
        repository="test-owner/app-repo",
        base_branch="main",
        openspec_path="openspec",
        roadmap_path="docs/ROADMAP.md",
    )
    in_memory_uow.projects.save(project)

    service = ContextDiscoveryService(in_memory_uow, project_root=repo_dir)
    report = service.discover_context("app-project")

    assert len(report.discovered_facts) >= 2
    assert any(f.source_file == "README.md" for f in report.discovered_facts)
    assert any("ROADMAP.md" in f.source_file for f in report.discovered_facts)
    assert len(report.inferred_structure) >= 1


def test_discover_backlog_non_destructive_reconciliation(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "app-repo"
    repo_dir.mkdir()
    (repo_dir / "docs").mkdir()
    roadmap_file = repo_dir / "docs" / "ROADMAP.md"
    roadmap_file.write_text(
        "# Roadmap\n"
        "- 010-auth: Authentication flow (BACKLOG)\n"
        "- 011-payments: Payment gateway integration (BACKLOG)\n"
    )

    project = Project(
        project_id="app-project",
        display_name="App Project",
        repository="test-owner/app-repo",
        base_branch="main",
        roadmap_path="docs/ROADMAP.md",
        backlog_path="docs/ROADMAP.md",
    )
    in_memory_uow.projects.save(project)

    # Pre-existing item with operator priority override
    existing_item = BacklogItem(
        project_id="app-project",
        item_key="010-auth",
        title="Custom Authentication Title",
        priority=WorkItemPriority.CRITICAL,
        status=WorkItemStatus.READY,
        source=WorkItemSource.ROADMAP,
        description="Manual description by operator",
    )
    in_memory_uow.backlog_items.save(existing_item)

    service = ContextDiscoveryService(in_memory_uow, project_root=repo_dir)
    items = service.discover_and_sync_backlog("app-project", operator_email="operator@example.com")

    # Must find both 010-auth and 011-payments
    assert len(items) == 2
    item_map = {i.item_key: i for i in items}

    # 010-auth must preserve operator priority override and manual description
    auth_item = item_map["010-auth"]
    assert auth_item.priority == WorkItemPriority.CRITICAL
    assert auth_item.title == "Custom Authentication Title"
    assert auth_item.description == "Manual description by operator"

    # 011-payments must be newly discovered
    payments_item = item_map["011-payments"]
    assert payments_item.title == "Payment gateway integration"
    assert payments_item.status == WorkItemStatus.BACKLOG
