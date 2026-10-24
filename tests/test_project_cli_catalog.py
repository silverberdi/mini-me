"""Read-only project catalogs exposed by the operator CLI."""

import json

from typer.testing import CliRunner

from minime.cli.main import app


def test_project_provider_catalog_cli_exposes_metadata_only():
    result = CliRunner().invoke(app, ["project", "catalog", "providers"])

    assert result.exit_code == 0
    catalog = json.loads(result.output)
    assert {item["id"] for item in catalog} == {"github", "ado"}
    github_fields = {field["name"]: field for field in catalog[0]["fields"]}
    assert github_fields["private_key"]["write_only"] is True
    assert "-----BEGIN" not in json.dumps(catalog)


def test_project_agent_catalog_cli_uses_read_only_discovery(monkeypatch):
    async def observed_catalog(self, project_root=None):
        assert project_root is None
        return {
            "agents": [{"id": "codex", "capability_status": "OBSERVED_READ_ONLY"}],
            "capability_discovery": "read-only; no inference or provider probe was invoked",
        }

    monkeypatch.setattr("minime.cli.main.ProjectCatalogService.agent_catalog", observed_catalog)
    result = CliRunner().invoke(app, ["project", "catalog", "agents"])

    assert result.exit_code == 0
    assert json.loads(result.output)["agents"][0]["id"] == "codex"


def test_project_agent_catalog_cli_checks_the_requested_bound_workspace(
    monkeypatch, in_memory_uow, tmp_path
):
    from contextlib import contextmanager

    from minime.cli import main as cli
    from minime.domain.models import Project, ProjectManagedRepositoryBinding
    from minime.services.project_service import ProjectService

    project = Project(
        project_id="demo",
        display_name="Demo",
        repository="example/demo",
    )
    in_memory_uow.projects.save(project)
    root = tmp_path / "managed"
    root.mkdir()
    in_memory_uow.project_managed_repository_bindings.save(
        ProjectManagedRepositoryBinding(
            project_id=project.project_id,
            canonical_repository_identity=project.repository,
            managed_repository_root=str(root),
            worktree_parent_dir=str(root / ".minime/worktrees"),
        )
    )

    @contextmanager
    def session():
        yield in_memory_uow

    monkeypatch.setattr(cli.db_manager, "session", session)
    monkeypatch.setattr(cli, "PostgresPersistenceUnitOfWork", lambda value: value)
    monkeypatch.setattr(
        ProjectService,
        "verified_managed_workspace_root",
        lambda _self, project_id: root if project_id == project.project_id else None,
    )

    async def observed_catalog(self, project_root=None):
        assert project_root == root
        return {"agents": [], "capability_discovery": "read-only"}

    monkeypatch.setattr(cli.ProjectCatalogService, "agent_catalog", observed_catalog)
    result = CliRunner().invoke(
        app, ["project", "catalog", "agents", "--project-id", project.project_id]
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["capability_discovery"] == "read-only"


def test_project_context_cli_is_registered_as_a_read_only_operation():
    result = CliRunner().invoke(app, ["project", "context", "--help"])

    assert result.exit_code == 0
    assert "verified managed repository binding" in result.output
