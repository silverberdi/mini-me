"""Regression coverage for the F1 unavailable boundary."""

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from minime.api.app import app
from minime.cli.main import app as cli


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


def test_retired_cli_group_fails_before_runtime_initialization():
    result = CliRunner().invoke(cli, ["scheduler", "status", "--json"])
    assert result.exit_code == 2
    assert "operation_unavailable" in result.output
