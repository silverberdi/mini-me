# Focused Task Group 4 tests: expensive-probe governance and observability.

import asyncio
from datetime import UTC, datetime, timedelta

from minime.adapters.provider_adapter import FakeProviderAdapter
from minime.config import ProbeConfig
from minime.domain.enums import EventType, ProviderResultClass
from minime.domain.models import Event, NormalizedProviderResult
from minime.services.provider_health_service import ProviderHealthService


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds: int):
        self.now = self.now + timedelta(seconds=seconds)


class _ExpensiveFake(FakeProviderAdapter):
    @property
    def probe_is_expensive(self):
        return True


def _service(uow, clock, monkeypatch, max_per_hour):
    monkeypatch.setattr("minime.services.provider_health_service.utc_now", clock)
    cfg = ProbeConfig(
        cooldown_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        max_per_hour=max_per_hour,
    )
    return ProviderHealthService(uow, probe_config=cfg)


def _setup_exhausted(service):
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex", role="implementer", result_class=ProviderResultClass.QUOTA_LIMIT
        )
    )


def _events(uow):
    return uow.events.list_events(limit=1000)


async def test_expensive_probe_below_limit_is_allowed(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch, max_per_hour=2)
    _setup_exhausted(service)
    adapter = _ExpensiveFake(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    await service.check_and_probe_provider("codex")
    assert adapter.probe_call_count == 1
    executed = [e for e in _events(in_memory_uow) if e.event_type.value == "PROVIDER_PROBE_EXECUTED"]
    assert len(executed) == 1
    assert executed[0].payload.get("kind") == "expensive"
    assert executed[0].payload.get("result") == "failure"


async def test_expensive_probe_at_limit_is_suppressed(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch, max_per_hour=1)
    _setup_exhausted(service)
    adapter = _ExpensiveFake(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    await service.check_and_probe_provider("codex")
    await service.check_and_probe_provider("codex")
    assert adapter.probe_call_count == 1
    suppressed = [
        e for e in _events(in_memory_uow) if e.event_type.value == "PROVIDER_PROBE_SUPPRESSED"
    ]
    assert len(suppressed) == 1
    assert suppressed[0].payload.get("reason") == "MAX_PER_HOUR"


async def test_cheap_probe_is_not_counted_toward_expensive_quota(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch, max_per_hour=0)
    _setup_exhausted(service)
    adapter = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    await service.check_and_probe_provider("codex")
    assert adapter.probe_call_count == 1
    assert not any(
        e.event_type.value == "PROVIDER_PROBE_SUPPRESSED" for e in _events(in_memory_uow)
    )
    assert not any(
        e.event_type.value == "PROVIDER_PROBE_EXECUTED" for e in _events(in_memory_uow)
    )


async def test_successful_recovery_leaves_success_evidence(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch, max_per_hour=2)
    _setup_exhausted(service)
    adapter = _ExpensiveFake(name="codex", available=True)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    assert await service.check_and_probe_provider("codex") is True
    executed = [e for e in _events(in_memory_uow) if e.event_type.value == "PROVIDER_PROBE_EXECUTED"]
    assert executed[0].payload.get("result") == "success"
    assert any(
        e.event_type.value == "PRIMARY_CAPACITY_RECOVERED" for e in _events(in_memory_uow)
    )


async def test_repeated_scheduler_cycles_do_not_exceed_max_per_hour(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch, max_per_hour=2)
    _setup_exhausted(service)
    adapter = _ExpensiveFake(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    for _ in range(10):
        await service.probe_unavailable_providers()
    assert adapter.probe_call_count == 2
    executed = [e for e in _events(in_memory_uow) if e.event_type.value == "PROVIDER_PROBE_EXECUTED"]
    suppressed = [
        e for e in _events(in_memory_uow) if e.event_type.value == "PROVIDER_PROBE_SUPPRESSED"
    ]
    assert len(executed) == 2
    assert len(suppressed) >= 1


async def test_probe_does_not_increment_implementation_retry_budget(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch, max_per_hour=1)
    _setup_exhausted(service)
    adapter = _ExpensiveFake(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    await service.check_and_probe_provider("codex")
    await service.check_and_probe_provider("codex")  # suppressed
    assert in_memory_uow.jobs.list_active_jobs() == []
    assert in_memory_uow.orchestration_runs.list_runs() == []
    retry_events = {
        "ATTEMPT_STARTED",
        "ATTEMPT_COMPLETED",
        "CORRECTIVE_RETRY_ISSUED",
        "AGENT_REASSIGNED",
    }
    assert not any(
        e.event_type.value in retry_events for e in _events(in_memory_uow)
    )


async def test_suppressed_probe_does_not_increment_retry_budget(in_memory_uow, monkeypatch):
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch, max_per_hour=1)
    _setup_exhausted(service)
    adapter = _ExpensiveFake(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    await service.check_and_probe_provider("codex")
    await service.check_and_probe_provider("codex")  # suppressed
    assert adapter.probe_call_count == 1
    assert in_memory_uow.jobs.list_active_jobs() == []
    assert in_memory_uow.orchestration_runs.list_runs() == []


async def test_unrelated_events_do_not_erase_rate_limit_truth(in_memory_uow, monkeypatch):
    """Leaf B: >1000 unrelated events must not displace the durable rate-limit
    truth (previously an arbitrary 1000-event global slice could erase it)."""
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch, max_per_hour=1)
    _setup_exhausted(service)
    adapter = _ExpensiveFake(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    await service.check_and_probe_provider("codex")
    assert adapter.probe_call_count == 1

    for i in range(1100):
        in_memory_uow.events.save(
            Event(
                event_type=EventType.PROVIDER_HEALTH_UPDATED,
                payload={"provider": "antigravity", "n": i},
                timestamp=clock(),
            )
        )

    await service.check_and_probe_provider("codex")
    assert adapter.probe_call_count == 1
    assert (
        in_memory_uow.events.count_events(
            EventType.PROVIDER_PROBE_SUPPRESSED.value, provider="codex"
        )
        == 1
    )


async def test_concurrent_eligible_checks_do_not_exceed_bound(in_memory_uow, monkeypatch):
    """Leaf B: concurrent eligibility checks must not exceed configured max_per_hour."""
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch, max_per_hour=2)
    _setup_exhausted(service)
    adapter = _ExpensiveFake(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    await asyncio.gather(
        *[service.check_and_probe_provider("codex") for _ in range(20)]
    )
    assert adapter.probe_call_count == 2


async def test_repeated_suppressed_ticks_bounded_suppression_evidence(
    in_memory_uow, monkeypatch
):
    """Leaf B: repeated suppressed scheduler ticks must not emit unbounded
    suppression evidence (bounded to one event per provider per hour)."""
    clock = _Clock()
    service = _service(in_memory_uow, clock, monkeypatch, max_per_hour=1)
    _setup_exhausted(service)
    adapter = _ExpensiveFake(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    await service.check_and_probe_provider("codex")
    for _ in range(30):
        await service.check_and_probe_provider("codex")
    assert adapter.probe_call_count == 1
    suppressed = [
        e for e in _events(in_memory_uow) if e.event_type.value == "PROVIDER_PROBE_SUPPRESSED"
    ]
    assert len(suppressed) == 1
