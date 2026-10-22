"""Regression coverage for the F1 unavailable boundary."""

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from minime.adapters.openspec import OpenSpecAdapter
from minime.api.app import app
from minime.cli.main import app as cli
from minime.domain.models import Project
from minime.services.legacy_unavailable import LegacyOperationUnavailable
from minime.tui import run_tui


def test_retired_api_operations_fail_closed_without_database(monkeypatch):
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "false")
    with TestClient(app, raise_server_exceptions=False) as client:
        for path in (
            "/api/v1/scheduler/tick",
            "/api/v1/orchestration/start",
            "/api/v1/projects/example/backlog",
        ):
            response = client.post(path) if path.endswith(("tick", "start")) else client.get(path)
            assert response.status_code == 410
            assert response.json()["code"] == "operation_unavailable"


def test_retired_openspec_preview_and_validation_writers_fail_closed(monkeypatch):
    """F1 cannot manufacture audit, preview, or validation state."""
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "false")
    with TestClient(app, raise_server_exceptions=False) as client:
        responses = (
            client.post("/api/v1/openspec/integrity/audit?project_id=example"),
            client.post(
                "/api/v1/previews/build",
                json={
                    "project_id": "example",
                    "change_name": "native-change",
                    "head_sha": "head",
                    "base_sha": "base",
                },
            ),
            client.post(
                "/api/v1/validations/submit",
                json={
                    "project_id": "example",
                    "change_name": "native-change",
                    "head_sha": "head",
                    "base_sha": "base",
                    "image_digest": "sha256:test",
                },
            ),
        )

    for response in responses:
        assert response.status_code == 410
        payload = response.json()
        assert payload.get("code", payload.get("detail", {}).get("code")) == "operation_unavailable"


def test_retired_cli_group_fails_before_runtime_initialization():
    result = CliRunner().invoke(cli, ["scheduler", "status", "--json"])
    assert result.exit_code == 2
    assert "operation_unavailable" in result.output


def test_every_retired_cli_entrypoint_fails_without_dispatch():
    runner = CliRunner()
    for args in (("run",), ("orchestrate", "start"), ("queue", "list"), ("tui",)):
        result = runner.invoke(cli, args)
        assert result.exit_code == 2
        assert "operation_unavailable" in result.output


def test_tui_boundary_is_importable_but_cannot_start_legacy_ui():
    with pytest.raises(LegacyOperationUnavailable, match="legacy_tui"):
        run_tui()


def test_openspec_adapter_inspects_existing_artifacts_without_writing(tmp_path):
    """The retained adapter reports filesystem facts but does not author artifacts."""
    change_dir = tmp_path / "openspec" / "changes" / "existing-native-change"
    change_dir.mkdir(parents=True)
    proposal = change_dir / "proposal.md"
    proposal.write_text("# native proposal\n", encoding="utf-8")
    before = proposal.read_bytes()

    project = Project(
        project_id="example",
        display_name="Example",
        repository="owner/example",
    )
    discovered = OpenSpecAdapter(cli_command="definitely-not-openspec").discover_changes(
        project, str(tmp_path)
    )

    assert [change.name for change in discovered] == ["existing-native-change"]
    assert discovered[0].proposal_path == str(proposal)
    assert proposal.read_bytes() == before
