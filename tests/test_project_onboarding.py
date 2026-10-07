"""Unit and integration tests for 021.1 Project Onboarding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import EventType, ProjectOnboardingStatus
from minime.domain.models import (
    Project,
    ProjectManagedRepositoryBinding,
    ProjectOnboardingInput,
)
from minime.services.project_onboarding_service import ProjectOnboardingService


@pytest.mark.parametrize(
    ("raw_repo", "norm_repo", "expected"),
    [
        (
            "silverberdi/mini-me",
            "silverberdi/mini-me",
            "https://github.com/silverberdi/mini-me.git",
        ),
        (
            "https://github.com/silverberdi/mini-me.git",
            "silverberdi/mini-me",
            "https://github.com/silverberdi/mini-me.git",
        ),
        (
            "git@github.com:silverberdi/mini-me.git",
            "silverberdi/mini-me",
            "git@github.com:silverberdi/mini-me.git",
        ),
        ("/tmp/local-repository", "owner/repo", "/tmp/local-repository"),
        ("file:///tmp/local-repository", "owner/repo", "file:///tmp/local-repository"),
    ],
)
def test_resolve_remote_source_preserves_explicit_sources_and_canonicalizes_github_identity(
    in_memory_uow: InMemoryPersistenceUnitOfWork,
    tmp_path: Path,
    raw_repo: str,
    norm_repo: str,
    expected: str,
) -> None:
    service = ProjectOnboardingService(in_memory_uow, project_root=tmp_path)

    assert service._resolve_remote_source(raw_repo, norm_repo) == expected


def test_registered_canonical_repository_identity_clones_from_github_com(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path, monkeypatch
) -> None:
    """A durable owner/repo identity must never become a Git hostname."""
    import subprocess

    from tests.conftest import ReadinessGitHubStub

    runtime_root = tmp_path / "runtime"
    (runtime_root / "openspec").mkdir(parents=True)
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_root))
    in_memory_uow.projects.save(
        Project(
            project_id="mini-me",
            display_name="mini me",
            repository="silverberdi/mini-me",
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
            reviewer="antigravity",
        )
    )

    clone_commands: list[list[str]] = []

    def failed_clone(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["git", "clone"]:
            clone_commands.append(command)
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="offline test")
        raise AssertionError(f"Unexpected subprocess command: {command}")

    monkeypatch.setattr(subprocess, "run", failed_clone)
    service = ProjectOnboardingService(
        in_memory_uow,
        project_root=runtime_root,
        github_adapter=ReadinessGitHubStub(),
        trusted_managed_root=trusted_root,
    )

    with pytest.raises(ValueError, match="https://github.com/silverberdi/mini-me.git"):
        service.onboard_project(
            ProjectOnboardingInput(
                project_id="mini-me",
                display_name="mini me",
                repository="silverberdi/mini-me",
                base_branch="main",
                openspec_path="openspec",
                implementer="codex",
                reviewer="antigravity",
            )
        )

    assert clone_commands == [
        [
            "git",
            "clone",
            "--branch",
            "main",
            "https://github.com/silverberdi/mini-me.git",
            str(trusted_root / "mini-me"),
        ],
        [
            "git",
            "clone",
            "https://github.com/silverberdi/mini-me.git",
            str(trusted_root / "mini-me"),
        ],
    ]
    assert in_memory_uow.project_managed_repository_bindings.get_by_project_id("mini-me") is None
    assert in_memory_uow.jobs.list_active_jobs() == []
    assert in_memory_uow.orchestration_runs.list_runs(is_active=True) == []


def test_registered_canonical_identity_completes_onboarding_with_github_transport(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path, monkeypatch
) -> None:
    """A GitHub transport must verify against the durable owner/repo identity."""
    import subprocess

    from tests.conftest import ReadinessGitHubStub

    runtime_root = tmp_path / "runtime"
    (runtime_root / "openspec").mkdir(parents=True)
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    managed_root = trusted_root / "mini-me"
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_root))
    in_memory_uow.projects.save(
        Project(
            project_id="mini-me",
            display_name="mini me",
            repository="silverberdi/mini-me",
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
            reviewer="antigravity",
        )
    )

    clone_commands: list[list[str]] = []

    def simulated_git(command: list[str], cwd=None, **kwargs) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["git", "clone"]:
            clone_commands.append(command)
            Path(command[-1], ".git").mkdir(parents=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, stdout="candidate-sha\n", stderr="")
        if command == ["git", "rev-parse", "origin/main"]:
            return subprocess.CompletedProcess(command, 0, stdout="candidate-sha\n", stderr="")
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{managed_root}\n", stderr="")
        if command == ["git", "remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="https://github.com/silverberdi/mini-me.git\n",
                stderr="",
            )
        raise AssertionError(f"Unexpected subprocess command: {command}")

    monkeypatch.setattr(subprocess, "run", simulated_git)
    result = ProjectOnboardingService(
        in_memory_uow,
        project_root=runtime_root,
        github_adapter=ReadinessGitHubStub(),
        trusted_managed_root=trusted_root,
    ).onboard_project(
        ProjectOnboardingInput(
            project_id="mini-me",
            display_name="mini me",
            repository="silverberdi/mini-me",
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
            reviewer="antigravity",
        )
    )

    binding = in_memory_uow.project_managed_repository_bindings.get_by_project_id("mini-me")
    assert result.status == ProjectOnboardingStatus.READY_FOR_WORK
    assert clone_commands[0][4] == "https://github.com/silverberdi/mini-me.git"
    assert binding is not None
    assert binding.canonical_repository_identity == "silverberdi/mini-me"
    marker = managed_root / ".minime-managed-project.json"
    assert json.loads(marker.read_text())["canonical_repository_identity"] == "silverberdi/mini-me"
    assert in_memory_uow.jobs.list_active_jobs() == []
    assert in_memory_uow.orchestration_runs.list_runs(is_active=True) == []


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
    import subprocess

    (repo_dir / "README.md").write_text("# Test Repo\nA test repository for onboarding.\n")
    subprocess.run(["git", "init"], cwd=repo_dir, check=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_dir, check=True)

    trusted_root = tmp_path / "trusted_managed_root"
    trusted_root.mkdir()

    from tests.conftest import ReadinessGitHubStub

    service = ProjectOnboardingService(
        in_memory_uow,
        project_root=repo_dir,
        github_adapter=ReadinessGitHubStub(),
        trusted_managed_root=trusted_root,
    )

    input_data = ProjectOnboardingInput(
        project_id="test-project",
        display_name="Test Project",
        repository=str(repo_dir),
        base_branch="main",
        openspec_path="openspec",
        roadmap_path="docs/ROADMAP.md",
        backlog_path="docs/ROADMAP.md",
    )

    result = service.onboard_project(input_data, operator_email="operator@example.com")

    assert result.project.project_id == "test-project"
    assert result.project.display_name == "Test Project"
    assert result.project.repository == str(repo_dir)
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

    # An existing project id may only resume bootstrap when its immutable
    # identity matches exactly.
    with pytest.raises(ValueError, match="immutable identity mismatch"):
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


def test_existing_matching_project_resumes_managed_workspace_bootstrap_idempotently(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path, monkeypatch
) -> None:
    """A matching registered project may establish its missing Stage C workspace once."""
    import json
    import subprocess

    from tests.conftest import ReadinessGitHubStub

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "openspec").mkdir()
    (source_repo / "README.md").write_text("# Source\n")
    subprocess.run(["git", "init"], cwd=source_repo, check=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=source_repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=source_repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source_repo, check=True)
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=source_repo, check=True)

    runtime_root = tmp_path / "runtime"
    (runtime_root / "openspec").mkdir(parents=True)
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_root))

    project = Project(
        project_id="existing-project",
        display_name="Existing Project",
        repository=str(source_repo),
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)
    service = ProjectOnboardingService(
        in_memory_uow,
        project_root=runtime_root,
        github_adapter=ReadinessGitHubStub(),
        trusted_managed_root=trusted_root,
    )
    request = ProjectOnboardingInput(
        project_id="existing-project",
        display_name="Attempted Rename",
        repository=str(source_repo),
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )

    first = service.onboard_project(request)
    binding = in_memory_uow.project_managed_repository_bindings.get_by_project_id(
        "existing-project"
    )
    assert first.project.display_name == "Existing Project"
    assert binding is not None
    assert binding.is_valid is True
    assert Path(binding.managed_repository_root).is_dir()
    assert Path(binding.worktree_parent_dir).is_dir()
    marker = Path(binding.managed_repository_root) / ".minime-managed-project.json"
    assert json.loads(marker.read_text()) == {
        "project_id": "existing-project",
        "canonical_repository_identity": str(source_repo),
    }
    assert subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=binding.managed_repository_root, check=True, capture_output=True, text=True
    ).stdout.strip() == subprocess.run(
        ["git", "rev-parse", "origin/main"], cwd=binding.managed_repository_root, check=True, capture_output=True, text=True
    ).stdout.strip()

    second = service.onboard_project(request)
    repeated_binding = in_memory_uow.project_managed_repository_bindings.get_by_project_id(
        "existing-project"
    )
    assert second.project.project_id == "existing-project"
    assert repeated_binding is not None
    assert repeated_binding.binding_id == binding.binding_id
    events = in_memory_uow.events.list_events(project_id="existing-project")
    onboarding_event = next(
        event for event in events if event.event_type == EventType.PROJECT_ONBOARDED
    )
    assert onboarding_event.payload["display_name"] == "Existing Project"
    assert in_memory_uow.jobs.list_active_jobs() == []
    assert in_memory_uow.orchestration_runs.list_runs(is_active=True) == []


def test_existing_project_refuses_invalid_managed_binding_before_bootstrap(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path, monkeypatch
) -> None:
    from tests.conftest import ReadinessGitHubStub

    runtime_root = tmp_path / "runtime"
    (runtime_root / "openspec").mkdir(parents=True)
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    managed_root = trusted_root / "existing-project"
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_root))

    in_memory_uow.projects.save(
        Project(
            project_id="existing-project",
            display_name="Existing Project",
            repository="owner/repo",
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
            reviewer="antigravity",
        )
    )
    in_memory_uow.project_managed_repository_bindings.save(
        ProjectManagedRepositoryBinding(
            project_id="existing-project",
            canonical_repository_identity="owner/repo",
            managed_repository_root=str(managed_root),
            worktree_parent_dir=str(managed_root / ".minime" / "worktrees"),
            is_valid=False,
            mismatch_reasons=["prior identity mismatch"],
        )
    )

    service = ProjectOnboardingService(
        in_memory_uow,
        project_root=runtime_root,
        github_adapter=ReadinessGitHubStub(),
        trusted_managed_root=trusted_root,
    )
    with pytest.raises(ValueError, match="Existing managed repository binding mismatch"):
        service.onboard_project(
            ProjectOnboardingInput(
                project_id="existing-project",
                display_name="Existing Project",
                repository="owner/repo",
                base_branch="main",
                openspec_path="openspec",
                implementer="codex",
                reviewer="antigravity",
            )
        )

    assert not managed_root.exists()
    assert in_memory_uow.jobs.list_active_jobs() == []
    assert in_memory_uow.orchestration_runs.list_runs(is_active=True) == []


@pytest.mark.parametrize(
    ("field_name", "field_value", "mismatch"),
    [
        ("default_base_branch", "release", "default base branch differs"),
        ("ownership_marker_filename", ".other-marker.json", "ownership marker filename differs"),
    ],
)
def test_existing_project_refuses_binding_configuration_mismatch_before_bootstrap(
    in_memory_uow: InMemoryPersistenceUnitOfWork,
    tmp_path: Path,
    monkeypatch,
    field_name: str,
    field_value: str,
    mismatch: str,
) -> None:
    """Resumption may not rewrite immutable binding configuration."""
    from tests.conftest import ReadinessGitHubStub

    runtime_root = tmp_path / "runtime"
    (runtime_root / "openspec").mkdir(parents=True)
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    managed_root = trusted_root / "existing-project"
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_root))

    in_memory_uow.projects.save(
        Project(
            project_id="existing-project",
            display_name="Existing Project",
            repository="owner/repo",
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
            reviewer="antigravity",
        )
    )
    binding_values = {
        "project_id": "existing-project",
        "canonical_repository_identity": "owner/repo",
        "managed_repository_root": str(managed_root),
        "worktree_parent_dir": str(managed_root / ".minime" / "worktrees"),
        field_name: field_value,
    }
    in_memory_uow.project_managed_repository_bindings.save(
        ProjectManagedRepositoryBinding(**binding_values)
    )

    service = ProjectOnboardingService(
        in_memory_uow,
        project_root=runtime_root,
        github_adapter=ReadinessGitHubStub(),
        trusted_managed_root=trusted_root,
    )
    with pytest.raises(ValueError, match=mismatch):
        service.onboard_project(
            ProjectOnboardingInput(
                project_id="existing-project",
                display_name="Existing Project",
                repository="owner/repo",
                base_branch="main",
                openspec_path="openspec",
                implementer="codex",
                reviewer="antigravity",
            )
        )

    assert not managed_root.exists()
    assert in_memory_uow.jobs.list_active_jobs() == []
    assert in_memory_uow.orchestration_runs.list_runs(is_active=True) == []


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
