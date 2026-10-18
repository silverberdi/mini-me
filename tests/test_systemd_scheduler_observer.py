from __future__ import annotations

import asyncio
import inspect
import sys
import types
from datetime import UTC, datetime, timedelta

from minime.services.systemd_scheduler_observer import (
    MAX_AGE_SECONDS,
    READ_TIMEOUT_SECONDS,
    SOURCE,
    UNIT_NAME,
    SystemdSchedulerObserver,
)


def _snapshot(now: datetime, **values):
    return {
        "active_state": "active",
        "sub_state": "running",
        "unit_file_state": "enabled",
        "observed_at": now,
        **values,
    }


def test_fixed_unit_and_independent_service_enablement_observation() -> None:
    now = datetime.now(UTC)
    observation = SystemdSchedulerObserver(lambda: _snapshot(now), now=lambda: now).observe()

    assert UNIT_NAME == "minime-scheduler.service"
    assert observation.active_state == "ACTIVE"
    assert observation.sub_state == "running"
    assert observation.enabled_state == "ENABLED"
    assert observation.source == SOURCE
    assert observation.freshness == "FRESH"
    assert observation.age_seconds == 0


def test_inactive_disabled_is_not_inferred_from_logical_mode() -> None:
    now = datetime.now(UTC)
    observation = SystemdSchedulerObserver(
        lambda: _snapshot(now, active_state="inactive", unit_file_state="disabled"),
        now=lambda: now,
    ).observe()

    assert observation.active_state == "INACTIVE"
    assert observation.enabled_state == "DISABLED"


def test_enablement_static_and_unsupported_active_values_stay_unknown() -> None:
    now = datetime.now(UTC)
    static_unit = SystemdSchedulerObserver(
        lambda: _snapshot(now, unit_file_state="static"), now=lambda: now
    ).observe()
    unsupported = SystemdSchedulerObserver(
        lambda: _snapshot(now, active_state="reloading"), now=lambda: now
    ).observe()

    assert static_unit.active_state == "ACTIVE"
    assert static_unit.enabled_state == "UNKNOWN"
    assert unsupported.active_state == "UNKNOWN"
    assert unsupported.freshness == "FRESH"


def test_stale_or_future_observation_is_unknown() -> None:
    now = datetime.now(UTC)
    stale = SystemdSchedulerObserver(
        lambda: _snapshot(now - timedelta(seconds=MAX_AGE_SECONDS + 1)), now=lambda: now
    ).observe()
    future = SystemdSchedulerObserver(
        lambda: _snapshot(now + timedelta(seconds=5)), now=lambda: now
    ).observe()

    assert stale.active_state == "UNKNOWN"
    assert stale.enabled_state == "UNKNOWN"
    assert stale.freshness == "UNKNOWN"
    assert future.active_state == "UNKNOWN"


def test_unavailable_or_malformed_observation_fails_closed() -> None:
    unavailable = SystemdSchedulerObserver(lambda: (_ for _ in ()).throw(OSError())).observe()
    malformed = SystemdSchedulerObserver(lambda: {"active_state": "active"}).observe()

    assert unavailable.active_state == "UNKNOWN"
    assert unavailable.enabled_state == "UNKNOWN"
    assert malformed.active_state == "UNKNOWN"
    assert malformed.reason == "missing_observation_time"


def test_dbus_reader_has_bounded_timeout_and_is_async_read_only() -> None:
    async def slow_reader():
        await asyncio.sleep(0.05)

    observation = SystemdSchedulerObserver(slow_reader, timeout_seconds=0.005).observe()

    assert READ_TIMEOUT_SECONDS == 1.0
    assert observation.reason == "observation_timeout"
    assert inspect.iscoroutinefunction(SystemdSchedulerObserver._read_systemd)
    source = inspect.getsource(SystemdSchedulerObserver._read_systemd)
    assert "call_get_unit(" in source
    assert "call_get_unit_file_state(" in source
    assert "call_start" not in source
    assert "call_stop" not in source
    assert "subprocess" not in source


def test_partial_dbus_connect_is_disconnected_when_observation_times_out(monkeypatch) -> None:
    state = {"disconnected": False}

    class FakeBus:
        def __init__(self, *, bus_type):
            assert bus_type == "system"

        async def connect(self):
            await asyncio.sleep(0.05)

        def disconnect(self):
            state["disconnected"] = True

    fake_module = types.ModuleType("dbus_next")
    fake_module.BusType = types.SimpleNamespace(SYSTEM="system")
    fake_module.MessageBus = FakeBus
    monkeypatch.setitem(sys.modules, "dbus_next", fake_module)

    observation = SystemdSchedulerObserver(timeout_seconds=0.005).observe()

    assert observation.reason == "observation_timeout"
    assert state["disconnected"] is True
