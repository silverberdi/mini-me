"""Domain models for mini me."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from minime.domain.enums import (
    PRIMARY_PROVIDERS,
    ActionRiskLevel,
    AdmissionDecision,
    AdmissionRefusalCode,
    AttemptProductivityClass,
    AuditFindingSeverity,
    AuditRiskLevel,
    AuditStatus,
    BlockerValidationVerdict,
    CapacitySignalSource,
    ChangeStatus,
    ContinuationDecision,
    EventType,
    EvidenceDiagnosticStatus,
    ExecutionOutcome,
    ExternalActionStatus,
    ExternalActionType,
    FindingSeverity,
    GitOperationStatus,
    HumanGate,
    JobStatus,
    LockSafetyStatus,
    OperatorActionErrorCode,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    PremiumProviderReasonCode,
    PreviewStatus,
    ProgressClassification,
    ProjectStatus,
    ProviderHealthStatus,
    ProviderResultClass,
    PullRequestLookupState,
    QueuePriority,
    ReadinessState,
    RemediationFailureCode,
    RemediationStatus,
    ReviewStatus,
    ReviewVerdict,
    SchedulerMode,
    TaskClass,
    ValidationVerdict,
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
    github_pr_number: int | None = None
    github_pr_url: str | None = None
    openspec_change_name: str
    is_valid: bool = True
    mismatch_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PullRequestLookupResult(BaseModel):
    """Explicit remote PR lookup state; absence is never represented by None alone."""

    state: PullRequestLookupState
    pull_request: dict[str, Any] | None = None
    detail: str | None = None


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
    attempt_count: int = 1
    reassignment_count: int = 0
    current_executor: str | None = None
    latest_outcome: ExecutionOutcome | None = None
    latest_progress: ProgressClassification | None = None
    continuation_decision: ContinuationDecision | None = None
    is_mixed_authorship: bool = False
    escalation_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RemediationContract(BaseModel):
    """Immutable, canonical authorization payload for one remediation identity."""

    contract_version: str = Field(min_length=1, max_length=32)
    run_id: str = Field(min_length=1, max_length=64)
    source_candidate_generation: int = Field(gt=0)
    source_candidate_sha: str = Field(min_length=1, max_length=64)
    source_candidate_base_sha: str = Field(min_length=1, max_length=64)
    change_name: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=4000)
    allowed_paths: list[str] = Field(min_length=1)
    protected_paths: list[str] = Field(default_factory=list)
    required_outcomes: list[str] = Field(default_factory=list)
    verification_commands: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    known_failures: list[str] = Field(default_factory=list)
    implementation_constraints: list[str] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True, extra="forbid")

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def canonical_json(self) -> str:
        return json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )

    def contract_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class CandidateRemediation(BaseModel):
    """Durable remediation request and resulting candidate identity."""

    remediation_id: str = Field(default_factory=generate_uuid)
    run_id: str
    job_id: str
    source_candidate_id: str
    source_generation: int
    source_candidate_sha: str
    source_base_sha: str
    contract_version: str
    contract_hash: str
    contract_payload: dict[str, Any]
    status: RemediationStatus = RemediationStatus.ADMITTED
    failure_code: RemediationFailureCode | None = None
    failure_reason: str | None = None
    workspace_path: str | None = None
    branch_name: str | None = None
    authorized_paths: list[str] = Field(default_factory=list)
    tree_fingerprint: str | None = None
    result_candidate_id: str | None = None
    result_generation: int | None = None
    result_candidate_sha: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class JobAttempt(BaseModel):
    """Durable execution attempt record for an executor run."""

    attempt_id: str = Field(default_factory=generate_uuid)
    job_id: str
    attempt_number: int
    executor_role: str
    model_identity: str
    start_sha: str | None = None
    end_sha: str | None = None
    normalized_outcome: ExecutionOutcome
    progress_classification: ProgressClassification | None = None
    continuation_decision: ContinuationDecision | None = None
    corrective_retries_count: int = 0
    same_outcome_streak: int = 1
    same_blocker_fingerprint_streak: int = 0
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    duration_ms: int | None = None
    corrective_prompt: str | None = None
    task_class: TaskClass | None = None
    productivity_class: AttemptProductivityClass | None = None
    premium_reason_code: PremiumProviderReasonCode | None = None
    is_same_sha_duplicate: bool = False
    error_details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class BlockerClaim(BaseModel):
    """Durable validated blocker claim record."""

    claim_id: str = Field(default_factory=generate_uuid)
    job_id: str
    attempt_id: str
    blocker_type: str
    blocker_fingerprint: str
    affected_requirement: str | None = None
    failing_invariant: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    attempted_remediation: str | None = None
    rationale: str | None = None
    is_agent_solvable: bool = True
    validation_verdict: BlockerValidationVerdict
    validation_rationale: str | None = None
    available_integration_points: list[dict[str, Any]] | list[str] | dict[str, Any] = Field(
        default_factory=list
    )
    created_at: datetime = Field(default_factory=utc_now)


class BlockerClaimPayload(BaseModel):
    """Parsed structured blocker payload from executor output."""

    blocker_type: str
    location: str | None = None
    affected_requirement: str | None = None
    failing_invariant: str | None = None
    evidence: dict[str, Any] | str | None = None
    attempted_remediation: str | None = None
    rationale: str | None = None
    is_agent_solvable: bool = True
    normalized_reason_code: str | None = None


class JobHandoff(BaseModel):
    """Durable structured handoff payload for executor takeover."""

    handoff_id: str = Field(default_factory=generate_uuid)
    job_id: str
    from_attempt_id: str
    to_attempt_id: str | None = None
    from_executor: str
    to_executor: str
    worktree_path: str
    base_sha: str
    candidate_sha: str
    completed_tasks: list[str] = Field(default_factory=list)
    remaining_tasks: list[str] = Field(default_factory=list)
    manifest_summary: dict[str, Any] = Field(default_factory=dict)
    checks_summary: dict[str, Any] = Field(default_factory=dict)
    blockers_summary: dict[str, Any] = Field(default_factory=dict)
    architectural_notes: dict[str, Any] = Field(default_factory=dict)
    do_not_redo_guidance: list[str] = Field(default_factory=list)
    authorship_history: list[dict[str, Any]] = Field(default_factory=list)
    is_consumed: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class CandidateManifest(BaseModel):
    """Cryptographic and structural worktree manifest for candidate review."""

    manifest_id: str = Field(default_factory=generate_uuid)
    job_id: str
    attempt_id: str | None = None
    candidate_sha: str
    tracked_files: list[dict[str, Any]] = Field(default_factory=list)
    staged_files: list[dict[str, Any]] = Field(default_factory=list)
    untracked_files: list[dict[str, Any]] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    total_files_count: int = 0
    manifest_hash: str
    created_at: datetime = Field(default_factory=utc_now)


class CandidateAuthorship(BaseModel):
    """Author contribution record across execution attempts."""

    authorship_id: str = Field(default_factory=generate_uuid)
    job_id: str
    agent_role: str
    model_identity: str
    attempt_number: int
    files_touched: list[str] = Field(default_factory=list)
    is_primary_author: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class EvidenceDiagnostic(BaseModel):
    """Machine-readable evidence and environment execution diagnostic."""

    diagnostic_id: str = Field(default_factory=generate_uuid)
    job_id: str
    attempt_id: str | None = None
    stage_type: str
    check_name: str | None = None
    diagnostic_status: EvidenceDiagnosticStatus
    environment_identity: str
    candidate_sha: str
    reason: str | None = None
    evidence_reference: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class OpenRouterBudgetPolicy(BaseModel):
    project_id: str
    enabled: bool = False
    daily_cap_usd: Decimal = Field(default_factory=lambda: Decimal("0.0"))
    monthly_cap_usd: Decimal = Field(default_factory=lambda: Decimal("0.0"))
    currency: str = "USD"
    policy_version: int = 1
    is_breached: bool = False
    updated_at: datetime = Field(default_factory=utc_now)


AUTHORITATIVE_PRICING_SOURCES: frozenset[str] = frozenset(
    {
        "operator_verified",
        "openrouter_catalog_verified",
        "openrouter_catalog_api",
    }
)


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

    @property
    def is_verified(self) -> bool:
        return self.source in AUTHORITATIVE_PRICING_SOURCES


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
    candidate_sha: str = ""
    candidate_generation: int | None = None
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
    reviewer_model: str | None = None
    orchestration_run_id: str | None = None
    candidate_generation: int | None = None
    candidate_sha: str
    base_sha: str
    manifest_id: str | None = None
    manifest_hash: str | None = None
    status: ReviewStatus = ReviewStatus.REVIEW_PENDING
    verdict: ReviewVerdict | None = None
    summary: str | None = None
    error_message: str | None = None
    is_mixed_authorship: bool = False
    authorship_evidence: dict[str, Any] = Field(default_factory=dict)
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
    provider: str = "deepseek_direct"
    model: str = "deepseek-chat"
    orchestration_run_id: str | None = None
    candidate_generation: int | None = None
    candidate_sha: str
    base_sha: str
    manifest_id: str | None = None
    manifest_hash: str | None = None
    is_full_candidate: bool | None = None
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


class OrchestrationRun(BaseModel):
    """Durable orchestration run state for one-change autonomous coordination."""

    run_id: str = Field(default_factory=generate_uuid)
    project_id: str
    change_name: str
    base_sha: str
    current_stage: OrchestrationStage = OrchestrationStage.ADMITTED
    resumable_stage: OrchestrationStage = OrchestrationStage.ADMITTED
    stop_outcome: OrchestrationStopOutcome | None = None
    human_gate: HumanGate | None = None
    stop_reason: str | None = None
    stop_details: dict[str, Any] = Field(default_factory=dict)
    active_job_id: str | None = None
    current_generation: int = 1
    current_candidate_sha: str | None = None
    retry_count: int = 0
    reassignment_count: int = 0
    pending_handoff: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def _map_candidate_sha(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "candidate_sha" in data and "current_candidate_sha" not in data:
                data["current_candidate_sha"] = data.pop("candidate_sha")
        return data

    @property
    def candidate_sha(self) -> str | None:
        return self.current_candidate_sha

    @candidate_sha.setter
    def candidate_sha(self, val: str | None) -> None:
        self.current_candidate_sha = val


class OrchestrationStageEvent(BaseModel):
    """Durable stage transition event for an orchestration run."""

    event_id: str = Field(default_factory=generate_uuid)
    run_id: str
    from_stage: OrchestrationStage | None = None
    to_stage: OrchestrationStage
    event_type: str = "STAGE_TRANSITION"
    transition_key: str | None = None
    evidence_references: dict[str, Any] = Field(default_factory=dict)
    actor: str = "system"
    created_at: datetime = Field(default_factory=utc_now)


class OrchestrationCandidate(BaseModel):
    """Durable immutable candidate generation record."""

    candidate_id: str = Field(default_factory=generate_uuid)
    run_id: str
    generation: int
    base_sha: str
    candidate_sha: str
    candidate_ref: str | None = None
    manifest_id: str | None = None
    manifest_hash: str
    authorship_summary: dict[str, Any] = Field(default_factory=dict)
    is_frozen: bool = True
    superseded_by_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class OrchestrationExternalAction(BaseModel):
    """Durable idempotency reservation record for mutating Git/GitHub actions."""

    action_id: str = Field(default_factory=generate_uuid)
    run_id: str
    action_key: str
    action_type: ExternalActionType
    target_identity: str
    request_fingerprint: str
    candidate_sha: str
    generation: int
    status: ExternalActionStatus = ExternalActionStatus.RESERVED
    remote_identifier: str | None = None
    result_payload: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    reserved_at: datetime = Field(default_factory=utc_now)
    reconciled_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AdmissionResult(BaseModel):
    """Result of single-change orchestration admission evaluation."""

    admitted: bool
    run: OrchestrationRun | None = None
    refusal_reason: str | None = None
    refusal_details: dict[str, Any] = Field(default_factory=dict)
    existing_run_id: str | None = None


class OrchestrationStatusView(BaseModel):
    """Comprehensive observability view for an orchestration run."""

    run_id: str
    project_id: str
    change_name: str
    current_stage: OrchestrationStage
    resumable_stage: OrchestrationStage
    is_active: bool
    active_job_id: str | None = None
    current_executor: str | None = None
    current_generation: int = 1
    base_sha: str
    candidate_sha: str | None = None
    manifest_hash: str | None = None
    checks_status: str | None = None
    review_verdict: str | None = None
    review_candidate_binding: dict[str, Any] | None = None
    audit_status: str | None = None
    audit_risk: str | None = None
    audit_candidate_binding: dict[str, Any] | None = None
    provider_capacity_state: dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0
    reassignment_count: int = 0
    pending_handoff: dict[str, Any] | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    pr_head_sha: str | None = None
    stop_outcome: OrchestrationStopOutcome | None = None
    human_gate: HumanGate | None = None
    stop_reason: str | None = None
    stop_details: dict[str, Any] = Field(default_factory=dict)

    remediation: dict[str, Any] | None = None
    last_transition: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class PreviewSession(BaseModel):
    """Durable preview session for an isolated candidate container environment."""

    preview_id: str = Field(default_factory=generate_uuid)
    project_id: str
    change_name: str
    run_id: str | None = None
    job_id: str | None = None
    candidate_generation: int = 1
    head_sha: str
    base_sha: str
    image_digest: str = ""
    status: PreviewStatus = PreviewStatus.REQUESTED
    container_id: str | None = None
    container_name: str | None = None
    allocated_port: int | None = None
    preview_url: str | None = None
    failure_reason: str | None = None
    failure_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    ready_at: datetime | None = None
    terminated_at: datetime | None = None


class ValidationScenario(BaseModel):
    """Structured visual / user-facing scenario for guided human validation."""

    scenario_id: str
    title: str
    description: str = ""
    ordered_steps: list[str] = Field(default_factory=list)
    expected_result: str = ""
    viewport: str | None = "desktop"
    required: bool = True


class ValidationRun(BaseModel):
    """Authoritative recorded validation run tied strictly to candidate identity."""

    validation_id: str = Field(default_factory=generate_uuid)
    preview_id: str | None = None
    project_id: str
    change_name: str
    run_id: str | None = None
    candidate_generation: int = 1
    head_sha: str
    base_sha: str
    image_digest: str
    verdict: ValidationVerdict = ValidationVerdict.PASS
    scenario_results: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = None
    operator: str | None = "operator"
    created_at: datetime = Field(default_factory=utc_now)


class ActionDescriptor(BaseModel):
    """Structured descriptor for action discovery presented to operators / clients."""

    action: OperatorActionType
    display_name: str
    description: str = ""
    enabled: bool = True
    disabled_reason: str | None = None
    requires_confirmation: bool = False
    confirmation_prompt: str | None = None
    risk_level: ActionRiskLevel = ActionRiskLevel.LOW
    parameters_schema: dict[str, Any] = Field(default_factory=dict)


class OperatorActionRequest(BaseModel):
    """Governed operator action request payload."""

    action_request_id: str = Field(default_factory=generate_uuid)
    project_id: str
    change_name: str
    run_id: str
    action_type: OperatorActionType
    parameters: dict[str, Any] = Field(default_factory=dict)
    actor_identity: str = "operator"
    source_interface: str = "tui"
    expected_stage: OrchestrationStage | None = None
    expected_generation: int | None = None
    expected_candidate_sha: str | None = None
    expected_human_gate: HumanGate | None = None
    requested_at: datetime = Field(default_factory=utc_now)


class OperatorActionResult(BaseModel):
    """Governed operator action execution result."""

    action_request_id: str
    action_type: OperatorActionType
    status: OperatorActionStatus
    error_code: OperatorActionErrorCode | None = None
    summary: str
    resulting_stage: OrchestrationStage | None = None
    resulting_outcome: OrchestrationStopOutcome | None = None
    resulting_gate: HumanGate | None = None
    evidence_reference: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime = Field(default_factory=utc_now)


class OperatorActionRecord(BaseModel):
    """Durable audit record of an operator action execution."""

    id: str = Field(default_factory=generate_uuid)
    action_request_id: str
    project_id: str
    change_name: str
    run_id: str | None = None
    job_id: str | None = None
    action_type: OperatorActionType
    actor_identity: str = "operator"
    source_interface: str = "tui"
    precondition_stage: str | None = None
    precondition_gate: str | None = None
    status: OperatorActionStatus = OperatorActionStatus.ACCEPTED
    error_code: OperatorActionErrorCode | None = None
    summary: str = ""
    resulting_stage: str | None = None
    resulting_outcome: str | None = None
    resulting_gate: str | None = None
    evidence_reference: str | None = None
    parameters_json: dict[str, Any] = Field(default_factory=dict)
    result_payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class WorkQueueItem(BaseModel):
    """Evaluated backlog work item in the scheduler queue."""

    queue_item_id: str = Field(default_factory=generate_uuid)
    project_id: str
    change_name: str
    github_issue_number: int | None = None
    github_issue_title: str | None = None
    github_project_item_id: str | None = None
    priority: QueuePriority = QueuePriority.NORMAL
    roadmap_stage: int | None = None
    dependencies: list[str] = Field(default_factory=list)
    readiness_state: ReadinessState = ReadinessState.NOT_READY
    unmet_readiness_reasons: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    admission_eligible: bool = False
    priority_score: float = 0.0
    discovered_at: datetime = Field(default_factory=utc_now)
    last_evaluated_at: datetime = Field(default_factory=utc_now)


class SchedulerDecisionRecord(BaseModel):
    """Immutable audit record of a scheduler admission evaluation."""

    decision_id: str = Field(default_factory=generate_uuid)
    project_id: str
    change_name: str
    github_issue_number: int | None = None
    decision: AdmissionDecision
    reason_code: AdmissionRefusalCode | None = None
    reason_summary: str
    priority_score: float = 0.0
    selected_implementer: str | None = None
    concurrency_snapshot: dict[str, Any] = Field(default_factory=dict)
    capacity_snapshot: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    evaluated_at: datetime = Field(default_factory=utc_now)


class QueueExplainReport(BaseModel):
    """Explainability report for work item queue position, score, and blockers."""

    project_id: str
    change_name: str
    github_issue_number: int | None = None
    readiness_state: ReadinessState
    admission_eligible: bool
    priority: QueuePriority
    base_score: float
    aging_bonus: float
    roadmap_precedence_penalty: float
    total_score: float
    queue_position: int | None = None
    blockers: list[str] = Field(default_factory=list)
    refusal_code: AdmissionRefusalCode | None = None
    selection_rationale: str
    evaluated_at: datetime = Field(default_factory=utc_now)


class SchedulerStatusView(BaseModel):
    """Operational status view of the autonomous scheduler and queue."""

    mode: SchedulerMode = SchedulerMode.RUN
    queue_depth: int = 0
    ready_count: int = 0
    blocked_count: int = 0
    active_runs_count: int = 0
    max_global_jobs: int = 1
    next_candidate: WorkQueueItem | None = None
    recent_decisions: list[SchedulerDecisionRecord] = Field(default_factory=list)
    provider_health: dict[str, str] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=utc_now)


class TaskClassificationResult(BaseModel):
    """Deterministic result of evaluating task and attempt classification."""

    task_class: TaskClass
    rationale: str
    signals: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=utc_now)


class ProviderSelectionExplanation(BaseModel):
    """Deterministic multi-factor provider selection decision and explanation."""

    selected_provider: str
    role: str
    task_class: TaskClass
    is_premium: bool = False
    premium_reason_code: PremiumProviderReasonCode | None = None
    explanation: str
    factors: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=utc_now)


class MaterialAuthorshipSummary(BaseModel):
    """Candidate-level material authorship provenance and reviewer independence eligibility."""

    candidate_sha: str
    generation: int = 1
    material_authors: list[str] = Field(default_factory=list)
    material_author_roles: list[str] = Field(default_factory=list)
    configured_reviewers: list[str] = Field(default_factory=list)
    eligible_reviewers: list[str] = Field(default_factory=list)
    disqualified_reviewers: list[str] = Field(default_factory=list)
    is_independent: bool = True
    evaluated_at: datetime = Field(default_factory=utc_now)


class ProviderEfficiencyMetrics(BaseModel):
    """Durable per-change and per-run provider efficiency and telemetry facts."""

    metrics_id: str = Field(default_factory=generate_uuid)
    run_id: str
    project_id: str
    change_name: str
    attempts_by_provider: dict[str, int] = Field(default_factory=dict)
    duration_by_provider_ms: dict[str, int] = Field(default_factory=dict)
    productive_attempt_count: int = 0
    no_progress_attempt_count: int = 0
    same_sha_retry_count: int = 0
    same_sha_retry_suppressed_count: int = 0
    corrective_retry_count: int = 0
    reassignments_count: int = 0
    reassignment_reason_codes: list[str] = Field(default_factory=list)
    provider_exhaustion_events: list[dict[str, Any]] = Field(default_factory=list)
    drain_transitions: list[dict[str, Any]] = Field(default_factory=list)
    premium_provider_assignments: int = 0
    premium_provider_reason_codes: list[str] = Field(default_factory=list)
    candidate_generations_count: int = 1
    time_to_candidate_ms: int | None = None
    time_to_checks_ms: int | None = None
    time_to_review_ms: int | None = None
    time_to_pr_ms: int | None = None
    total_cycle_time_ms: int | None = None
    human_gates_count: int = 0
    operator_actions_count: int = 0
    self_hosting_native_phases: int = 0
    self_hosting_total_phases: int = 0
    self_hosting_percentage: float = 0.0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class EfficiencyTelemetryView(BaseModel):
    """Aggregated operational view of provider efficiency telemetry."""

    project_id: str
    change_name: str
    run_id: str
    metrics: ProviderEfficiencyMetrics
    provider_summary: list[dict[str, Any]] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=utc_now)
