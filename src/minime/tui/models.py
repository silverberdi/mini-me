"""TUI state models, helpers, and formatting utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from rich.text import Text

from minime.logging import redact_secrets


class TuiViewMode(str, Enum):
    OVERVIEW = "overview"
    CHANGES = "changes"
    DETAIL = "detail"
    PREVIEW = "preview"


class ChangeFilter(str, Enum):
    ALL = "ALL"
    ACTIVE = "ACTIVE"
    ATTENTION = "ATTENTION"
    READY = "READY"
    COMPLETED = "COMPLETED"


# ---------------------------------------------------------------------------
# Formatting Helpers
# ---------------------------------------------------------------------------


def short_sha(sha: str | None, length: int = 8) -> str:
    """Format full git SHA or hash to a short form."""
    if not sha:
        return "—"
    clean = sha.strip()
    if clean.startswith("sha256:"):
        digest = clean[7:]
        return f"sha256:{digest[:length]}"
    return clean[:length] if len(clean) >= length else clean


def format_duration(ms: int | None) -> str:
    """Format milliseconds into human-readable duration."""
    if ms is None or ms < 0:
        return "—"
    if ms < 1000:
        return f"{ms}ms"
    sec = ms / 1000.0
    if sec < 60:
        return f"{sec:.1f}s"
    minutes = int(sec // 60)
    rem_sec = int(sec % 60)
    return f"{minutes}m {rem_sec}s"


def format_timestamp(iso_str: str | None) -> str:
    """Format ISO timestamp into compact local readable form."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        diff = now - dt
        # If today, show time + relative
        secs = int(diff.total_seconds())
        if secs < 60:
            return "just now"
        elif secs < 3600:
            return f"{secs // 60}m ago"
        elif secs < 86400:
            return f"{secs // 3600}h ago"
        else:
            days = secs // 86400
            return f"{days}d ago"
    except Exception:
        return iso_str[:19].replace("T", " ")


def get_status_text(status_val: str | None) -> Text:
    """Return a styled Rich Text badge for operational statuses."""
    if not status_val:
        return Text("UNKNOWN", style="dim")

    s = status_val.upper().strip()
    if s in {"READY", "COMPLETED", "READY_TO_MERGE", "PASSED", "PASS", "HEALTHY", "TRUE"}:
        return Text(f" {s} ", style="bold black on green")
    elif s in {"RUNNING", "ACTIVE", "IMPLEMENTING", "EXECUTING", "BUILDING", "PROBING", "STARTING"}:
        return Text(f" {s} ", style="bold black on cyan")
    elif s in {
        "NEEDS_HUMAN",
        "WAITING",
        "WAITING_CAPACITY",
        "STALE",
        "CHANGES_REQUIRED",
        "WARNING",
        "DEGRADED",
    }:
        return Text(f" {s} ", style="bold black on yellow")
    elif s in {
        "FAILED",
        "BLOCKED",
        "RECOVERY_BLOCKED",
        "REJECTED",
        "CRITICAL",
        "HIGH",
        "STOPPED",
        "FALSE",
    }:
        return Text(f" {s} ", style="bold white on red")
    elif s in {"DISCOVERED", "NOT_READY", "NOT_STARTED", "SKIPPED", "HISTORICAL", "SUPERSEDED"}:
        return Text(f" {s} ", style="dim")
    return Text(f" {s} ", style="white on dark_blue")


def get_phase_text(phase_name: str, phase_status: str | None) -> Text:
    """Format pipeline phase with icon and status."""
    st = (phase_status or "not_started").lower()
    icon = "○"
    style = "dim"
    if st == "passed":
        icon = "✓"
        style = "green bold"
    elif st == "running":
        icon = "⟳"
        style = "cyan bold"
    elif st == "failed":
        icon = "✗"
        style = "red bold"
    elif st == "blocked":
        icon = "⏸"
        style = "yellow bold"
    elif st == "waiting":
        icon = "⏳"
        style = "yellow"

    return Text.assemble(
        (f"{icon} ", style), (phase_name, "bold" if st in {"passed", "running"} else "dim")
    )


def get_risk_text(risk: str | None) -> Text:
    """Format DeepSeek audit risk level."""
    if not risk:
        return Text("—", style="dim")
    r = risk.lower().strip()
    if r == "low":
        return Text(" LOW RISK ", style="bold black on green")
    elif r == "medium":
        return Text(" MEDIUM RISK ", style="bold black on yellow")
    elif r in {"high", "critical"}:
        return Text(f" {r.upper()} RISK ", style="bold white on red")
    return Text(f" {r.upper()} ", style="dim")


def sanitize_text(text: str | None) -> str:
    """Sanitize secrets from any arbitrary text."""
    if not text:
        return ""
    return redact_secrets(str(text))
