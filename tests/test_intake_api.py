"""Integration tests for 021 Work Intake & Onboarding REST API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tests.conftest import InMemoryPersistenceUnitOfWork, ReadinessGitHubStub

from minime.api.app import app, get_github_adapter, get_uow
from minime.domain.models import Project


def test_api_onboard_project(in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path) -> None:
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_github_adapter] = lambda: ReadinessGitHubStub()
    client = TestClient(app)

    repo_dir = tmp_path / "api-repo"
    repo_dir.mkdir()
    (repo_dir / "docs").mkdir()
    (repo_dir / "docs" / "ROADMAP.md").write_text("# Roadmap\n- 030-feature: Feature A\n")

    resp = client.post(
        "/api/v1/projects/onboard",
        json={
            "project_id": "api-project",
            "display_name": "API Project",
            "repository": "test-owner/api-repo",
            "base_branch": "main",
            "roadmap_path": "docs/ROADMAP.md",
            "backlog_path": "docs/ROADMAP.md",
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
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_github_adapter] = lambda: ReadinessGitHubStub()
    client = TestClient(app)

    project = Project(
        project_id="api-project",
        display_name="API Project",
        repository="test-owner/api-repo",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

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
