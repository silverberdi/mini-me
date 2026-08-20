"""Tests for configuration parsing, secret redaction, and structured logging."""

import json
import logging

import pytest

from minime.config import DatabaseConfig
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
