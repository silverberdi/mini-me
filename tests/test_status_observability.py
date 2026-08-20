"""Tests for status observability, FastAPI endpoints, and CLI interface."""

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from minime.api.app import app, get_uow
from minime.cli.main import app as cli_app
from minime.domain.enums import ReadinessState
from minime.domain.models import Change, Project
from minime.services.status_service import StatusService

runner = CliRunner()


def test_status_service(in_memory_uow):
    service = StatusService(in_memory_uow)

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        change_id="c-001",
        project_id="mini-me",
        name="001-foundation",
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    status_data = service.get_system_status()
    assert status_data["projects_count"] == 1
    assert status_data["projects"][0]["project_id"] == "mini-me"
    assert status_data["projects"][0]["changes"][0]["name"] == "001-foundation"
    assert status_data["projects"][0]["changes"][0]["readiness"] == "READY"


def test_fastapi_endpoints(in_memory_uow):
    # Override get_uow dependency with in_memory_uow
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    # Health
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["version"] == "0.1.0"

    # Register project
    payload = {
        "project_id": "test-api-proj",
        "display_name": "API Test Project",
        "repository": "https://github.com/org/api-test.git",
        "base_branch": "main",
        "implementer": "codex",
        "reviewer": "antigravity",
    }
    res = client.post("/projects", json=payload)
    assert res.status_code == 201
    assert res.json()["project_id"] == "test-api-proj"
    assert res.json()["repository"] == "org/api-test"

    # List projects
    res = client.get("/projects")
    assert res.status_code == 200
    assert len(res.json()) >= 1

    # Get project by ID
    res = client.get("/projects/test-api-proj")
    assert res.status_code == 200
    assert res.json()["display_name"] == "API Test Project"

    # Discover changes
    res = client.post("/projects/test-api-proj/discover?project_root=.")
    assert res.status_code == 200

    # Clean up dependency override
    app.dependency_overrides.clear()


def test_cli_help():
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    assert "mini me" in result.stdout
    assert "status" in result.stdout
    assert "project" in result.stdout
    assert "discover" in result.stdout
    assert "readiness" in result.stdout
