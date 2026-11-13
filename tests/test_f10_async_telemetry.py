import asyncio

import pytest

from minime.services.event_broker import EventBroker
from minime.services.quota_telemetry import (
    QuotaObservation,
    QuotaTelemetryService,
    parse_five_hour_usage,
)


def test_five_hour_parser_is_explicit_and_fail_closed():
    assert parse_five_hour_usage('{"remaining_percent": 73, "window": "5h"}') == {
        "remaining_percent": 73.0,
        "reset_at": None,
        "window": "5h",
    }
    assert parse_five_hour_usage('{"remaining_percent": 101, "window": "5h"}') is None
    assert parse_five_hour_usage("monthly balance: 73") is None


@pytest.mark.asyncio
async def test_quota_telemetry_caches_observation_for_ttl(monkeypatch):
    service = QuotaTelemetryService(ttl_seconds=60)
    calls = 0

    async def observe(self):
        nonlocal calls
        calls += 1
        return QuotaObservation(self.provider, "AVAILABLE", "now", "test")

    monkeypatch.setattr("minime.services.quota_telemetry.ProviderQuotaStrategy.observe", observe)
    await service.observe("codex")
    await service.observe("codex")
    assert calls == 1


@pytest.mark.asyncio
async def test_quota_api_does_not_invent_provider_balances_or_percentages(monkeypatch):
    from minime.api.app import get_provider_quotas

    observed = [
        {
            "provider": "openrouter",
            "state": "UNKNOWN",
            "observed_at": "2026-11-12T12:00:00+00:00",
            "source": "openrouter_credits",
            "balance": None,
            "remaining_percent": None,
        }
    ]

    async def snapshot():
        return observed

    monkeypatch.setattr("minime.api.app.quota_telemetry.snapshot", snapshot)
    response = await get_provider_quotas(_operator=object())
    assert response["providers"] == observed
    assert "openrouter" not in response
    assert "deepseek" not in response


@pytest.mark.asyncio
async def test_event_broker_broadcasts_sse_and_drops_slow_subscriber():
    broker = EventBroker(queue_size=1)
    stream = broker.subscribe()
    first = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    await broker.publish("run.transition", {"run_id": "run-1", "stage": "RUNNING_TESTS"})
    assert "event: run.transition" in await first
    await stream.aclose()
