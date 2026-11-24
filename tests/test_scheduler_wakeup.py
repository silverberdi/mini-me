from __future__ import annotations

import asyncio
import json

import pytest

from minime.db.notifications import SCHEDULER_WAKEUP_CHANNEL
from minime.services.scheduler_wakeup import SchedulerWakeupListener, parse_scheduler_wakeup


def _payload(**overrides: str) -> str:
    data = {
        "project_id": "project-1",
        "run_id": "run-1",
        "action_id": "action-1",
        "reason": "accepted_action",
    }
    data.update(overrides)
    return json.dumps(data, separators=(",", ":"))


def test_scheduler_wakeup_payload_is_strict_and_separate_from_sse():
    assert parse_scheduler_wakeup(SCHEDULER_WAKEUP_CHANNEL, _payload()).run_id == "run-1"
    assert parse_scheduler_wakeup(
        SCHEDULER_WAKEUP_CHANNEL, _payload(reason="watchdog_diagnosis")
    ).reason == "watchdog_diagnosis"
    assert parse_scheduler_wakeup("minime_run_transition", _payload()) is None
    assert parse_scheduler_wakeup(SCHEDULER_WAKEUP_CHANNEL, "{}") is None
    assert parse_scheduler_wakeup(SCHEDULER_WAKEUP_CHANNEL, _payload(reason="scheduler_transition")) is None
    assert parse_scheduler_wakeup(SCHEDULER_WAKEUP_CHANNEL, _payload(reason="stale")) is None
    assert parse_scheduler_wakeup(SCHEDULER_WAKEUP_CHANNEL, _payload(run_id="")) is None
    assert parse_scheduler_wakeup(SCHEDULER_WAKEUP_CHANNEL, "x" * 513) is None


@pytest.mark.asyncio
async def test_invalid_wakeup_does_not_reconcile_and_concurrent_duplicates_coalesce():
    reasons: list[str] = []

    async def reconcile(reason: str) -> None:
        reasons.append(reason)
        await asyncio.sleep(0.01)

    listener = SchedulerWakeupListener("postgresql://unused", reconcile)
    await listener._handle_notification(SCHEDULER_WAKEUP_CHANNEL, "{}")
    assert reasons == []
    await asyncio.gather(
        listener._handle_notification(SCHEDULER_WAKEUP_CHANNEL, _payload()),
        listener._handle_notification(SCHEDULER_WAKEUP_CHANNEL, _payload()),
    )
    assert reasons == ["wake-up"]
    assert listener._wake_event.is_set() is False


@pytest.mark.asyncio
async def test_scheduler_wakeup_listener_reconciles_again_after_coalesced_cycle():
    reasons: list[str] = []

    async def reconcile(reason: str) -> None:
        reasons.append(reason)

    listener = SchedulerWakeupListener("postgresql://unused", reconcile)
    await listener._handle_notification(SCHEDULER_WAKEUP_CHANNEL, _payload())
    await listener._handle_notification(SCHEDULER_WAKEUP_CHANNEL, _payload())

    assert reasons == ["wake-up", "wake-up"]
    assert listener._wake_event.is_set() is False


@pytest.mark.asyncio
async def test_listener_stop_is_cancelable_and_reconnect_calls_same_reconciliation():
    reasons: list[str] = []

    async def reconcile(reason: str) -> None:
        reasons.append(reason)

    listener = SchedulerWakeupListener("postgresql://unused", reconcile)
    await listener.reconcile_startup()
    assert reasons == ["startup"]
    await listener.stop()
