"""Read-only, fixed-target observation of the scheduler's systemd unit."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

UNIT_NAME = "minime-scheduler.service"
SYSTEMD_BUS_NAME = "org.freedesktop.systemd1"
SYSTEMD_MANAGER_PATH = "/org/freedesktop/systemd1"
SYSTEMD_MANAGER_INTERFACE = "org.freedesktop.systemd1.Manager"
SYSTEMD_UNIT_INTERFACE = "org.freedesktop.systemd1.Unit"
DBUS_PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
SOURCE = "systemd-dbus-read-only"
MAX_AGE_SECONDS = 30.0
READ_TIMEOUT_SECONDS = 1.0

_ACTIVE_STATES = {"active", "inactive", "activating", "deactivating", "failed"}


@dataclass(frozen=True)
class SchedulerServiceObservation:
    active_state: str = "UNKNOWN"
    sub_state: str = "UNKNOWN"
    enabled_state: str = "UNKNOWN"
    source: str = SOURCE
    observed_at: datetime | None = None
    age_seconds: float | None = None
    freshness: str = "UNKNOWN"
    reason: str = "unavailable"


class SystemdSchedulerObserver:
    """Observe only the known scheduler unit; this class has no control methods."""

    def __init__(
        self,
        reader: Callable[[], Any] | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        timeout_seconds: float = READ_TIMEOUT_SECONDS,
    ) -> None:
        self._reader = reader or self._read_systemd
        self._now = now or (lambda: datetime.now(UTC))
        self._timeout_seconds = min(max(timeout_seconds, 0.001), READ_TIMEOUT_SECONDS)

    def observe(self) -> SchedulerServiceObservation:
        try:
            result = self._reader()
            if inspect.isawaitable(result):
                result = asyncio.run(asyncio.wait_for(result, timeout=self._timeout_seconds))
            return self._normalize(result)
        except TimeoutError:
            return SchedulerServiceObservation(reason="observation_timeout")
        except Exception:
            # Do not expose D-Bus errors or host details in the dashboard read model.
            return SchedulerServiceObservation(reason="observation_unavailable")

    def _normalize(self, result: Any) -> SchedulerServiceObservation:
        if not isinstance(result, dict):
            return SchedulerServiceObservation(reason="malformed_observation")

        observed_at = result.get("observed_at")
        if not isinstance(observed_at, datetime):
            return SchedulerServiceObservation(reason="missing_observation_time")
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        age = (self._now() - observed_at.astimezone(UTC)).total_seconds()
        if age < -1 or age > MAX_AGE_SECONDS:
            return SchedulerServiceObservation(
                observed_at=observed_at,
                age_seconds=max(age, 0.0),
                reason="stale_or_future_observation",
            )

        raw_active = result.get("active_state")
        raw_sub = result.get("sub_state")
        raw_enabled = result.get("unit_file_state")
        if raw_active not in _ACTIVE_STATES or not isinstance(raw_sub, str) or not raw_sub:
            return SchedulerServiceObservation(
                observed_at=observed_at,
                age_seconds=max(age, 0.0),
                freshness="FRESH",
                reason="unsupported_active_state",
            )
        # These combinations cannot describe a coherent systemd unit snapshot.
        # Keep the read model fail-closed rather than showing a stale/contradictory
        # service state as operationally active.
        if (
            (raw_active == "inactive" and raw_sub == "running")
            or (raw_active == "active" and raw_sub in {"dead", "failed"})
            or (raw_active == "failed" and raw_sub != "failed")
        ):
            return SchedulerServiceObservation(
                observed_at=observed_at,
                age_seconds=max(age, 0.0),
                freshness="UNKNOWN",
                reason="contradictory_active_sub_state",
            )

        return SchedulerServiceObservation(
            active_state=raw_active.upper(),
            sub_state=raw_sub,
            enabled_state=("ENABLED" if raw_enabled == "enabled" else "DISABLED")
            if raw_enabled in {"enabled", "disabled"}
            else "UNKNOWN",
            observed_at=observed_at,
            age_seconds=max(age, 0.0),
            freshness="FRESH",
            reason="observed",
        )

    async def _read_systemd(self) -> dict[str, Any]:
        """Use only read-only systemd manager/property methods over the system bus."""
        from dbus_next import BusType, MessageBus

        bus = MessageBus(bus_type=BusType.SYSTEM)
        try:
            await bus.connect()
            manager_intro = await bus.introspect(SYSTEMD_BUS_NAME, SYSTEMD_MANAGER_PATH)
            manager_obj = bus.get_proxy_object(
                SYSTEMD_BUS_NAME, SYSTEMD_MANAGER_PATH, manager_intro
            )
            manager = manager_obj.get_interface(SYSTEMD_MANAGER_INTERFACE)
            unit_path = await manager.call_get_unit(UNIT_NAME)
            unit_intro = await bus.introspect(SYSTEMD_BUS_NAME, unit_path)
            unit_obj = bus.get_proxy_object(SYSTEMD_BUS_NAME, unit_path, unit_intro)
            properties = unit_obj.get_interface(DBUS_PROPERTIES_INTERFACE)
            active = await properties.call_get(SYSTEMD_UNIT_INTERFACE, "ActiveState")
            sub = await properties.call_get(SYSTEMD_UNIT_INTERFACE, "SubState")
            enabled = await manager.call_get_unit_file_state(UNIT_NAME)
            return {
                "active_state": active.value,
                "sub_state": sub.value,
                "unit_file_state": enabled,
                "observed_at": datetime.now(UTC),
            }
        finally:
            # Disconnect is safe when cancellation happened during connect().
            bus.disconnect()
