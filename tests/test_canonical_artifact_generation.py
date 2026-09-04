"""Unit and integration tests for 021.4 Canonical Artifact Generation."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import WorkItemPriority, WorkItemStatus
from minime.domain.models import BacklogItem, Project
from minime.services.intake_service import IntakeService
from minime.services.openspec_generator import OpenSpecGenerator


def test_openspec_generator_creates_valid_structure(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    generator = OpenSpecGenerator(project_root=repo_dir)

    item = BacklogItem(
        project_id="test-proj",
        item_key="022-rate-limiting",
        title="API Rate Limiting",
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.PREPARING,
        description="Implement token bucket rate limiter on all API routes.",
        acceptance_criteria=[
            "Returns HTTP 429 when quota exceeded",
            "Rate limit resets every 60 seconds",
        ],
    )

    generated = generator.generate_from_backlog_item(item, project_name="test-proj")
    spec_dir = generator.write_to_disk(generated, "openspec")

    assert generated.change_name == "022-rate-limiting"
    assert (spec_dir / "proposal.md").exists()
    assert (spec_dir / "design.md").exists()
    assert (spec_dir / "tasks.md").exists()
    assert (spec_dir / "specs" / "api-rate-limiting" / "spec.md").exists()

    proposal_content = (spec_dir / "proposal.md").read_text()
    assert "API Rate Limiting" in proposal_content
    assert "Returns HTTP 429 when quota exceeded" in proposal_content


def test_prepare_work_item_idempotency(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "app-repo"
    repo_dir.mkdir()

    project = Project(
        project_id="app-proj",
        display_name="App Project",
        repository="test-owner/app-repo",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    item = BacklogItem(
        project_id="app-proj",
        item_key="023-caching",
        title="Response Caching",
        priority=WorkItemPriority.NORMAL,
        status=WorkItemStatus.BACKLOG,
        description="Add in-memory caching for read endpoints.",
        acceptance_criteria=["Cached responses return header X-Cache: HIT"],
    )
    in_memory_uow.backlog_items.save(item)

    from tests.conftest import ReadinessGitHubStub

    service = IntakeService(
        in_memory_uow, project_root=repo_dir, github_adapter=ReadinessGitHubStub()
    )

    # First prepare run
    res1 = service.prepare_work_item(
        "app-proj", "023-caching", operator_email="operator@example.com"
    )
    assert res1.openspec_change_name == "023-caching"
    assert res1.github_issue_number is not None
    assert res1.readiness_state.value == "READY"

    # Second prepare run (must be idempotent, not duplicate issues)
    res2 = service.prepare_work_item(
        "app-proj", "023-caching", operator_email="operator@example.com"
    )
    assert res2.github_issue_number == res1.github_issue_number
    assert res2.openspec_change_name == res1.openspec_change_name
    assert res2.readiness_state.value == "READY"
