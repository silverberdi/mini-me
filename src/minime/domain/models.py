"""Domain models for mini me."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from minime.domain.enums import (
    ChangeStatus,
    EventType,
    FindingSeverity,
    JobStatus,
    ProjectStatus,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
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


class Job(BaseModel):
    """Durable execution job state for an implementation pipeline run."""

    job_id: str = Field(default_factory=generate_uuid)
    project_id: str
    change_name: str
    status: JobStatus = JobStatus.QUEUED
    implementer_role: str
    candidate_sha: str | None = None
    base_sha: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class JobLog(BaseModel):
    """Redacted job output or system log line."""

    log_id: str = Field(default_factory=generate_uuid)
    job_id: str
    stream: str
    message: str
    timestamp: datetime = Field(default_factory=utc_now)


class CheckResult(BaseModel):
    """Evidence record for a deterministic check command."""

    result_id: str = Field(default_factory=generate_uuid)
    job_id: str
    check_name: str
    command: str
    exit_code: int
    duration_ms: int
    output_snippet: str
    created_at: datetime = Field(default_factory=utc_now)


class ReviewFinding(BaseModel):
    """Structured finding emitted by a complementary reviewer."""

    finding_id: str = Field(default_factory=generate_uuid)
    review_id: str
    severity: FindingSeverity
    location: str | None = None
    violated_requirement: str
    expected_correction: str
    created_at: datetime = Field(default_factory=utc_now)


class Review(BaseModel):
    """Durable review state record for an implementation candidate."""

    review_id: str = Field(default_factory=generate_uuid)
    job_id: str
    project_id: str
    change_name: str
    reviewer_role: str
    candidate_sha: str
    base_sha: str
    status: ReviewStatus = ReviewStatus.REVIEW_PENDING
    verdict: ReviewVerdict | None = None
    summary: str | None = None
    error_message: str | None = None
    findings: list[ReviewFinding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReviewFindingPayload(BaseModel):
    """Finding item within structured reviewer payload."""

    severity: FindingSeverity
    location: str | None = None
    violated_requirement: str
    expected_correction: str


class ReviewVerdictPayload(BaseModel):
    """Structured payload contract required from complementary reviewer."""

    verdict: ReviewVerdict
    summary: str = ""
    findings: list[ReviewFindingPayload] = Field(default_factory=list)

