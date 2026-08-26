"""Tests for configuration parsing, secret redaction, and structured logging."""

import json
import logging

import pytest

from minime.config import (
    AppConfig,
    CliInvocationConfig,
    DatabaseConfig,
    ProviderConfig,
    resolve_cli_invocation,
)
from minime.db.session import validate_postgres_url
from minime.logging import (
    StructuredJsonFormatter,
    clear_correlation_context,
    get_correlation_context,
    redact_secrets,
    set_correlation_context,
)


def test_database_config_postgres_enforcement(monkeypatch):
    # Setting a non-postgres URL should raise ValueError
    monkeypatch.setenv("MINIME_DATABASE_URL", "sqlite:///test.db")
    db_config = DatabaseConfig()
    with pytest.raises(ValueError, match="strictly requires PostgreSQL"):
        db_config.resolve_url()

    # Setting a postgres URL should succeed
    monkeypatch.setenv("MINIME_DATABASE_URL", "postgresql://user:pass@localhost:5432/minime")
    url = db_config.resolve_url()
    assert url == "postgresql://user:pass@localhost:5432/minime"


def test_validate_postgres_url():
    with pytest.raises(ValueError, match="exclusively supports PostgreSQL"):
        validate_postgres_url("sqlite:///app.db")

    with pytest.raises(ValueError, match="exclusively supports PostgreSQL"):
        validate_postgres_url("mysql://root:pass@localhost/db")

    # Valid PostgreSQL URLs
    validate_postgres_url("postgresql://localhost:5432/minime")
    validate_postgres_url("postgresql+psycopg://user:pass@localhost:5432/minime")


def test_secret_redaction(monkeypatch):
    monkeypatch.setenv(
        "MINIME_DATABASE_URL", "postgresql://minime:supersecretpass@localhost:5432/minime"
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-secret-12345")

    text = (
        "Connecting to postgresql://minime:supersecretpass@localhost:5432/minime "
        "with key sk-deepseek-secret-12345 and api_key=another_secret_token"
    )
    redacted = redact_secrets(text)

    assert "supersecretpass" not in redacted
    assert "sk-deepseek-secret-12345" not in redacted
    assert "another_secret_token" not in redacted
    assert "[REDACTED]" in redacted


def test_correlation_context_and_json_logging():
    clear_correlation_context()


def test_cli_invocation_profiles_resolve_without_provider_specific_runner_logic():
    config = AppConfig(
        providers={
            "test-cli": ProviderConfig(
                command="future-runner",
                roles=["implementer", "reviewer"],
                invocation={
                    "implementer": CliInvocationConfig(
                        args=["--edit", "--input", "-"], prompt_transport="stdin"
                    ),
                    "reviewer": CliInvocationConfig(
                        args=["--review", "--input", "-"], prompt_transport="stdin"
                    ),
                },
            )
        }
    )

    implementer = resolve_cli_invocation("test-cli", "implementer", config)
    reviewer = resolve_cli_invocation("test-cli", "reviewer", config)

    assert (implementer.executable, implementer.args) == (
        "future-runner",
        ("--edit", "--input", "-"),
    )
    assert reviewer.args == ("--review", "--input", "-")


@pytest.mark.parametrize(
    ("provider", "role", "message"),
    [
        ("missing", "implementer", "not configured"),
        ("disabled", "implementer", "disabled"),
        ("test-cli", "auditor", "does not allow role"),
        ("test-cli", "reviewer", "no invocation profile"),
    ],
)
def test_cli_invocation_resolution_fails_closed(provider, role, message):
    config = AppConfig(
        providers={
            "disabled": ProviderConfig(enabled=False),
            "test-cli": ProviderConfig(
                command="runner",
                roles=["implementer", "reviewer"],
                invocation={"implementer": CliInvocationConfig()},
            )
        }
    )
    with pytest.raises(ValueError, match=message):
        resolve_cli_invocation(provider, role, config)


def test_cli_invocation_rejects_unsupported_prompt_transport():
    config = AppConfig(
        providers={
            "test-cli": ProviderConfig(
                command="runner",
                roles=["implementer"],
                invocation={
                    "implementer": CliInvocationConfig(prompt_transport="file")
                },
            )
        }
    )
    with pytest.raises(ValueError, match="Unsupported prompt transport"):
        resolve_cli_invocation("test-cli", "implementer", config)
    assert get_correlation_context() == {
        "project_id": None,
        "change_id": None,
        "operation_id": None,
    }

    set_correlation_context(project_id="proj-1", change_id="001-feat", operation_id="check_1")
    ctx = get_correlation_context()
    assert ctx["project_id"] == "proj-1"
    assert ctx["change_id"] == "001-feat"
    assert ctx["operation_id"] == "check_1"

    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="minime.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test log message with api_key=secret123",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "minime.test"
    assert parsed["project_id"] == "proj-1"
    assert parsed["change_id"] == "001-feat"
    assert parsed["operation_id"] == "check_1"
    assert "secret123" not in parsed["message"]
    assert "[REDACTED]" in parsed["message"]

    clear_correlation_context()
