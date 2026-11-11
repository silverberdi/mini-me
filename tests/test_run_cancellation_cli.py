from typer.testing import CliRunner

from minime.cli.main import app


def test_request_cancel_requires_run_identity_and_reason():
    result = CliRunner().invoke(app, ["request", "cancel", "--help"])

    assert result.exit_code == 0
    assert "--run-id" in result.stdout
    assert "--reason" in result.stdout
    assert "--idempotency-key" in result.stdout


def test_request_complete_keeps_physical_validation_semantics():
    result = CliRunner().invoke(app, ["request", "complete", "--help"])

    assert result.exit_code == 0
    assert "Physical validation accepted by operator" in result.stdout
