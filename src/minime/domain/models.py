"""Domain models for mini me."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from minime.domain.enums import (
    PRIMARY_PROVIDERS,
    AuditFindingSeverity,
    AuditRiskLevel,
    AuditStatus,
    CapacitySignalSource,
    ChangeStatus,
    EventType,
    FindingSeverity,
    GitOperationStatus,
    JobStatus,
    LockSafetyStatus,
    ProjectStatus,
    ProviderHealthStatus,
    ProviderResultClass,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
    SchedulerMode,
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
    waiting_provider: str | None = None
    capacity_block_reason: str | None = None
    recovery_blocked_reason: str | None = None
    expected_reset_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class OpenRouterBudgetPolicy(BaseModel):
    project_id: str
    enabled: bool = False
    daily_cap_usd: Decimal = Field(default_factory=lambda: Decimal("0.0"))
    monthly_cap_usd: Decimal = Field(default_factory=lambda: Decimal("0.0"))
    currency: str = "USD"
    policy_version: int = 1
    is_breached: bool = False
    updated_at: datetime = Field(default_factory=utc_now)


class OpenRouterPricingSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    snapshot_id: str = Field(alias="id")
    canonical_model_identity: str
    routed_model_identity: str
    prompt_price_per_token: Decimal
    output_price_per_token: Decimal
    additional_cost_per_request: Decimal = Field(default_factory=lambda: Decimal("0.0"))
    currency: str = "USD"
    source: str = "openrouter_catalog_api"
    observed_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)


class BudgetReservation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    reservation_id: str = Field(default_factory=generate_uuid, alias="id")
    project_id: str
    job_id: str
    change_id: str
    role: str
    canonical_model_identity: str
    reserved_amount_usd: Decimal
    status: str
    pricing_snapshot_id: str
    correlation_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BudgetLedgerEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    entry_id: str = Field(default_factory=generate_uuid, alias="id")
    reservation_id: str | None = None
    project_id: str
    job_id: str
    change_id: str
    provider: str = "openrouter"
    role: str
    canonical_model_identity: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    amount_usd: Decimal
    entry_type: str
    created_at: datetime = Field(default_factory=utc_now)


class NormalizedProviderResult(BaseModel):
    """Normalized provider result conforming to schemas/provider-result.schema.json."""

    result_class: ProviderResultClass
    provider: str
    role: str
    model: str | None = None
    retry_after: str | None = None
    capacity_reset_at: datetime | None = None
    summary: str | None = None
    raw_output: str | None = None


class ProviderHealth(BaseModel):
    """Durable primary provider health and availability record."""

    health_id: str = Field(default_factory=generate_uuid)
    provider: str
    model: str | None = None
    status: ProviderHealthStatus = ProviderHealthStatus.AVAILABLE
    consecutive_failures: int = 0
    last_result_class: ProviderResultClass | None = None
    last_error_summary: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    def validate_primary(self) -> None:
        """Enforce that only primary providers (Codex, Antigravity) are tracked."""
        if self.provider not in PRIMARY_PROVIDERS:
            raise ValueError(
                f"Invalid primary provider '{self.provider}'. "
                f"005 capacity tracking is restricted strictly to {PRIMARY_PROVIDERS}."
            )


class CapacityWindow(BaseModel):
    """Durable record of quota exhaustion and reset window."""

    window_id: str = Field(default_factory=generate_uuid)
    provider: str
    model: str | None = None
    quota_exhausted_at: datetime = Field(default_factory=utc_now)
    capacity_reset_at: datetime | None = None
    retry_after_seconds: int | None = None
    source_signal: CapacitySignalSource = CapacitySignalSource.UNKNOWN
    created_at: datetime = Field(default_factory=utc_now)

    def validate_primary(self) -> None:
        """Enforce that only primary providers (Codex, Antigravity) are tracked."""
        if self.provider not in PRIMARY_PROVIDERS:
            raise ValueError(
                f"Invalid primary provider '{self.provider}'. "
                f"005 capacity windows are restricted strictly to {PRIMARY_PROVIDERS}."
            )


class SchedulerStatus(BaseModel):
    """Runtime status of the scheduler and capacity gating."""

    mode: SchedulerMode
    admission_allowed: bool
    active_jobs_count: int
    primary_capacity_available: bool
    reason: str | None = None
    recovery_state: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class LockInspectionResult(BaseModel):
    """Result of safe Git lock ownership and boundary inspection."""

    verdict: LockSafetyStatus
    lock_path: str
    reason: str
    owning_pid: int | None = None
    operation_id: str | None = None
    inspected_at: datetime = Field(default_factory=utc_now)


class GitOperation(BaseModel):
    """Durable record of a Git operation launched by mini me."""

    operation_id: str = Field(default_factory=generate_uuid)
    job_id: str
    project_id: str
    worktree_path: str
    operation_type: str
    pid: int | None = None
    status: GitOperationStatus = GitOperationStatus.RUNNING
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


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


class AuditFinding(BaseModel):
    """Structured finding emitted by DeepSeek Direct audit."""

    finding_id: str = Field(default_factory=generate_uuid)
    audit_id: str
    severity: AuditFindingSeverity
    category: str
    message: str
    file: str | None = None
    location: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AuditRecord(BaseModel):
    """Durable DeepSeek Direct audit lifecycle record."""

    audit_id: str = Field(default_factory=generate_uuid)
    job_id: str
    project_id: str
    change_name: str
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    candidate_sha: str
    base_sha: str
    review_id: str | None = None
    review_verdict: ReviewVerdict | None = None
    status: AuditStatus = AuditStatus.AUDIT_PENDING
    risk: AuditRiskLevel | None = None
    summary: str | None = None
    error_message: str | None = None
    findings: list[AuditFinding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AuditFindingPayload(BaseModel):
    """Finding item in DeepSeek audit result schema."""

    severity: AuditFindingSeverity
    category: str
    message: str
    file: str | None = None
    location: str | None = None

    model_config = {"extra": "forbid"}


class AuditResult(BaseModel):
    """Strict DeepSeek audit result payload."""

    risk: AuditRiskLevel
    findings: list[AuditFindingPayload] = Field(default_factory=list)
    summary: str

    model_config = {"extra": "forbid"}
