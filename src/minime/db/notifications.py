"""Transactional PostgreSQL notifications for persisted orchestration transitions."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

RUN_TRANSITION_CHANNEL = "minime_run_transition"
SCHEDULER_WAKEUP_CHANNEL = "minime_scheduler_wakeup"
SCHEDULER_WAKEUP_MAX_PAYLOAD_BYTES = 512


def notify_scheduler_wakeup(
    session: Session, *, project_id: str, run_id: str, action_id: str, reason: str
) -> None:
    """Queue an ephemeral Scheduler hint in the current transaction."""
    payload: dict[str, Any] = {
        "project_id": project_id,
        "run_id": run_id,
        "action_id": action_id,
        "reason": reason,
    }
    serialized = json.dumps(payload, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > SCHEDULER_WAKEUP_MAX_PAYLOAD_BYTES:
        raise ValueError("Scheduler wake-up notification payload exceeds 512 bytes")
    session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": SCHEDULER_WAKEUP_CHANNEL, "payload": serialized},
    )


def notify_run_transition(
    session: Session, *, project_id: str, run_id: str, stage: str
) -> None:
    """Queue a minimal Run transition hint in the current database transaction."""
    payload: dict[str, Any] = {
        "project_id": project_id,
        "run_id": run_id,
        "stage": stage,
    }
    serialized = json.dumps(payload, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > 512:
        raise ValueError("Run transition notification payload exceeds 512 bytes")

    session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": RUN_TRANSITION_CHANNEL, "payload": serialized},
    )
