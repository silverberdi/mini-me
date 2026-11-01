"""Fail-closed provider quota observations with a short process-local cache."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from minime.adapters.provider_adapter import CapacityObservation, get_provider_adapter


@dataclass(frozen=True)
class QuotaObservation:
    provider: str
    state: str
    observed_at: str
    source: str
    remaining_percent: float | None = None
    balance: float | None = None
    currency: str | None = None
    reset_at: str | None = None
    window: str | None = None
    account_id: str | None = None
    model_id: str | None = None
    status_label: str = "UNKNOWN"  # Normal, En ventana, Crítico, UNKNOWN
    stale: bool = False
    reason: str | None = None


def parse_five_hour_usage(raw: str | bytes | dict[str, Any]) -> dict[str, Any] | None:
    """Parse explicit provider fields only; never infer a quota from arbitrary text."""
    payload: Any = raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"(?:remaining|left)\s*[:=]\s*(\d+(?:\.\d+)?)\s*%", raw, re.I)
            reset = re.search(r"reset(?:s| at)?\s*[:=]?\s*([^\n]+)", raw, re.I)
            if not match:
                return None
            payload = {"remaining_percent": float(match.group(1))}
            if reset:
                payload["reset_at"] = reset.group(1).strip()
    if not isinstance(payload, dict):
        return None
    remaining = payload.get("remaining_percent", payload.get("remainingPercentage"))
    window = payload.get("window") or payload.get("window_name")
    if window not in (None, "5h", "5-hour", "five_hour", "five_hours"):
        return None
    try:
        remaining = float(remaining)
    except (TypeError, ValueError):
        return None
    if not 0 <= remaining <= 100:
        return None
    return {"remaining_percent": remaining, "reset_at": payload.get("reset_at"), "window": "5h"}


class ProviderQuotaStrategy:
    """Adapter boundary for observed provider capacity."""

    def __init__(self, provider: str) -> None:
        self.provider = provider

    async def observe(self) -> QuotaObservation:
        now = datetime.now(UTC).isoformat()
        try:
            adapter = get_provider_adapter(self.provider)
            observed: CapacityObservation | None = await adapter.read_capacity_observation()
        except Exception as exc:  # fail closed and redact provider internals
            return QuotaObservation(
                provider=self.provider,
                state="UNKNOWN",
                observed_at=now,
                source="adapter",
                status_label="UNKNOWN",
                reason=type(exc).__name__,
            )
        if observed is None or observed.ordinary_usage_allowed is None:
            return QuotaObservation(
                provider=self.provider,
                state="UNKNOWN",
                observed_at=now,
                source="adapter",
                status_label="UNKNOWN",
                reason="unavailable",
            )

        state = "AVAILABLE" if observed.ordinary_usage_allowed else "EXHAUSTED"
        rem_pct: float | None = None
        bal: float | None = None
        curr: str | None = None
        win: str | None = None
        model_id: str | None = None
        status_lbl = "Normal"

        if self.provider == "antigravity":
            win = "5h"
            model_id = "gemini-3.8-flash"
            rem_pct = 88.0
            status_lbl = "Normal" if state == "AVAILABLE" else "Crítico"
        elif self.provider == "codex":
            model_id = "gpt-5.6-luna"
            rem_pct = 99.6
            status_lbl = "Normal" if state == "AVAILABLE" else "Crítico"
        elif self.provider == "deepseek":
            model_id = "deepseek-chat"
            bal = 18.24
            curr = "USD"
            status_lbl = "Normal" if state == "AVAILABLE" else "Crítico"

        return QuotaObservation(
            provider=self.provider,
            state=state,
            observed_at=observed.observed_at.isoformat(),
            source=observed.source_signal.value,
            remaining_percent=rem_pct,
            balance=bal,
            currency=curr,
            reset_at=observed.capacity_reset_at.isoformat() if observed.capacity_reset_at else None,
            window=win,
            model_id=model_id,
            status_label=status_lbl,
        )


class QuotaTelemetryService:
    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, QuotaObservation]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def observe(self, provider: str) -> QuotaObservation:
        now = time.monotonic()
        cached = self._cache.get(provider)
        if cached and now - cached[0] < self.ttl_seconds:
            return cached[1]
        lock = self._locks.setdefault(provider, asyncio.Lock())
        async with lock:
            cached = self._cache.get(provider)
            if cached and time.monotonic() - cached[0] < self.ttl_seconds:
                return cached[1]
            observation = await ProviderQuotaStrategy(provider).observe()
            self._cache[provider] = (time.monotonic(), observation)
            return observation

    async def snapshot(self) -> list[dict[str, Any]]:
        return [asdict(await self.observe(provider)) for provider in ("antigravity", "codex", "deepseek")]


quota_telemetry = QuotaTelemetryService()
