"""Integration tests for 021 Work Intake & Onboarding REST API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tests.conftest import (
    InMemoryPersistenceUnitOfWork,
    ReadinessGitHubStub,
    attach_local_bare_origin,
    setup_managed_repository_fixture,
)

from minime.api.app import (
    app,
    get_github_adapter,
    get_intake_service,
    get_onboarding_service,
    get_uow,
)
from minime.domain.models import Project
from minime.services.intake_service import IntakeService
from minime.services.project_onboarding_service import ProjectOnboardingService


def test_api_onboard_project(in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "openspec").mkdir(parents=True, exist_ok=True)
    (runtime_root / "docs").mkdir(parents=True, exist_ok=True)
    (runtime_root / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n- 030-feature: Feature A\n", encoding="utf-8"
    )

    trusted_root = tmp_path / "managed"
    trusted_root.mkdir(parents=True, exist_ok=True)

    import subprocess

    remote_bare = tmp_path / "remote_api_repo.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote_bare)], check=True, capture_output=True
    )

    seed_dir = tmp_path / "seed"
    subprocess.run(
        ["git", "clone", str(remote_bare), str(seed_dir)], check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test Dev"], cwd=seed_dir, check=True)
    subprocess.run(["git", "config", "user.email", "dev@test.local"], cwd=seed_dir, check=True)
    (seed_dir / "README.md").write_text(
        "# API Repo\nA test repository for onboarding.\n", encoding="utf-8"
    )
    (seed_dir / "openspec").mkdir(exist_ok=True)
    (seed_dir / "docs").mkdir(exist_ok=True)
    (seed_dir / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n- 030-feature: Feature A\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=seed_dir, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=seed_dir, check=True, capture_output=True
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=seed_dir, check=True, capture_output=True)

    github_stub = ReadinessGitHubStub()
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_github_adapter] = lambda: github_stub
    app.dependency_overrides[get_onboarding_service] = lambda: ProjectOnboardingService(
        in_memory_uow,
        project_root=runtime_root,
        github_adapter=github_stub,
        trusted_managed_root=trusted_root,
    )
    client = TestClient(app)

    managed_target = trusted_root / "api-project"
    worktrees_target = trusted_root / "worktrees" / "api-project"

    resp = client.post(
        "/api/v1/projects/onboard",
        json={
            "project_id": "api-project",
            "display_name": "API Project",
            "repository": str(remote_bare),
            "base_branch": "main",
            "roadmap_path": "docs/ROADMAP.md",
            "backlog_path": "docs/ROADMAP.md",
            "managed_repository_root": str(managed_target),
            "worktree_parent_dir": str(worktrees_target),
        },
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["project"]["project_id"] == "api-project"
    assert data["project"]["onboarding_status"] == "READY_FOR_WORK"
    assert data["discovered_items_count"] >= 1


def test_api_backlog_crud_and_lifecycle(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "api-repo"
    setup_managed_repository_fixture(in_memory_uow, "api-project", repo_dir, tmp_path / "worktrees")
    attach_local_bare_origin(repo_dir, uow=in_memory_uow, project_id="api-project")

    github_stub = ReadinessGitHubStub()
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_github_adapter] = lambda: github_stub
    app.dependency_overrides[get_intake_service] = lambda: IntakeService(
        in_memory_uow, project_root=repo_dir, github_adapter=github_stub
    )
    client = TestClient(app)

    project = Project(
        project_id="api-project",
        display_name="API Project",
        repository="test-owner/api-repo",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    from minime.domain.enums import ProviderHealthStatus
    from minime.domain.models import ProviderHealth

    in_memory_uow.provider_health.save(
        ProviderHealth(
            health_id="ph-codex", provider="codex", status=ProviderHealthStatus.AVAILABLE
        )
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(
            health_id="ph-antigravity",
            provider="antigravity",
            status=ProviderHealthStatus.AVAILABLE,
        )
    )

    # 1. Create work item
    create_resp = client.post(
        "/api/v1/projects/api-project/backlog",
        json={
            "title": "API Rate Limiting",
            "priority": "HIGH",
            "description": "Rate limiting implementation.",
            "acceptance_criteria": ["429 returned on limit"],
        },
    )
    assert create_resp.status_code == 201
    item = create_resp.json()
    item_key = item["item_key"]

    # 2. Get backlog
    list_resp = client.get("/api/v1/projects/api-project/backlog")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1

    # 3. Prepare work item
    prep_resp = client.post(f"/api/v1/projects/api-project/backlog/{item_key}/prepare")
    assert prep_resp.status_code == 200
    prep_data = prep_resp.json()
    assert prep_data["readiness_state"] == "READY"

    # 4. Start work item
    start_resp = client.post(f"/api/v1/projects/api-project/backlog/{item_key}/start")
    assert start_resp.status_code == 200
    start_data = start_resp.json()
    assert start_data["is_admitted"] is True
    assert start_data["run_id"] is not None

    # 5. Delete work item
    del_resp = client.delete(f"/api/v1/projects/api-project/backlog/{item_key}")
    assert del_resp.status_code in (200, 204)
