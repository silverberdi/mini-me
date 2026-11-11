from typer.testing import CliRunner
from typer.main import get_command

from minime.cli.main import app


def test_request_cancel_requires_run_identity_and_reason():
    command = get_command(app)
    cancel_command = command.commands["request"].commands["cancel"]
    parameter_names = {parameter.name for parameter in cancel_command.params}

    assert {"project_id", "run_id", "reason", "idempotency_key"} <= parameter_names


def test_request_complete_keeps_physical_validation_semantics():
    result = CliRunner().invoke(app, ["request", "complete", "--help"])

    assert result.exit_code == 0
    assert "Physical validation accepted by operator" in result.stdout
