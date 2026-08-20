"""Tests for project registration, update, repository binding, and complementary roles."""

import pytest

from minime.domain.enums import EventType, ProjectStatus
from minime.services.project_service import (
    ProjectService,
    normalize_repository_identity,
    validate_complementary_roles,
)


def test_normalize_repository_identity():
    assert normalize_repository_identity("owner/repo") == "owner/repo"
    assert normalize_repository_identity("https://github.com/owner/repo.git") == "owner/repo"
    assert normalize_repository_identity("https://github.com/owner/repo") == "owner/repo"
    assert normalize_repository_identity("git@github.com:owner/repo.git") == "owner/repo"
    assert normalize_repository_identity("ssh://git@github.com/owner/repo.git") == "owner/repo"
    assert normalize_repository_identity("/var/repos/local-repo") == "/var/repos/local-repo"

    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_repository_identity("")


def test_complementary_roles_validation():
    # Valid complementary roles
    validate_complementary_roles("codex", "antigravity")
    validate_complementary_roles("antigravity", "codex")
    validate_complementary_roles("Codex", "Antigravity")

    # Invalid non-complementary primary roles
    with pytest.raises(ValueError, match="cannot be both implementer and reviewer"):
        validate_complementary_roles("codex", "codex")

    with pytest.raises(ValueError, match="cannot be both implementer and reviewer"):
        validate_complementary_roles("antigravity", "antigravity")


def test_project_registration_and_immutable_id(in_memory_uow):
    service = ProjectService(in_memory_uow)

    project = service.register_project(
        project_id="proj-alpha",
        display_name="Project Alpha",
        repository="git@github.com:org/proj-alpha.git",
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )

    assert project.project_id == "proj-alpha"
    assert project.display_name == "Project Alpha"
    assert project.repository == "org/proj-alpha"
    assert project.status == ProjectStatus.ACTIVE

    # Check event emission
    events = in_memory_uow.events.list_events(project_id="proj-alpha")
    assert len(events) == 1
    assert events[0].event_type == EventType.PROJECT_REGISTERED

    # Update display name
    updated = service.update_project(
        project_id="proj-alpha",
        display_name="Project Alpha Renamed",
    )
    assert updated.project_id == "proj-alpha"  # ID is unchanged
    assert updated.display_name == "Project Alpha Renamed"

    # Re-registering the same project_id must fail
    with pytest.raises(ValueError, match="already registered"):
        service.register_project(
            project_id="proj-alpha",
            display_name="Duplicate",
            repository="org/proj-alpha",
        )


def test_project_registration_invalid_policy(in_memory_uow):
    service = ProjectService(in_memory_uow)

    # Missing required repository
    with pytest.raises(ValueError, match="repository is required"):
        service.register_project(
            project_id="proj-err",
            display_name="No Repo",
            repository="",
        )

    # Same primary agent for both roles
    with pytest.raises(ValueError, match="cannot be both implementer and reviewer"):
        service.register_project(
            project_id="proj-err2",
            display_name="Self Review",
            repository="org/repo",
            implementer="codex",
            reviewer="codex",
        )
