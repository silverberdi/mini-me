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
    async def observed_catalog(self):
        return {
            "agents": [{"id": "codex", "capability_status": "OBSERVED_READ_ONLY"}],
            "capability_discovery": "read-only; no inference or provider probe was invoked",
        }

    monkeypatch.setattr("minime.cli.main.ProjectCatalogService.agent_catalog", observed_catalog)
    result = CliRunner().invoke(app, ["project", "catalog", "agents"])

    assert result.exit_code == 0
    assert json.loads(result.output)["agents"][0]["id"] == "codex"
