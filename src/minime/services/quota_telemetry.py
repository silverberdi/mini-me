"""Fail-closed provider quota observations with a short process-local cache."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from minime.adapters.provider_adapter import (
    AntigravityProviderAdapter,
    CapacityObservation,
    CodexProviderAdapter,
    DeepSeekProviderAdapter,
    get_provider_adapter,
)

logger = logging.getLogger(__name__)


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
    """Adapter boundary for observed provider capacity without synthetic defaults."""

    def __init__(self, provider: str) -> None:
        self.provider = provider

    async def observe(self) -> QuotaObservation:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        try:
            adapter = get_provider_adapter(self.provider)
        except Exception as exc:
            return QuotaObservation(
                provider=self.provider,
                state="UNKNOWN",
                observed_at=now,
                source="adapter",
                status_label="UNKNOWN",
                reason=type(exc).__name__,
            )

        if self.provider == "antigravity":
            return await self._observe_antigravity(adapter, now)
        elif self.provider == "codex":
            return await self._observe_codex(adapter, now)
        elif self.provider == "deepseek":
            return await self._observe_deepseek(adapter, now)
        else:
            return QuotaObservation(
                provider=self.provider,
                state="UNKNOWN",
                observed_at=now,
                source="adapter",
                status_label="UNKNOWN",
                reason="unsupported_provider",
            )

    async def _observe_antigravity(self, adapter: Any, now: str) -> QuotaObservation:
        try:
            raw_obs: CapacityObservation | None = await adapter.read_capacity_observation()
            if raw_obs is None or raw_obs.ordinary_usage_allowed is None:
                return QuotaObservation(
                    provider=self.provider,
                    state="UNKNOWN",
                    observed_at=now,
                    source="adapter",
                    status_label="UNKNOWN",
                    reason="unavailable",
                )
            
            # Extract real 5h window percentage directly from agy CLI /usage
            proc = await asyncio.create_subprocess_exec(
                "agy", "-p", "/usage", "--output-format", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            data = json.loads(stdout.decode("utf-8", errors="replace"))
            groups = data.get("command", {}).get("data", {}).get("groups", [])
            gemini_group = next((g for g in groups if "gemini" in g.get("name", "").lower()), None)
            
            rem_pct = None
            reset_at = raw_obs.capacity_reset_at.isoformat() if raw_obs.capacity_reset_at else None
            if gemini_group:
                buckets = gemini_group.get("buckets", [])
                b5h = next((b for b in buckets if b.get("window") == "5h" or "5h" in b.get("id", "")), None)
                if b5h and "remaining_fraction" in b5h:
                    rem_pct = round(float(b5h["remaining_fraction"]) * 100.0, 1)
                    if b5h.get("reset_time"):
                        reset_at = b5h["reset_time"]

            parsed = parse_five_hour_usage({"remaining_percent": rem_pct, "window": "5h", "reset_at": reset_at}) if rem_pct is not None else None
            state = "AVAILABLE" if raw_obs.ordinary_usage_allowed else "EXHAUSTED"
            
            status_lbl = "Normal"
            if state == "EXHAUSTED" or (rem_pct is not None and rem_pct < 10.0):
                status_lbl = "Crítico"
            elif rem_pct is not None and rem_pct < 30.0:
                status_lbl = "En ventana"

            return QuotaObservation(
                provider=self.provider,
                state=state,
                observed_at=raw_obs.observed_at.isoformat() if raw_obs.observed_at else now,
                source=raw_obs.source_signal.value if hasattr(raw_obs.source_signal, "value") else str(raw_obs.source_signal),
                remaining_percent=parsed["remaining_percent"] if parsed else rem_pct,
                balance=None,
                currency=None,
                reset_at=parsed["reset_at"] if parsed else reset_at,
                window="5h",
                model_id=raw_obs.model or "gemini-3.8-flash",
                status_label=status_lbl,
                account_id=raw_obs.account_id,
            )
        except Exception as exc:
            logger.warning("Failed observing Antigravity quota: %s", exc)
            return QuotaObservation(
                provider=self.provider,
                state="UNKNOWN",
                observed_at=now,
                source="adapter",
                status_label="UNKNOWN",
                reason=type(exc).__name__,
            )

    async def _observe_codex(self, adapter: Any, now: str) -> QuotaObservation:
        try:
            raw_obs: CapacityObservation | None = await adapter.read_capacity_observation()
            if raw_obs is None or raw_obs.ordinary_usage_allowed is None:
                return QuotaObservation(
                    provider=self.provider,
                    state="UNKNOWN",
                    observed_at=now,
                    source="adapter",
                    status_label="UNKNOWN",
                    reason="unavailable",
                )
            
            # Extract real 5h rate limit from Codex app-server
            rem_pct = None
            reset_at = raw_obs.capacity_reset_at.isoformat() if raw_obs.capacity_reset_at else None
            if hasattr(adapter, "_call_app_server_method"):
                rate_limits = await adapter._call_app_server_method("account/rateLimits/read", timeout_seconds=5.0)
                if isinstance(rate_limits, dict):
                    buckets = rate_limits.get("rateLimitsByLimitId", {})
                    bucket = buckets.get("codex") or rate_limits.get("rateLimits", {})
                    if isinstance(bucket, dict):
                        primary = bucket.get("primary", {})
                        if isinstance(primary, dict) and "usedPercent" in primary:
                            used = float(primary["usedPercent"])
                            rem_pct = max(0.0, round(100.0 - used, 1))
                            if primary.get("resetsAt"):
                                reset_at = datetime.fromtimestamp(primary["resetsAt"], tz=UTC).isoformat()

            parsed = parse_five_hour_usage({"remaining_percent": rem_pct, "window": "5h", "reset_at": reset_at}) if rem_pct is not None else None
            state = "AVAILABLE" if raw_obs.ordinary_usage_allowed else "EXHAUSTED"

            status_lbl = "Normal"
            if state == "EXHAUSTED" or (rem_pct is not None and rem_pct < 10.0):
                status_lbl = "Crítico"
            elif rem_pct is not None and rem_pct < 30.0:
                status_lbl = "En ventana"

            return QuotaObservation(
                provider=self.provider,
                state=state,
                observed_at=raw_obs.observed_at.isoformat() if raw_obs.observed_at else now,
                source=raw_obs.source_signal.value if hasattr(raw_obs.source_signal, "value") else str(raw_obs.source_signal),
                remaining_percent=parsed["remaining_percent"] if parsed else rem_pct,
                balance=None,
                currency=None,
                reset_at=parsed["reset_at"] if parsed else reset_at,
                window="5h",
                model_id=raw_obs.model or "gpt-5.6-luna",
                status_label=status_lbl,
                account_id=raw_obs.account_id,
            )
        except Exception as exc:
            logger.warning("Failed observing Codex quota: %s", exc)
            return QuotaObservation(
                provider=self.provider,
                state="UNKNOWN",
                observed_at=now,
                source="adapter",
                status_label="UNKNOWN",
                reason=type(exc).__name__,
            )

    async def _observe_deepseek(self, adapter: Any, now: str) -> QuotaObservation:
        try:
            key = getattr(adapter, "_api_key", lambda: None)() or os.environ.get("DEEPSEEK_API_KEY", "").strip()
            base_url = getattr(adapter, "_base_url", "https://api.deepseek.com")
            if not key:
                return QuotaObservation(
                    provider=self.provider,
                    state="UNKNOWN",
                    observed_at=now,
                    source="adapter",
                    status_label="UNKNOWN",
                    reason="missing_api_key",
                )

            async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
                resp = await client.get("/user/balance", headers={"Authorization": f"Bearer {key}"})
            
            if resp.status_code != 200:
                return QuotaObservation(
                    provider=self.provider,
                    state="UNKNOWN",
                    observed_at=now,
                    source="deepseek_account_balance",
                    status_label="UNKNOWN",
                    reason=f"http_{resp.status_code}",
                )
            
            payload = resp.json()
            is_available = bool(payload.get("is_available"))
            balance_infos = payload.get("balance_infos", [])
            
            bal = None
            curr = None
            if balance_infos and isinstance(balance_infos, list):
                first_info = balance_infos[0]
                curr = first_info.get("currency", "USD")
                total_str = first_info.get("total_balance")
                if total_str is not None:
                    bal = float(Decimal(str(total_str)))

            state = "AVAILABLE" if is_available else "EXHAUSTED"
            status_lbl = "Normal"
            if state == "EXHAUSTED" or (bal is not None and bal <= 0.0):
                status_lbl = "Crítico"
            elif bal is not None and bal < 2.0:
                status_lbl = "En ventana"

            return QuotaObservation(
                provider=self.provider,
                state=state,
                observed_at=now,
                source="deepseek_account_balance",
                remaining_percent=None,
                balance=bal,
                currency=curr,
                reset_at=None,
                window=None,
                model_id="deepseek-chat",
                status_label=status_lbl,
                account_id=getattr(adapter, "account_fingerprint", None),
            )
        except Exception as exc:
            logger.warning("Failed observing DeepSeek balance: %s", exc)
            return QuotaObservation(
                provider=self.provider,
                state="UNKNOWN",
                observed_at=now,
                source="adapter",
                status_label="UNKNOWN",
                reason=type(exc).__name__,
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
