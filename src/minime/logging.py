"""Structured and redacted logging for mini me."""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from minime.config import get_secret_patterns

_current_project_id: ContextVar[str | None] = ContextVar("current_project_id", default=None)
_current_change_id: ContextVar[str | None] = ContextVar("current_change_id", default=None)
_current_operation_id: ContextVar[str | None] = ContextVar("current_operation_id", default=None)


def set_correlation_context(
    project_id: str | None = None,
    change_id: str | None = None,
    operation_id: str | None = None,
) -> None:
    """Set the active correlation context for the current execution context."""
    if project_id is not None:
        _current_project_id.set(project_id)
    if change_id is not None:
        _current_change_id.set(change_id)
    if operation_id is not None:
        _current_operation_id.set(operation_id)


def clear_correlation_context() -> None:
    """Clear the active correlation context."""
    _current_project_id.set(None)
    _current_change_id.set(None)
    _current_operation_id.set(None)


def get_correlation_context() -> dict[str, str | None]:
    """Retrieve current correlation identifiers."""
    return {
        "project_id": _current_project_id.get(),
        "change_id": _current_change_id.get(),
        "operation_id": _current_operation_id.get(),
    }


def redact_secrets(text: str, custom_secrets: list[str] | None = None) -> str:
    """Redact known secret patterns and standard credential formats from text."""
    if not text:
        return text

    # Redact URL passwords (e.g. postgresql://user:pass@host)
    redacted = re.sub(r"://([^:]+):([^@]+)@", r"://\1:[REDACTED]@", text)

    # Redact common key=value patterns for keys/tokens
    redacted = re.sub(
        r"(api[_-]?key|access[_-]?key|secret[_-]?key|token|password|secret)=([^\s&;]+)",
        r"\1=[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )

    # Redact common standalone secret tokens (e.g. OpenAI/Anthropic/DeepSeek sk-..., GitHub ghp_.../github_pat_..., AWS AKIA..., Slack xoxb-...)
    redacted = re.sub(r"\b(sk-[a-zA-Z0-9_\-]{12,})\b", "[REDACTED_KEY]", redacted)
    redacted = re.sub(r"\b(ghp_[a-zA-Z0-9]{20,})\b", "[REDACTED_TOKEN]", redacted)
    redacted = re.sub(r"\b(github_pat_[a-zA-Z0-9_]{22,})\b", "[REDACTED_TOKEN]", redacted)
    redacted = re.sub(r"\b(AKIA[0-9A-Z]{16})\b", "[REDACTED_KEY]", redacted)
    redacted = re.sub(r"\b(xox[baprs]-[0-9a-zA-Z\-]{10,})\b", "[REDACTED_TOKEN]", redacted)

    # Redact explicit registered secrets
    secrets = get_secret_patterns()
    if custom_secrets:
        secrets.extend(custom_secrets)

    for secret in secrets:
        if secret and secret in redacted:
            redacted = redacted.replace(secret, "[REDACTED]")

    return redacted


class StructuredJsonFormatter(logging.Formatter):
    """Formatter that outputs structured JSON with correlation IDs and redaction."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_correlation_context()
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
            "project_id": getattr(record, "project_id", ctx["project_id"]),
            "change_id": getattr(record, "change_id", ctx["change_id"]),
            "operation_id": getattr(record, "operation_id", ctx["operation_id"]),
        }

        if record.exc_info:
            payload["exception"] = redact_secrets(self.formatException(record.exc_info))

        # Include any extra attributes attached to record
        for key, val in record.__dict__.items():
            if key not in (
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "project_id",
                "change_id",
                "operation_id",
            ):
                payload[key] = val

        return json.dumps(payload)


def configure_logging(level: int = logging.INFO, json_output: bool = True) -> None:
    """Configure root and minime loggers."""
    handler = logging.StreamHandler()
    if json_output:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
        )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with minime conventions."""
    return logging.getLogger(f"minime.{name}")
