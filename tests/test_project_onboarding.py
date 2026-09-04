"""Unit and integration tests for 021.1 Project Onboarding."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import ProjectOnboardingStatus
from minime.domain.models import Project, ProjectOnboardingInput
from minime.services.project_onboarding_service import ProjectOnboardingService


def test_onboard_new_project_success(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    # Setup temporary project repository
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    (repo_dir / "docs").mkdir()
    (repo_dir / "docs" / "ROADMAP.md").write_text(
        "# Test Roadmap\n- 001-initial-work (BACKLOG): First task\n"
    )
    (repo_dir / "openspec").mkdir()
    (repo_dir / "README.md").write_text("# Test Repo\nA test repository for onboarding.\n")

    from tests.conftest import ReadinessGitHubStub

    service = ProjectOnboardingService(
        in_memory_uow,
        project_root=repo_dir,
        github_adapter=ReadinessGitHubStub(),
    )

    input_data = ProjectOnboardingInput(
        project_id="test-project",
        display_name="Test Project",
        repository="test-owner/test-repo",
        base_branch="main",
        openspec_path="openspec",
        roadmap_path="docs/ROADMAP.md",
        backlog_path="docs/ROADMAP.md",
    )

    result = service.onboard_project(input_data, operator_email="operator@example.com")

    assert result.project.project_id == "test-project"
    assert result.project.display_name == "Test Project"
    assert result.project.repository == "test-owner/test-repo"
    assert result.project.onboarding_status == ProjectOnboardingStatus.READY_FOR_WORK
    assert result.discovered_items_count >= 1

    # Verify saved in persistence
    saved = in_memory_uow.projects.get_by_id("test-project")
    assert saved is not None
    assert saved.onboarding_status == ProjectOnboardingStatus.READY_FOR_WORK


def test_onboard_project_conflict_detection(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    from tests.conftest import ReadinessGitHubStub

    existing = Project(
        project_id="existing-project",
        display_name="Existing",
        repository="test-owner/existing-repo",
        base_branch="main",
    )
    in_memory_uow.projects.save(existing)

    service = ProjectOnboardingService(
        in_memory_uow,
        project_root=tmp_path,
        github_adapter=ReadinessGitHubStub(),
    )

    # Attempt duplicate project_id
    with pytest.raises(ValueError, match="already registered"):
        service.onboard_project(
            ProjectOnboardingInput(
                project_id="existing-project",
                display_name="Duplicate",
                repository="test-owner/new-repo",
            )
        )

    # Attempt duplicate repository binding
    with pytest.raises(ValueError, match="already bound"):
        service.onboard_project(
            ProjectOnboardingInput(
                project_id="new-project",
                display_name="New Project",
                repository="test-owner/existing-repo",
            )
        )


def test_onboard_project_invalid_repository_fails_closed(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    from tests.conftest import ReadinessGitHubStub

    service = ProjectOnboardingService(
        in_memory_uow,
        project_root=tmp_path,
        github_adapter=ReadinessGitHubStub(),
    )

    with pytest.raises(ValueError, match="repository identifier is required"):
        service.onboard_project(
            ProjectOnboardingInput(
                project_id="bad-project",
                display_name="Bad",
                repository="",
            )
        )
