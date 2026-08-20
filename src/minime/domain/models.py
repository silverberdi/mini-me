"""Domain models for mini me."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ProjectStatus,
    ReadinessState,
)


def utc_now() -> datetime:
    """Return the current datetime with UTC timezone."""
    return datetime.now(UTC)


def generate_uuid() -> str:
    """Generate a UUID4 hex string."""
    return str(uuid.uuid4())


class Project(BaseModel):
    """Project domain model with immutable internal project_id."""

    project_id: str
    display_name: str
    repository: str
    base_branch: str = "main"
    openspec_path: str = "openspec"
    implementer: str = "codex"
    reviewer: str = "antigravity"
    checks: list[dict[str, Any]] = Field(default_factory=list)
    external_providers_allowed: list[str] = Field(
        default_factory=lambda: ["codex", "antigravity", "deepseek"]
    )
    openrouter_drain_allowed: bool = False
    deployment_preview: dict[str, Any] = Field(default_factory=dict)
    deployment_production: dict[str, Any] = Field(default_factory=dict)
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ProjectBinding(BaseModel):
    """Durable project-repository-work binding model."""

    binding_id: str = Field(default_factory=generate_uuid)
    project_id: str
    repository: str
    github_issue_number: int | None = None
    github_project_item_id: str | None = None
    openspec_change_name: str
    is_valid: bool = True
    mismatch_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Change(BaseModel):
    """OpenSpec change domain model."""

    change_id: str = Field(default_factory=generate_uuid)
    project_id: str
    name: str
    status: ChangeStatus = ChangeStatus.DISCOVERED
    stage: str | None = None
    schema_name: str = "spec-driven"
    proposal_path: str | None = None
    tasks_path: str | None = None
    design_path: str | None = None
    specs_paths: list[str] = Field(default_factory=list)
    last_readiness_status: ReadinessState = ReadinessState.NOT_READY
    last_readiness_reasons: list[str] = Field(default_factory=list)
    discovered_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReadinessCheck(BaseModel):
    """Individual readiness check outcome."""

    name: str
    passed: bool
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ReadinessEvaluation(BaseModel):
    """Result of Definition of Ready (DoR) evaluation."""

    change_id: str
    project_id: str
    status: ReadinessState
    is_ready: bool
    unmet_reasons: list[str] = Field(default_factory=list)
    checks: list[ReadinessCheck] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=utc_now)


class Event(BaseModel):
    """Durable operational and audit event."""

    event_id: str = Field(default_factory=generate_uuid)
    event_type: EventType
    project_id: str | None = None
    change_id: str | None = None
    operation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class MetricFact(BaseModel):
    """Timestamped fact for calculating cycle/lead time and attempt metrics."""

    fact_id: str = Field(default_factory=generate_uuid)
    metric_name: str
    project_id: str | None = None
    change_id: str | None = None
    stage: str | None = None
    duration_ms: int | None = None
    fact_value: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=utc_now)
