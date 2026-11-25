"""Deterministic, ledger-backed temporal telemetry for the operations dashboard."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _value(item: Any, name: str, default: Any = None) -> Any:
    return getattr(item, name, default)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class TemporalTelemetryPointDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    value: float
    source_timestamps: list[str] = Field(min_length=1)
    quality: str = "verified"

    @model_validator(mode="after")
    def require_verifiable_observation(self) -> "TemporalTelemetryPointDTO":
        if not self.timestamp.strip() or not self.source_timestamps:
            raise ValueError("temporal telemetry points require timestamp and source")
        return self


class TemporalTelemetrySeriesDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str
    label: str
    project_id: str | None = None
    color: str
    points: list[TemporalTelemetryPointDTO] = Field(default_factory=list)
    no_data: bool = False


class TemporalTelemetryProjectionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    window_days: int
    granularity: str
    axis: list[str] = Field(default_factory=list)
    series: list[TemporalTelemetrySeriesDTO] = Field(default_factory=list)
    no_data: bool = True
    units: str
    excluded: dict[str, int] = Field(default_factory=dict)


class TemporalMultiseriesTelemetryService:
    """Projects durable run, interval and settlement facts into one read model."""

    DIMENSIONS = {"autonomy", "time", "cost"}
    COLORS = ("#f8fafc", "#38bdf8", "#a78bfa", "#34d399", "#fbbf24", "#fb7185")

    def __init__(self, uow: Any) -> None:
        self.uow = uow

    def project(
        self,
        dimension: str = "autonomy",
        window_days: int = 30,
        granularity: str | None = None,
    ) -> TemporalTelemetryProjectionDTO:
        if dimension not in self.DIMENSIONS:
            raise ValueError(f"unsupported temporal telemetry dimension: {dimension}")
        window_days = max(1, min(int(window_days), 90))
        granularity = granularity or ("daily" if window_days <= 30 else "weekly")
        if granularity not in {"daily", "weekly"}:
            raise ValueError("granularity must be daily or weekly")

        now = datetime.now(UTC)
        start = (now - timedelta(days=window_days - 1)).date()
        projects = list(getattr(self.uow.projects, "list_all", lambda: [])())
        project_ids = [str(_value(p, "project_id")) for p in projects if _value(p, "project_id")]
        runs = list(getattr(self.uow.orchestration_runs, "list_runs", lambda: [])())
        observations: dict[str, dict[str, list[tuple[datetime, float, list[str]]]]] = defaultdict(lambda: defaultdict(list))
        excluded: dict[str, int] = defaultdict(int)
        for run in runs:
            observation_time = (
                _timestamp(_value(run, "completed_at"))
                or _timestamp(_value(run, "updated_at"))
                or _timestamp(_value(run, "created_at"))
            )
            if observation_time is None or observation_time.date() < start:
                continue
            observed = self._observation(run, dimension)
            if observed is None:
                excluded["unverified_or_incomplete"] += 1
                continue
            timestamp, value, sources, excluded_waits = observed
            if excluded_waits:
                excluded["human_gate_wait_intervals"] += excluded_waits
            bucket = self._bucket(timestamp, granularity)
            observations[str(_value(run, "project_id"))][bucket].append((timestamp, value, sources))

        axis = self._axis(start, now.date(), granularity)
        series: list[TemporalTelemetrySeriesDTO] = []
        for index, project_id in enumerate(project_ids):
            points = self._points(
                observations.get(project_id, {}),
                axis,
                percentage=dimension == "autonomy",
            )
            series.append(TemporalTelemetrySeriesDTO(
                series_id=f"project:{project_id}",
                label=self._project_label(projects, project_id),
                project_id=project_id,
                color=self.COLORS[(index + 1) % len(self.COLORS)],
                points=points,
                no_data=not bool(points),
            ))

        global_points: list[TemporalTelemetryPointDTO] = []
        for bucket in axis:
            values = [
                item for project in observations.values() for item in project.get(bucket, [])
            ]
            if values:
                global_points.append(
                    self._point(bucket, values, percentage=dimension == "autonomy")
                )
        series.insert(0, TemporalTelemetrySeriesDTO(
            series_id="global",
            label="Global (Todos los proyectos)",
            color=self.COLORS[0],
            points=global_points,
            no_data=not bool(global_points),
        ))
        return TemporalTelemetryProjectionDTO(
            dimension=dimension,
            window_days=window_days,
            granularity=granularity,
            axis=axis,
            series=series,
            no_data=not bool(global_points),
            units={"autonomy": "%", "time": "min", "cost": "USD"}[dimension],
            excluded=dict(excluded),
        )

    def _observation(self, run: Any, dimension: str) -> tuple[datetime, float, list[str], int] | None:
        timestamp = _timestamp(_value(run, "completed_at")) or _timestamp(_value(run, "updated_at")) or _timestamp(_value(run, "created_at"))
        if timestamp is None:
            return None
        if dimension == "autonomy":
            if _value(run, "is_active", True):
                return None
            stage = _value(_value(run, "current_stage"), "value", _value(run, "current_stage"))
            outcome = _value(_value(run, "stop_outcome"), "value", _value(run, "stop_outcome"))
            if str(stage).upper() != "COMPLETED" and str(outcome).upper() != "COMPLETED":
                return None
            events_repo = getattr(self.uow, "orchestration_stage_events", None)
            events = (
                list(events_repo.list_by_run(_value(run, "run_id")))
                if events_repo and hasattr(events_repo, "list_by_run") else []
            )
            details = _value(run, "stop_details", {}) or {}
            resolved_gates = details.get("resolved_human_gates")
            if not events:
                return None
            if resolved_gates is None:
                has_run_evidence = bool(
                    details.get("pr1_url")
                    or details.get("pr2_url")
                    or details.get("test_evidence")
                    or details.get("complexity")
                    or details.get("apply_limits")
                )
                if not has_run_evidence:
                    return None
                resolved_gates = []
            elif not isinstance(resolved_gates, list):
                return None
            actions_repo = getattr(self.uow, "operator_actions", None)
            actions = (
                list(actions_repo.list_by_run(_value(run, "run_id")))
                if actions_repo and hasattr(actions_repo, "list_by_run") else []
            )
            source_times = [
                _iso(_timestamp(_value(event, "created_at")) or timestamp) for event in events
            ]
            return timestamp, 0.0 if resolved_gates or actions else 1.0, source_times, 0
        if dimension == "time":
            duration, sources, excluded = self._machine_duration(run)
            if duration is None:
                return None
            return timestamp, round(duration / 60000.0, 3), sources, excluded
        amount = self._liquidated_cost(run)
        if amount is None:
            return None
        return timestamp, float(amount), [_iso(timestamp)], 0

    def _metrics(self, run: Any) -> Any | None:
        repo = getattr(self.uow, "provider_efficiency", None)
        getter = getattr(repo, "get_by_run_id", None)
        return getter(_value(run, "run_id")) if callable(getter) else None

    def _machine_duration(self, run: Any) -> tuple[int | None, list[str], int]:
        events_repo = getattr(self.uow, "orchestration_stage_events", None)
        events = list(events_repo.list_by_run(_value(run, "run_id"))) if events_repo and hasattr(events_repo, "list_by_run") else []
        duration = 0
        sources: list[str] = []
        excluded = 0
        for event in events:
            refs = _value(event, "evidence_references", {}) or {}
            ms = refs.get("duration_ms") if refs.get("duration_ms") is not None else refs.get("active_machine_duration_ms", refs.get("stage_duration_ms"))
            stage = str(_value(_value(event, "from_stage"), "value", _value(event, "from_stage", ""))).upper()
            if ms is None:
                continue
            if "HUMAN" in stage or "GATE" in stage or refs.get("interval_type") == "human_gate_wait":
                excluded += 1
                continue
            duration += max(0, int(ms))
            created = _timestamp(_value(event, "created_at"))
            if created:
                sources.append(_iso(created))
        if duration:
            if not sources:
                created = _timestamp(_value(run, "created_at"))
                if created:
                    sources.append(_iso(created))
            return duration, sorted(set(sources)), excluded
        attempts_repo = getattr(self.uow, "job_attempts", None)
        job_id = _value(run, "active_job_id")
        attempts = list(attempts_repo.list_by_job(job_id)) if attempts_repo and job_id and hasattr(attempts_repo, "list_by_job") else []
        duration = sum(int(_value(a, "duration_ms", 0) or 0) for a in attempts)
        return (duration, [_iso(_timestamp(_value(run, "created_at")) or datetime.now(UTC))], excluded) if duration else (None, [], excluded)

    def _liquidated_cost(self, run: Any) -> Decimal | None:
        repo = getattr(self.uow, "budget_ledger", None)
        entries = list(repo.list_by_project(_value(run, "project_id"))) if repo and hasattr(repo, "list_by_project") else []
        total = Decimal("0")
        found = False
        for entry in entries:
            if _value(entry, "change_id") != _value(run, "change_name") and _value(entry, "job_id") != _value(run, "active_job_id"):
                continue
            entry_type = str(_value(entry, "entry_type", "")).upper()
            if entry_type not in {"SETTLEMENT", "BREACH_SETTLEMENT"}:
                continue
            if not (_value(entry, "reservation_id") or _value(entry, "usage_identity")):
                continue
            try:
                amount = Decimal(str(_value(entry, "amount_usd")))
            except Exception:
                continue
            if amount.is_finite() and amount >= 0:
                total += amount
                found = True
        return total if found else None

    @staticmethod
    def _bucket(timestamp: datetime, granularity: str) -> str:
        day = timestamp.date()
        if granularity == "daily":
            return day.isoformat()
        return (day - timedelta(days=day.weekday())).isoformat()

    def _axis(self, start: Any, end: Any, granularity: str) -> list[str]:
        current = start
        if granularity == "weekly":
            current -= timedelta(days=current.weekday())
        result: list[str] = []
        while current <= end:
            result.append(current.isoformat())
            current += timedelta(days=1 if granularity == "daily" else 7)
        return result

    @staticmethod
    def _points(
        values: dict[str, list[tuple[datetime, float, list[str]]]],
        axis: list[str],
        *,
        percentage: bool = False,
    ) -> list[TemporalTelemetryPointDTO]:
        return [
            TemporalMultiseriesTelemetryService._point(
                bucket, values[bucket], percentage=percentage
            )
            for bucket in axis
            if bucket in values
        ]

    @staticmethod
    def _point(
        bucket: str,
        values: list[tuple[datetime, float, list[str]]],
        *,
        percentage: bool = False,
    ) -> TemporalTelemetryPointDTO:
        average = sum(value for _, value, _ in values) / len(values)
        if percentage:
            average *= 100
        return TemporalTelemetryPointDTO(
            timestamp=bucket,
            value=round(average, 3),
            source_timestamps=sorted(
                {source for _, _, sources in values for source in sources}
            ),
        )

    @staticmethod
    def _project_label(projects: Iterable[Any], project_id: str) -> str:
        for project in projects:
            if str(_value(project, "project_id")) == project_id:
                return str(_value(project, "display_name") or _value(project, "name") or project_id)
        return project_id


# Keep the long class name typo-free at the call site while preserving a small
# compatibility alias for early consumers of the service.
TemporalTelemetryService = TemporalMultiseriesTelemetryService


def _iso(timestamp: datetime) -> str:
    return timestamp.astimezone(UTC).isoformat()
