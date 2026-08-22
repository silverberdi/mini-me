"""Unit tests for budget and OpenRouter CLI commands."""

from typer.testing import CliRunner

from minime.cli.main import app as cli_app

runner = CliRunner()


def test_cli_budget_help():
    res = runner.invoke(cli_app, ["budget", "--help"])
    assert res.exit_code == 0
    assert "status" in res.output


def test_cli_providers_openrouter_help():
    res = runner.invoke(cli_app, ["providers", "--help"])
    assert res.exit_code == 0
    assert "openrouter" in res.output
