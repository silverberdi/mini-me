"""Transactional PostgreSQL notifications for persisted orchestration transitions."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

RUN_TRANSITION_CHANNEL = "minime_run_transition"


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
