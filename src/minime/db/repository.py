"""PostgreSQL repository implementations and transactional persistence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from minime.db.models import (
    AuditFindingModel,
    AuditModel,
    BlockerClaimModel,
    BudgetLedgerModel,
    BudgetReservationModel,
    CandidateAuthorshipModel,
    CandidateManifestModel,
    CandidateRemediationModel,
    CapacityWindowModel,
    ChangeModel,
    CheckResultModel,
    EventModel,
    EvidenceDiagnosticModel,
    GitOperationModel,
    JobAttemptModel,
    JobHandoffModel,
    JobLogModel,
    JobModel,
    MetricFactModel,
    OpenRouterBudgetPolicyModel,
    OpenRouterPricingSnapshotModel,
    OperatorActionRecordModel,
    OrchestrationCandidateModel,
    OrchestrationExternalActionModel,
    OrchestrationRunModel,
    OrchestrationStageEventModel,
    PreviewSessionModel,
    ProjectBindingModel,
    ProjectModel,
    ProviderEfficiencyMetricsModel,
    ProviderHealthModel,
    ReviewFindingModel,
    ReviewModel,
    SchedulerDecisionRecordModel,
    ValidationRunModel,
    WorkQueueSnapshotModel,
)
from minime.domain.enums import (
    PRIMARY_PROVIDERS,
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
    QueuePriority,
    ReadinessState,
    RemediationFailureCode,
    RemediationStatus,
    ReviewStatus,
    ReviewVerdict,
    TaskClass,
    ValidationVerdict,
)
from minime.domain.interfaces import (
    AuditFindingRepositoryInterface,
    AuditRepositoryInterface,
    BlockerClaimRepositoryInterface,
    BudgetLedgerRepositoryInterface,
    BudgetReservationRepositoryInterface,
    CandidateAuthorshipRepositoryInterface,
    CandidateManifestRepositoryInterface,
    CapacityWindowRepositoryInterface,
    ChangeRepositoryInterface,
    CheckResultRepositoryInterface,
    EventRepositoryInterface,
    EvidenceDiagnosticRepositoryInterface,
    GitOperationRepositoryInterface,
    JobAttemptRepositoryInterface,
    JobHandoffRepositoryInterface,
    JobLogRepositoryInterface,
    JobRepositoryInterface,
    MetricFactRepositoryInterface,
    OpenRouterBudgetPolicyRepositoryInterface,
    OpenRouterPricingSnapshotRepositoryInterface,
    OperatorActionRepositoryInterface,
    OrchestrationCandidateRepositoryInterface,
    OrchestrationExternalActionRepositoryInterface,
    OrchestrationRunRepositoryInterface,
    OrchestrationStageEventRepositoryInterface,
    PersistenceUnitOfWork,
    PreviewSessionRepositoryInterface,
    ProjectBindingRepositoryInterface,
    ProjectRepositoryInterface,
    ProviderEfficiencyMetricsRepositoryInterface,
    ProviderHealthRepositoryInterface,
    ReviewFindingRepositoryInterface,
    ReviewRepositoryInterface,
    SchedulerDecisionRepositoryInterface,
    ValidationRunRepositoryInterface,
    WorkQueueRepositoryInterface,
)
from minime.domain.models import (
    AUTHORITATIVE_PRICING_SOURCES,
    AuditFinding,
    AuditRecord,
    BlockerClaim,
    BudgetLedgerEntry,
    BudgetReservation,
    CandidateAuthorship,
    CandidateManifest,
    CandidateRemediation,
    CapacityWindow,
    Change,
    CheckResult,
    Event,
    EvidenceDiagnostic,
    GitOperation,
    Job,
    JobAttempt,
    JobHandoff,
    JobLog,
    MetricFact,
    OpenRouterBudgetPolicy,
    OpenRouterPricingSnapshot,
    OperatorActionRecord,
    OrchestrationCandidate,
    OrchestrationExternalAction,
    OrchestrationRun,
    OrchestrationStageEvent,
    PreviewSession,
    Project,
    ProjectBinding,
    ProviderEfficiencyMetrics,
    ProviderHealth,
    Review,
    ReviewFinding,
    SchedulerDecisionRecord,
    ValidationRun,
    WorkQueueItem,
    utc_now,
)


def _decimal_to_float(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


def _to_decimal(value: Decimal | float | str | int | None, default: str = "0.0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def project_model_to_domain(model: ProjectModel) -> Project:
    return Project(
        project_id=model.id,
        display_name=model.display_name,
        repository=model.repository,
        base_branch=model.base_branch,
        openspec_path=model.openspec_path,
        implementer=model.implementer,
        reviewer=model.reviewer,
        checks=model.checks or [],
        external_providers_allowed=model.external_providers_allowed or [],
        openrouter_drain_allowed=model.openrouter_drain_allowed,
        deployment_preview=model.deployment_preview or {},
        deployment_production=model.deployment_production or {},
        status=ProjectStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def change_model_to_domain(model: ChangeModel) -> Change:
    return Change(
        change_id=model.id,
        project_id=model.project_id,
        name=model.name,
        status=ChangeStatus(model.status),
        stage=model.stage,
        schema_name=model.schema_name,
        proposal_path=model.proposal_path,
        tasks_path=model.tasks_path,
        design_path=model.design_path,
        specs_paths=model.specs_paths or [],
        last_readiness_status=ReadinessState(model.last_readiness_status),
        last_readiness_reasons=model.last_readiness_reasons or [],
        discovered_at=model.discovered_at,
        updated_at=model.updated_at,
    )


def binding_model_to_domain(model: ProjectBindingModel) -> ProjectBinding:
    return ProjectBinding(
        binding_id=model.id,
        project_id=model.project_id,
        repository=model.repository,
        github_issue_number=model.github_issue_number,
        github_project_item_id=model.github_project_item_id,
        github_pr_number=model.github_pr_number,
        github_pr_url=model.github_pr_url,
        openspec_change_name=model.openspec_change_name,
        is_valid=model.is_valid,
        mismatch_reasons=model.mismatch_reasons or [],
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def event_model_to_domain(model: EventModel) -> Event:
    return Event(
        event_id=model.id,
        event_type=EventType(model.event_type),
        project_id=model.project_id,
        change_id=model.change_id,
        operation_id=model.operation_id,
        payload=model.payload or {},
        timestamp=model.timestamp,
    )


def fact_model_to_domain(model: MetricFactModel) -> MetricFact:
    return MetricFact(
        fact_id=model.id,
        metric_name=model.metric_name,
        project_id=model.project_id,
        change_id=model.change_id,
        stage=model.stage,
        duration_ms=model.duration_ms,
        fact_value=model.fact_value,
        details=model.details or {},
        recorded_at=model.recorded_at,
    )


def job_model_to_domain(model: JobModel) -> Job:
    return Job(
        job_id=model.id,
        project_id=model.project_id,
        change_name=model.change_name,
        status=JobStatus(model.status),
        implementer_role=model.implementer_role,
        candidate_sha=model.candidate_sha,
        base_sha=model.base_sha,
        error_message=model.error_message,
        waiting_provider=model.waiting_provider,
        capacity_block_reason=model.capacity_block_reason,
        recovery_blocked_reason=model.recovery_blocked_reason,
        expected_reset_at=model.expected_reset_at,
        attempt_count=model.attempt_count,
        reassignment_count=model.reassignment_count,
        current_executor=model.current_executor,
        latest_outcome=ExecutionOutcome(model.latest_outcome) if model.latest_outcome else None,
        latest_progress=ProgressClassification(model.latest_progress)
        if model.latest_progress
        else None,
        continuation_decision=ContinuationDecision(model.continuation_decision)
        if model.continuation_decision
        else None,
        is_mixed_authorship=model.is_mixed_authorship,
        escalation_reason=model.escalation_reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def job_attempt_model_to_domain(model: JobAttemptModel) -> JobAttempt:
    return JobAttempt(
        attempt_id=model.id,
        job_id=model.job_id,
        attempt_number=model.attempt_number,
        executor_role=model.executor_role,
        model_identity=model.model_identity,
        start_sha=model.start_sha,
        end_sha=model.end_sha,
        normalized_outcome=ExecutionOutcome(model.normalized_outcome),
        progress_classification=ProgressClassification(model.progress_classification)
        if model.progress_classification
        else None,
        continuation_decision=ContinuationDecision(model.continuation_decision)
        if model.continuation_decision
        else None,
        corrective_retries_count=model.corrective_retries_count,
        same_outcome_streak=model.same_outcome_streak,
        same_blocker_fingerprint_streak=model.same_blocker_fingerprint_streak,
        started_at=model.started_at,
        completed_at=model.completed_at,
        duration_ms=model.duration_ms,
        corrective_prompt=model.corrective_prompt,
        task_class=TaskClass(model.task_class) if model.task_class else None,
        productivity_class=AttemptProductivityClass(model.productivity_class)
        if model.productivity_class
        else None,
        premium_reason_code=PremiumProviderReasonCode(model.premium_reason_code)
        if model.premium_reason_code
        else None,
        is_same_sha_duplicate=bool(model.is_same_sha_duplicate),
        error_details=model.error_details or {},
        created_at=model.created_at,
    )


def blocker_claim_model_to_domain(model: BlockerClaimModel) -> BlockerClaim:
    return BlockerClaim(
        claim_id=model.id,
        job_id=model.job_id,
        attempt_id=model.attempt_id,
        blocker_type=model.blocker_type,
        blocker_fingerprint=model.blocker_fingerprint,
        affected_requirement=model.affected_requirement,
        failing_invariant=model.failing_invariant,
        evidence=model.evidence or {},
        attempted_remediation=model.attempted_remediation,
        rationale=model.rationale,
        is_agent_solvable=model.is_agent_solvable,
        validation_verdict=BlockerValidationVerdict(model.validation_verdict),
        validation_rationale=model.validation_rationale,
        available_integration_points=model.available_integration_points or [],
        created_at=model.created_at,
    )


def job_handoff_model_to_domain(model: JobHandoffModel) -> JobHandoff:
    return JobHandoff(
        handoff_id=model.id,
        job_id=model.job_id,
        from_attempt_id=model.from_attempt_id,
        to_attempt_id=model.to_attempt_id,
        from_executor=model.from_executor,
        to_executor=model.to_executor,
        worktree_path=model.worktree_path,
        base_sha=model.base_sha,
        candidate_sha=model.candidate_sha,
        completed_tasks=model.completed_tasks or [],
        remaining_tasks=model.remaining_tasks or [],
        manifest_summary=model.manifest_summary or {},
        checks_summary=model.checks_summary or {},
        blockers_summary=model.blockers_summary or {},
        architectural_notes=model.architectural_notes or {},
        do_not_redo_guidance=model.do_not_redo_guidance or [],
        authorship_history=model.authorship_history or [],
        is_consumed=model.is_consumed,
        created_at=model.created_at,
    )


def candidate_manifest_model_to_domain(model: CandidateManifestModel) -> CandidateManifest:
    return CandidateManifest(
        manifest_id=model.id,
        job_id=model.job_id,
        attempt_id=model.attempt_id,
        candidate_sha=model.candidate_sha,
        tracked_files=model.tracked_files or [],
        staged_files=model.staged_files or [],
        untracked_files=model.untracked_files or [],
        deleted_files=model.deleted_files or [],
        total_files_count=model.total_files_count,
        manifest_hash=model.manifest_hash,
        created_at=model.created_at,
    )


def candidate_authorship_model_to_domain(model: CandidateAuthorshipModel) -> CandidateAuthorship:
    return CandidateAuthorship(
        authorship_id=model.id,
        job_id=model.job_id,
        agent_role=model.agent_role,
        model_identity=model.model_identity,
        attempt_number=model.attempt_number,
        files_touched=model.files_touched or [],
        is_primary_author=model.is_primary_author,
        created_at=model.created_at,
    )


def evidence_diagnostic_model_to_domain(model: EvidenceDiagnosticModel) -> EvidenceDiagnostic:
    return EvidenceDiagnostic(
        diagnostic_id=model.id,
        job_id=model.job_id,
        attempt_id=model.attempt_id,
        stage_type=model.stage_type,
        check_name=model.check_name,
        diagnostic_status=EvidenceDiagnosticStatus(model.diagnostic_status),
        environment_identity=model.environment_identity,
        candidate_sha=model.candidate_sha,
        reason=model.reason,
        evidence_reference=model.evidence_reference or {},
        created_at=model.created_at,
    )


def provider_health_model_to_domain(model: ProviderHealthModel) -> ProviderHealth:
    return ProviderHealth(
        health_id=model.id,
        provider=model.provider,
        model=model.model,
        status=ProviderHealthStatus(model.status),
        consecutive_failures=model.consecutive_failures,
        last_result_class=ProviderResultClass(model.last_result_class)
        if model.last_result_class
        else None,
        last_error_summary=model.last_error_summary,
        last_success_at=model.last_success_at,
        last_failure_at=model.last_failure_at,
        updated_at=model.updated_at,
    )


def capacity_window_model_to_domain(model: CapacityWindowModel) -> CapacityWindow:
    return CapacityWindow(
        window_id=model.id,
        provider=model.provider,
        model=model.model,
        quota_exhausted_at=model.quota_exhausted_at,
        capacity_reset_at=model.capacity_reset_at,
        retry_after_seconds=model.retry_after_seconds,
        source_signal=CapacitySignalSource(model.source_signal)
        if model.source_signal
        else CapacitySignalSource.UNKNOWN,
        created_at=model.created_at,
    )


def git_operation_model_to_domain(model: GitOperationModel) -> GitOperation:
    return GitOperation(
        operation_id=model.id,
        job_id=model.job_id,
        project_id=model.project_id,
        worktree_path=model.worktree_path,
        operation_type=model.operation_type,
        pid=model.pid,
        status=GitOperationStatus(model.status),
        started_at=model.started_at,
        completed_at=model.completed_at,
    )


def job_log_model_to_domain(model: JobLogModel) -> JobLog:
    return JobLog(
        log_id=model.id,
        job_id=model.job_id,
        stream=model.stream,
        message=model.message,
        timestamp=model.timestamp,
    )


def check_result_model_to_domain(model: CheckResultModel) -> CheckResult:
    return CheckResult(
        result_id=model.id,
        job_id=model.job_id,
        check_name=model.check_name,
        command=model.command,
        exit_code=model.exit_code,
        duration_ms=model.duration_ms,
        output_snippet=model.output_snippet,
        candidate_sha=model.candidate_sha or "",
        candidate_generation=model.candidate_generation,
        created_at=model.created_at,
    )


def review_finding_model_to_domain(model: ReviewFindingModel) -> ReviewFinding:
    return ReviewFinding(
        finding_id=model.id,
        review_id=model.review_id,
        severity=FindingSeverity(model.severity),
        location=model.location,
        violated_requirement=model.violated_requirement,
        expected_correction=model.expected_correction,
        created_at=model.created_at,
    )


def review_model_to_domain(model: ReviewModel) -> Review:
    return Review(
        review_id=model.id,
        job_id=model.job_id,
        project_id=model.project_id,
        change_name=model.change_name,
        reviewer_role=model.reviewer_role,
        reviewer_model=model.reviewer_model,
        orchestration_run_id=model.orchestration_run_id,
        candidate_generation=model.candidate_generation,
        candidate_sha=model.candidate_sha,
        base_sha=model.base_sha,
        manifest_id=model.manifest_id,
        manifest_hash=model.manifest_hash,
        status=ReviewStatus(model.status),
        verdict=ReviewVerdict(model.verdict) if model.verdict else None,
        summary=model.summary,
        error_message=model.error_message,
        is_mixed_authorship=model.is_mixed_authorship,
        authorship_evidence=model.authorship_evidence or {},
        findings=[review_finding_model_to_domain(f) for f in (model.findings or [])],
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def audit_finding_model_to_domain(model: AuditFindingModel) -> AuditFinding:
    return AuditFinding(
        finding_id=model.id,
        audit_id=model.audit_id,
        severity=AuditFindingSeverity(model.severity),
        category=model.category,
        message=model.message,
        file=model.file,
        location=model.location,
        created_at=model.created_at,
    )


def audit_model_to_domain(model: AuditModel) -> AuditRecord:
    return AuditRecord(
        audit_id=model.id,
        job_id=model.job_id,
        project_id=model.project_id,
        change_name=model.change_name,
        provider=model.provider,
        model=model.model,
        orchestration_run_id=model.orchestration_run_id,
        candidate_generation=model.candidate_generation,
        candidate_sha=model.candidate_sha,
        base_sha=model.base_sha,
        manifest_id=model.manifest_id,
        manifest_hash=model.manifest_hash,
        is_full_candidate=model.is_full_candidate,
        review_id=model.review_id,
        review_verdict=ReviewVerdict(model.review_verdict) if model.review_verdict else None,
        status=AuditStatus(model.status),
        risk=AuditRiskLevel(model.risk) if model.risk else None,
        summary=model.summary,
        error_message=model.error_message,
        findings=[audit_finding_model_to_domain(f) for f in (model.findings or [])],
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def budget_policy_model_to_domain(model: OpenRouterBudgetPolicyModel) -> OpenRouterBudgetPolicy:
    return OpenRouterBudgetPolicy(
        project_id=model.project_id,
        enabled=model.enabled,
        daily_cap_usd=_to_decimal(model.daily_cap_usd),
        monthly_cap_usd=_to_decimal(model.monthly_cap_usd),
        currency=model.currency,
        policy_version=model.policy_version,
        is_breached=model.is_breached,
        updated_at=model.updated_at,
    )


def pricing_snapshot_model_to_domain(
    model: OpenRouterPricingSnapshotModel,
) -> OpenRouterPricingSnapshot:
    return OpenRouterPricingSnapshot(
        snapshot_id=model.id,
        canonical_model_identity=model.canonical_model_identity,
        routed_model_identity=model.routed_model_identity,
        prompt_price_per_token=_to_decimal(model.prompt_price_per_token),
        output_price_per_token=_to_decimal(model.output_price_per_token),
        additional_cost_per_request=_to_decimal(model.additional_cost_per_request),
        currency=model.currency,
        source=model.source,
        observed_at=model.observed_at,
        created_at=model.created_at,
    )


def budget_reservation_model_to_domain(model: BudgetReservationModel) -> BudgetReservation:
    return BudgetReservation(
        reservation_id=model.id,
        project_id=model.project_id,
        job_id=model.job_id,
        change_id=model.change_id,
        role=model.role,
        canonical_model_identity=model.canonical_model_identity,
        reserved_amount_usd=_to_decimal(model.reserved_amount_usd),
        status=model.status,
        pricing_snapshot_id=model.pricing_snapshot_id,
        correlation_id=model.correlation_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def budget_ledger_model_to_domain(model: BudgetLedgerModel) -> BudgetLedgerEntry:
    return BudgetLedgerEntry(
        entry_id=model.id,
        reservation_id=model.reservation_id,
        project_id=model.project_id,
        job_id=model.job_id,
        change_id=model.change_id,
        provider=model.provider,
        role=model.role,
        canonical_model_identity=model.canonical_model_identity,
        prompt_tokens=model.prompt_tokens,
        completion_tokens=model.completion_tokens,
        total_tokens=model.total_tokens,
        amount_usd=_to_decimal(model.amount_usd),
        entry_type=model.entry_type,
        created_at=model.created_at,
    )


def orchestration_run_model_to_domain(model: OrchestrationRunModel) -> OrchestrationRun:
    return OrchestrationRun(
        run_id=model.id,
        project_id=model.project_id,
        change_name=model.change_name,
        base_sha=model.base_sha,
        current_stage=OrchestrationStage(model.current_stage),
        resumable_stage=OrchestrationStage(model.resumable_stage),
        stop_outcome=OrchestrationStopOutcome(model.stop_outcome) if model.stop_outcome else None,
        human_gate=HumanGate(model.human_gate) if model.human_gate else None,
        stop_reason=model.stop_reason,
        stop_details=model.stop_details or {},
        active_job_id=model.active_job_id,
        current_generation=model.current_generation,
        current_candidate_sha=model.current_candidate_sha,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def orchestration_stage_event_model_to_domain(
    model: OrchestrationStageEventModel,
) -> OrchestrationStageEvent:
    return OrchestrationStageEvent(
        event_id=model.id,
        run_id=model.run_id,
        from_stage=OrchestrationStage(model.from_stage) if model.from_stage else None,
        to_stage=OrchestrationStage(model.to_stage),
        event_type=model.event_type,
        transition_key=model.transition_key,
        evidence_references=model.evidence_references or {},
        actor=model.actor,
        created_at=model.created_at,
    )


def orchestration_candidate_model_to_domain(
    model: OrchestrationCandidateModel,
) -> OrchestrationCandidate:
    return OrchestrationCandidate(
        candidate_id=model.id,
        run_id=model.run_id,
        generation=model.generation,
        base_sha=model.base_sha,
        candidate_sha=model.candidate_sha,
        candidate_ref=model.candidate_ref,
        manifest_id=model.manifest_id,
        manifest_hash=model.manifest_hash,
        authorship_summary=model.authorship_summary or {},
        is_frozen=model.is_frozen,
        superseded_by_id=model.superseded_by_id,
        created_at=model.created_at,
    )


def candidate_remediation_model_to_domain(model: CandidateRemediationModel) -> CandidateRemediation:
    return CandidateRemediation(
        remediation_id=model.id,
        run_id=model.run_id,
        job_id=model.job_id,
        source_candidate_id=model.source_candidate_id,
        source_generation=model.source_generation,
        source_candidate_sha=model.source_candidate_sha,
        source_base_sha=model.source_base_sha,
        contract_version=model.contract_version,
        contract_hash=model.contract_hash,
        contract_payload=model.contract_payload or {},
        status=RemediationStatus(model.status),
        failure_code=RemediationFailureCode(model.failure_code) if model.failure_code else None,
        failure_reason=model.failure_reason,
        workspace_path=model.workspace_path,
        branch_name=model.branch_name,
        authorized_paths=model.authorized_paths or [],
        tree_fingerprint=model.tree_fingerprint,
        result_candidate_id=model.result_candidate_id,
        result_generation=model.result_generation,
        result_candidate_sha=model.result_candidate_sha,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def orchestration_external_action_model_to_domain(
    model: OrchestrationExternalActionModel,
) -> OrchestrationExternalAction:
    return OrchestrationExternalAction(
        action_id=model.id,
        run_id=model.run_id,
        action_key=model.action_key,
        action_type=ExternalActionType(model.action_type),
        target_identity=model.target_identity,
        request_fingerprint=model.request_fingerprint,
        candidate_sha=model.candidate_sha,
        generation=model.generation,
        status=ExternalActionStatus(model.status),
        remote_identifier=model.remote_identifier,
        result_payload=model.result_payload or {},
        error_message=model.error_message,
        reserved_at=model.reserved_at,
        reconciled_at=model.reconciled_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class PostgresProjectRepository(ProjectRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, project: Project) -> None:
        existing = self.session.get(ProjectModel, project.project_id)
        if existing:
            existing.display_name = project.display_name
            existing.repository = project.repository
            existing.base_branch = project.base_branch
            existing.openspec_path = project.openspec_path
            existing.implementer = project.implementer
            existing.reviewer = project.reviewer
            existing.checks = project.checks
            existing.external_providers_allowed = project.external_providers_allowed
            existing.openrouter_drain_allowed = project.openrouter_drain_allowed
            existing.deployment_preview = project.deployment_preview
            existing.deployment_production = project.deployment_production
            existing.status = project.status.value
            existing.updated_at = project.updated_at
        else:
            model = ProjectModel(
                id=project.project_id,
                display_name=project.display_name,
                repository=project.repository,
                base_branch=project.base_branch,
                openspec_path=project.openspec_path,
                implementer=project.implementer,
                reviewer=project.reviewer,
                checks=project.checks,
                external_providers_allowed=project.external_providers_allowed,
                openrouter_drain_allowed=project.openrouter_drain_allowed,
                deployment_preview=project.deployment_preview,
                deployment_production=project.deployment_production,
                status=project.status.value,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
            self.session.add(model)

    def get_by_id(self, project_id: str) -> Project | None:
        model = self.session.get(ProjectModel, project_id)
        return project_model_to_domain(model) if model else None

    def list_all(self) -> list[Project]:
        stmt = select(ProjectModel).order_by(ProjectModel.id)
        models = self.session.scalars(stmt).all()
        return [project_model_to_domain(m) for m in models]


class PostgresChangeRepository(ChangeRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, change: Change) -> None:
        physical = self.session.get(ChangeModel, change.change_id)
        logical_matches = self.session.scalars(
            select(ChangeModel).where(
                ChangeModel.project_id == change.project_id, ChangeModel.name == change.name
            )
        ).all()
        if len(logical_matches) > 1:
            raise ValueError(
                f"Ambiguous logical Change identity for project '{change.project_id}' and "
                f"change '{change.name}': {len(logical_matches)} rows found."
            )
        if physical is not None and logical_matches and logical_matches[0].id != physical.id:
            raise ValueError(
                f"Conflicting Change identities: physical id '{change.change_id}' does not "
                f"match the logical row for project '{change.project_id}' and change "
                f"'{change.name}'."
            )
        if physical:
            # A loaded domain entity carries an explicit lifecycle update.  Its
            # physical identity and original discovery timestamp are immutable,
            # but all caller-provided mutable state must be persisted.
            existing = physical
            existing.name = change.name
            existing.project_id = change.project_id
            existing.status = change.status.value
            existing.stage = change.stage
            existing.schema_name = change.schema_name
            existing.proposal_path = change.proposal_path
            existing.tasks_path = change.tasks_path
            existing.design_path = change.design_path
            existing.specs_paths = change.specs_paths
            existing.last_readiness_status = change.last_readiness_status.value
            existing.last_readiness_reasons = change.last_readiness_reasons
            existing.updated_at = change.updated_at
        elif logical_matches:
            # An unattached discovery object refreshes filesystem metadata but
            # must not regress the durable lifecycle/readiness state.
            existing = logical_matches[0]
            existing.schema_name = change.schema_name
            existing.proposal_path = change.proposal_path
            existing.tasks_path = change.tasks_path
            existing.design_path = change.design_path
            existing.specs_paths = change.specs_paths
            existing.updated_at = change.updated_at
        else:
            model = ChangeModel(
                id=change.change_id,
                project_id=change.project_id,
                name=change.name,
                status=change.status.value,
                stage=change.stage,
                schema_name=change.schema_name,
                proposal_path=change.proposal_path,
                tasks_path=change.tasks_path,
                design_path=change.design_path,
                specs_paths=change.specs_paths,
                last_readiness_status=change.last_readiness_status.value,
                last_readiness_reasons=change.last_readiness_reasons,
                discovered_at=change.discovered_at,
                updated_at=change.updated_at,
            )
            self.session.add(model)

    def get_by_id(self, change_id: str) -> Change | None:
        model = self.session.get(ChangeModel, change_id)
        return change_model_to_domain(model) if model else None

    def get_by_name(self, project_id: str, name: str) -> Change | None:
        stmt = select(ChangeModel).where(
            ChangeModel.project_id == project_id, ChangeModel.name == name
        )
        models = self.session.scalars(stmt).all()
        if len(models) > 1:
            raise ValueError(
                f"Ambiguous logical Change identity for project '{project_id}' and change "
                f"'{name}': {len(models)} rows found."
            )
        return change_model_to_domain(models[0]) if models else None

    def list_by_project(self, project_id: str) -> list[Change]:
        stmt = (
            select(ChangeModel)
            .where(ChangeModel.project_id == project_id)
            .order_by(ChangeModel.discovered_at)
        )
        models = self.session.scalars(stmt).all()
        return [change_model_to_domain(m) for m in models]


class PostgresProjectBindingRepository(ProjectBindingRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, binding: ProjectBinding) -> None:
        existing = self.session.get(ProjectBindingModel, binding.binding_id)
        if existing:
            existing.repository = binding.repository
            existing.github_issue_number = binding.github_issue_number
            existing.github_project_item_id = binding.github_project_item_id
            existing.github_pr_number = binding.github_pr_number
            existing.github_pr_url = binding.github_pr_url
            existing.openspec_change_name = binding.openspec_change_name
            existing.is_valid = binding.is_valid
            existing.mismatch_reasons = binding.mismatch_reasons
            existing.updated_at = binding.updated_at
        else:
            model = ProjectBindingModel(
                id=binding.binding_id,
                project_id=binding.project_id,
                repository=binding.repository,
                github_issue_number=binding.github_issue_number,
                github_project_item_id=binding.github_project_item_id,
                github_pr_number=binding.github_pr_number,
                github_pr_url=binding.github_pr_url,
                openspec_change_name=binding.openspec_change_name,
                is_valid=binding.is_valid,
                mismatch_reasons=binding.mismatch_reasons,
                created_at=binding.created_at,
                updated_at=binding.updated_at,
            )
            self.session.add(model)

    def get_by_id(self, binding_id: str) -> ProjectBinding | None:
        model = self.session.get(ProjectBindingModel, binding_id)
        return binding_model_to_domain(model) if model else None

    def get_by_project_and_change(self, project_id: str, change_name: str) -> ProjectBinding | None:
        stmt = select(ProjectBindingModel).where(
            ProjectBindingModel.project_id == project_id,
            ProjectBindingModel.openspec_change_name == change_name,
        )
        models = self.session.scalars(stmt).all()
        if len(models) > 1:
            raise ValueError(
                f"Ambiguous bindings: {len(models)} bindings found for project '{project_id}' "
                f"and change '{change_name}'."
            )
        return binding_model_to_domain(models[0]) if models else None


class PostgresEventRepository(EventRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, event: Event) -> None:
        model = EventModel(
            id=event.event_id,
            event_type=event.event_type.value,
            project_id=event.project_id,
            change_id=event.change_id,
            operation_id=event.operation_id,
            payload=event.payload,
            timestamp=event.timestamp,
        )
        self.session.add(model)

    def list_events(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        stmt = select(EventModel)
        if project_id:
            stmt = stmt.where(EventModel.project_id == project_id)
        if change_id:
            stmt = stmt.where(EventModel.change_id == change_id)
        stmt = stmt.order_by(desc(EventModel.timestamp)).limit(limit)
        models = self.session.scalars(stmt).all()
        return [event_model_to_domain(m) for m in models]


class PostgresMetricFactRepository(MetricFactRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, fact: MetricFact) -> None:
        model = MetricFactModel(
            id=fact.fact_id,
            metric_name=fact.metric_name,
            project_id=fact.project_id,
            change_id=fact.change_id,
            stage=fact.stage,
            duration_ms=fact.duration_ms,
            fact_value=fact.fact_value,
            details=fact.details,
            recorded_at=fact.recorded_at,
        )
        self.session.add(model)

    def list_facts(
        self,
        project_id: str | None = None,
        change_id: str | None = None,
        metric_name: str | None = None,
        limit: int = 100,
    ) -> list[MetricFact]:
        stmt = select(MetricFactModel)
        if project_id:
            stmt = stmt.where(MetricFactModel.project_id == project_id)
        if change_id:
            stmt = stmt.where(MetricFactModel.change_id == change_id)
        if metric_name:
            stmt = stmt.where(MetricFactModel.metric_name == metric_name)
        stmt = stmt.order_by(desc(MetricFactModel.recorded_at)).limit(limit)
        models = self.session.scalars(stmt).all()
        return [fact_model_to_domain(m) for m in models]


class PostgresJobRepository(JobRepositoryInterface):
    VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
        JobStatus.QUEUED: {
            JobStatus.RUNNING,
            JobStatus.WAITING_CAPACITY,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.RUNNING: {
            JobStatus.CHECKS_RUNNING,
            JobStatus.CHECKS_PASSED,
            JobStatus.CHECKS_FAILED,
            JobStatus.RUNNING,  # multi-attempt continuation loops
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_RUNNING: {
            JobStatus.CHECKS_PASSED,
            JobStatus.CHECKS_FAILED,
            JobStatus.RUNNING,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_PASSED: {
            JobStatus.REVIEW_RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.CHECKS_PASSED,
            JobStatus.READY_TO_MERGE,
            JobStatus.WAITING_CAPACITY,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHECKS_FAILED: {
            JobStatus.RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.CHECKS_PASSED,
            JobStatus.CHECKS_FAILED,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.REVIEW_RUNNING: {
            JobStatus.AUDIT_RUNNING,
            JobStatus.CHANGES_REQUIRED,
            JobStatus.CHECKS_PASSED,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.AUDIT_RUNNING: {
            JobStatus.READY_TO_MERGE,
            JobStatus.AUDIT_BLOCKED,
            JobStatus.CHECKS_PASSED,
            JobStatus.QUEUED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.WAITING_CAPACITY: {
            JobStatus.RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.REVIEW_RUNNING,
            JobStatus.AUDIT_RUNNING,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.RECOVERY_BLOCKED: {
            JobStatus.WAITING_CAPACITY,
            JobStatus.RUNNING,
            JobStatus.REVIEW_RUNNING,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.READY_TO_MERGE: {
            JobStatus.POST_MERGE_RECONCILING,
            JobStatus.COMPLETED,
        },
        JobStatus.POST_MERGE_RECONCILING: {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.COMPLETED: set(),
        JobStatus.AUDIT_BLOCKED: {
            JobStatus.RUNNING,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.CHANGES_REQUIRED: {
            JobStatus.RUNNING,
            JobStatus.NEEDS_HUMAN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.NEEDS_HUMAN: {
            JobStatus.RUNNING,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.FAILED: set(),
        JobStatus.CANCELLED: set(),
    }

    def __init__(self, session: Session):
        self.session = session

    def save(self, job: Job) -> None:
        existing = self.session.get(JobModel, job.job_id)
        if existing:
            existing.status = job.status.value
            existing.implementer_role = job.implementer_role
            existing.candidate_sha = job.candidate_sha
            existing.base_sha = job.base_sha
            existing.error_message = job.error_message
            existing.waiting_provider = job.waiting_provider
            existing.capacity_block_reason = job.capacity_block_reason
            existing.recovery_blocked_reason = job.recovery_blocked_reason
            existing.expected_reset_at = job.expected_reset_at
            existing.attempt_count = job.attempt_count
            existing.reassignment_count = job.reassignment_count
            existing.current_executor = job.current_executor
            existing.latest_outcome = job.latest_outcome.value if job.latest_outcome else None
            existing.latest_progress = job.latest_progress.value if job.latest_progress else None
            existing.continuation_decision = (
                job.continuation_decision.value if job.continuation_decision else None
            )
            existing.is_mixed_authorship = job.is_mixed_authorship
            existing.escalation_reason = job.escalation_reason
            existing.updated_at = job.updated_at
        else:
            model = JobModel(
                id=job.job_id,
                project_id=job.project_id,
                change_name=job.change_name,
                status=job.status.value,
                implementer_role=job.implementer_role,
                candidate_sha=job.candidate_sha,
                base_sha=job.base_sha,
                error_message=job.error_message,
                waiting_provider=job.waiting_provider,
                capacity_block_reason=job.capacity_block_reason,
                recovery_blocked_reason=job.recovery_blocked_reason,
                expected_reset_at=job.expected_reset_at,
                attempt_count=job.attempt_count,
                reassignment_count=job.reassignment_count,
                current_executor=job.current_executor,
                latest_outcome=job.latest_outcome.value if job.latest_outcome else None,
                latest_progress=job.latest_progress.value if job.latest_progress else None,
                continuation_decision=(
                    job.continuation_decision.value if job.continuation_decision else None
                ),
                is_mixed_authorship=job.is_mixed_authorship,
                escalation_reason=job.escalation_reason,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
            self.session.add(model)

    def get_by_id(self, job_id: str) -> Job | None:
        model = self.session.get(JobModel, job_id)
        return job_model_to_domain(model) if model else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[Job]:
        stmt = (
            select(JobModel)
            .where(JobModel.project_id == project_id)
            .order_by(desc(JobModel.created_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [job_model_to_domain(m) for m in models]

    def list_active_jobs(self) -> list[Job]:
        active_statuses = [
            JobStatus.QUEUED.value,
            JobStatus.RUNNING.value,
            JobStatus.CHECKS_RUNNING.value,
            JobStatus.CHECKS_PASSED.value,
            JobStatus.REVIEW_RUNNING.value,
            JobStatus.AUDIT_RUNNING.value,
            JobStatus.WAITING_CAPACITY.value,
            JobStatus.RECOVERY_BLOCKED.value,
        ]
        stmt = (
            select(JobModel)
            .where(JobModel.status.in_(active_statuses))
            .order_by(JobModel.created_at)
        )
        models = self.session.scalars(stmt).all()
        return [job_model_to_domain(m) for m in models]

    def transition(self, job_id: str, new_status: str, error_message: str | None = None) -> Job:
        model = self.session.get(JobModel, job_id)
        if not model:
            raise ValueError(f"Job '{job_id}' not found.")
        current = JobStatus(model.status)
        target = JobStatus(new_status)
        if current != target and target not in self.VALID_TRANSITIONS[current]:
            raise ValueError(f"Invalid job status transition: {current.value} -> {target.value}.")
        model.status = target.value
        model.error_message = error_message
        model.updated_at = utc_now()
        return job_model_to_domain(model)

    def set_waiting_capacity(
        self,
        job_id: str,
        waiting_provider: str,
        reason: str,
        expected_reset_at: datetime | None = None,
    ) -> Job:
        model = self.session.get(JobModel, job_id)
        if not model:
            raise ValueError(f"Job '{job_id}' not found.")
        current = JobStatus(model.status)
        target = JobStatus.WAITING_CAPACITY
        if target not in self.VALID_TRANSITIONS[current]:
            raise ValueError(f"Invalid job status transition: {current.value} -> {target.value}.")
        model.status = target.value
        model.waiting_provider = waiting_provider
        model.capacity_block_reason = reason
        model.expected_reset_at = expected_reset_at
        model.updated_at = utc_now()
        return job_model_to_domain(model)

    def set_recovery_blocked(self, job_id: str, reason: str) -> Job:
        model = self.session.get(JobModel, job_id)
        if not model:
            raise ValueError(f"Job '{job_id}' not found.")
        current = JobStatus(model.status)
        target = JobStatus.RECOVERY_BLOCKED
        if target not in self.VALID_TRANSITIONS[current]:
            raise ValueError(f"Invalid job status transition: {current.value} -> {target.value}.")
        model.status = target.value
        model.recovery_blocked_reason = reason
        model.updated_at = utc_now()
        return job_model_to_domain(model)

    for _status in JobStatus:
        VALID_TRANSITIONS[_status].add(JobStatus.RECOVERY_BLOCKED)


class PostgresJobLogRepository(JobLogRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, log: JobLog) -> None:
        self.session.add(
            JobLogModel(
                id=log.log_id,
                job_id=log.job_id,
                stream=log.stream,
                message=log.message,
                timestamp=log.timestamp,
            )
        )

    def list_by_job(self, job_id: str, limit: int = 500) -> list[JobLog]:
        stmt = (
            select(JobLogModel)
            .where(JobLogModel.job_id == job_id)
            .order_by(JobLogModel.timestamp)
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [job_log_model_to_domain(m) for m in models]


class PostgresCheckResultRepository(CheckResultRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, result: CheckResult) -> None:
        self.session.add(
            CheckResultModel(
                id=result.result_id,
                job_id=result.job_id,
                check_name=result.check_name,
                command=result.command,
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
                output_snippet=result.output_snippet,
                candidate_sha=result.candidate_sha or None,
                candidate_generation=result.candidate_generation,
                created_at=result.created_at,
            )
        )

    def list_by_job(self, job_id: str) -> list[CheckResult]:
        stmt = (
            select(CheckResultModel)
            .where(CheckResultModel.job_id == job_id)
            .order_by(CheckResultModel.created_at)
        )
        models = self.session.scalars(stmt).all()
        return [check_result_model_to_domain(m) for m in models]


class PostgresReviewRepository(ReviewRepositoryInterface):
    _valid_transitions: dict[ReviewStatus, set[ReviewStatus]] = {
        ReviewStatus.REVIEW_PENDING: {
            ReviewStatus.REVIEW_RUNNING,
            ReviewStatus.REVIEW_FAILED,
            ReviewStatus.REVIEW_TIMED_OUT,
        },
        ReviewStatus.REVIEW_RUNNING: {
            ReviewStatus.REVIEW_COMPLETED,
            ReviewStatus.REVIEW_FAILED,
            ReviewStatus.REVIEW_TIMED_OUT,
        },
        ReviewStatus.REVIEW_COMPLETED: set(),
        ReviewStatus.REVIEW_FAILED: set(),
        ReviewStatus.REVIEW_TIMED_OUT: set(),
    }

    def __init__(self, session: Session):
        self.session = session

    def save(self, review: Review) -> None:
        existing = self.session.get(ReviewModel, review.review_id)
        if existing:
            existing.status = review.status.value
            existing.verdict = review.verdict.value if review.verdict else None
            existing.summary = review.summary
            existing.error_message = review.error_message
            existing.is_mixed_authorship = review.is_mixed_authorship
            existing.authorship_evidence = review.authorship_evidence
            existing.reviewer_model = review.reviewer_model
            existing.orchestration_run_id = review.orchestration_run_id
            existing.candidate_generation = review.candidate_generation
            existing.candidate_sha = review.candidate_sha
            existing.base_sha = review.base_sha
            existing.manifest_id = review.manifest_id
            existing.manifest_hash = review.manifest_hash
            existing.updated_at = review.updated_at
        else:
            model = ReviewModel(
                id=review.review_id,
                job_id=review.job_id,
                project_id=review.project_id,
                change_name=review.change_name,
                reviewer_role=review.reviewer_role,
                reviewer_model=review.reviewer_model,
                orchestration_run_id=review.orchestration_run_id,
                candidate_generation=review.candidate_generation,
                candidate_sha=review.candidate_sha,
                base_sha=review.base_sha,
                manifest_id=review.manifest_id,
                manifest_hash=review.manifest_hash,
                status=review.status.value,
                verdict=review.verdict.value if review.verdict else None,
                summary=review.summary,
                error_message=review.error_message,
                is_mixed_authorship=review.is_mixed_authorship,
                authorship_evidence=review.authorship_evidence,
                created_at=review.created_at,
                updated_at=review.updated_at,
            )
            self.session.add(model)

    def get_by_id(self, review_id: str) -> Review | None:
        model = self.session.get(ReviewModel, review_id)
        return review_model_to_domain(model) if model else None

    def get_by_job_id(self, job_id: str) -> Review | None:
        stmt = (
            select(ReviewModel)
            .where(ReviewModel.job_id == job_id)
            .order_by(desc(ReviewModel.created_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return review_model_to_domain(model) if model else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[Review]:
        stmt = (
            select(ReviewModel)
            .where(ReviewModel.project_id == project_id)
            .order_by(desc(ReviewModel.created_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [review_model_to_domain(m) for m in models]

    def transition(
        self,
        review_id: str,
        new_status: str,
        verdict: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> Review:
        model = self.session.get(ReviewModel, review_id)
        if not model:
            raise ValueError(f"Review '{review_id}' not found.")
        current = ReviewStatus(model.status)
        target = ReviewStatus(new_status)
        if target not in self._valid_transitions[current]:
            raise ValueError(
                f"Invalid review status transition: {current.value} -> {target.value}."
            )
        model.status = target.value
        if verdict:
            model.verdict = ReviewVerdict(verdict).value
        if summary is not None:
            model.summary = summary
        if error_message is not None:
            model.error_message = error_message
        model.updated_at = utc_now()
        return review_model_to_domain(model)


class PostgresReviewFindingRepository(ReviewFindingRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, finding: ReviewFinding) -> None:
        self.session.add(
            ReviewFindingModel(
                id=finding.finding_id,
                review_id=finding.review_id,
                severity=finding.severity.value,
                location=finding.location,
                violated_requirement=finding.violated_requirement,
                expected_correction=finding.expected_correction,
                created_at=finding.created_at,
            )
        )

    def list_by_review(self, review_id: str) -> list[ReviewFinding]:
        stmt = (
            select(ReviewFindingModel)
            .where(ReviewFindingModel.review_id == review_id)
            .order_by(ReviewFindingModel.created_at)
        )
        models = self.session.scalars(stmt).all()
        return [review_finding_model_to_domain(m) for m in models]


class PostgresAuditRepository(AuditRepositoryInterface):
    _valid_transitions: dict[AuditStatus, set[AuditStatus]] = {
        AuditStatus.AUDIT_PENDING: {
            AuditStatus.AUDIT_RUNNING,
            AuditStatus.AUDIT_FAILED,
            AuditStatus.AUDIT_TIMED_OUT,
        },
        AuditStatus.AUDIT_RUNNING: {
            AuditStatus.AUDIT_COMPLETED,
            AuditStatus.AUDIT_BLOCKED,
            AuditStatus.AUDIT_FAILED,
            AuditStatus.AUDIT_TIMED_OUT,
        },
        AuditStatus.AUDIT_COMPLETED: set(),
        AuditStatus.AUDIT_BLOCKED: set(),
        AuditStatus.AUDIT_FAILED: set(),
        AuditStatus.AUDIT_TIMED_OUT: set(),
    }

    def __init__(self, session: Session):
        self.session = session

    def save(self, audit: AuditRecord) -> None:
        existing = self.session.get(AuditModel, audit.audit_id)
        if existing:
            existing.status = audit.status.value
            existing.risk = audit.risk.value if audit.risk else None
            existing.summary = audit.summary
            existing.error_message = audit.error_message
            existing.provider = audit.provider
            existing.model = audit.model
            existing.orchestration_run_id = audit.orchestration_run_id
            existing.candidate_generation = audit.candidate_generation
            existing.candidate_sha = audit.candidate_sha
            existing.base_sha = audit.base_sha
            existing.manifest_id = audit.manifest_id
            existing.manifest_hash = audit.manifest_hash
            existing.is_full_candidate = audit.is_full_candidate
            existing.updated_at = audit.updated_at
        else:
            self.session.add(
                AuditModel(
                    id=audit.audit_id,
                    job_id=audit.job_id,
                    project_id=audit.project_id,
                    change_name=audit.change_name,
                    provider=audit.provider,
                    model=audit.model,
                    orchestration_run_id=audit.orchestration_run_id,
                    candidate_generation=audit.candidate_generation,
                    candidate_sha=audit.candidate_sha,
                    base_sha=audit.base_sha,
                    manifest_id=audit.manifest_id,
                    manifest_hash=audit.manifest_hash,
                    is_full_candidate=audit.is_full_candidate,
                    review_id=audit.review_id,
                    review_verdict=audit.review_verdict.value if audit.review_verdict else None,
                    status=audit.status.value,
                    risk=audit.risk.value if audit.risk else None,
                    summary=audit.summary,
                    error_message=audit.error_message,
                    created_at=audit.created_at,
                    updated_at=audit.updated_at,
                )
            )

    def get_by_id(self, audit_id: str) -> AuditRecord | None:
        model = self.session.get(AuditModel, audit_id)
        return audit_model_to_domain(model) if model else None

    def get_by_job_id(self, job_id: str) -> AuditRecord | None:
        stmt = (
            select(AuditModel)
            .where(AuditModel.job_id == job_id)
            .order_by(desc(AuditModel.created_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return audit_model_to_domain(model) if model else None

    def list_by_project(self, project_id: str, limit: int = 100) -> list[AuditRecord]:
        stmt = (
            select(AuditModel)
            .where(AuditModel.project_id == project_id)
            .order_by(desc(AuditModel.created_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [audit_model_to_domain(m) for m in models]

    def transition(
        self,
        audit_id: str,
        new_status: str,
        risk: str | None = None,
        summary: str | None = None,
        error_message: str | None = None,
    ) -> AuditRecord:
        model = self.session.get(AuditModel, audit_id)
        if not model:
            raise ValueError(f"Audit '{audit_id}' not found.")
        current = AuditStatus(model.status)
        target = AuditStatus(new_status)
        if target not in self._valid_transitions[current]:
            raise ValueError(f"Invalid audit status transition: {current.value} -> {target.value}.")
        model.status = target.value
        if risk:
            model.risk = AuditRiskLevel(risk).value
        if summary is not None:
            model.summary = summary
        if error_message is not None:
            model.error_message = error_message
        model.updated_at = utc_now()
        return audit_model_to_domain(model)


class PostgresAuditFindingRepository(AuditFindingRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, finding: AuditFinding) -> None:
        self.session.add(
            AuditFindingModel(
                id=finding.finding_id,
                audit_id=finding.audit_id,
                severity=finding.severity.value,
                category=finding.category,
                message=finding.message,
                file=finding.file,
                location=finding.location,
                created_at=finding.created_at,
            )
        )

    def list_by_audit(self, audit_id: str) -> list[AuditFinding]:
        stmt = (
            select(AuditFindingModel)
            .where(AuditFindingModel.audit_id == audit_id)
            .order_by(AuditFindingModel.created_at)
        )
        models = self.session.scalars(stmt).all()
        return [audit_finding_model_to_domain(m) for m in models]


class PostgresProviderHealthRepository(ProviderHealthRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def _validate_primary_provider(self, provider: str) -> None:
        if provider not in PRIMARY_PROVIDERS:
            raise ValueError(
                f"Invalid primary provider '{provider}'. "
                f"005 capacity tracking is restricted strictly to {PRIMARY_PROVIDERS}."
            )

    def save(self, health: ProviderHealth) -> None:
        health.validate_primary()
        existing = self.session.scalars(
            select(ProviderHealthModel).where(ProviderHealthModel.provider == health.provider)
        ).first()
        if existing:
            existing.model = health.model
            existing.status = health.status.value
            existing.consecutive_failures = health.consecutive_failures
            existing.last_result_class = (
                health.last_result_class.value if health.last_result_class else None
            )
            existing.last_error_summary = health.last_error_summary
            existing.last_success_at = health.last_success_at
            existing.last_failure_at = health.last_failure_at
            existing.updated_at = health.updated_at
        else:
            model = ProviderHealthModel(
                id=health.health_id,
                provider=health.provider,
                model=health.model,
                status=health.status.value,
                consecutive_failures=health.consecutive_failures,
                last_result_class=health.last_result_class.value
                if health.last_result_class
                else None,
                last_error_summary=health.last_error_summary,
                last_success_at=health.last_success_at,
                last_failure_at=health.last_failure_at,
                updated_at=health.updated_at,
            )
            self.session.add(model)

    def get_by_provider(self, provider: str) -> ProviderHealth | None:
        self._validate_primary_provider(provider)
        stmt = select(ProviderHealthModel).where(ProviderHealthModel.provider == provider)
        model = self.session.scalars(stmt).first()
        return provider_health_model_to_domain(model) if model else None

    def list_all(self) -> list[ProviderHealth]:
        stmt = select(ProviderHealthModel).order_by(ProviderHealthModel.provider)
        models = self.session.scalars(stmt).all()
        return [provider_health_model_to_domain(m) for m in models]

    def update_health(
        self,
        provider: str,
        status: str,
        result_class: str | None = None,
        error_summary: str | None = None,
        consecutive_failures: int | None = None,
    ) -> ProviderHealth:
        self._validate_primary_provider(provider)
        model = self.session.scalars(
            select(ProviderHealthModel).where(ProviderHealthModel.provider == provider)
        ).first()
        now = utc_now()
        target_status = ProviderHealthStatus(status)
        target_result_class = ProviderResultClass(result_class) if result_class else None

        if not model:
            init_failures = (
                consecutive_failures
                if consecutive_failures is not None
                else (0 if target_status == ProviderHealthStatus.AVAILABLE else 1)
            )
            model = ProviderHealthModel(
                id=f"ph-{provider}",
                provider=provider,
                status=target_status.value,
                consecutive_failures=init_failures,
                last_result_class=target_result_class.value if target_result_class else None,
                last_error_summary=error_summary,
                last_success_at=now if target_status == ProviderHealthStatus.AVAILABLE else None,
                last_failure_at=now if target_status != ProviderHealthStatus.AVAILABLE else None,
                updated_at=now,
            )
            self.session.add(model)
        else:
            model.status = target_status.value
            if target_result_class:
                model.last_result_class = target_result_class.value
            if error_summary is not None:
                model.last_error_summary = error_summary
            if consecutive_failures is not None:
                model.consecutive_failures = consecutive_failures
            elif target_status == ProviderHealthStatus.AVAILABLE:
                model.consecutive_failures = 0
            else:
                model.consecutive_failures += 1

            if (
                target_status == ProviderHealthStatus.AVAILABLE
                and target_result_class == ProviderResultClass.SUCCESS
            ):
                model.last_success_at = now
            elif target_result_class and target_result_class != ProviderResultClass.SUCCESS:
                model.last_failure_at = now

            model.updated_at = now

        return provider_health_model_to_domain(model)


class PostgresCapacityWindowRepository(CapacityWindowRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def _validate_primary_provider(self, provider: str) -> None:
        if provider not in PRIMARY_PROVIDERS:
            raise ValueError(
                f"Invalid primary provider '{provider}'. "
                f"005 capacity windows are restricted strictly to {PRIMARY_PROVIDERS}."
            )

    def save(self, window: CapacityWindow) -> None:
        window.validate_primary()
        model = CapacityWindowModel(
            id=window.window_id,
            provider=window.provider,
            model=window.model,
            quota_exhausted_at=window.quota_exhausted_at,
            capacity_reset_at=window.capacity_reset_at,
            retry_after_seconds=window.retry_after_seconds,
            source_signal=window.source_signal.value,
            created_at=window.created_at,
        )
        self.session.add(model)

    def get_latest_for_provider(self, provider: str) -> CapacityWindow | None:
        self._validate_primary_provider(provider)
        stmt = (
            select(CapacityWindowModel)
            .where(CapacityWindowModel.provider == provider)
            .order_by(desc(CapacityWindowModel.quota_exhausted_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return capacity_window_model_to_domain(model) if model else None

    def list_by_provider(self, provider: str, limit: int = 50) -> list[CapacityWindow]:
        self._validate_primary_provider(provider)
        stmt = (
            select(CapacityWindowModel)
            .where(CapacityWindowModel.provider == provider)
            .order_by(desc(CapacityWindowModel.quota_exhausted_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [capacity_window_model_to_domain(m) for m in models]


class PostgresGitOperationRepository(GitOperationRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, operation: GitOperation) -> None:
        existing = self.session.get(GitOperationModel, operation.operation_id)
        if existing:
            existing.job_id = operation.job_id
            existing.project_id = operation.project_id
            existing.worktree_path = operation.worktree_path
            existing.operation_type = operation.operation_type
            existing.pid = operation.pid
            existing.status = operation.status.value
            existing.started_at = operation.started_at
            existing.completed_at = operation.completed_at
        else:
            model = GitOperationModel(
                id=operation.operation_id,
                job_id=operation.job_id,
                project_id=operation.project_id,
                worktree_path=operation.worktree_path,
                operation_type=operation.operation_type,
                pid=operation.pid,
                status=operation.status.value,
                started_at=operation.started_at,
                completed_at=operation.completed_at,
            )
            self.session.add(model)

    def get_by_id(self, operation_id: str) -> GitOperation | None:
        model = self.session.get(GitOperationModel, operation_id)
        return git_operation_model_to_domain(model) if model else None

    def list_by_job(self, job_id: str) -> list[GitOperation]:
        stmt = (
            select(GitOperationModel)
            .where(GitOperationModel.job_id == job_id)
            .order_by(desc(GitOperationModel.started_at))
        )
        models = self.session.scalars(stmt).all()
        return [git_operation_model_to_domain(m) for m in models]

    def list_by_worktree(self, worktree_path: str) -> list[GitOperation]:
        stmt = (
            select(GitOperationModel)
            .where(GitOperationModel.worktree_path == worktree_path)
            .order_by(desc(GitOperationModel.started_at))
        )
        models = self.session.scalars(stmt).all()
        return [git_operation_model_to_domain(m) for m in models]

    def update_status(
        self,
        operation_id: str,
        status: GitOperationStatus,
        completed_at: datetime | None = None,
    ) -> GitOperation | None:
        model = self.session.get(GitOperationModel, operation_id)
        if not model:
            return None
        model.status = status.value
        if completed_at:
            model.completed_at = completed_at
        return git_operation_model_to_domain(model)


class PostgresOpenRouterBudgetPolicyRepository(OpenRouterBudgetPolicyRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def get_for_update(self, project_id: str) -> OpenRouterBudgetPolicy | None:
        model = self.session.scalars(
            select(OpenRouterBudgetPolicyModel)
            .where(OpenRouterBudgetPolicyModel.project_id == project_id)
            .with_for_update()
        ).first()
        return budget_policy_model_to_domain(model) if model else None

    def save(self, policy: OpenRouterBudgetPolicy) -> None:
        existing = self.session.get(OpenRouterBudgetPolicyModel, policy.project_id)
        if existing:
            existing.enabled = policy.enabled
            existing.daily_cap_usd = policy.daily_cap_usd
            existing.monthly_cap_usd = policy.monthly_cap_usd
            existing.currency = policy.currency
            existing.policy_version = policy.policy_version
            existing.is_breached = policy.is_breached
            existing.updated_at = policy.updated_at
            return
        self.session.add(
            OpenRouterBudgetPolicyModel(
                project_id=policy.project_id,
                enabled=policy.enabled,
                daily_cap_usd=policy.daily_cap_usd,
                monthly_cap_usd=policy.monthly_cap_usd,
                currency=policy.currency,
                policy_version=policy.policy_version,
                is_breached=policy.is_breached,
                updated_at=policy.updated_at,
            )
        )

    def get_by_project(self, project_id: str) -> OpenRouterBudgetPolicy | None:
        model = self.session.get(OpenRouterBudgetPolicyModel, project_id)
        return budget_policy_model_to_domain(model) if model else None


class PostgresOpenRouterPricingSnapshotRepository(OpenRouterPricingSnapshotRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, snapshot: OpenRouterPricingSnapshot) -> None:
        if self.session.get(OpenRouterPricingSnapshotModel, snapshot.snapshot_id):
            return
        self.session.add(
            OpenRouterPricingSnapshotModel(
                id=snapshot.snapshot_id,
                canonical_model_identity=snapshot.canonical_model_identity,
                routed_model_identity=snapshot.routed_model_identity,
                prompt_price_per_token=snapshot.prompt_price_per_token,
                output_price_per_token=snapshot.output_price_per_token,
                additional_cost_per_request=snapshot.additional_cost_per_request,
                currency=snapshot.currency,
                source=snapshot.source,
                observed_at=snapshot.observed_at,
                created_at=snapshot.created_at,
            )
        )

    def get_by_id(self, snapshot_id: str) -> OpenRouterPricingSnapshot | None:
        model = self.session.get(OpenRouterPricingSnapshotModel, snapshot_id)
        return pricing_snapshot_model_to_domain(model) if model else None

    def get_latest_verified_for_model(
        self, routed_model: str, canonical_name: str | None = None
    ) -> OpenRouterPricingSnapshot | None:
        stmt = (
            select(OpenRouterPricingSnapshotModel)
            .where(
                OpenRouterPricingSnapshotModel.routed_model_identity == routed_model,
                OpenRouterPricingSnapshotModel.source.in_(AUTHORITATIVE_PRICING_SOURCES),
            )
            .order_by(
                OpenRouterPricingSnapshotModel.observed_at.desc(),
                OpenRouterPricingSnapshotModel.created_at.desc(),
            )
        )
        if canonical_name:
            stmt = stmt.where(
                OpenRouterPricingSnapshotModel.canonical_model_identity == canonical_name
            )
        model = self.session.scalars(stmt).first()
        return pricing_snapshot_model_to_domain(model) if model else None

    def list_by_model(self, routed_model: str) -> list[OpenRouterPricingSnapshot]:
        stmt = (
            select(OpenRouterPricingSnapshotModel)
            .where(OpenRouterPricingSnapshotModel.routed_model_identity == routed_model)
            .order_by(OpenRouterPricingSnapshotModel.observed_at.desc())
        )
        return [pricing_snapshot_model_to_domain(m) for m in self.session.scalars(stmt).all()]


class PostgresBudgetReservationRepository(BudgetReservationRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, reservation: BudgetReservation) -> None:
        existing = self.session.get(BudgetReservationModel, reservation.reservation_id)
        if existing:
            existing.status = reservation.status
            existing.updated_at = reservation.updated_at
            return
        self.session.add(
            BudgetReservationModel(
                id=reservation.reservation_id,
                project_id=reservation.project_id,
                job_id=reservation.job_id,
                change_id=reservation.change_id,
                role=reservation.role,
                canonical_model_identity=reservation.canonical_model_identity,
                reserved_amount_usd=reservation.reserved_amount_usd,
                status=reservation.status,
                pricing_snapshot_id=reservation.pricing_snapshot_id,
                correlation_id=reservation.correlation_id,
                created_at=reservation.created_at,
                updated_at=reservation.updated_at,
            )
        )

    def get_by_id(self, reservation_id: str) -> BudgetReservation | None:
        model = self.session.get(BudgetReservationModel, reservation_id)
        return budget_reservation_model_to_domain(model) if model else None

    def list_by_project(self, project_id: str) -> list[BudgetReservation]:
        return [
            budget_reservation_model_to_domain(m)
            for m in self.session.scalars(
                select(BudgetReservationModel).where(
                    BudgetReservationModel.project_id == project_id
                )
            ).all()
        ]


class PostgresBudgetLedgerRepository(BudgetLedgerRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, entry: BudgetLedgerEntry) -> None:
        self.session.add(
            BudgetLedgerModel(
                id=entry.entry_id,
                reservation_id=entry.reservation_id,
                project_id=entry.project_id,
                job_id=entry.job_id,
                change_id=entry.change_id,
                provider=entry.provider,
                role=entry.role,
                canonical_model_identity=entry.canonical_model_identity,
                prompt_tokens=entry.prompt_tokens,
                completion_tokens=entry.completion_tokens,
                total_tokens=entry.total_tokens,
                amount_usd=entry.amount_usd,
                entry_type=entry.entry_type,
                created_at=entry.created_at,
            )
        )

    def list_by_project(self, project_id: str) -> list[BudgetLedgerEntry]:
        return [
            budget_ledger_model_to_domain(m)
            for m in self.session.scalars(
                select(BudgetLedgerModel).where(BudgetLedgerModel.project_id == project_id)
            ).all()
        ]


class PostgresJobAttemptRepository(JobAttemptRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, attempt: JobAttempt) -> None:
        existing = self.session.get(JobAttemptModel, attempt.attempt_id)
        if existing:
            existing.start_sha = attempt.start_sha
            existing.end_sha = attempt.end_sha
            existing.normalized_outcome = attempt.normalized_outcome.value
            existing.progress_classification = (
                attempt.progress_classification.value if attempt.progress_classification else None
            )
            existing.continuation_decision = (
                attempt.continuation_decision.value if attempt.continuation_decision else None
            )
            existing.corrective_retries_count = attempt.corrective_retries_count
            existing.same_outcome_streak = attempt.same_outcome_streak
            existing.same_blocker_fingerprint_streak = attempt.same_blocker_fingerprint_streak
            existing.completed_at = attempt.completed_at
            existing.duration_ms = attempt.duration_ms
            existing.corrective_prompt = attempt.corrective_prompt
            existing.task_class = attempt.task_class.value if attempt.task_class else None
            existing.productivity_class = (
                attempt.productivity_class.value if attempt.productivity_class else None
            )
            existing.premium_reason_code = (
                attempt.premium_reason_code.value if attempt.premium_reason_code else None
            )
            existing.is_same_sha_duplicate = attempt.is_same_sha_duplicate
            existing.error_details = attempt.error_details
        else:
            self.session.add(
                JobAttemptModel(
                    id=attempt.attempt_id,
                    job_id=attempt.job_id,
                    attempt_number=attempt.attempt_number,
                    executor_role=attempt.executor_role,
                    model_identity=attempt.model_identity,
                    start_sha=attempt.start_sha,
                    end_sha=attempt.end_sha,
                    normalized_outcome=attempt.normalized_outcome.value,
                    progress_classification=(
                        attempt.progress_classification.value
                        if attempt.progress_classification
                        else None
                    ),
                    continuation_decision=(
                        attempt.continuation_decision.value
                        if attempt.continuation_decision
                        else None
                    ),
                    corrective_retries_count=attempt.corrective_retries_count,
                    same_outcome_streak=attempt.same_outcome_streak,
                    same_blocker_fingerprint_streak=attempt.same_blocker_fingerprint_streak,
                    started_at=attempt.started_at,
                    completed_at=attempt.completed_at,
                    duration_ms=attempt.duration_ms,
                    corrective_prompt=attempt.corrective_prompt,
                    task_class=attempt.task_class.value if attempt.task_class else None,
                    productivity_class=(
                        attempt.productivity_class.value if attempt.productivity_class else None
                    ),
                    premium_reason_code=(
                        attempt.premium_reason_code.value if attempt.premium_reason_code else None
                    ),
                    is_same_sha_duplicate=attempt.is_same_sha_duplicate,
                    error_details=attempt.error_details,
                    created_at=attempt.created_at,
                )
            )

    def get_by_id(self, attempt_id: str) -> JobAttempt | None:
        model = self.session.get(JobAttemptModel, attempt_id)
        return job_attempt_model_to_domain(model) if model else None

    def list_by_job(self, job_id: str) -> list[JobAttempt]:
        stmt = (
            select(JobAttemptModel)
            .where(JobAttemptModel.job_id == job_id)
            .order_by(JobAttemptModel.attempt_number.asc())
        )
        return [job_attempt_model_to_domain(m) for m in self.session.scalars(stmt).all()]

    def get_latest_attempt(self, job_id: str) -> JobAttempt | None:
        stmt = (
            select(JobAttemptModel)
            .where(JobAttemptModel.job_id == job_id)
            .order_by(JobAttemptModel.attempt_number.desc())
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return job_attempt_model_to_domain(model) if model else None


class PostgresBlockerClaimRepository(BlockerClaimRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, claim: BlockerClaim) -> None:
        existing = self.session.get(BlockerClaimModel, claim.claim_id)
        if existing:
            existing.validation_verdict = claim.validation_verdict.value
            existing.validation_rationale = claim.validation_rationale
            existing.available_integration_points = claim.available_integration_points
        else:
            self.session.add(
                BlockerClaimModel(
                    id=claim.claim_id,
                    job_id=claim.job_id,
                    attempt_id=claim.attempt_id,
                    blocker_type=claim.blocker_type,
                    blocker_fingerprint=claim.blocker_fingerprint,
                    affected_requirement=claim.affected_requirement,
                    failing_invariant=claim.failing_invariant,
                    evidence=claim.evidence,
                    attempted_remediation=claim.attempted_remediation,
                    rationale=claim.rationale,
                    is_agent_solvable=claim.is_agent_solvable,
                    validation_verdict=claim.validation_verdict.value,
                    validation_rationale=claim.validation_rationale,
                    available_integration_points=claim.available_integration_points,
                    created_at=claim.created_at,
                )
            )

    def get_by_id(self, claim_id: str) -> BlockerClaim | None:
        model = self.session.get(BlockerClaimModel, claim_id)
        return blocker_claim_model_to_domain(model) if model else None

    def list_by_job(self, job_id: str) -> list[BlockerClaim]:
        stmt = (
            select(BlockerClaimModel)
            .where(BlockerClaimModel.job_id == job_id)
            .order_by(BlockerClaimModel.created_at.asc())
        )
        return [blocker_claim_model_to_domain(m) for m in self.session.scalars(stmt).all()]

    def list_by_attempt(self, attempt_id: str) -> list[BlockerClaim]:
        stmt = (
            select(BlockerClaimModel)
            .where(BlockerClaimModel.attempt_id == attempt_id)
            .order_by(BlockerClaimModel.created_at.asc())
        )
        return [blocker_claim_model_to_domain(m) for m in self.session.scalars(stmt).all()]


class PostgresJobHandoffRepository(JobHandoffRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, handoff: JobHandoff) -> None:
        existing = self.session.get(JobHandoffModel, handoff.handoff_id)
        if existing:
            existing.to_attempt_id = handoff.to_attempt_id
            existing.is_consumed = handoff.is_consumed
        else:
            self.session.add(
                JobHandoffModel(
                    id=handoff.handoff_id,
                    job_id=handoff.job_id,
                    from_attempt_id=handoff.from_attempt_id,
                    to_attempt_id=handoff.to_attempt_id,
                    from_executor=handoff.from_executor,
                    to_executor=handoff.to_executor,
                    worktree_path=handoff.worktree_path,
                    base_sha=handoff.base_sha,
                    candidate_sha=handoff.candidate_sha,
                    completed_tasks=handoff.completed_tasks,
                    remaining_tasks=handoff.remaining_tasks,
                    manifest_summary=handoff.manifest_summary,
                    checks_summary=handoff.checks_summary,
                    blockers_summary=handoff.blockers_summary,
                    architectural_notes=handoff.architectural_notes,
                    do_not_redo_guidance=handoff.do_not_redo_guidance,
                    authorship_history=handoff.authorship_history,
                    is_consumed=handoff.is_consumed,
                    created_at=handoff.created_at,
                )
            )

    def get_by_id(self, handoff_id: str) -> JobHandoff | None:
        model = self.session.get(JobHandoffModel, handoff_id)
        return job_handoff_model_to_domain(model) if model else None

    def get_latest_handoff(self, job_id: str) -> JobHandoff | None:
        stmt = (
            select(JobHandoffModel)
            .where(JobHandoffModel.job_id == job_id)
            .order_by(JobHandoffModel.created_at.desc())
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return job_handoff_model_to_domain(model) if model else None

    def list_by_job(self, job_id: str) -> list[JobHandoff]:
        stmt = (
            select(JobHandoffModel)
            .where(JobHandoffModel.job_id == job_id)
            .order_by(JobHandoffModel.created_at.asc())
        )
        return [job_handoff_model_to_domain(m) for m in self.session.scalars(stmt).all()]


class PostgresCandidateManifestRepository(CandidateManifestRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, manifest: CandidateManifest) -> None:
        existing = self.session.get(CandidateManifestModel, manifest.manifest_id)
        if existing:
            existing.attempt_id = manifest.attempt_id
            existing.tracked_files = manifest.tracked_files
            existing.staged_files = manifest.staged_files
            existing.untracked_files = manifest.untracked_files
            existing.deleted_files = manifest.deleted_files
            existing.total_files_count = manifest.total_files_count
            existing.manifest_hash = manifest.manifest_hash
        else:
            self.session.add(
                CandidateManifestModel(
                    id=manifest.manifest_id,
                    job_id=manifest.job_id,
                    attempt_id=manifest.attempt_id,
                    candidate_sha=manifest.candidate_sha,
                    tracked_files=manifest.tracked_files,
                    staged_files=manifest.staged_files,
                    untracked_files=manifest.untracked_files,
                    deleted_files=manifest.deleted_files,
                    total_files_count=manifest.total_files_count,
                    manifest_hash=manifest.manifest_hash,
                    created_at=manifest.created_at,
                )
            )

    def get_by_id(self, manifest_id: str) -> CandidateManifest | None:
        model = self.session.get(CandidateManifestModel, manifest_id)
        return candidate_manifest_model_to_domain(model) if model else None

    def get_by_candidate_sha(self, job_id: str, candidate_sha: str) -> CandidateManifest | None:
        stmt = (
            select(CandidateManifestModel)
            .where(
                CandidateManifestModel.job_id == job_id,
                CandidateManifestModel.candidate_sha == candidate_sha,
            )
            .order_by(CandidateManifestModel.created_at.desc())
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return candidate_manifest_model_to_domain(model) if model else None

    def get_latest_manifest(self, job_id: str) -> CandidateManifest | None:
        stmt = (
            select(CandidateManifestModel)
            .where(CandidateManifestModel.job_id == job_id)
            .order_by(CandidateManifestModel.created_at.desc())
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return candidate_manifest_model_to_domain(model) if model else None


class PostgresCandidateAuthorshipRepository(CandidateAuthorshipRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, authorship: CandidateAuthorship) -> None:
        existing = self.session.get(CandidateAuthorshipModel, authorship.authorship_id)
        if existing:
            existing.files_touched = authorship.files_touched
            existing.is_primary_author = authorship.is_primary_author
        else:
            self.session.add(
                CandidateAuthorshipModel(
                    id=authorship.authorship_id,
                    job_id=authorship.job_id,
                    agent_role=authorship.agent_role,
                    model_identity=authorship.model_identity,
                    attempt_number=authorship.attempt_number,
                    files_touched=authorship.files_touched,
                    is_primary_author=authorship.is_primary_author,
                    created_at=authorship.created_at,
                )
            )
        self.session.flush()

    def list_by_job(self, job_id: str) -> list[CandidateAuthorship]:
        stmt = (
            select(CandidateAuthorshipModel)
            .where(CandidateAuthorshipModel.job_id == job_id)
            .order_by(CandidateAuthorshipModel.attempt_number.asc())
        )
        return [candidate_authorship_model_to_domain(m) for m in self.session.scalars(stmt).all()]


class PostgresEvidenceDiagnosticRepository(EvidenceDiagnosticRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, diagnostic: EvidenceDiagnostic) -> None:
        existing = self.session.get(EvidenceDiagnosticModel, diagnostic.diagnostic_id)
        if existing:
            existing.diagnostic_status = diagnostic.diagnostic_status.value
            existing.reason = diagnostic.reason
            existing.evidence_reference = diagnostic.evidence_reference
        else:
            self.session.add(
                EvidenceDiagnosticModel(
                    id=diagnostic.diagnostic_id,
                    job_id=diagnostic.job_id,
                    attempt_id=diagnostic.attempt_id,
                    stage_type=diagnostic.stage_type,
                    check_name=diagnostic.check_name,
                    diagnostic_status=diagnostic.diagnostic_status.value,
                    environment_identity=diagnostic.environment_identity,
                    candidate_sha=diagnostic.candidate_sha,
                    reason=diagnostic.reason,
                    evidence_reference=diagnostic.evidence_reference,
                    created_at=diagnostic.created_at,
                )
            )

    def list_by_job(self, job_id: str) -> list[EvidenceDiagnostic]:
        stmt = (
            select(EvidenceDiagnosticModel)
            .where(EvidenceDiagnosticModel.job_id == job_id)
            .order_by(EvidenceDiagnosticModel.created_at.asc())
        )
        return [evidence_diagnostic_model_to_domain(m) for m in self.session.scalars(stmt).all()]

    def list_by_attempt(self, attempt_id: str) -> list[EvidenceDiagnostic]:
        stmt = (
            select(EvidenceDiagnosticModel)
            .where(EvidenceDiagnosticModel.attempt_id == attempt_id)
            .order_by(EvidenceDiagnosticModel.created_at.asc())
        )
        return [evidence_diagnostic_model_to_domain(m) for m in self.session.scalars(stmt).all()]


class PostgresOrchestrationRunRepository(OrchestrationRunRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, run: OrchestrationRun) -> None:
        existing = self.session.get(OrchestrationRunModel, run.run_id)
        if existing:
            existing.project_id = run.project_id
            existing.change_name = run.change_name
            existing.base_sha = run.base_sha
            existing.current_stage = run.current_stage.value
            existing.resumable_stage = run.resumable_stage.value
            existing.human_gate = run.human_gate.value if run.human_gate else None
            existing.stop_reason = run.stop_reason
            existing.stop_details = run.stop_details
            existing.stop_outcome = run.stop_outcome.value if run.stop_outcome else None
            existing.human_gate = run.human_gate.value if run.human_gate else None
            existing.stop_reason = run.stop_reason
            existing.stop_details = run.stop_details
            existing.active_job_id = run.active_job_id
            existing.current_generation = run.current_generation
            existing.current_candidate_sha = run.current_candidate_sha
            existing.is_active = run.is_active
            existing.updated_at = utc_now()
        else:
            self.session.add(
                OrchestrationRunModel(
                    id=run.run_id,
                    project_id=run.project_id,
                    change_name=run.change_name,
                    base_sha=run.base_sha,
                    current_stage=run.current_stage.value,
                    resumable_stage=run.resumable_stage.value,
                    stop_outcome=run.stop_outcome.value if run.stop_outcome else None,
                    human_gate=run.human_gate.value if run.human_gate else None,
                    stop_reason=run.stop_reason,
                    stop_details=run.stop_details,
                    active_job_id=run.active_job_id,
                    current_generation=run.current_generation,
                    current_candidate_sha=run.current_candidate_sha,
                    is_active=run.is_active,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )

    def get_by_id(self, run_id: str) -> OrchestrationRun | None:
        model = self.session.get(OrchestrationRunModel, run_id)
        return orchestration_run_model_to_domain(model) if model else None

    def get_active_run(self, project_id: str, change_name: str) -> OrchestrationRun | None:
        stmt = select(OrchestrationRunModel).where(
            OrchestrationRunModel.project_id == project_id,
            OrchestrationRunModel.change_name == change_name,
            OrchestrationRunModel.is_active.is_(True),
        )
        model = self.session.scalars(stmt).first()
        return orchestration_run_model_to_domain(model) if model else None

    def list_runs(
        self,
        project_id: str | None = None,
        change_name: str | None = None,
        is_active: bool | None = None,
    ) -> list[OrchestrationRun]:
        stmt = select(OrchestrationRunModel)
        if project_id:
            stmt = stmt.where(OrchestrationRunModel.project_id == project_id)
        if change_name:
            stmt = stmt.where(OrchestrationRunModel.change_name == change_name)
        if is_active is not None:
            stmt = stmt.where(OrchestrationRunModel.is_active.is_(is_active))
        stmt = stmt.order_by(desc(OrchestrationRunModel.created_at))
        return [orchestration_run_model_to_domain(m) for m in self.session.scalars(stmt).all()]

    def update_stage(
        self,
        run_id: str,
        current_stage: OrchestrationStage,
        resumable_stage: OrchestrationStage,
    ) -> OrchestrationRun:
        model = self.session.get(OrchestrationRunModel, run_id)
        if not model:
            raise ValueError(f"Orchestration run '{run_id}' not found")
        model.current_stage = current_stage.value
        model.resumable_stage = resumable_stage.value
        model.updated_at = utc_now()
        return orchestration_run_model_to_domain(model)

    def update_stop_outcome(
        self,
        run_id: str,
        stop_outcome: OrchestrationStopOutcome,
        human_gate: HumanGate | None = None,
        stop_reason: str | None = None,
        stop_details: dict[str, Any] | None = None,
        is_active: bool = False,
    ) -> OrchestrationRun:
        model = self.session.get(OrchestrationRunModel, run_id)
        if not model:
            raise ValueError(f"Orchestration run '{run_id}' not found")
        model.stop_outcome = stop_outcome.value if stop_outcome else None
        model.human_gate = human_gate.value if human_gate else None
        model.stop_reason = stop_reason
        model.stop_details = stop_details or {}
        model.is_active = is_active
        model.updated_at = utc_now()
        return orchestration_run_model_to_domain(model)

    def update_candidate_binding(
        self,
        run_id: str,
        current_generation: int,
        current_candidate_sha: str | None,
    ) -> OrchestrationRun:
        model = self.session.get(OrchestrationRunModel, run_id)
        if not model:
            raise ValueError(f"Orchestration run '{run_id}' not found")
        model.current_generation = current_generation
        model.current_candidate_sha = current_candidate_sha
        model.updated_at = utc_now()
        return orchestration_run_model_to_domain(model)

    def update_active_job(
        self,
        run_id: str,
        active_job_id: str | None,
    ) -> OrchestrationRun:
        model = self.session.get(OrchestrationRunModel, run_id)
        if not model:
            raise ValueError(f"Orchestration run '{run_id}' not found")
        model.active_job_id = active_job_id
        model.updated_at = utc_now()
        return orchestration_run_model_to_domain(model)


class PostgresOrchestrationStageEventRepository(OrchestrationStageEventRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, event: OrchestrationStageEvent) -> None:
        self.session.add(
            OrchestrationStageEventModel(
                id=event.event_id,
                run_id=event.run_id,
                from_stage=event.from_stage.value if event.from_stage else None,
                to_stage=event.to_stage.value,
                event_type=event.event_type,
                transition_key=event.transition_key,
                evidence_references=event.evidence_references,
                actor=event.actor,
                created_at=event.created_at,
            )
        )

    def list_by_run(self, run_id: str) -> list[OrchestrationStageEvent]:
        stmt = (
            select(OrchestrationStageEventModel)
            .where(OrchestrationStageEventModel.run_id == run_id)
            .order_by(OrchestrationStageEventModel.created_at.asc())
        )
        return [
            orchestration_stage_event_model_to_domain(m) for m in self.session.scalars(stmt).all()
        ]

    def get_by_transition_key(self, transition_key: str) -> OrchestrationStageEvent | None:
        stmt = select(OrchestrationStageEventModel).where(
            OrchestrationStageEventModel.transition_key == transition_key
        )
        model = self.session.scalars(stmt).first()
        return orchestration_stage_event_model_to_domain(model) if model else None


class PostgresOrchestrationCandidateRepository(OrchestrationCandidateRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, candidate: OrchestrationCandidate) -> None:
        existing = self.session.get(OrchestrationCandidateModel, candidate.candidate_id)
        if existing:
            existing.manifest_id = candidate.manifest_id
            existing.candidate_ref = candidate.candidate_ref
            existing.manifest_hash = candidate.manifest_hash
            existing.authorship_summary = candidate.authorship_summary
            existing.is_frozen = candidate.is_frozen
            existing.superseded_by_id = candidate.superseded_by_id
        else:
            self.session.add(
                OrchestrationCandidateModel(
                    id=candidate.candidate_id,
                    run_id=candidate.run_id,
                    generation=candidate.generation,
                    base_sha=candidate.base_sha,
                    candidate_sha=candidate.candidate_sha,
                    candidate_ref=candidate.candidate_ref,
                    manifest_id=candidate.manifest_id,
                    manifest_hash=candidate.manifest_hash,
                    authorship_summary=candidate.authorship_summary,
                    is_frozen=candidate.is_frozen,
                    superseded_by_id=candidate.superseded_by_id,
                    created_at=candidate.created_at,
                )
            )

    def get_by_id(self, candidate_id: str) -> OrchestrationCandidate | None:
        model = self.session.get(OrchestrationCandidateModel, candidate_id)
        return orchestration_candidate_model_to_domain(model) if model else None

    def get_by_generation(self, run_id: str, generation: int) -> OrchestrationCandidate | None:
        stmt = select(OrchestrationCandidateModel).where(
            OrchestrationCandidateModel.run_id == run_id,
            OrchestrationCandidateModel.generation == generation,
        )
        model = self.session.scalars(stmt).first()
        return orchestration_candidate_model_to_domain(model) if model else None

    def get_latest_for_run(self, run_id: str) -> OrchestrationCandidate | None:
        stmt = (
            select(OrchestrationCandidateModel)
            .where(OrchestrationCandidateModel.run_id == run_id)
            .order_by(desc(OrchestrationCandidateModel.generation))
        )
        model = self.session.scalars(stmt).first()
        return orchestration_candidate_model_to_domain(model) if model else None

    def list_by_run(self, run_id: str) -> list[OrchestrationCandidate]:
        stmt = (
            select(OrchestrationCandidateModel)
            .where(OrchestrationCandidateModel.run_id == run_id)
            .order_by(OrchestrationCandidateModel.generation.asc())
        )
        return [
            orchestration_candidate_model_to_domain(m) for m in self.session.scalars(stmt).all()
        ]

    def supersede(self, candidate_id: str, superseded_by_id: str) -> None:
        model = self.session.get(OrchestrationCandidateModel, candidate_id)
        if model:
            model.superseded_by_id = superseded_by_id


class PostgresCandidateRemediationRepository:
    """Durable repository for immutable remediation authorizations."""

    def __init__(self, session: Session):
        self.session = session

    def save(self, remediation: CandidateRemediation) -> None:
        existing = self.session.get(CandidateRemediationModel, remediation.remediation_id)
        values = dict(
            run_id=remediation.run_id,
            job_id=remediation.job_id,
            source_candidate_id=remediation.source_candidate_id,
            source_generation=remediation.source_generation,
            source_candidate_sha=remediation.source_candidate_sha,
            source_base_sha=remediation.source_base_sha,
            contract_version=remediation.contract_version,
            contract_hash=remediation.contract_hash,
            contract_payload=remediation.contract_payload,
            status=remediation.status.value,
            failure_code=remediation.failure_code.value if remediation.failure_code else None,
            failure_reason=remediation.failure_reason,
            workspace_path=remediation.workspace_path,
            branch_name=remediation.branch_name,
            authorized_paths=remediation.authorized_paths,
            tree_fingerprint=remediation.tree_fingerprint,
            result_candidate_id=remediation.result_candidate_id,
            result_generation=remediation.result_generation,
            result_candidate_sha=remediation.result_candidate_sha,
            updated_at=utc_now(),
        )
        if existing:
            if (
                existing.contract_hash != remediation.contract_hash
                or existing.contract_payload != remediation.contract_payload
            ):
                raise ValueError("Admitted remediation contract cannot be replaced.")
            for key, value in values.items():
                setattr(existing, key, value)
        else:
            self.session.add(
                CandidateRemediationModel(
                    id=remediation.remediation_id, created_at=remediation.created_at, **values
                )
            )

    def get_by_id(self, remediation_id: str) -> CandidateRemediation | None:
        model = self.session.get(CandidateRemediationModel, remediation_id)
        return candidate_remediation_model_to_domain(model) if model else None

    def get_by_identity(
        self, run_id: str, source_generation: int, source_candidate_sha: str, contract_hash: str
    ) -> CandidateRemediation | None:
        stmt = select(CandidateRemediationModel).where(
            CandidateRemediationModel.run_id == run_id,
            CandidateRemediationModel.source_generation == source_generation,
            CandidateRemediationModel.source_candidate_sha == source_candidate_sha,
            CandidateRemediationModel.contract_hash == contract_hash,
        )
        model = self.session.scalars(stmt).first()
        return candidate_remediation_model_to_domain(model) if model else None

    def list_by_run(self, run_id: str) -> list[CandidateRemediation]:
        stmt = (
            select(CandidateRemediationModel)
            .where(CandidateRemediationModel.run_id == run_id)
            .order_by(CandidateRemediationModel.created_at.asc())
        )
        return [candidate_remediation_model_to_domain(m) for m in self.session.scalars(stmt).all()]


class PostgresOrchestrationExternalActionRepository(OrchestrationExternalActionRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def reserve(self, action: OrchestrationExternalAction) -> None:
        existing = self.session.get(OrchestrationExternalActionModel, action.action_id)
        if not existing:
            self.session.add(
                OrchestrationExternalActionModel(
                    id=action.action_id,
                    run_id=action.run_id,
                    action_key=action.action_key,
                    action_type=action.action_type.value,
                    target_identity=action.target_identity,
                    request_fingerprint=action.request_fingerprint,
                    candidate_sha=action.candidate_sha,
                    generation=action.generation,
                    status=action.status.value,
                    remote_identifier=action.remote_identifier,
                    result_payload=action.result_payload,
                    error_message=action.error_message,
                    reserved_at=action.reserved_at,
                    reconciled_at=action.reconciled_at,
                    created_at=action.created_at,
                    updated_at=action.updated_at,
                )
            )

    def get_by_action_key(self, action_key: str) -> OrchestrationExternalAction | None:
        stmt = select(OrchestrationExternalActionModel).where(
            OrchestrationExternalActionModel.action_key == action_key
        )
        model = self.session.scalars(stmt).first()
        return orchestration_external_action_model_to_domain(model) if model else None

    def list_by_run(self, run_id: str) -> list[OrchestrationExternalAction]:
        stmt = (
            select(OrchestrationExternalActionModel)
            .where(OrchestrationExternalActionModel.run_id == run_id)
            .order_by(OrchestrationExternalActionModel.created_at.asc())
        )
        return [
            orchestration_external_action_model_to_domain(m)
            for m in self.session.scalars(stmt).all()
        ]

    def update_status(
        self,
        action_key: str,
        status: ExternalActionStatus,
        remote_identifier: str | None = None,
        result_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> OrchestrationExternalAction:
        stmt = select(OrchestrationExternalActionModel).where(
            OrchestrationExternalActionModel.action_key == action_key
        )
        model = self.session.scalars(stmt).first()
        if not model:
            raise ValueError(f"External action '{action_key}' not found")
        model.status = status.value
        if remote_identifier is not None:
            model.remote_identifier = remote_identifier
        if result_payload is not None:
            model.result_payload = result_payload
        if error_message is not None:
            model.error_message = error_message
        if status in {
            ExternalActionStatus.COMPLETED,
            ExternalActionStatus.FAILED,
            ExternalActionStatus.AMBIGUOUS,
        }:
            model.reconciled_at = utc_now()
        model.updated_at = utc_now()
        return orchestration_external_action_model_to_domain(model)


def preview_session_domain_to_model(session: PreviewSession) -> PreviewSessionModel:
    return PreviewSessionModel(
        id=session.preview_id,
        project_id=session.project_id,
        change_name=session.change_name,
        run_id=session.run_id,
        job_id=session.job_id,
        candidate_generation=session.candidate_generation,
        head_sha=session.head_sha,
        base_sha=session.base_sha,
        image_digest=session.image_digest,
        status=session.status.value,
        container_id=session.container_id,
        container_name=session.container_name,
        allocated_port=session.allocated_port,
        preview_url=session.preview_url,
        failure_reason=session.failure_reason,
        failure_code=session.failure_code,
        created_at=session.created_at,
        ready_at=session.ready_at,
        terminated_at=session.terminated_at,
    )


def preview_session_model_to_domain(model: PreviewSessionModel) -> PreviewSession:
    return PreviewSession(
        preview_id=model.id,
        project_id=model.project_id,
        change_name=model.change_name,
        run_id=model.run_id,
        job_id=model.job_id,
        candidate_generation=model.candidate_generation,
        head_sha=model.head_sha,
        base_sha=model.base_sha,
        image_digest=model.image_digest or "",
        status=PreviewStatus(model.status),
        container_id=model.container_id,
        container_name=model.container_name,
        allocated_port=model.allocated_port,
        preview_url=model.preview_url,
        failure_reason=model.failure_reason,
        failure_code=model.failure_code,
        created_at=model.created_at,
        ready_at=model.ready_at,
        terminated_at=model.terminated_at,
    )


def validation_run_domain_to_model(run: ValidationRun) -> ValidationRunModel:
    return ValidationRunModel(
        id=run.validation_id,
        preview_id=run.preview_id,
        project_id=run.project_id,
        change_name=run.change_name,
        run_id=run.run_id,
        candidate_generation=run.candidate_generation,
        head_sha=run.head_sha,
        base_sha=run.base_sha,
        image_digest=run.image_digest,
        verdict=run.verdict.value,
        scenario_results=run.scenario_results,
        notes=run.notes,
        operator=run.operator,
        created_at=run.created_at,
    )


def validation_run_model_to_domain(model: ValidationRunModel) -> ValidationRun:
    return ValidationRun(
        validation_id=model.id,
        preview_id=model.preview_id,
        project_id=model.project_id,
        change_name=model.change_name,
        run_id=model.run_id,
        candidate_generation=model.candidate_generation,
        head_sha=model.head_sha,
        base_sha=model.base_sha,
        image_digest=model.image_digest,
        verdict=ValidationVerdict(model.verdict),
        scenario_results=model.scenario_results or [],
        notes=model.notes,
        operator=model.operator,
        created_at=model.created_at,
    )


class PostgresPreviewSessionRepository(PreviewSessionRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, session: PreviewSession) -> None:
        existing = self.session.get(PreviewSessionModel, session.preview_id)
        if existing:
            existing.status = session.status.value
            existing.image_digest = session.image_digest
            existing.container_id = session.container_id
            existing.container_name = session.container_name
            existing.allocated_port = session.allocated_port
            existing.preview_url = session.preview_url
            existing.failure_reason = session.failure_reason
            existing.failure_code = session.failure_code
            existing.ready_at = session.ready_at
            existing.terminated_at = session.terminated_at
        else:
            model = preview_session_domain_to_model(session)
            self.session.add(model)

    def get_by_id(self, preview_id: str) -> PreviewSession | None:
        model = self.session.get(PreviewSessionModel, preview_id)
        return preview_session_model_to_domain(model) if model else None

    def get_latest_for_run(self, run_id: str) -> PreviewSession | None:
        stmt = (
            select(PreviewSessionModel)
            .where(PreviewSessionModel.run_id == run_id)
            .order_by(desc(PreviewSessionModel.created_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return preview_session_model_to_domain(model) if model else None

    def get_latest_for_candidate(
        self, project_id: str, change_name: str, head_sha: str
    ) -> PreviewSession | None:
        stmt = (
            select(PreviewSessionModel)
            .where(
                PreviewSessionModel.project_id == project_id,
                PreviewSessionModel.change_name == change_name,
                PreviewSessionModel.head_sha == head_sha,
            )
            .order_by(desc(PreviewSessionModel.created_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return preview_session_model_to_domain(model) if model else None

    def list_by_change(self, project_id: str, change_name: str) -> list[PreviewSession]:
        stmt = (
            select(PreviewSessionModel)
            .where(
                PreviewSessionModel.project_id == project_id,
                PreviewSessionModel.change_name == change_name,
            )
            .order_by(desc(PreviewSessionModel.created_at))
        )
        models = self.session.scalars(stmt).all()
        return [preview_session_model_to_domain(m) for m in models]

    def list_active(self) -> list[PreviewSession]:
        active_statuses = [
            PreviewStatus.REQUESTED.value,
            PreviewStatus.BUILDING.value,
            PreviewStatus.STARTING.value,
            PreviewStatus.PROBING.value,
            PreviewStatus.READY.value,
        ]
        stmt = (
            select(PreviewSessionModel)
            .where(PreviewSessionModel.status.in_(active_statuses))
            .order_by(desc(PreviewSessionModel.created_at))
        )
        models = self.session.scalars(stmt).all()
        return [preview_session_model_to_domain(m) for m in models]

    def get_active_for_change(self, project_id: str, change_name: str) -> PreviewSession | None:
        active_statuses = [
            PreviewStatus.REQUESTED.value,
            PreviewStatus.BUILDING.value,
            PreviewStatus.STARTING.value,
            PreviewStatus.PROBING.value,
            PreviewStatus.READY.value,
        ]
        stmt = (
            select(PreviewSessionModel)
            .where(
                PreviewSessionModel.project_id == project_id,
                PreviewSessionModel.change_name == change_name,
                PreviewSessionModel.status.in_(active_statuses),
            )
            .order_by(desc(PreviewSessionModel.created_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return preview_session_model_to_domain(model) if model else None


class PostgresValidationRunRepository(ValidationRunRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, validation: ValidationRun) -> None:
        existing = self.session.get(ValidationRunModel, validation.validation_id)
        if existing:
            existing.verdict = validation.verdict.value
            existing.scenario_results = validation.scenario_results
            existing.notes = validation.notes
            existing.operator = validation.operator
        else:
            model = validation_run_domain_to_model(validation)
            self.session.add(model)

    def get_by_id(self, validation_id: str) -> ValidationRun | None:
        model = self.session.get(ValidationRunModel, validation_id)
        return validation_run_model_to_domain(model) if model else None

    def get_latest_for_candidate(
        self,
        project_id: str,
        change_name: str,
        head_sha: str,
        base_sha: str,
        image_digest: str,
    ) -> ValidationRun | None:
        stmt = (
            select(ValidationRunModel)
            .where(
                ValidationRunModel.project_id == project_id,
                ValidationRunModel.change_name == change_name,
                ValidationRunModel.head_sha == head_sha,
                ValidationRunModel.base_sha == base_sha,
                ValidationRunModel.image_digest == image_digest,
            )
            .order_by(desc(ValidationRunModel.created_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return validation_run_model_to_domain(model) if model else None

    def list_by_change(self, project_id: str, change_name: str) -> list[ValidationRun]:
        stmt = (
            select(ValidationRunModel)
            .where(
                ValidationRunModel.project_id == project_id,
                ValidationRunModel.change_name == change_name,
            )
            .order_by(desc(ValidationRunModel.created_at))
        )
        models = self.session.scalars(stmt).all()
        return [validation_run_model_to_domain(m) for m in models]

    def list_by_run(self, run_id: str) -> list[ValidationRun]:
        stmt = (
            select(ValidationRunModel)
            .where(ValidationRunModel.run_id == run_id)
            .order_by(desc(ValidationRunModel.created_at))
        )
        models = self.session.scalars(stmt).all()
        return [validation_run_model_to_domain(m) for m in models]


def operator_action_record_model_to_domain(
    model: OperatorActionRecordModel,
) -> OperatorActionRecord:
    return OperatorActionRecord(
        id=model.id,
        action_request_id=model.action_request_id,
        project_id=model.project_id,
        change_name=model.change_name,
        run_id=model.run_id,
        job_id=model.job_id,
        action_type=OperatorActionType(model.action_type),
        actor_identity=model.actor_identity,
        source_interface=model.source_interface,
        precondition_stage=model.precondition_stage,
        precondition_gate=model.precondition_gate,
        status=OperatorActionStatus(model.status),
        error_code=OperatorActionErrorCode(model.error_code) if model.error_code else None,
        summary=model.summary,
        resulting_stage=model.resulting_stage,
        resulting_outcome=model.resulting_outcome,
        resulting_gate=model.resulting_gate,
        evidence_reference=model.evidence_reference,
        parameters_json=dict(model.parameters_json or {}),
        result_payload_json=dict(model.result_payload_json or {}),
        created_at=model.created_at,
    )


def operator_action_record_domain_to_model(
    domain: OperatorActionRecord,
) -> OperatorActionRecordModel:
    return OperatorActionRecordModel(
        id=domain.id,
        action_request_id=domain.action_request_id,
        project_id=domain.project_id,
        change_name=domain.change_name,
        run_id=domain.run_id,
        job_id=domain.job_id,
        action_type=domain.action_type.value
        if hasattr(domain.action_type, "value")
        else str(domain.action_type),
        actor_identity=domain.actor_identity,
        source_interface=domain.source_interface,
        precondition_stage=domain.precondition_stage,
        precondition_gate=domain.precondition_gate,
        status=domain.status.value if hasattr(domain.status, "value") else str(domain.status),
        error_code=domain.error_code.value
        if domain.error_code and hasattr(domain.error_code, "value")
        else (str(domain.error_code) if domain.error_code else None),
        summary=domain.summary,
        resulting_stage=domain.resulting_stage,
        resulting_outcome=domain.resulting_outcome,
        resulting_gate=domain.resulting_gate,
        evidence_reference=domain.evidence_reference,
        parameters_json=domain.parameters_json,
        result_payload_json=domain.result_payload_json,
        created_at=domain.created_at,
    )


class PostgresOperatorActionRepository(OperatorActionRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, record: OperatorActionRecord) -> None:
        existing = self.session.get(OperatorActionRecordModel, record.id)
        if existing:
            existing.status = (
                record.status.value if hasattr(record.status, "value") else str(record.status)
            )
            existing.error_code = (
                record.error_code.value
                if record.error_code and hasattr(record.error_code, "value")
                else (str(record.error_code) if record.error_code else None)
            )
            existing.summary = record.summary
            existing.resulting_stage = record.resulting_stage
            existing.resulting_outcome = record.resulting_outcome
            existing.resulting_gate = record.resulting_gate
            existing.evidence_reference = record.evidence_reference
            existing.parameters_json = record.parameters_json
            existing.result_payload_json = record.result_payload_json
        else:
            model = operator_action_record_domain_to_model(record)
            self.session.add(model)

    def get_by_id(self, record_id: str) -> OperatorActionRecord | None:
        model = self.session.get(OperatorActionRecordModel, record_id)
        return operator_action_record_model_to_domain(model) if model else None

    def get_by_request_id(self, action_request_id: str) -> OperatorActionRecord | None:
        stmt = (
            select(OperatorActionRecordModel)
            .where(OperatorActionRecordModel.action_request_id == action_request_id)
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return operator_action_record_model_to_domain(model) if model else None

    def list_by_run(self, run_id: str, limit: int = 50) -> list[OperatorActionRecord]:
        stmt = (
            select(OperatorActionRecordModel)
            .where(OperatorActionRecordModel.run_id == run_id)
            .order_by(desc(OperatorActionRecordModel.created_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [operator_action_record_model_to_domain(m) for m in models]

    def list_by_project(self, project_id: str, limit: int = 50) -> list[OperatorActionRecord]:
        stmt = (
            select(OperatorActionRecordModel)
            .where(OperatorActionRecordModel.project_id == project_id)
            .order_by(desc(OperatorActionRecordModel.created_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [operator_action_record_model_to_domain(m) for m in models]


def work_queue_item_domain_to_model(item: WorkQueueItem) -> WorkQueueSnapshotModel:
    return WorkQueueSnapshotModel(
        id=item.queue_item_id,
        project_id=item.project_id,
        change_name=item.change_name,
        github_issue_number=item.github_issue_number,
        github_issue_title=item.github_issue_title,
        github_project_item_id=item.github_project_item_id,
        priority=item.priority.value if hasattr(item.priority, "value") else str(item.priority),
        roadmap_stage=item.roadmap_stage,
        dependencies=item.dependencies,
        readiness_state=item.readiness_state.value
        if hasattr(item.readiness_state, "value")
        else str(item.readiness_state),
        unmet_readiness_reasons=item.unmet_readiness_reasons,
        blocked_reason=item.blocked_reason,
        admission_eligible=item.admission_eligible,
        priority_score=item.priority_score,
        discovered_at=item.discovered_at,
        last_evaluated_at=item.last_evaluated_at,
    )


def work_queue_item_model_to_domain(model: WorkQueueSnapshotModel) -> WorkQueueItem:
    return WorkQueueItem(
        queue_item_id=model.id,
        project_id=model.project_id,
        change_name=model.change_name,
        github_issue_number=model.github_issue_number,
        github_issue_title=model.github_issue_title,
        github_project_item_id=model.github_project_item_id,
        priority=QueuePriority(model.priority) if model.priority else QueuePriority.NORMAL,
        roadmap_stage=model.roadmap_stage,
        dependencies=model.dependencies or [],
        readiness_state=ReadinessState(model.readiness_state)
        if model.readiness_state
        else ReadinessState.NOT_READY,
        unmet_readiness_reasons=model.unmet_readiness_reasons or [],
        blocked_reason=model.blocked_reason,
        admission_eligible=model.admission_eligible,
        priority_score=float(model.priority_score or 0.0),
        discovered_at=model.discovered_at,
        last_evaluated_at=model.last_evaluated_at,
    )


def scheduler_decision_domain_to_model(
    decision: SchedulerDecisionRecord,
) -> SchedulerDecisionRecordModel:
    return SchedulerDecisionRecordModel(
        id=decision.decision_id,
        project_id=decision.project_id,
        change_name=decision.change_name,
        github_issue_number=decision.github_issue_number,
        decision=decision.decision.value
        if hasattr(decision.decision, "value")
        else str(decision.decision),
        reason_code=decision.reason_code.value
        if decision.reason_code and hasattr(decision.reason_code, "value")
        else (str(decision.reason_code) if decision.reason_code else None),
        reason_summary=decision.reason_summary,
        priority_score=decision.priority_score,
        selected_implementer=decision.selected_implementer,
        concurrency_snapshot=decision.concurrency_snapshot,
        capacity_snapshot=decision.capacity_snapshot,
        run_id=decision.run_id,
        evaluated_at=decision.evaluated_at,
    )


def scheduler_decision_model_to_domain(
    model: SchedulerDecisionRecordModel,
) -> SchedulerDecisionRecord:
    return SchedulerDecisionRecord(
        decision_id=model.id,
        project_id=model.project_id,
        change_name=model.change_name,
        github_issue_number=model.github_issue_number,
        decision=AdmissionDecision(model.decision),
        reason_code=AdmissionRefusalCode(model.reason_code) if model.reason_code else None,
        reason_summary=model.reason_summary or "",
        priority_score=float(model.priority_score or 0.0),
        selected_implementer=model.selected_implementer,
        concurrency_snapshot=model.concurrency_snapshot or {},
        capacity_snapshot=model.capacity_snapshot or {},
        run_id=model.run_id,
        evaluated_at=model.evaluated_at,
    )


class PostgresWorkQueueRepository(WorkQueueRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, item: WorkQueueItem) -> None:
        stmt = (
            select(WorkQueueSnapshotModel)
            .where(
                WorkQueueSnapshotModel.project_id == item.project_id,
                WorkQueueSnapshotModel.change_name == item.change_name,
            )
            .limit(1)
        )
        existing = self.session.scalars(stmt).first()
        if existing:
            existing.github_issue_number = item.github_issue_number
            existing.github_issue_title = item.github_issue_title
            existing.github_project_item_id = item.github_project_item_id
            existing.priority = (
                item.priority.value if hasattr(item.priority, "value") else str(item.priority)
            )
            existing.roadmap_stage = item.roadmap_stage
            existing.dependencies = item.dependencies
            existing.readiness_state = (
                item.readiness_state.value
                if hasattr(item.readiness_state, "value")
                else str(item.readiness_state)
            )
            existing.unmet_readiness_reasons = item.unmet_readiness_reasons
            existing.blocked_reason = item.blocked_reason
            existing.admission_eligible = item.admission_eligible
            existing.priority_score = item.priority_score
            existing.last_evaluated_at = item.last_evaluated_at
        else:
            model = work_queue_item_domain_to_model(item)
            self.session.add(model)

    def get_by_id(self, queue_item_id: str) -> WorkQueueItem | None:
        model = self.session.get(WorkQueueSnapshotModel, queue_item_id)
        return work_queue_item_model_to_domain(model) if model else None

    def get_by_project_and_change(self, project_id: str, change_name: str) -> WorkQueueItem | None:
        stmt = (
            select(WorkQueueSnapshotModel)
            .where(
                WorkQueueSnapshotModel.project_id == project_id,
                WorkQueueSnapshotModel.change_name == change_name,
            )
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return work_queue_item_model_to_domain(model) if model else None

    def list_all(self, project_id: str | None = None) -> list[WorkQueueItem]:
        stmt = select(WorkQueueSnapshotModel)
        if project_id:
            stmt = stmt.where(WorkQueueSnapshotModel.project_id == project_id)
        stmt = stmt.order_by(
            desc(WorkQueueSnapshotModel.priority_score), WorkQueueSnapshotModel.discovered_at
        )
        models = self.session.scalars(stmt).all()
        return [work_queue_item_model_to_domain(m) for m in models]

    def list_ready(self, project_id: str | None = None) -> list[WorkQueueItem]:
        stmt = select(WorkQueueSnapshotModel).where(
            WorkQueueSnapshotModel.admission_eligible.is_(True)
        )
        if project_id:
            stmt = stmt.where(WorkQueueSnapshotModel.project_id == project_id)
        stmt = stmt.order_by(
            desc(WorkQueueSnapshotModel.priority_score), WorkQueueSnapshotModel.discovered_at
        )
        models = self.session.scalars(stmt).all()
        return [work_queue_item_model_to_domain(m) for m in models]

    def delete(self, queue_item_id: str) -> None:
        model = self.session.get(WorkQueueSnapshotModel, queue_item_id)
        if model:
            self.session.delete(model)


class PostgresSchedulerDecisionRepository(SchedulerDecisionRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, decision: SchedulerDecisionRecord) -> None:
        model = scheduler_decision_domain_to_model(decision)
        self.session.add(model)

    def get_by_id(self, decision_id: str) -> SchedulerDecisionRecord | None:
        model = self.session.get(SchedulerDecisionRecordModel, decision_id)
        return scheduler_decision_model_to_domain(model) if model else None

    def list_by_change(
        self, project_id: str, change_name: str, limit: int = 50
    ) -> list[SchedulerDecisionRecord]:
        stmt = (
            select(SchedulerDecisionRecordModel)
            .where(
                SchedulerDecisionRecordModel.project_id == project_id,
                SchedulerDecisionRecordModel.change_name == change_name,
            )
            .order_by(desc(SchedulerDecisionRecordModel.evaluated_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [scheduler_decision_model_to_domain(m) for m in models]

    def list_recent(
        self, project_id: str | None = None, limit: int = 100
    ) -> list[SchedulerDecisionRecord]:
        stmt = select(SchedulerDecisionRecordModel)
        if project_id:
            stmt = stmt.where(SchedulerDecisionRecordModel.project_id == project_id)
        stmt = stmt.order_by(desc(SchedulerDecisionRecordModel.evaluated_at)).limit(limit)
        models = self.session.scalars(stmt).all()
        return [scheduler_decision_model_to_domain(m) for m in models]


def provider_efficiency_metrics_model_to_domain(
    model: ProviderEfficiencyMetricsModel,
) -> ProviderEfficiencyMetrics:
    return ProviderEfficiencyMetrics(
        metrics_id=model.id,
        run_id=model.run_id,
        project_id=model.project_id,
        change_name=model.change_name,
        attempts_by_provider=model.attempts_by_provider or {},
        duration_by_provider_ms=model.duration_by_provider_ms or {},
        productive_attempt_count=model.productive_attempt_count,
        no_progress_attempt_count=model.no_progress_attempt_count,
        same_sha_retry_count=model.same_sha_retry_count,
        same_sha_retry_suppressed_count=model.same_sha_retry_suppressed_count,
        corrective_retry_count=model.corrective_retry_count,
        reassignments_count=model.reassignments_count,
        reassignment_reason_codes=model.reassignment_reason_codes or [],
        provider_exhaustion_events=model.provider_exhaustion_events or [],
        drain_transitions=model.drain_transitions or [],
        premium_provider_assignments=model.premium_provider_assignments,
        premium_provider_reason_codes=model.premium_provider_reason_codes or [],
        candidate_generations_count=model.candidate_generations_count,
        time_to_candidate_ms=model.time_to_candidate_ms,
        time_to_checks_ms=model.time_to_checks_ms,
        time_to_review_ms=model.time_to_review_ms,
        time_to_pr_ms=model.time_to_pr_ms,
        total_cycle_time_ms=model.total_cycle_time_ms,
        human_gates_count=model.human_gates_count,
        operator_actions_count=model.operator_actions_count,
        self_hosting_native_phases=model.self_hosting_native_phases,
        self_hosting_total_phases=model.self_hosting_total_phases,
        self_hosting_percentage=model.self_hosting_percentage,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class PostgresProviderEfficiencyMetricsRepository(ProviderEfficiencyMetricsRepositoryInterface):
    def __init__(self, session: Session):
        self.session = session

    def save(self, metrics: ProviderEfficiencyMetrics) -> None:
        existing = self.session.get(ProviderEfficiencyMetricsModel, metrics.metrics_id)
        if not existing:
            stmt = (
                select(ProviderEfficiencyMetricsModel)
                .where(ProviderEfficiencyMetricsModel.run_id == metrics.run_id)
                .limit(1)
            )
            existing = self.session.scalars(stmt).first()

        if existing:
            existing.attempts_by_provider = metrics.attempts_by_provider
            existing.duration_by_provider_ms = metrics.duration_by_provider_ms
            existing.productive_attempt_count = metrics.productive_attempt_count
            existing.no_progress_attempt_count = metrics.no_progress_attempt_count
            existing.same_sha_retry_count = metrics.same_sha_retry_count
            existing.same_sha_retry_suppressed_count = metrics.same_sha_retry_suppressed_count
            existing.corrective_retry_count = metrics.corrective_retry_count
            existing.reassignments_count = metrics.reassignments_count
            existing.reassignment_reason_codes = metrics.reassignment_reason_codes
            existing.provider_exhaustion_events = metrics.provider_exhaustion_events
            existing.drain_transitions = metrics.drain_transitions
            existing.premium_provider_assignments = metrics.premium_provider_assignments
            existing.premium_provider_reason_codes = metrics.premium_provider_reason_codes
            existing.candidate_generations_count = metrics.candidate_generations_count
            existing.time_to_candidate_ms = metrics.time_to_candidate_ms
            existing.time_to_checks_ms = metrics.time_to_checks_ms
            existing.time_to_review_ms = metrics.time_to_review_ms
            existing.time_to_pr_ms = metrics.time_to_pr_ms
            existing.total_cycle_time_ms = metrics.total_cycle_time_ms
            existing.human_gates_count = metrics.human_gates_count
            existing.operator_actions_count = metrics.operator_actions_count
            existing.self_hosting_native_phases = metrics.self_hosting_native_phases
            existing.self_hosting_total_phases = metrics.self_hosting_total_phases
            existing.self_hosting_percentage = metrics.self_hosting_percentage
            existing.updated_at = metrics.updated_at
        else:
            self.session.add(
                ProviderEfficiencyMetricsModel(
                    id=metrics.metrics_id,
                    run_id=metrics.run_id,
                    project_id=metrics.project_id,
                    change_name=metrics.change_name,
                    attempts_by_provider=metrics.attempts_by_provider,
                    duration_by_provider_ms=metrics.duration_by_provider_ms,
                    productive_attempt_count=metrics.productive_attempt_count,
                    no_progress_attempt_count=metrics.no_progress_attempt_count,
                    same_sha_retry_count=metrics.same_sha_retry_count,
                    same_sha_retry_suppressed_count=metrics.same_sha_retry_suppressed_count,
                    corrective_retry_count=metrics.corrective_retry_count,
                    reassignments_count=metrics.reassignments_count,
                    reassignment_reason_codes=metrics.reassignment_reason_codes,
                    provider_exhaustion_events=metrics.provider_exhaustion_events,
                    drain_transitions=metrics.drain_transitions,
                    premium_provider_assignments=metrics.premium_provider_assignments,
                    premium_provider_reason_codes=metrics.premium_provider_reason_codes,
                    candidate_generations_count=metrics.candidate_generations_count,
                    time_to_candidate_ms=metrics.time_to_candidate_ms,
                    time_to_checks_ms=metrics.time_to_checks_ms,
                    time_to_review_ms=metrics.time_to_review_ms,
                    time_to_pr_ms=metrics.time_to_pr_ms,
                    total_cycle_time_ms=metrics.total_cycle_time_ms,
                    human_gates_count=metrics.human_gates_count,
                    operator_actions_count=metrics.operator_actions_count,
                    self_hosting_native_phases=metrics.self_hosting_native_phases,
                    self_hosting_total_phases=metrics.self_hosting_total_phases,
                    self_hosting_percentage=metrics.self_hosting_percentage,
                    created_at=metrics.created_at,
                    updated_at=metrics.updated_at,
                )
            )

    def get_by_id(self, metrics_id: str) -> ProviderEfficiencyMetrics | None:
        model = self.session.get(ProviderEfficiencyMetricsModel, metrics_id)
        return provider_efficiency_metrics_model_to_domain(model) if model else None

    def get_by_run_id(self, run_id: str) -> ProviderEfficiencyMetrics | None:
        stmt = (
            select(ProviderEfficiencyMetricsModel)
            .where(ProviderEfficiencyMetricsModel.run_id == run_id)
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return provider_efficiency_metrics_model_to_domain(model) if model else None

    def get_by_project_and_change(
        self, project_id: str, change_name: str
    ) -> ProviderEfficiencyMetrics | None:
        stmt = (
            select(ProviderEfficiencyMetricsModel)
            .where(
                ProviderEfficiencyMetricsModel.project_id == project_id,
                ProviderEfficiencyMetricsModel.change_name == change_name,
            )
            .order_by(desc(ProviderEfficiencyMetricsModel.updated_at))
            .limit(1)
        )
        model = self.session.scalars(stmt).first()
        return provider_efficiency_metrics_model_to_domain(model) if model else None

    def list_by_project(
        self, project_id: str, limit: int | None = None
    ) -> list[ProviderEfficiencyMetrics]:
        stmt = (
            select(ProviderEfficiencyMetricsModel)
            .where(ProviderEfficiencyMetricsModel.project_id == project_id)
            .order_by(desc(ProviderEfficiencyMetricsModel.updated_at))
            .limit(limit)
        )
        models = self.session.scalars(stmt).all()
        return [provider_efficiency_metrics_model_to_domain(m) for m in models]


class PostgresPersistenceUnitOfWork(PersistenceUnitOfWork):
    """Encapsulates a database session for atomic operations across repositories."""

    def __init__(self, session: Session):
        self.session = session
        self.projects = PostgresProjectRepository(session)
        self.changes = PostgresChangeRepository(session)
        self.bindings = PostgresProjectBindingRepository(session)
        self.events = PostgresEventRepository(session)
        self.metrics = PostgresMetricFactRepository(session)
        self.jobs = PostgresJobRepository(session)
        self.job_logs = PostgresJobLogRepository(session)
        self.check_results = PostgresCheckResultRepository(session)
        self.reviews = PostgresReviewRepository(session)
        self.review_findings = PostgresReviewFindingRepository(session)
        self.audits = PostgresAuditRepository(session)
        self.audit_findings = PostgresAuditFindingRepository(session)
        self.provider_health = PostgresProviderHealthRepository(session)
        self.capacity_windows = PostgresCapacityWindowRepository(session)
        self.git_operations = PostgresGitOperationRepository(session)
        self.budget_policies = PostgresOpenRouterBudgetPolicyRepository(session)
        self.pricing_snapshots = PostgresOpenRouterPricingSnapshotRepository(session)
        self.budget_reservations = PostgresBudgetReservationRepository(session)
        self.budget_ledger = PostgresBudgetLedgerRepository(session)
        self.job_attempts = PostgresJobAttemptRepository(session)
        self.blocker_claims = PostgresBlockerClaimRepository(session)
        self.job_handoffs = PostgresJobHandoffRepository(session)
        self.candidate_manifests = PostgresCandidateManifestRepository(session)
        self.candidate_authorships = PostgresCandidateAuthorshipRepository(session)
        self.evidence_diagnostics = PostgresEvidenceDiagnosticRepository(session)
        self.orchestration_runs = PostgresOrchestrationRunRepository(session)
        self.orchestration_stage_events = PostgresOrchestrationStageEventRepository(session)
        self.orchestration_candidates = PostgresOrchestrationCandidateRepository(session)
        self.candidate_remediations = PostgresCandidateRemediationRepository(session)
        self.orchestration_external_actions = PostgresOrchestrationExternalActionRepository(session)
        self.preview_sessions = PostgresPreviewSessionRepository(session)
        self.validation_runs = PostgresValidationRunRepository(session)
        self.operator_actions = PostgresOperatorActionRepository(session)
        self.work_queue = PostgresWorkQueueRepository(session)
        self.scheduler_decisions = PostgresSchedulerDecisionRepository(session)
        self.provider_efficiency = PostgresProviderEfficiencyMetricsRepository(session)

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
