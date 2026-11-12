"""Small process-local event broker used by the PWA SSE stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any


class EventBroker:
    """Fan out bounded operational events without becoming durable state."""

    def __init__(
        self,
        max_subscribers: int = 128,
        queue_size: int = 64,
        keepalive_seconds: float = 15.0,
    ) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._reconnect_required: set[asyncio.Queue[dict[str, Any]]] = set()
        self._max_subscribers = max_subscribers
        self._queue_size = queue_size
        self._keepalive_seconds = keepalive_seconds
        self._lock = asyncio.Lock()

    async def subscribe(self) -> AsyncIterator[str]:
        if len(self._subscribers) >= self._max_subscribers:
            raise RuntimeError("event stream capacity exhausted")
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=self._keepalive_seconds)
                    yield f"event: {event['type']}\ndata: {json.dumps(event['data'], separators=(',', ':'))}\n\n"
                    if queue in self._reconnect_required:
                        return
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            async with self._lock:
                self._subscribers.discard(queue)
                self._reconnect_required.discard(queue)

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        event = {"type": event_type, "data": data}
        async with self._lock:
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                if event_type == "run.transition":
                    self._reconnect_required.add(queue)


event_broker = EventBroker()
