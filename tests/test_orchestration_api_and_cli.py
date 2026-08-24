"""Tests for Orchestration FastAPI endpoints and CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from conftest import create_isolated_openspec_change
from minime.api.app import app, get_uow
from minime.cli.main import app as cli_app
from minime.domain.enums import (
    ProjectStatus,
    ProviderHealthStatus,
    ReadinessState,
)
from minime.domain.models import (
    Change,
    Project,
    ProjectBinding,
    ProviderHealth,
)

runner = CliRunner()


@pytest.fixture
def setup_api_env(tmp_path: Path, in_memory_uow):
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# API Test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True
    )

    project_id = "test-project"
    change_name = "008-autonomous-change-orchestration"

    project = Project(
        project_id=project_id,
        display_name="Test Project",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
        status=ProjectStatus.ACTIVE,
        checks=[{"name": "pytest", "command": "pytest"}],
    )
    in_memory_uow.projects.save(project)

    binding = ProjectBinding(
        project_id=project_id,
        openspec_change_name=change_name,
        repository="silverberdi/mini-me",
        github_issue_number=16,
        is_valid=True,
    )
    in_memory_uow.bindings.save(binding)

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE)
    )

    create_isolated_openspec_change(
        tmp_path,
        change_name=change_name,
        proposal_content="# Proposal\n\nAPI tests.\n",
        tasks_content="## 1. Foundation\n- [x] 1.1 Complete schema <!-- id: 1.1 -->\n",
        design_content="# Design\n\nAPI endpoints.\n",
        spec_content="# Spec\n\n## Requirements\nFastAPI and CLI.\n",
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Add OpenSpec change"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True
    )

    in_memory_uow.changes.save(
        Change(
            project_id=project_id,
            name=change_name,
            schema_name="feature",
            last_readiness_status=ReadinessState.READY,
        )
    )

    return {"project_id": project_id, "change_name": change_name, "project_root": str(tmp_path)}


def test_api_admit_and_status(setup_api_env, in_memory_uow):
    env = setup_api_env
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    # 1. Admit change
    res = client.post(
        "/api/v1/orchestration/admit",
        json={
            "project_id": env["project_id"],
            "change_name": env["change_name"],
            "project_root": env["project_root"],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["admitted"] is True

    # 2. List runs (empty initially)
    list_res = client.get("/api/v1/orchestration/runs", params={"project_id": env["project_id"]})
    assert list_res.status_code == 200
    assert isinstance(list_res.json(), list)

    app.dependency_overrides.clear()


def test_cli_commands(setup_api_env, in_memory_uow, monkeypatch):
    env = setup_api_env

    class FakeSessionContext:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("minime.cli.main.db_manager.session", lambda: FakeSessionContext())
    monkeypatch.setattr(
        "minime.cli.main.PostgresPersistenceUnitOfWork", lambda session: in_memory_uow
    )

    # 1. minime orchestrate list
    res = runner.invoke(cli_app, ["orchestrate", "list", "--project-id", env["project_id"]])
    assert res.exit_code == 0

    # 2. Non-existent run status returns error
    bad_res = runner.invoke(cli_app, ["orchestrate", "status", "non-existent-run-id"])
    assert bad_res.exit_code != 0
