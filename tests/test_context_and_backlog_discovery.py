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


def test_duplicate_roadmap_headings_same_slug(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Phase D: ROADMAP containing duplicate section headers produces single COMPLETED projection."""
    repo_dir = tmp_path / "app-repo"
    repo_dir.mkdir()
    (repo_dir / "docs").mkdir()
    roadmap_file = repo_dir / "docs" / "ROADMAP.md"
    roadmap_file.write_text(
        "# Roadmap\n\n"
        "### 019 — Server Runtime & Production Deployment (`019-server-runtime-deployment`)\n\n"
        "### 019 — Server Runtime & Production Deployment (`019-server-runtime-deployment`) — DELIVERED\n"
    )

    project = Project(
        project_id="app-project",
        display_name="App Project",
        repository="test-owner/app-repo",
        base_branch="main",
        roadmap_path="docs/ROADMAP.md",
    )
    in_memory_uow.projects.save(project)

    service = ContextDiscoveryService(in_memory_uow, project_root=repo_dir)
    report, items = service.discover_context_pure("app-project")

    # Must produce exactly ONE BacklogItem
    assert len(items) == 1
    assert report.discovered_items_count == 1
    item = items[0]
    assert item.item_key == "019-server-runtime-deployment"
    assert item.status == WorkItemStatus.COMPLETED


def test_status_precedence_order_independence(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Phase H 2 & 3: Weaker first observation vs stronger second, and reverse order produce identical COMPLETED result."""
    repo_dir1 = tmp_path / "app-repo1"
    repo_dir1.mkdir()
    (repo_dir1 / "docs").mkdir()
    (repo_dir1 / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n\n"
        "### 019 — Server Runtime (`019-server-runtime-deployment`)\n\n"
        "### 019 — Server Runtime (`019-server-runtime-deployment`) — DELIVERED\n"
    )

    repo_dir2 = tmp_path / "app-repo2"
    repo_dir2.mkdir()
    (repo_dir2 / "docs").mkdir()
    (repo_dir2 / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n\n"
        "### 019 — Server Runtime (`019-server-runtime-deployment`) — DELIVERED\n\n"
        "### 019 — Server Runtime (`019-server-runtime-deployment`)\n"
    )

    project1 = Project(
        project_id="p1",
        display_name="P1",
        repository="owner/r1",
        roadmap_path="docs/ROADMAP.md",
    )
    project2 = Project(
        project_id="p2",
        display_name="P2",
        repository="owner/r2",
        roadmap_path="docs/ROADMAP.md",
    )
    in_memory_uow.projects.save(project1)
    in_memory_uow.projects.save(project2)

    service1 = ContextDiscoveryService(in_memory_uow, project_root=repo_dir1)
    _, items1 = service1.discover_context_pure("p1")

    service2 = ContextDiscoveryService(in_memory_uow, project_root=repo_dir2)
    _, items2 = service2.discover_context_pure("p2")

    assert len(items1) == 1
    assert items1[0].status == WorkItemStatus.COMPLETED

    assert len(items2) == 1
    assert items2[0].status == WorkItemStatus.COMPLETED


def test_discover_context_persistence_idempotency(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Phase H 5 & 6: discover_context persists cleanly and repeated calls remain idempotent."""
    repo_dir = tmp_path / "app-repo"
    repo_dir.mkdir()
    (repo_dir / "docs").mkdir()
    (repo_dir / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n\n"
        "### 019 — Server Runtime (`019-server-runtime-deployment`)\n\n"
        "### 019 — Server Runtime (`019-server-runtime-deployment`) — DELIVERED\n"
        "### 020 — Next Feature (`020-next-feature`)\n"
    )

    project = Project(
        project_id="app-project",
        display_name="App Project",
        repository="test-owner/app-repo",
        roadmap_path="docs/ROADMAP.md",
    )
    in_memory_uow.projects.save(project)

    service = ContextDiscoveryService(in_memory_uow, project_root=repo_dir)

    # First discovery
    service.discover_context("app-project")
    items_after_1 = in_memory_uow.backlog_items.list_by_project("app-project")
    assert len(items_after_1) == 2

    # Second discovery (idempotent repeat)
    service.discover_context("app-project")
    items_after_2 = in_memory_uow.backlog_items.list_by_project("app-project")
    assert len(items_after_2) == 2

    item_map = {i.item_key: i for i in items_after_2}
    assert item_map["019-server-runtime-deployment"].status == WorkItemStatus.COMPLETED
    assert item_map["020-next-feature"].status == WorkItemStatus.BACKLOG


def test_existing_persisted_completed_item_not_resurrected(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Phase H 7: Existing persisted COMPLETED item is preserved even if source contains BACKLOG state."""
    repo_dir = tmp_path / "app-repo"
    repo_dir.mkdir()
    (repo_dir / "docs").mkdir()
    (repo_dir / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n\n### 019 — Server Runtime (`019-server-runtime-deployment`)\n"
    )

    project = Project(
        project_id="app-project",
        display_name="App Project",
        repository="test-owner/app-repo",
        roadmap_path="docs/ROADMAP.md",
    )
    in_memory_uow.projects.save(project)

    # Pre-existing completed item in DB
    existing_item = BacklogItem(
        project_id="app-project",
        item_key="019-server-runtime-deployment",
        title="019 Server Runtime",
        status=WorkItemStatus.COMPLETED,
        source=WorkItemSource.ROADMAP,
    )
    in_memory_uow.backlog_items.save(existing_item)

    service = ContextDiscoveryService(in_memory_uow, project_root=repo_dir)
    service.discover_context("app-project")

    persisted = in_memory_uow.backlog_items.get_by_project_and_key(
        "app-project", "019-server-runtime-deployment"
    )
    assert persisted is not None
    assert persisted.status == WorkItemStatus.COMPLETED


def test_cross_source_duplication_deduplicated(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Phase E: Key appearing in ROADMAP and BACKLOG produces single deterministic projection."""
    repo_dir = tmp_path / "app-repo"
    repo_dir.mkdir()
    (repo_dir / "docs").mkdir()
    (repo_dir / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n\n### 019 — Server Runtime (`019-server-runtime-deployment`)\n"
    )
    (repo_dir / "docs" / "BACKLOG.md").write_text(
        "# Backlog\n\n- [x] 019-server-runtime-deployment\n"
    )

    project = Project(
        project_id="app-project",
        display_name="App Project",
        repository="test-owner/app-repo",
        roadmap_path="docs/ROADMAP.md",
        backlog_path="docs/BACKLOG.md",
    )
    in_memory_uow.projects.save(project)

    service = ContextDiscoveryService(in_memory_uow, project_root=repo_dir)
    _, items = service.discover_context_pure("app-project")

    assert len(items) == 1
    assert items[0].item_key == "019-server-runtime-deployment"
    assert items[0].status == WorkItemStatus.COMPLETED
