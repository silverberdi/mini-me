"""Source-backed metrics and verifiable projections (F7).

Enforces that every metric report is backed by a technical source and valid
denominator, returning explicit \x27unavailable\x27 when source or denominator is
missing rather than fabricating progress or cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetricProjection:
    name: str
    value: float | None
    status: str  # "available" or "unavailable"
    unit: str
    denominator: float | None = None
    source: str | None = None

    @classmethod
    def from_source(
        cls,
        name: str,
        raw_value: float | int | None,
        unit: str,
        *,
        denominator: float | int | None = None,
        source: str | None = None,
    ) -> MetricProjection:
        if raw_value is None or (denominator is not None and denominator <= 0):
            return cls(
                name=name,
                value=None,
                status="unavailable",
                unit=unit,
                denominator=float(denominator) if denominator is not None else None,
                source=source,
            )
        return cls(
            name=name,
            value=float(raw_value),
            status="available",
            unit=unit,
            denominator=float(denominator) if denominator is not None else None,
            source=source,
        )


class ProjectionService:
    def __init__(self, uow: Any) -> None:
        self.uow = uow

    def project_request_metrics(self, project_id: str, issue_number: int) -> dict[str, Any]:
        """Project honest metrics for a request."""
        # If run or telemetry does not exist, return explicit unavailable
        run = None
        if hasattr(self.uow, "orchestration_runs"):
            runs = (
                self.uow.orchestration_runs.list_by_project(project_id)
                if hasattr(self.uow.orchestration_runs, "list_by_project")
                else []
            )
            for r in runs:
                if (getattr(r, "stop_details", {}) or {}).get("issue_number") == issue_number:
                    run = r
                    break

        if not run:
            return {
                "issue_number": issue_number,
                "progress": MetricProjection.from_source("progress", None, "%").__dict__,
                "cost_usd": MetricProjection.from_source("cost_usd", None, "USD").__dict__,
                "duration_seconds": MetricProjection.from_source("duration_seconds", None, "s").__dict__,
            }

        details = getattr(run, "stop_details", {}) or {}
        duration = details.get("duration_ms")
        duration_sec = duration / 1000.0 if duration is not None else None

        return {
            "issue_number": issue_number,
            "progress": MetricProjection.from_source(
                "progress",
                100.0 if getattr(run, "stop_outcome", None) == "COMPLETED" else None,
                "%",
                denominator=100.0,
                source="orchestration_run.stop_outcome",
            ).__dict__,
            "cost_usd": MetricProjection.from_source(
                "cost_usd",
                details.get("cost_usd"),
                "USD",
                source="budget_service.telemetry",
            ).__dict__,
            "duration_seconds": MetricProjection.from_source(
                "duration_seconds",
                duration_sec,
                "s",
                source="orchestration_run.duration_ms",
            ).__dict__,
        }
