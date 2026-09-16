# Focused Task Group 3 tests: deterministic persisted probe cooldown/backoff.

from datetime import UTC, datetime, timedelta

from minime.adapters.provider_adapter import FakeProviderAdapter
from minime.config import ProbeConfig
from minime.domain.enums import ProviderHealthStatus, ProviderResultClass
from minime.domain.models import NormalizedProviderResult, ProviderHealth
from minime.services.provider_health_service import ProviderHealthService


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds: int):
        self.now = self.now + timedelta(seconds=seconds)


def _service(uow, clock, monkeypatch):
    monkeypatch.setattr("minime.services.provider_health_service.utc_now", clock)
    cfg = ProbeConfig(
        cooldown_seconds=60,
        backoff_base_seconds=60,
        backoff_max_seconds=240,
        max_per_hour=100,
    )
    return ProviderHealthService(uow, probe_config=cfg)


async def test_unknown_reset_first_probe_runs_then_cooldown_suppresses(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex", role="implementer", result_class=ProviderResultClass.QUOTA_LIMIT
        )
    )
    fake = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda provider: fake
    )
    clock.advance(60)  # first probe must respect the cooldown baseline
    assert await service.check_and_probe_provider("codex") is False
    assert fake.probe_call_count == 1
    assert await service.check_and_probe_provider("codex") is False
    assert fake.probe_call_count == 1
    health = service.get_health("codex")
    assert health.last_probe_at is not None
    assert health.consecutive_probe_failures == 1


async def test_probe_becomes_eligible_after_cooldown(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex", role="implementer", result_class=ProviderResultClass.QUOTA_LIMIT
        )
    )
    fake = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda provider: fake
    )
    clock.advance(60)
    await service.check_and_probe_provider("codex")
    assert fake.probe_call_count == 1
    clock.advance(61)
    await service.check_and_probe_provider("codex")
    assert fake.probe_call_count == 2


async def test_failed_recovery_increases_backoff(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex", role="implementer", result_class=ProviderResultClass.QUOTA_LIMIT
        )
    )
    fake = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda provider: fake
    )
    clock.advance(60)
    await service.check_and_probe_provider("codex")  # failures=1 at t=60
    clock.advance(61)
    await service.check_and_probe_provider("codex")  # failures=2 at t=121
    assert fake.probe_call_count == 2
    clock.advance(61)  # t=182, backoff for failures=2 is 120s -> not yet eligible
    await service.check_and_probe_provider("codex")
    assert fake.probe_call_count == 2
    clock.advance(59)  # t=241 -> eligible
    await service.check_and_probe_provider("codex")
    assert fake.probe_call_count == 3


async def test_backoff_caps_at_maximum(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex", role="implementer", result_class=ProviderResultClass.QUOTA_LIMIT
        )
    )
    health = service.get_health("codex")
    health.consecutive_probe_failures = 10
    health.last_probe_at = clock.now
    in_memory_uow.provider_health.save(health)
    fake = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda provider: fake
    )
    await service.check_and_probe_provider("codex")
    assert fake.probe_call_count == 0
    clock.advance(239)  # below backoff_max (240)
    await service.check_and_probe_provider("codex")
    assert fake.probe_call_count == 0
    clock.advance(1)  # t=240 -> eligible
    await service.check_and_probe_provider("codex")
    assert fake.probe_call_count == 1


async def test_successful_recovery_clears_backoff_state(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex", role="implementer", result_class=ProviderResultClass.QUOTA_LIMIT
        )
    )
    fake = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda provider: fake
    )
    clock.advance(60)
    await service.check_and_probe_provider("codex")
    assert fake.probe_call_count == 1
    assert service.get_health("codex").consecutive_probe_failures == 1
    clock.advance(61)
    fake.available = True
    assert await service.check_and_probe_provider("codex") is True
    health = service.get_health("codex")
    assert health.status == ProviderHealthStatus.AVAILABLE
    assert health.consecutive_probe_failures == 0


async def test_known_future_reset_prevents_early_probe(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch)
    future = clock.now + timedelta(hours=1)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex",
            role="implementer",
            result_class=ProviderResultClass.QUOTA_LIMIT,
            capacity_reset_at=future,
        )
    )
    fake = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda provider: fake
    )
    assert await service.check_and_probe_provider("codex") is False
    assert fake.probe_call_count == 0


async def test_probe_state_survives_service_recreation(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex", role="implementer", result_class=ProviderResultClass.QUOTA_LIMIT
        )
    )
    fake1 = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda provider: fake1
    )
    clock.advance(60)
    await service.check_and_probe_provider("codex")
    assert fake1.probe_call_count == 1

    service2 = ProviderHealthService(in_memory_uow, probe_config=ProbeConfig())
    fake2 = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda provider: fake2
    )
    assert await service2.check_and_probe_provider("codex") is False
    assert fake2.probe_call_count == 0


def test_provider_health_probe_state_round_trip(in_memory_uow):
    ts = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
    health = ProviderHealth(
        provider="codex",
        status=ProviderHealthStatus.EXHAUSTED,
        last_probe_at=ts,
        consecutive_probe_failures=3,
        probe_window_started_at=ts,
        probe_count_in_window=2,
    )
    in_memory_uow.provider_health.save(health)
    got = in_memory_uow.provider_health.get_by_provider("codex")
    assert got.last_probe_at == ts
    assert got.consecutive_probe_failures == 3
    assert got.probe_window_started_at == ts
    assert got.probe_count_in_window == 2


async def test_unknown_reset_first_probe_respects_cooldown(in_memory_uow, monkeypatch):
    """Leaf A regression: exhaustion at T0 with unknown reset must not probe
    before T0+cooldown; the first expensive probe is anchored to the exhaustion
    baseline rather than firing immediately."""
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex", role="implementer", result_class=ProviderResultClass.QUOTA_LIMIT
        )
    )
    fake = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda provider: fake
    )
    # Tick repeatedly inside the cooldown window: zero probes must fire.
    for _ in range(5):
        clock.advance(10)  # t=10..50, all < T0+60
        assert await service.check_and_probe_provider("codex") is False
    assert fake.probe_call_count == 0
    # Cross the cooldown boundary: exactly one probe fires.
    clock.advance(11)  # t=61 >= T0+60
    assert await service.check_and_probe_provider("codex") is False
    assert fake.probe_call_count == 1
