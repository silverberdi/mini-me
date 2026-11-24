"""Ephemeral PostgreSQL wake-ups for the existing Scheduler reconciliation."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from psycopg import AsyncConnection

from minime.db.notifications import SCHEDULER_WAKEUP_CHANNEL, SCHEDULER_WAKEUP_MAX_PAYLOAD_BYTES

logger = logging.getLogger(__name__)

_VALID_WAKEUP_REASONS = frozenset({"accepted_action"})


@dataclass(frozen=True)
class SchedulerWakeup:
    project_id: str
    run_id: str
    action_id: str
    reason: str


def parse_scheduler_wakeup(channel: str, payload: str) -> SchedulerWakeup | None:
    """Validate a hint; invalid input is never allowed to trigger reconciliation."""
    if channel != SCHEDULER_WAKEUP_CHANNEL:
        return None
    if len(payload.encode("utf-8")) > SCHEDULER_WAKEUP_MAX_PAYLOAD_BYTES:
        return None
    try:
        data = json.loads(payload)
        fields = ("project_id", "run_id", "action_id", "reason")
        if not isinstance(data, dict) or set(data) != set(fields):
            return None
        values = {key: data[key] for key in fields}
        if any(not isinstance(value, str) or not value for value in values.values()):
            return None
        limits = {"project_id": 128, "run_id": 64, "action_id": 128, "reason": 64}
        if any(len(values[key]) > limit for key, limit in limits.items()):
            return None
        if values["reason"] not in _VALID_WAKEUP_REASONS:
            return None
        return SchedulerWakeup(**values)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


Reconcile = Callable[[str], Awaitable[None]]


class SchedulerWakeupListener:
    """Cancelable, reconnecting LISTEN connection; hints are never queued."""

    _INITIAL_RETRY_SECONDS = 0.5
    _MAX_RETRY_SECONDS = 30.0

    def __init__(self, database_url: str, reconcile: Reconcile) -> None:
        self._database_url = database_url
        self._reconcile = reconcile
        self._task: asyncio.Task[None] | None = None
        self._reconcile_lock = asyncio.Lock()
        self._wake_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen_forever(), name="scheduler-wakeup-listener")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def wait_for_wakeup(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        self._wake_event.clear()
        return True

    async def reconcile_startup(self) -> None:
        await self._reconcile_once("startup")

    async def _listen_forever(self) -> None:
        retry_seconds = self._INITIAL_RETRY_SECONDS
        while True:
            try:
                async with await AsyncConnection.connect(
                    self._database_url, autocommit=True, application_name="minime-scheduler-wakeup"
                ) as connection:
                    await connection.execute(f"LISTEN {SCHEDULER_WAKEUP_CHANNEL}")
                    await self._reconcile_once("reconnect")
                    retry_seconds = self._INITIAL_RETRY_SECONDS
                    async for notification in connection.notifies():
                        await self._handle_notification(notification.channel, notification.payload)
                    raise ConnectionError("Scheduler wake-up notification stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Scheduler wake-up listener disconnected; retrying (%s)", type(exc).__name__)
                await asyncio.sleep(retry_seconds)
                retry_seconds = min(retry_seconds * 2, self._MAX_RETRY_SECONDS)

    async def _handle_notification(self, channel: str, payload: str) -> None:
        hint = parse_scheduler_wakeup(channel, payload)
        if hint is None:
            logger.warning("Rejected malformed Scheduler wake-up notification")
            return
        # NOTIFY is a hint, not a queue.  Keep one in-flight wake-up marker only
        # for the duration of reconciliation, so a burst coalesces without
        # leaving an in-memory item behind after the work has been observed.
        if self._wake_event.is_set():
            return
        self._wake_event.set()
        try:
            await self._reconcile_once("wake-up")
        finally:
            self._wake_event.clear()

    async def _reconcile_once(self, reason: str) -> None:
        if self._reconcile_lock.locked():
            self._wake_event.set()
            return
        async with self._reconcile_lock:
            await self._reconcile(reason)


class SchedulerWakeupBridge:
    """Thread-safe bridge for the synchronous CLI Scheduler loop."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listener: SchedulerWakeupListener | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        def run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._listener = SchedulerWakeupListener(self._database_url, self._mark_wakeup)
            self._loop.run_until_complete(self._listener.start())
            self._loop.run_forever()
            self._loop.run_until_complete(self._listener.stop())
            self._loop.close()

        self._thread = threading.Thread(target=run, name="scheduler-wakeup-listener", daemon=True)
        self._thread.start()

    async def _mark_wakeup(self, _reason: str) -> None:
        self._event.set()

    def wait(self, timeout: float) -> bool:
        triggered = self._event.wait(timeout)
        self._event.clear()
        return triggered

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
            self._loop = None
