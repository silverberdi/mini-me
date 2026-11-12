from __future__ import annotations

import asyncio
import json

import pytest

from minime.domain.enums import OrchestrationStage
from minime.services.event_broker import EventBroker
from minime.services.postgres_run_event_listener import PostgresRunEventListener


@pytest.mark.asyncio
async def test_listener_relays_only_valid_run_transition_payloads():
    published = []

    async def publish(event_type, data):
        published.append((event_type, data))

    listener = PostgresRunEventListener("postgresql://unused", publish)
    await listener._handle_notification(
        "minime_run_transition",
        json.dumps({"project_id": "p1", "run_id": "r1", "stage": OrchestrationStage.IMPLEMENTING.value}),
    )
    await listener._handle_notification("minime_run_transition", "{}")
    await listener._handle_notification("wrong_channel", "{}")
    await listener._handle_notification(
        "minime_run_transition",
        json.dumps({"project_id": "p" * 600, "run_id": "r1", "stage": "IMPLEMENTING"}),
    )

    assert published == [
        ("run.transition", {"project_id": "p1", "run_id": "r1", "stage": "IMPLEMENTING"})
    ]


@pytest.mark.asyncio
async def test_transition_queue_overflow_disconnects_only_slow_subscriber():
    broker = EventBroker(queue_size=1, keepalive_seconds=0.01)
    slow = broker.subscribe()
    healthy = broker.subscribe()
    slow_initial = asyncio.create_task(anext(slow))
    healthy_initial = asyncio.create_task(anext(healthy))
    await asyncio.sleep(0)

    await broker.publish("run.transition", {"run_id": "r1"})
    assert (await slow_initial).startswith("event: run.transition")
    assert (await healthy_initial).startswith("event: run.transition")

    await broker.publish("run.transition", {"run_id": "r2"})
    assert '"run_id":"r2"' in await anext(healthy)
    await broker.publish("run.transition", {"run_id": "r3"})

    # The healthy subscriber receives the queued event and remains connected.
    assert '"run_id":"r3"' in await anext(healthy)
    # The slow subscriber stream closes so the browser reconnects and re-reads its snapshot.
    with pytest.raises(StopAsyncIteration):
        await anext(slow)
    assert len(broker._subscribers) == 1
    await healthy.aclose()
