"""Relay committed scheduler Run transitions from PostgreSQL to API SSE clients."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from psycopg import AsyncConnection

from minime.db.notifications import RUN_TRANSITION_CHANNEL
from minime.domain.enums import OrchestrationStage

logger = logging.getLogger(__name__)

EventPublisher = Callable[[str, dict[str, Any]], Awaitable[None]]


class PostgresRunEventListener:
    """Own one reconnecting LISTEN connection for scheduler stage transitions."""

    _INITIAL_RETRY_SECONDS = 0.5
    _MAX_RETRY_SECONDS = 30.0
    _MAX_PAYLOAD_BYTES = 512

    def __init__(self, database_url: str, publish: EventPublisher) -> None:
        self._database_url = database_url
        self._publish = publish
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen_forever(), name="postgres-run-event-listener")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _listen_forever(self) -> None:
        retry_seconds = self._INITIAL_RETRY_SECONDS
        while True:
            try:
                async with await AsyncConnection.connect(
                    self._database_url,
                    autocommit=True,
                    application_name="minime-api-run-event-listener",
                ) as connection:
                    await connection.execute(f"LISTEN {RUN_TRANSITION_CHANNEL}")
                    logger.info("PostgreSQL Run event listener connected")
                    # Reconcile streams that connected while LISTEN was unavailable,
                    # including the API's first successful listener connection.
                    await self._publish("run.resync", {"scope": "selected_project"})
                    retry_seconds = self._INITIAL_RETRY_SECONDS

                    async for notification in connection.notifies():
                        await self._handle_notification(
                            notification.channel, notification.payload
                        )
                    raise ConnectionError("PostgreSQL notification stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "PostgreSQL Run event listener disconnected; retrying (%s)",
                    type(exc).__name__,
                )
                await asyncio.sleep(retry_seconds)
                retry_seconds = min(retry_seconds * 2, self._MAX_RETRY_SECONDS)

    async def _handle_notification(self, channel: str, payload: str) -> None:
        if channel != RUN_TRANSITION_CHANNEL or len(payload.encode("utf-8")) > self._MAX_PAYLOAD_BYTES:
            logger.warning("Rejected malformed PostgreSQL Run transition notification")
            return
        try:
            data = json.loads(payload)
            if not isinstance(data, dict) or set(data) != {"project_id", "run_id", "stage"}:
                raise ValueError("invalid fields")
            project_id = data["project_id"]
            run_id = data["run_id"]
            stage = data["stage"]
            if (
                not isinstance(project_id, str)
                or not project_id
                or len(project_id) > 128
                or not isinstance(run_id, str)
                or not run_id
                or len(run_id) > 64
                or not isinstance(stage, str)
                or OrchestrationStage(stage).value != stage
            ):
                raise ValueError("invalid transition identity")
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("Rejected malformed PostgreSQL Run transition notification")
            return

        await self._publish(
            "run.transition",
            {"project_id": project_id, "run_id": run_id, "stage": stage},
        )
