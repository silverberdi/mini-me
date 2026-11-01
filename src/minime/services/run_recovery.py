"""Startup recovery over the existing fenced claim authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from minime.domain.interfaces import PersistenceUnitOfWork


class RunRecoveryService:
    def __init__(self, uow: PersistenceUnitOfWork, stale_after: timedelta = timedelta(seconds=90)):
        self.uow = uow
        self.stale_after = stale_after

    def discover_and_claim(self) -> list[tuple[str, str]]:
        """Return only runs durably claimed by this process; losers do no dispatch."""
        now = datetime.now(UTC)
        recovered: list[tuple[str, str]] = []
        for run in self.uow.orchestration_runs.list_runs(is_active=True):
            updated = run.updated_at.astimezone(UTC) if run.updated_at.tzinfo else run.updated_at.replace(tzinfo=UTC)
            if now - updated < self.stale_after:
                continue
            claim = self.uow.claims.acquire_or_reacquire(
                f"orchestration-run:{run.run_id}", f"recovery-{uuid4()}", lease_seconds=90
            )
            if claim is not None:
                recovered.append((run.project_id, run.run_id))
        if recovered:
            self.uow.commit()
        return recovered
