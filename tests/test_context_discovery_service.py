"""Project context reads resolve through validated durable repository bindings."""

import json
import subprocess

import pytest

from minime.domain.models import (
    Project,
    ProjectManagedRepositoryBinding,
)
from minime.services.context_discovery_service import ContextDiscoveryService


def _bound_repository(tmp_path, uow):
    root = tmp_path / "bound-repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin", "https://github.com/example/demo.git"],
        check=True,
    )
    (root / ".minime-managed-project.json").write_text(
        json.dumps(
            {
                "project_id": "demo",
                "canonical_repository_identity": "example/demo",
            }
        )
    )
    (root / "README.md").write_text("# Bound Repository\n")
    (root / "openspec").mkdir()
    uow.projects.save(
        Project(project_id="demo", display_name="Demo", repository="example/demo")
    )
    uow.project_managed_repository_bindings.save(
        ProjectManagedRepositoryBinding(
            project_id="demo",
            canonical_repository_identity="example/demo",
            managed_repository_root=str(root),
            worktree_parent_dir=str(root / ".minime/worktrees"),
            ownership_marker_filename=".minime-managed-project.json",
            is_valid=True,
        )
    )
    return root


def test_context_discovery_reads_only_the_valid_bound_project_repository(tmp_path, in_memory_uow):
    _bound_repository(tmp_path, in_memory_uow)
    service = ContextDiscoveryService(in_memory_uow)

    report = service.discover_context_pure("demo")

    assert report.discovered_facts[0].source_file == "README.md"
    assert report.discovered_facts[0].detail == "Bound Repository"


def test_context_api_reads_the_bound_repository_under_operator_auth(
    tmp_path, in_memory_uow, monkeypatch
):
    from fastapi.testclient import TestClient

    from minime.api.app import app, get_current_operator, get_uow

    _bound_repository(tmp_path, in_memory_uow)
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "false")
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_current_operator] = lambda: object()
    try:
        response = TestClient(app).get("/api/v1/projects/demo/context")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.json()
    assert response.json()["discovered_facts"][0]["detail"] == "Bound Repository"


def test_context_discovery_fails_closed_without_a_durable_repository_binding(in_memory_uow):
    in_memory_uow.projects.save(
        Project(project_id="demo", display_name="Demo", repository="example/demo")
    )

    with pytest.raises(ValueError, match="binding is missing or invalid"):
        ContextDiscoveryService(in_memory_uow).discover_context_pure("demo")
