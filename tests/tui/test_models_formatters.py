"""Unit tests for TUI models, formatters, and secret sanitization."""

from __future__ import annotations

from rich.text import Text

from minime.tui.models import (
    format_duration,
    format_timestamp,
    get_phase_text,
    get_risk_text,
    get_status_text,
    sanitize_text,
    short_sha,
)


def test_short_sha_formatting():
    assert short_sha(None) == "—"
    assert short_sha("") == "—"
    assert short_sha("abcdef1234567890") == "abcdef12"
    assert short_sha("sha256:1234567890abcdef", 8) == "sha256:12345678"
    assert short_sha("short") == "short"


def test_format_duration():
    assert format_duration(None) == "—"
    assert format_duration(-5) == "—"
    assert format_duration(450) == "450ms"
    assert format_duration(1500) == "1.5s"
    assert format_duration(65000) == "1m 5s"


def test_format_timestamp():
    assert format_timestamp(None) == "—"
    assert format_timestamp("") == "—"
    assert format_timestamp("2026-08-30T14:00:00Z") != "—"


def test_status_badge_styling():
    ready_badge = get_status_text("READY")
    assert isinstance(ready_badge, Text)
    assert "READY" in ready_badge.plain

    running_badge = get_status_text("RUNNING")
    assert "RUNNING" in running_badge.plain

    failed_badge = get_status_text("FAILED")
    assert "FAILED" in failed_badge.plain

    attn_badge = get_status_text("NEEDS_HUMAN")
    assert "NEEDS_HUMAN" in attn_badge.plain

    stale_badge = get_status_text("STALE")
    assert "STALE" in stale_badge.plain


def test_risk_badge_styling():
    low_risk = get_risk_text("low")
    assert "LOW RISK" in low_risk.plain

    med_risk = get_risk_text("medium")
    assert "MEDIUM RISK" in med_risk.plain

    high_risk = get_risk_text("high")
    assert "HIGH RISK" in high_risk.plain

    crit_risk = get_risk_text("critical")
    assert "CRITICAL RISK" in crit_risk.plain


def test_phase_badge_styling():
    p1 = get_phase_text("Readiness", "passed")
    assert "✓" in p1.plain
    assert "Readiness" in p1.plain

    p2 = get_phase_text("Implementation", "running")
    assert "⟳" in p2.plain

    p3 = get_phase_text("Checks", "failed")
    assert "✗" in p3.plain


def test_sanitize_text_redacts_secrets(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret-deepseek-key-12345")
    sanitized = sanitize_text("Used key: sk-secret-deepseek-key-12345 in call")
    assert "sk-secret-deepseek-key-12345" not in sanitized
    assert "REDACTED" in sanitized

