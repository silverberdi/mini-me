"""Operator Actions Control Plane service for mini me.

Provides canonical action discovery, authority validation, optimistic concurrency,
idempotency, cancellation safety, and durable audit persistence across presentation layers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from minime.config import (
    OpenSpecStage,
    ProjectConfig,
    load_config,
    resolve_stage_profile,
)
from minime.domain.enums import (
    ActionRiskLevel,
    EventType,
    HumanGate,
    JobStatus,
    OperatorActionErrorCode,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    PreviewStatus,
    ProviderHealthStatus,
    RecoverySource,
    ReviewStatus,
    ValidationVerdict,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    ActionDescriptor,
    Event,
    OperatorActionRecord,
    OperatorActionRequest,
    OperatorActionResult,
    OrchestrationRun,
    PreviewSession,
    utc_now,
)
from minime.logging import redact_secrets
from minime.services.container_preview_service import ContainerPreviewService
from minime.services.orchestration_service import OrchestrationService
from minime.services.post_merge_service import PostMergeReconciliationService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.recovery_convergence_service import RecoveryConvergenceService
from minime.services.restart_recovery_service import RestartRecoveryService
from minime.services.validation_authority_service import ValidationAuthorityService

logger = logging.getLogger(__name__)


class ControlPlaneService:
    """Canonical Operator Control Plane service."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        orchestration_service: OrchestrationService | None = None,
        preview_service: ContainerPreviewService | None = None,
        validation_service: ValidationAuthorityService | None = None,
        recovery_service: RestartRecoveryService | None = None,
        provider_health_service: ProviderHealthService | None = None,
        post_merge_service: PostMergeReconciliationService | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.orchestration_service = orchestration_service or OrchestrationService(
            uow, project_root=self.project_root
        )
        self.preview_service = preview_service or ContainerPreviewService(uow)
        self.validation_service = validation_service or ValidationAuthorityService(uow)
        self.recovery_service = recovery_service or RestartRecoveryService(
            uow, project_root=self.project_root
        )
        self.provider_health_service = provider_health_service or ProviderHealthService(uow)
        self.recovery_convergence_service = RecoveryConvergenceService(
            uow,
            project_root=self.project_root,
            health_service=self.provider_health_service,
            orchestration_service=self.orchestration_service,
        )
        gh_adapter = getattr(self.orchestration_service, "github_adapter", None)
        self.post_merge_service = post_merge_service or PostMergeReconciliationService(
            uow, project_root=self.project_root, github_adapter=gh_adapter
        )

    def _deepseek_review_authorized_total(self, run: OrchestrationRun) -> Decimal | None:
        """Return prior DeepSeek review authorizations for this Run, or None if ambiguous."""
        total = Decimal("0")
        review_actions = {
            OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW: "CONTRACT_REVIEW",
            OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW: "REVIEW",
        }
        for action in self.uow.operator_actions.list_by_run(run.run_id):
            expected_stage = review_actions.get(action.action_type)
            if not expected_stage or action.status != OperatorActionStatus.COMPLETED:
                continue
            auth = action.result_payload_json.get("authorization", {})
            if (
                action.project_id != run.project_id
                or action.change_name != run.change_name
                or action.run_id != run.run_id
                or not action.job_id
                or auth.get("provider") != "deepseek"
                or auth.get("billing_origin") != "deepseek_direct"
                or auth.get("stage") != expected_stage
                or auth.get("run_id") != run.run_id
                or auth.get("job_id") != action.job_id
            ):
                return None
            try:
                amount = Decimal(str(auth["max_spend_usd"]))
            except Exception:
                return None
            if not amount.is_finite() or amount <= 0:
                return None
            total += amount
        return total

    def _deepseek_combined_review_limit(self, budget: dict[str, Any]) -> Decimal:
        """Use an explicit pilot limit, defaulting to the sum of stage ceilings."""
        try:
            configured = budget.get("maximum_combined_review_usd")
            if configured is not None:
                limit = Decimal(str(configured))
            else:
                contract = Decimal(str(budget.get("maximum_contract_review_usd", "0")))
                code = Decimal(str(budget.get("maximum_code_review_usd", "0")))
                limit = contract + code
        except Exception:
            return Decimal("0")
        return limit if limit.is_finite() and limit > 0 else Decimal("0")

    def _deepseek_review_total_within_limit(
        self, run: OrchestrationRun, budget: dict[str, Any], requested: Decimal
    ) -> bool:
        prior_total = self._deepseek_review_authorized_total(run)
        limit = self._deepseek_combined_review_limit(budget)
        return prior_total is not None and limit > 0 and prior_total + requested <= limit

    def get_available_actions(self, run_id: str) -> list[ActionDescriptor]:
        """Discover all supported operator actions for a run and their current eligibility."""
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if not run:
            return []

        project = self.uow.projects.get_by_id(run.project_id)
        active_preview = self.uow.preview_sessions.get_active_for_change(
            run.project_id, run.change_name
        )

        descriptors: list[ActionDescriptor] = []

        # 1. CONTINUE / RESUME
        continue_enabled = False
        continue_reason: str | None = None
        if run.is_active and run.stop_outcome != OrchestrationStopOutcome.WAITING_CAPACITY:
            continue_reason = "Run is already active"
        elif run.current_stage == OrchestrationStage.PR_PREPARED:
            continue_reason = "Run has completed PR preparation"
        elif run.stop_outcome == OrchestrationStopOutcome.CANCELLED:
            continue_reason = "Run was cancelled"
        elif (
            run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
            or run.human_gate == HumanGate.NEEDS_HUMAN
        ):
            stop_reason = run.stop_reason or ""
            stop_details = run.stop_details or {}
            is_preserved_conflict = (
                "PRESERVED_CANDIDATE" in stop_reason
                or "PRESERVED_CANDIDATE" in str(stop_details)
                or "integration" in stop_reason.lower()
                or "base advanced" in stop_reason.lower()
            )
            is_ui_validation = (
                "UI_VALIDATION" in stop_reason
                or "VALIDATION_REQUIRED" in str(stop_details)
                or "validation" in stop_reason.lower()
            )
            if is_preserved_conflict or is_ui_validation:
                continue_enabled = False
                continue_reason = "Run is stopped at a human gate; use Resolve Gate instead."
            else:
                continue_enabled = True
        elif run.resumable_stage is not None or run.stop_outcome in {
            OrchestrationStopOutcome.WAITING_CAPACITY,
            OrchestrationStopOutcome.WAITING_EXTERNAL,
            OrchestrationStopOutcome.FAILED,
        }:
            continue_enabled = True
        else:
            continue_reason = "Run is not in a resumable state"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.CONTINUE,
                display_name="Continue / Resume",
                description="Resume execution from persisted checkpoint using canonical orchestration semantics.",
                enabled=continue_enabled,
                disabled_reason=continue_reason,
                requires_confirmation=False,
                risk_level=ActionRiskLevel.LOW,
            )
        )

        # 2. RETRY
        retry_enabled = False
        retry_reason: str | None = None
        if run.is_active:
            retry_reason = "Run is already active"
        elif run.current_stage in {
            OrchestrationStage.RUNNING_CHECKS,
            OrchestrationStage.IMPLEMENTING,
        }:
            if run.retry_count >= 3:
                retry_reason = f"Maximum retry limit reached ({run.retry_count}/3)"
            else:
                retry_enabled = True
        else:
            retry_reason = "Retry is only available for failed implementation or check stages"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.RETRY,
                display_name="Retry Stage",
                description="Retry the failed stage/attempt within configured retry budgets.",
                enabled=retry_enabled,
                disabled_reason=retry_reason,
                requires_confirmation=True,
                confirmation_prompt="Retry current failed stage? A new attempt will be recorded.",
                risk_level=ActionRiskLevel.MEDIUM,
            )
        )

        # 3. REASSIGN
        reassign_enabled = False
        reassign_reason: str | None = None
        if run.is_active:
            reassign_reason = "Run is already active"
        elif project and len(project.external_providers_allowed) > 1:
            if run.current_stage in {
                OrchestrationStage.IMPLEMENTING,
                OrchestrationStage.RUNNING_CHECKS,
                OrchestrationStage.REVIEW_REMEDIATION,
                OrchestrationStage.COMPLEMENTARY_REVIEW,
            }:
                reassign_enabled = True
            else:
                reassign_reason = (
                    "Reassignment only applicable during implementation or review stages"
                )
        else:
            reassign_reason = "No alternative providers configured for project"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.REASSIGN,
                display_name="Reassign Executor",
                description="Reassign execution to an alternative compatible provider under governance.",
                enabled=reassign_enabled,
                disabled_reason=reassign_reason,
                requires_confirmation=True,
                confirmation_prompt="Reassign execution to alternative provider? Preserves candidate evidence and enforces model independence.",
                risk_level=ActionRiskLevel.MEDIUM,
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "target_executor": {
                            "type": "string",
                            "description": "Target agent/executor role (e.g. codex, antigravity)",
                        }
                    },
                },
            )
        )

        # 4. RESOLVE_GATE
        gate_enabled = False
        gate_reason: str | None = None
        gate_schema: dict[str, Any] = {}
        gate_prompt: str | None = None

        if (
            run.human_gate == HumanGate.NEEDS_HUMAN
            or run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
        ):
            # Check gate type from stop_reason or details
            stop_reason = run.stop_reason or ""
            stop_details = run.stop_details or {}

            if (
                "PRESERVED_CANDIDATE" in stop_reason
                or "PRESERVED_CANDIDATE" in str(stop_details)
                or "integration" in stop_reason.lower()
                or "base advanced" in stop_reason.lower()
            ):
                gate_enabled = True
                gate_prompt = "Resolve preserved candidate conflict by continuing candidate or starting bounded remediation."
                gate_schema = {
                    "type": "object",
                    "properties": {
                        "resolution_type": {
                            "type": "string",
                            "enum": ["continue_preserved", "remediate_preserved"],
                        },
                        "contract": {
                            "type": "string",
                            "description": "Path to remediation contract JSON",
                        },
                        "candidate_ref": {
                            "type": "string",
                            "description": "Optional branch ref for adoption",
                        },
                    },
                    "required": ["resolution_type"],
                }
            elif (
                "UI_VALIDATION" in stop_reason
                or "VALIDATION_REQUIRED" in str(stop_details)
                or "validation" in stop_reason.lower()
            ):
                gate_enabled = True
                gate_prompt = "Submit authoritative human validation verdict for candidate preview."
                gate_schema = {
                    "type": "object",
                    "properties": {
                        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
                        "notes": {"type": "string"},
                        "operator": {"type": "string"},
                    },
                    "required": ["verdict"],
                }
            else:
                gate_enabled = False
                gate_reason = (
                    f"Gate type '{stop_reason}' requires specific manual resolution guidance"
                )
        else:
            gate_reason = "Run is not currently stopped at a human gate"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.RESOLVE_GATE,
                display_name="Resolve Gate",
                description="Resolve an active NEEDS_HUMAN blocker through its canonical resolution contract.",
                enabled=gate_enabled,
                disabled_reason=gate_reason,
                requires_confirmation=True,
                confirmation_prompt=gate_prompt,
                risk_level=ActionRiskLevel.HIGH,
                parameters_schema=gate_schema,
            )
        )

        # 5. CANCEL
        cancel_enabled = False
        cancel_reason: str | None = None
        if run.is_active:
            cancel_enabled = True
        elif (
            run.current_stage == OrchestrationStage.PR_PREPARED
            or run.stop_outcome == OrchestrationStopOutcome.CANCELLED
        ):
            cancel_reason = "Run is already terminal or cancelled"
        else:
            cancel_reason = "Run is not active"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.CANCEL,
                display_name="Cancel Run",
                description="Safely stop active execution while preserving candidate evidence and Git refs.",
                enabled=cancel_enabled,
                disabled_reason=cancel_reason,
                requires_confirmation=True,
                confirmation_prompt="Cancel active execution? Candidate evidence, review records, and worktrees will be preserved.",
                risk_level=ActionRiskLevel.HIGH,
            )
        )

        # 6. START_PREVIEW
        preview_start_enabled = False
        preview_start_reason: str | None = None
        if not project or not project.deployment_preview:
            preview_start_reason = "No preview deployment configured for project"
        elif not run.candidate_sha:
            preview_start_reason = "No frozen candidate available for preview"
        elif active_preview and active_preview.status in {
            PreviewStatus.READY,
            PreviewStatus.STARTING,
            PreviewStatus.PROBING,
        }:
            preview_start_reason = f"Preview session already active ({active_preview.status.value})"
        else:
            preview_start_enabled = True

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.START_PREVIEW,
                display_name="Start Preview",
                description="Build and run isolated container preview for candidate.",
                enabled=preview_start_enabled,
                disabled_reason=preview_start_reason,
                requires_confirmation=False,
                risk_level=ActionRiskLevel.LOW,
            )
        )

        # 7. TEARDOWN_PREVIEW
        preview_stop_enabled = False
        preview_stop_reason: str | None = None
        if active_preview and active_preview.status not in {
            PreviewStatus.TERMINATED,
            PreviewStatus.FAILED,
        }:
            preview_stop_enabled = True
        else:
            preview_stop_reason = "No active container preview session"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.TEARDOWN_PREVIEW,
                display_name="Teardown Preview",
                description="Stop and clean up active candidate preview container.",
                enabled=preview_stop_enabled,
                disabled_reason=preview_stop_reason,
                requires_confirmation=False,
                risk_level=ActionRiskLevel.LOW,
            )
        )

        # 8. RECOVER_LOCKS
        locks_enabled = False
        locks_reason: str | None = None
        if (
            run.stop_outcome == OrchestrationStopOutcome.WAITING_EXTERNAL
            or "lock" in (run.stop_reason or "").lower()
        ):
            locks_enabled = True
        else:
            locks_reason = "No abandoned locks detected for this run"

        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.RECOVER_LOCKS,
                display_name="Recover Locks",
                description="Safely release abandoned Git locks after verifying PID ownership.",
                enabled=locks_enabled,
                disabled_reason=locks_reason,
                requires_confirmation=True,
                confirmation_prompt="Recover abandoned Git locks with verified ownership?",
                risk_level=ActionRiskLevel.HIGH,
            )
        )

        # 9. RECONCILE_POST_MERGE
        post_merge_enabled = (
            run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
            or run.current_stage
            in {OrchestrationStage.PR_PREPARED, OrchestrationStage.POST_MERGE_RECONCILING}
        )
        post_merge_reason = (
            None if post_merge_enabled else "Run is not awaiting post-merge reconciliation"
        )
        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.RECONCILE_POST_MERGE,
                display_name="Reconcile Post-Merge",
                description="Detect merge, verify candidate ancestry, reconcile terminal state, sync OpenSpec, and clean up resources.",
                enabled=post_merge_enabled,
                disabled_reason=post_merge_reason,
                requires_confirmation=False,
                risk_level=ActionRiskLevel.LOW,
            )
        )

        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        contract_review_authorization_allowed = bool(
            job
            and run.current_stage
            in {
                OrchestrationStage.ADMITTED,
                OrchestrationStage.PREPARING_EXECUTION,
                OrchestrationStage.IMPLEMENTING,
            }
            and run.project_id == job.project_id
            and run.change_name == job.change_name
            and not self.uow.job_attempts.list_by_job(job.job_id)
            and not job.candidate_sha
            and not self.uow.reviews.get_by_job_stage(job.job_id, "CONTRACT_REVIEW")
        )
        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW,
                display_name="Authorize DeepSeek Contract Review",
                description=(
                    "Authorize one bounded, direct-account DeepSeek review for the exact "
                    "OpenSpec contract. This does not authorize APPLY or merge."
                ),
                enabled=contract_review_authorization_allowed,
                disabled_reason=(
                    None
                    if contract_review_authorization_allowed
                    else "A matching admitted Run/Job without an existing contract review is required."
                ),
                requires_confirmation=True,
                confirmation_prompt=(
                    "Authorize a single direct DeepSeek CONTRACT_REVIEW spend up to the "
                    "configured maximum for this Run/Job?"
                ),
                risk_level=ActionRiskLevel.HIGH,
                parameters_schema={
                    "type": "object",
                    "required": ["max_spend_usd", "expires_at", "pricing_snapshot_id"],
                    "properties": {
                        "max_spend_usd": {"type": "string"},
                        "expires_at": {"type": "string", "format": "date-time"},
                        "pricing_snapshot_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            )
        )

        code_candidate = (
            self.uow.orchestration_candidates.get_by_generation(
                run.run_id, run.current_generation
            )
            if job
            else None
        )
        code_manifest = (
            self.uow.candidate_manifests.get_by_id(code_candidate.manifest_id)
            if code_candidate and code_candidate.manifest_id
            else None
        )
        check_evidence = (
            [
                check
                for check in self.uow.check_results.list_by_job(job.job_id)
                if check.candidate_sha == code_candidate.candidate_sha
                and check.candidate_generation == code_candidate.generation
                and check.exit_code == 0
            ]
            if job and code_candidate
            else []
        )
        prior_code_review = (
            self.uow.reviews.get_by_job_stage(job.job_id, "CODE_REVIEW") if job else None
        )
        code_review_slot_open = bool(
            prior_code_review is None
            or (
                prior_code_review.status == ReviewStatus.REVIEW_RUNNING
                and prior_code_review.budget_authorization_id is None
                and prior_code_review.budget_reservation_id is None
                and prior_code_review.provider is None
            )
        )
        code_review_authorization_allowed = bool(
            job
            and code_candidate
            and code_manifest
            and code_candidate.is_frozen
            and code_candidate.run_id == run.run_id
            and code_candidate.generation == run.current_generation
            and code_candidate.candidate_sha == job.candidate_sha
            and code_candidate.candidate_sha == run.current_candidate_sha
            and code_candidate.base_sha == run.base_sha
            and code_manifest.job_id == job.job_id
            and code_manifest.candidate_sha == code_candidate.candidate_sha
            and code_manifest.manifest_hash == code_candidate.manifest_hash
            and check_evidence
            and job.status in {JobStatus.CHECKS_PASSED, JobStatus.WAITING_CAPACITY}
            and run.project_id == job.project_id
            and run.change_name == job.change_name
            and code_review_slot_open
        )
        descriptors.append(
            ActionDescriptor(
                action=OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
                display_name="Authorize DeepSeek Code Review",
                description=(
                    "Authorize one bounded, direct-account DeepSeek read-only review of "
                    "the exact frozen candidate. This does not authorize merge."
                ),
                enabled=code_review_authorization_allowed,
                disabled_reason=(
                    None
                    if code_review_authorization_allowed
                    else "A matching frozen candidate with passing checks and no code review is required."
                ),
                requires_confirmation=True,
                confirmation_prompt=(
                    "Authorize one direct DeepSeek REVIEW spend up to the configured "
                    "maximum for this exact candidate?"
                ),
                risk_level=ActionRiskLevel.HIGH,
                parameters_schema={
                    "type": "object",
                    "required": ["max_spend_usd", "expires_at", "pricing_snapshot_id"],
                    "properties": {
                        "max_spend_usd": {"type": "string"},
                        "expires_at": {"type": "string", "format": "date-time"},
                        "pricing_snapshot_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            )
        )

        return descriptors

    def execute_action(self, request: OperatorActionRequest) -> OperatorActionResult:
        """Governed execution of an operator action with optimistic concurrency and idempotency."""
        sanitized_params = redact_secrets(request.parameters)

        # 1. Idempotency Check
        existing_record = self.uow.operator_actions.get_by_request_id(request.action_request_id)
        if existing_record:
            logger.info(
                f"Action request {request.action_request_id} was already executed with status {existing_record.status.value}"
            )
            return OperatorActionResult(
                action_request_id=existing_record.action_request_id,
                action_type=existing_record.action_type,
                status=existing_record.status,
                error_code=existing_record.error_code,
                summary=existing_record.summary,
                resulting_stage=OrchestrationStage(existing_record.resulting_stage)
                if existing_record.resulting_stage
                else None,
                resulting_outcome=OrchestrationStopOutcome(existing_record.resulting_outcome)
                if existing_record.resulting_outcome
                else None,
                resulting_gate=HumanGate(existing_record.resulting_gate)
                if existing_record.resulting_gate
                else None,
                evidence_reference=existing_record.evidence_reference,
                payload=existing_record.result_payload_json,
                executed_at=existing_record.created_at,
            )

        # 2. Authority & Run Lookup
        run_repo = self.uow.orchestration_runs
        if request.action_type in {
            OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW,
            OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
        }:
            # Serialize the combined per-Run review ceiling check with its
            # durable authorization insert. Without this row lock, simultaneous
            # CONTRACT_REVIEW and CODE_REVIEW authorizations could each observe
            # stale totals and exceed the pilot cap.
            get_for_update = getattr(run_repo, "get_for_update", None)
            run = get_for_update(request.run_id) if callable(get_for_update) else None
            if run is None:
                run = run_repo.get_by_id(request.run_id)
        else:
            run = run_repo.get_by_id(request.run_id)
        if not run:
            return self._record_and_return_rejection(
                request=request,
                run=None,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=f"Orchestration run '{request.run_id}' not found.",
                sanitized_params=sanitized_params,
            )

        if run.project_id != request.project_id or run.change_name != request.change_name:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=f"Run project/change mismatch: requested ({request.project_id}/{request.change_name}) vs actual ({run.project_id}/{run.change_name}).",
                sanitized_params=sanitized_params,
            )

        # 3. Optimistic Concurrency Checks
        stale_error = self._check_optimistic_concurrency(request, run)
        if stale_error:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.STALE_OPERATOR_STATE,
                summary=stale_error,
                sanitized_params=sanitized_params,
            )

        # 4. Dispatch Action
        try:
            if request.action_type in {OperatorActionType.CONTINUE, OperatorActionType.RESUME}:
                return self._execute_continue(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.RETRY:
                return self._execute_retry(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.REASSIGN:
                return self._execute_reassign(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.RESOLVE_GATE:
                return self._execute_resolve_gate(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.CANCEL:
                return self._execute_cancel(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.START_PREVIEW:
                return self._execute_start_preview(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.TEARDOWN_PREVIEW:
                return self._execute_teardown_preview(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.RECOVER_LOCKS:
                return self._execute_recover_locks(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.RECONCILE_POST_MERGE:
                return self._execute_reconcile_post_merge(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW:
                return self._execute_authorize_deepseek_review(request, run, sanitized_params)
            elif request.action_type == OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW:
                return self._execute_authorize_deepseek_code_review(request, run, sanitized_params)
            else:
                return self._record_and_return_rejection(
                    request=request,
                    run=run,
                    error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                    summary=f"Unsupported action type '{request.action_type}'.",
                    sanitized_params=sanitized_params,
                )
        except Exception as exc:
            logger.error(
                f"Error executing action {request.action_type} for run {run.run_id}: {exc}",
                exc_info=True,
            )
            # Every action handler shares this failure boundary.  In particular,
            # cancellation mutates a linked Job and its run in one transaction;
            # roll that work back before the durable FAILED audit record is
            # written in a clean transaction.
            self.uow.rollback()
            persisted_run = self.uow.orchestration_runs.get_by_id(run.run_id) or run
            err_msg = redact_secrets(str(exc))
            record = OperatorActionRecord(
                action_request_id=request.action_request_id,
                project_id=request.project_id,
                change_name=request.change_name,
                run_id=request.run_id,
                action_type=request.action_type,
                actor_identity=request.actor_identity,
                source_interface=request.source_interface,
                precondition_stage=persisted_run.current_stage.value,
                precondition_gate=(
                    persisted_run.human_gate.value if persisted_run.human_gate else None
                ),
                status=OperatorActionStatus.FAILED,
                error_code=OperatorActionErrorCode.ACTION_EXECUTION_FAILED,
                summary=f"Internal execution failure: {err_msg}",
                parameters_json=sanitized_params,
                result_payload_json={"error": err_msg},
            )
            self.uow.operator_actions.save(record)
            self.uow.commit()

            return OperatorActionResult(
                action_request_id=request.action_request_id,
                action_type=request.action_type,
                status=OperatorActionStatus.FAILED,
                error_code=OperatorActionErrorCode.ACTION_EXECUTION_FAILED,
                summary=f"Internal execution failure: {err_msg}",
                resulting_stage=persisted_run.current_stage,
                resulting_outcome=persisted_run.stop_outcome,
                resulting_gate=persisted_run.human_gate,
            )

    def _check_optimistic_concurrency(
        self, request: OperatorActionRequest, run: OrchestrationRun
    ) -> str | None:
        """Validate expected state fields against canonical run."""
        if request.expected_stage and run.current_stage != request.expected_stage:
            return f"State conflict: expected stage '{request.expected_stage.value}', but run is in stage '{run.current_stage.value}'."
        if (
            request.expected_generation is not None
            and run.current_generation != request.expected_generation
        ):
            return f"State conflict: expected generation '{request.expected_generation}', but run is generation '{run.current_generation}'."
        if request.expected_candidate_sha and run.candidate_sha != request.expected_candidate_sha:
            return f"State conflict: expected candidate SHA '{request.expected_candidate_sha}', but actual SHA is '{run.candidate_sha}'."
        if request.expected_human_gate and run.human_gate != request.expected_human_gate:
            return f"State conflict: expected human gate '{request.expected_human_gate.value}', but actual gate is '{run.human_gate.value if run.human_gate else 'None'}'."
        return None

    def _record_and_return_rejection(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun | None,
        error_code: OperatorActionErrorCode,
        summary: str,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        """Persist structured rejection and emit event."""
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value if run else None,
            precondition_gate=run.human_gate.value if run and run.human_gate else None,
            status=OperatorActionStatus.REJECTED,
            error_code=error_code,
            summary=summary,
            parameters_json=sanitized_params,
            result_payload_json={"error_code": error_code.value, "summary": summary},
        )
        self.uow.operator_actions.save(record)
        self.uow.events.save(
            Event(
                event_type=EventType.OPERATOR_ACTION_REJECTED,
                payload={
                    "action_request_id": request.action_request_id,
                    "action_type": request.action_type.value,
                    "error_code": error_code.value,
                    "summary": summary,
                    "project_id": request.project_id,
                    "change_name": request.change_name,
                    "run_id": request.run_id,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.REJECTED,
            error_code=error_code,
            summary=summary,
            resulting_stage=run.current_stage if run else None,
            resulting_outcome=run.stop_outcome if run else None,
            resulting_gate=run.human_gate if run else None,
        )

    def _execute_continue(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        waiting_capacity_checkpoint = run.stop_outcome == OrchestrationStopOutcome.WAITING_CAPACITY
        if run.is_active and not sanitized_params.get("force") and not waiting_capacity_checkpoint:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Cannot continue run: execution is already active.",
                sanitized_params=sanitized_params,
            )

        if (
            run.current_stage == OrchestrationStage.PR_PREPARED
            or run.stop_outcome == OrchestrationStopOutcome.CANCELLED
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary=f"Cannot continue run in terminal or cancelled state ({run.stop_outcome.value if run.stop_outcome else run.current_stage.value}).",
                sanitized_params=sanitized_params,
            )

        # Clear stop outcome and human gate upon explicit operator continuation
        if (
            run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
            or run.human_gate == HumanGate.NEEDS_HUMAN
            or sanitized_params.get("force")
        ):
            run.stop_outcome = None
            run.human_gate = None
            run.is_active = True
            run.stop_reason = None
            run.stop_details = {}
            if run.active_job_id:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                if job:
                    if job.base_sha and job.base_sha != run.base_sha:
                        run.base_sha = job.base_sha
                    job.status = JobStatus.RUNNING
                    job.continuation_decision = None
                    job.escalation_reason = None
                    self.uow.jobs.save(job)
            if run.current_stage in {
                OrchestrationStage.EVALUATING_ATTEMPT,
                OrchestrationStage.FREEZING_CANDIDATE,
                OrchestrationStage.RUNNING_CHECKS,
            }:
                run.resumable_stage = OrchestrationStage.IMPLEMENTING
                run.current_stage = OrchestrationStage.IMPLEMENTING
            self.uow.orchestration_runs.save(run)
            self.uow.commit()

        # Drive run continuation through canonical RecoveryConvergenceService
        self.recovery_convergence_service.request_run_continuation(
            run.run_id,
            source=RecoverySource.CONTROL_PLANE,
            force=True,
            drive_admitted=True,
        )
        resumed_run = self.uow.orchestration_runs.get_by_id(run.run_id) or run
        linked_job = (
            self.uow.jobs.get_by_id(resumed_run.active_job_id)
            if resumed_run.active_job_id
            else None
        )
        job_status = linked_job.status.value if linked_job else None
        continuation_active = bool(
            resumed_run.is_active
            and linked_job
            and linked_job.status
            in {
                JobStatus.RUNNING,
                JobStatus.CHECKS_RUNNING,
                JobStatus.REVIEW_RUNNING,
                JobStatus.AUDIT_RUNNING,
            }
        )
        run_active = bool(resumed_run.is_active)
        outcome = resumed_run.stop_outcome.value if resumed_run.stop_outcome else "NONE"
        job_result = job_status or "NO_LINKED_JOB"
        summary = (
            f"Continue request processed; persisted run_active={str(run_active).lower()}, "
            f"stage={resumed_run.current_stage.value}, outcome={outcome}, "
            f"linked_job_status={job_result}, "
            f"execution_active={str(continuation_active).lower()}."
        )
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=resumed_run.current_stage.value,
            resulting_outcome=resumed_run.stop_outcome.value if resumed_run.stop_outcome else None,
            resulting_gate=resumed_run.human_gate.value if resumed_run.human_gate else None,
            parameters_json=sanitized_params,
            result_payload_json={
                "request_processed": True,
                "run_active": run_active,
                "execution_active": continuation_active,
                "resulting_stage": resumed_run.current_stage.value,
                "resulting_outcome": resumed_run.stop_outcome.value
                if resumed_run.stop_outcome
                else None,
                "linked_job_status": job_status,
            },
        )
        self.uow.operator_actions.save(record)
        self.uow.events.save(
            Event(
                event_type=EventType.OPERATOR_ACTION_EXECUTED,
                payload={
                    "action_request_id": request.action_request_id,
                    "action_type": request.action_type.value,
                    "actor_identity": request.actor_identity,
                    "project_id": request.project_id,
                    "change_name": request.change_name,
                    "run_id": request.run_id,
                    "stage": resumed_run.current_stage.value,
                    "run_active": run_active,
                    "execution_active": continuation_active,
                    "linked_job_status": job_status,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=resumed_run.current_stage,
            resulting_outcome=resumed_run.stop_outcome,
            resulting_gate=resumed_run.human_gate,
            payload={
                "request_processed": True,
                "run_active": run_active,
                "execution_active": continuation_active,
                "resulting_stage": resumed_run.current_stage.value,
                "resulting_outcome": resumed_run.stop_outcome.value
                if resumed_run.stop_outcome
                else None,
                "linked_job_status": job_status,
            },
        )

    def _execute_authorize_deepseek_review(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        """Persist a one-use contract-review spend authorization after non-inference checks."""
        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        if (
            not job
            or run.current_stage
            not in {
                OrchestrationStage.ADMITTED,
                OrchestrationStage.PREPARING_EXECUTION,
                OrchestrationStage.IMPLEMENTING,
            }
            or run.active_job_id != job.job_id
            or run.project_id != job.project_id
            or run.change_name != job.change_name
            or bool(self.uow.job_attempts.list_by_job(job.job_id))
            or bool(job.candidate_sha)
            or self.uow.reviews.get_by_job_stage(job.job_id, "CONTRACT_REVIEW")
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="DeepSeek spend authorization is only available before APPLY for the exact active Run/Job.",
                sanitized_params=sanitized_params,
            )
        prior = [
            action
            for action in self.uow.operator_actions.list_by_run(run.run_id)
            if action.action_type == OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW
            and action.status == OperatorActionStatus.COMPLETED
        ]
        if prior:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_ALREADY_COMPLETED,
                summary="A DeepSeek CONTRACT_REVIEW authorization already exists for this Run.",
                sanitized_params=sanitized_params,
            )
        if set(sanitized_params) != {"max_spend_usd", "expires_at", "pricing_snapshot_id"}:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Authorization requires exactly max_spend_usd, expires_at, and pricing_snapshot_id.",
                sanitized_params=sanitized_params,
            )
        try:
            max_spend = Decimal(str(sanitized_params["max_spend_usd"]))
            expires_at = datetime.fromisoformat(str(sanitized_params["expires_at"]))
            if expires_at.tzinfo is None or max_spend <= 0:
                raise ValueError("invalid authorization bound")
        except (InvalidOperation, ValueError, TypeError):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Authorization amount or expiry is invalid.",
                sanitized_params=sanitized_params,
            )
        now = utc_now()
        if expires_at <= now or (expires_at - now).total_seconds() > 3600:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Contract-review spend authorization must expire within one hour.",
                sanitized_params=sanitized_params,
            )

        project = self.uow.projects.get_by_id(run.project_id)
        if not project:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Project binding is unavailable for spend authorization.",
                sanitized_params=sanitized_params,
            )
        app_config = load_config()
        project_config = app_config.projects.get(project.project_id) or ProjectConfig(
            repository=project.repository,
            base_branch=project.base_branch,
            openspec_path=project.openspec_path,
            implementer=project.implementer,
            reviewer=project.reviewer,
            external_providers_allowed=project.external_providers_allowed,
        )
        provider_config = app_config.providers.get("deepseek")
        configured_max = (
            provider_config.budget.get("maximum_contract_review_usd")
            if provider_config and isinstance(provider_config.budget, dict)
            else None
        )
        try:
            configured_max = Decimal(str(configured_max))
        except Exception:
            configured_max = Decimal("0")
        if max_spend > configured_max:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Requested spend exceeds the configured contract-review ceiling or no ceiling exists.",
                sanitized_params=sanitized_params,
            )
        review_budget = provider_config.budget if provider_config else {}
        if not self._deepseek_review_total_within_limit(run, review_budget, max_spend):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Combined DeepSeek review authorizations exceed the configured pilot ceiling or are ambiguous.",
                sanitized_params=sanitized_params,
            )
        try:
            profile = resolve_stage_profile(
                project_config, OpenSpecStage.CONTRACT_REVIEW, app_config=app_config
            )
            from minime.adapters.provider_adapter import get_provider_adapter

            adapter = get_provider_adapter("deepseek", app_config)
            supported, _ = __import__("asyncio").run(
                adapter.check_model_supported(profile.model, effort=profile.effort)
            )
            account_fingerprint = getattr(adapter, "account_fingerprint", None)
            snapshot = self.uow.pricing_snapshots.get_by_id(
                str(sanitized_params["pricing_snapshot_id"])
            )
        except Exception:
            supported = False
            account_fingerprint = None
            snapshot = None
            profile = None
        if (
            not profile
            or profile.provider != "deepseek"
            or not supported
            or not account_fingerprint
            or not snapshot
            or not snapshot.is_verified
            or snapshot.provider != "deepseek"
            or snapshot.account_fingerprint != account_fingerprint
            or snapshot.canonical_model_identity != profile.model
            or snapshot.billing_origin != "deepseek_direct"
            or snapshot.currency != "USD"
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Direct DeepSeek model, account, and verified price evidence is unavailable or mismatched.",
                sanitized_params=sanitized_params,
            )

        authorization = {
            "provider": "deepseek",
            "account_fingerprint": account_fingerprint,
            "model": profile.model,
            "stage": "CONTRACT_REVIEW",
            "billing_origin": "deepseek_direct",
            "pricing_snapshot_id": snapshot.snapshot_id,
            "run_id": run.run_id,
            "job_id": job.job_id,
            "max_spend_usd": str(max_spend),
            "expires_at": expires_at.isoformat(),
            "authorized_by": request.actor_identity,
            "action_request_id": request.action_request_id,
        }
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=run.project_id,
            change_name=run.change_name,
            run_id=run.run_id,
            job_id=job.job_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            status=OperatorActionStatus.COMPLETED,
            summary="One-use DeepSeek Direct CONTRACT_REVIEW budget authorized; APPLY and merge remain separate gates.",
            evidence_reference=snapshot.snapshot_id,
            parameters_json=sanitized_params,
            result_payload_json={"authorization": authorization},
        )
        self.uow.operator_actions.save(record)
        self.uow.events.save(
            Event(
                event_type=EventType.OPERATOR_ACTION_EXECUTED,
                payload={
                    "action_request_id": request.action_request_id,
                    "action_type": request.action_type.value,
                    "run_id": run.run_id,
                    "job_id": job.job_id,
                    "provider": "deepseek",
                    "stage": "CONTRACT_REVIEW",
                    "model": profile.model,
                    "authorization_id": request.action_request_id,
                },
                timestamp=now,
            )
        )
        self.uow.commit()
        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=record.summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            evidence_reference=snapshot.snapshot_id,
            payload={
                "provider": "deepseek",
                "stage": "CONTRACT_REVIEW",
                "maximum_usd": str(max_spend),
            },
        )

    def _execute_authorize_deepseek_code_review(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        """Authorize one bounded review for a specific frozen candidate only."""
        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        candidate = (
            self.uow.orchestration_candidates.get_by_generation(
                run.run_id, run.current_generation
            )
            if job
            else None
        )
        manifest = (
            self.uow.candidate_manifests.get_by_id(candidate.manifest_id)
            if candidate and candidate.manifest_id
            else None
        )
        passing_checks = (
            [
                item
                for item in self.uow.check_results.list_by_job(job.job_id)
                if candidate
                and item.candidate_sha == candidate.candidate_sha
                and item.candidate_generation == candidate.generation
                and item.exit_code == 0
            ]
            if job
            else []
        )
        prior_code_review = (
            self.uow.reviews.get_by_job_stage(job.job_id, "CODE_REVIEW") if job else None
        )
        review_slot_open = bool(
            prior_code_review is None
            or (
                prior_code_review.status == ReviewStatus.REVIEW_RUNNING
                and prior_code_review.budget_authorization_id is None
                and prior_code_review.budget_reservation_id is None
                and prior_code_review.provider is None
            )
        )
        if (
            not job
            or not candidate
            or not manifest
            or not candidate.is_frozen
            or run.active_job_id != job.job_id
            or run.project_id != job.project_id
            or run.change_name != job.change_name
            or candidate.run_id != run.run_id
            or candidate.generation != run.current_generation
            or candidate.candidate_sha != job.candidate_sha
            or candidate.candidate_sha != run.current_candidate_sha
            or candidate.base_sha != run.base_sha
            or manifest.job_id != job.job_id
            or manifest.candidate_sha != candidate.candidate_sha
            or manifest.manifest_hash != candidate.manifest_hash
            or job.status not in {JobStatus.CHECKS_PASSED, JobStatus.WAITING_CAPACITY}
            or not passing_checks
            or not review_slot_open
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Code-review authorization requires the exact frozen candidate and passing checks.",
                sanitized_params=sanitized_params,
            )
        prior_same_candidate = any(
            action.action_type == OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW
            and action.status == OperatorActionStatus.COMPLETED
            and action.job_id == job.job_id
            and action.result_payload_json.get("authorization", {}).get("candidate_sha")
            == candidate.candidate_sha
            for action in self.uow.operator_actions.list_by_run(run.run_id)
        )
        if prior_same_candidate:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_ALREADY_COMPLETED,
                summary="Code-review spend is already authorized for this candidate.",
                sanitized_params=sanitized_params,
            )
        if set(sanitized_params) != {"max_spend_usd", "expires_at", "pricing_snapshot_id"}:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Authorization requires exactly max_spend_usd, expires_at, and pricing_snapshot_id.",
                sanitized_params=sanitized_params,
            )
        try:
            max_spend = Decimal(str(sanitized_params["max_spend_usd"]))
            expires_at = datetime.fromisoformat(str(sanitized_params["expires_at"]))
            if expires_at.tzinfo is None or max_spend <= 0:
                raise ValueError("invalid authorization bound")
        except (InvalidOperation, ValueError, TypeError):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Authorization amount or expiry is invalid.",
                sanitized_params=sanitized_params,
            )
        now = utc_now()
        if expires_at <= now or (expires_at - now).total_seconds() > 3600:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary="Code-review authorization must expire within one hour.",
                sanitized_params=sanitized_params,
            )
        project = self.uow.projects.get_by_id(run.project_id)
        if not project:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Project binding is unavailable for code-review authorization.",
                sanitized_params=sanitized_params,
            )
        app_config = load_config()
        project_config = app_config.projects.get(project.project_id) or ProjectConfig(
            repository=project.repository,
            base_branch=project.base_branch,
            openspec_path=project.openspec_path,
            implementer=project.implementer,
            reviewer=project.reviewer,
            external_providers_allowed=project.external_providers_allowed,
        )
        provider_config = app_config.providers.get("deepseek")
        configured_max = (
            provider_config.budget.get("maximum_code_review_usd")
            if provider_config and isinstance(provider_config.budget, dict)
            else None
        )
        try:
            configured_max = Decimal(str(configured_max))
        except Exception:
            configured_max = Decimal("0")
        if max_spend > configured_max:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Requested spend exceeds the configured code-review ceiling or no ceiling exists.",
                sanitized_params=sanitized_params,
            )
        review_budget = provider_config.budget if provider_config else {}
        if not self._deepseek_review_total_within_limit(run, review_budget, max_spend):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Combined DeepSeek review authorizations exceed the configured pilot ceiling or are ambiguous.",
                sanitized_params=sanitized_params,
            )
        try:
            profile = resolve_stage_profile(
                project_config, OpenSpecStage.REVIEW, app_config=app_config
            )
            from minime.adapters.provider_adapter import get_provider_adapter

            adapter = get_provider_adapter("deepseek", app_config)
            supported, _ = __import__("asyncio").run(
                adapter.check_model_supported(profile.model, effort=profile.effort)
            )
            account_fingerprint = getattr(adapter, "account_fingerprint", None)
            snapshot = self.uow.pricing_snapshots.get_by_id(
                str(sanitized_params["pricing_snapshot_id"])
            )
        except Exception:
            supported = False
            account_fingerprint = None
            snapshot = None
            profile = None
        if (
            not profile
            or profile.provider != "deepseek"
            or not supported
            or not account_fingerprint
            or not snapshot
            or not snapshot.is_verified
            or snapshot.provider != "deepseek"
            or snapshot.account_fingerprint != account_fingerprint
            or snapshot.canonical_model_identity != profile.model
            or snapshot.billing_origin != "deepseek_direct"
            or snapshot.currency != "USD"
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Direct DeepSeek code-review model, account, and verified price evidence is unavailable or mismatched.",
                sanitized_params=sanitized_params,
            )
        authorization = {
            "provider": "deepseek",
            "account_fingerprint": account_fingerprint,
            "model": profile.model,
            "stage": "REVIEW",
            "billing_origin": "deepseek_direct",
            "pricing_snapshot_id": snapshot.snapshot_id,
            "run_id": run.run_id,
            "job_id": job.job_id,
            "candidate_sha": candidate.candidate_sha,
            "base_sha": candidate.base_sha,
            "generation": candidate.generation,
            "manifest_id": candidate.manifest_id,
            "manifest_hash": candidate.manifest_hash,
            "max_spend_usd": str(max_spend),
            "expires_at": expires_at.isoformat(),
            "authorized_by": request.actor_identity,
            "action_request_id": request.action_request_id,
        }
        summary = "One-use DeepSeek Direct code REVIEW authorized for the exact candidate; merge remains a separate human gate."
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=run.project_id,
            change_name=run.change_name,
            run_id=run.run_id,
            job_id=job.job_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            evidence_reference=snapshot.snapshot_id,
            parameters_json=sanitized_params,
            result_payload_json={"authorization": authorization},
        )
        self.uow.operator_actions.save(record)
        self.uow.events.save(
            Event(
                event_type=EventType.OPERATOR_ACTION_EXECUTED,
                payload={
                    "action_request_id": request.action_request_id,
                    "action_type": request.action_type.value,
                    "run_id": run.run_id,
                    "job_id": job.job_id,
                    "provider": "deepseek",
                    "stage": "REVIEW",
                    "candidate_sha": candidate.candidate_sha,
                    "manifest_hash": candidate.manifest_hash,
                    "model": profile.model,
                    "authorization_id": request.action_request_id,
                },
                timestamp=now,
            )
        )
        self.uow.commit()
        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            evidence_reference=snapshot.snapshot_id,
            payload={
                "provider": "deepseek",
                "stage": "REVIEW",
                "candidate_sha": candidate.candidate_sha,
                "maximum_usd": str(max_spend),
            },
        )

    def _execute_retry(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        if run.is_active:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Cannot retry stage: run is already active.",
                sanitized_params=sanitized_params,
            )

        if run.current_stage not in {
            OrchestrationStage.RUNNING_CHECKS,
            OrchestrationStage.IMPLEMENTING,
        }:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary=f"Retry is not permitted from stage '{run.current_stage.value}'.",
                sanitized_params=sanitized_params,
            )

        if run.retry_count >= 3:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary=f"Retry limit exceeded for run ({run.retry_count}/3).",
                sanitized_params=sanitized_params,
            )

        # Increment retry count and resume through RecoveryConvergenceService
        run.retry_count += 1
        with self.uow.orchestration_runs.session.begin_nested():
            run.stop_outcome = None
            run.human_gate = None
            run.is_active = True
            run.stop_reason = None
            run.stop_details = {}
            if run.active_job_id:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                if job:
                    if job.base_sha and job.base_sha != run.base_sha:
                        run.base_sha = job.base_sha
                    job.status = JobStatus.RUNNING
                    job.continuation_decision = None
                    job.escalation_reason = None
                    self.uow.jobs.save(job)
            run.resumable_stage = OrchestrationStage.IMPLEMENTING
            run.current_stage = OrchestrationStage.IMPLEMENTING
            self.uow.orchestration_runs.save(run)
            self.uow.commit()

        self.recovery_convergence_service.request_run_continuation(
            run.run_id, source=RecoverySource.CONTROL_PLANE, force=True
        )
        resumed_run = self.uow.orchestration_runs.get_by_id(run.run_id) or run

        summary = f"Stage retried (attempt #{resumed_run.retry_count}); stage is now {resumed_run.current_stage.value}."
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=resumed_run.current_stage.value,
            resulting_outcome=resumed_run.stop_outcome.value if resumed_run.stop_outcome else None,
            resulting_gate=resumed_run.human_gate.value if resumed_run.human_gate else None,
            parameters_json=sanitized_params,
            result_payload_json={"retry_count": resumed_run.retry_count},
        )
        self.uow.operator_actions.save(record)
        self.uow.events.save(
            Event(
                event_type=EventType.OPERATOR_ACTION_EXECUTED,
                payload={
                    "action_request_id": request.action_request_id,
                    "action_type": request.action_type.value,
                    "retry_count": resumed_run.retry_count,
                    "run_id": request.run_id,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=resumed_run.current_stage,
            resulting_outcome=resumed_run.stop_outcome,
            resulting_gate=resumed_run.human_gate,
            payload={"retry_count": resumed_run.retry_count},
        )

    def _execute_reassign(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        if run.is_active:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Cannot reassign executor: run is currently active.",
                sanitized_params=sanitized_params,
            )

        project = self.uow.projects.get_by_id(run.project_id)
        if not project:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="Project not found.",
                sanitized_params=sanitized_params,
            )

        target_executor = sanitized_params.get("target_executor")
        if not target_executor:
            # Pick alternate allowed provider
            allowed = project.external_providers_allowed
            target_executor = allowed[1] if len(allowed) > 1 else allowed[0]

        if target_executor not in project.external_providers_allowed:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.PROVIDER_UNAVAILABLE,
                summary=f"Target executor '{target_executor}' is not in allowed providers {project.external_providers_allowed}.",
                sanitized_params=sanitized_params,
            )

        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        if not job or job.project_id != run.project_id or job.change_name != run.change_name:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary="REASSIGN requires the exact linked Job for this Run.",
                sanitized_params=sanitized_params,
            )

        if job.status not in {JobStatus.NEEDS_HUMAN, JobStatus.FAILED, JobStatus.RECOVERY_BLOCKED}:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary=f"Cannot reassign linked Job in status {job.status.value}.",
                sanitized_params=sanitized_params,
            )
        if job.current_executor == target_executor:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Target executor is already assigned to the linked Job.",
                sanitized_params=sanitized_params,
            )
        if job.reassignment_count >= 2:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.BUDGET_BLOCKED,
                summary="Canonical per-job reassignment limit (2) has been reached.",
                sanitized_params=sanitized_params,
            )

        # An unknown or stale provider-health state is not authorization to
        # dispatch a manually selected executor.
        health = self.provider_health_service.get_existing_health(target_executor)
        if not health or health.status != ProviderHealthStatus.AVAILABLE:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.PROVIDER_UNAVAILABLE,
                summary=f"Target provider '{target_executor}' is not currently available.",
                sanitized_params=sanitized_params,
            )

        # REASSIGN only records durable intent. Execution remains a distinct
        # operator CONTINUE action. The existing job repository performs the
        # executor mutation under the current run claim/fence.
        rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
        claim = rec_svc.acquire_claim(f"run:{run.run_id}")
        if not claim:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.RECOVERY_REQUIRED,
                summary="Could not acquire the canonical run recovery claim for reassignment.",
                sanitized_params=sanitized_params,
            )
        from minime.domain.models import RecoveryClaimContext

        claim_context = RecoveryClaimContext(
            claim_key=claim.claim_key,
            owner_instance_id=claim.owner_instance_id,
            fence_token=claim.fence_token,
            lease_expires_at=claim.lease_expires_at,
        )
        committed = False
        try:
            current_job = self.uow.jobs.get_by_id(job.job_id)
            if (
                not current_job
                or current_job.project_id != run.project_id
                or current_job.change_name != run.change_name
                or current_job.status
                not in {JobStatus.NEEDS_HUMAN, JobStatus.FAILED, JobStatus.RECOVERY_BLOCKED}
                or current_job.reassignment_count >= 2
            ):
                raise ValueError("Linked Job changed or reached the reassignment ceiling.")
            self.uow.jobs.update_executor_fenced(
                current_job.job_id, target_executor, claim_context=claim_context
            )
            current_job.current_executor = target_executor
            current_job.reassignment_count += 1
            self.uow.jobs.save(current_job)
            summary = (
                f"Executor reassignment to {target_executor} was durably applied; "
                "a separate authorized CONTINUE is required to resume execution."
            )
            record = OperatorActionRecord(
                action_request_id=request.action_request_id,
                project_id=request.project_id,
                change_name=request.change_name,
                run_id=request.run_id,
                job_id=current_job.job_id,
                action_type=request.action_type,
                actor_identity=request.actor_identity,
                source_interface=request.source_interface,
                precondition_stage=run.current_stage.value,
                precondition_gate=run.human_gate.value if run.human_gate else None,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                parameters_json=sanitized_params,
                result_payload_json={
                    "target_executor": target_executor,
                    "executor_assignment_applied": True,
                    "reassignment_count": current_job.reassignment_count,
                    "execution_started": False,
                },
            )
            self.uow.operator_actions.save(record)
            self.uow.events.save(
                Event(
                    event_type=EventType.OPERATOR_ACTION_EXECUTED,
                    payload={
                        "action_request_id": request.action_request_id,
                        "action_type": request.action_type.value,
                        "target_executor": target_executor,
                        "run_id": request.run_id,
                        "job_id": current_job.job_id,
                        "execution_started": False,
                    },
                    timestamp=utc_now(),
                )
            )
            rec_svc.validate_claim(claim_context)
            self.uow.commit()
            committed = True
            result_payload = record.result_payload_json
        finally:
            if not committed:
                self.uow.rollback()
            try:
                rec_svc.release_claim(claim_context)
            except Exception:
                # The assignment plus action record are already atomic and
                # durable once committed; lease expiry remains the safe
                # fallback if best-effort release itself is unavailable.
                logger.warning("Could not release reassignment recovery claim for %s", run.run_id)

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            payload=result_payload,
        )

    def _execute_resolve_gate(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        if (
            run.human_gate != HumanGate.NEEDS_HUMAN
            and run.stop_outcome != OrchestrationStopOutcome.NEEDS_HUMAN
        ):
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Cannot resolve gate: run is not stopped at a NEEDS_HUMAN gate.",
                sanitized_params=sanitized_params,
            )

        resolution_type = sanitized_params.get("resolution_type")
        verdict_param = sanitized_params.get("verdict")

        if verdict_param:
            # Visual validation resolution
            verdict = (
                ValidationVerdict.PASS
                if str(verdict_param).upper() == "PASS"
                else ValidationVerdict.FAIL
            )
            notes = sanitized_params.get("notes", "Resolved via Control Plane")
            operator = sanitized_params.get("operator", request.actor_identity)

            # Record validation
            active_preview = self.uow.preview_sessions.get_active_for_change(
                run.project_id, run.change_name
            )
            validation_run = self.validation_service.record_validation(
                project_id=run.project_id,
                change_name=run.change_name,
                head_sha=run.candidate_sha or "",
                base_sha=run.base_sha,
                image_digest=active_preview.image_digest if active_preview else "",
                verdict=verdict,
                scenario_results=[],
                notes=notes,
                operator=operator,
                preview_id=active_preview.preview_id if active_preview else None,
                run_id=run.run_id,
            )

            # Advance orchestration through RecoveryConvergenceService
            rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
            rec_svc.request_run_continuation(run.run_id, source=RecoverySource.CONTROL_PLANE)
            resumed_run = self.uow.orchestration_runs.get_by_id(run.run_id) or run

            summary = f"UI Validation recorded ({verdict.value}); run advanced to stage {resumed_run.current_stage.value}."
            record = OperatorActionRecord(
                action_request_id=request.action_request_id,
                project_id=request.project_id,
                change_name=request.change_name,
                run_id=request.run_id,
                action_type=request.action_type,
                actor_identity=request.actor_identity,
                source_interface=request.source_interface,
                precondition_stage=run.current_stage.value,
                precondition_gate=run.human_gate.value if run.human_gate else None,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage.value,
                resulting_outcome=resumed_run.stop_outcome.value
                if resumed_run.stop_outcome
                else None,
                resulting_gate=resumed_run.human_gate.value if resumed_run.human_gate else None,
                evidence_reference=validation_run.validation_id,
                parameters_json=sanitized_params,
                result_payload_json={
                    "validation_id": validation_run.validation_id,
                    "verdict": verdict.value,
                },
            )
            self.uow.operator_actions.save(record)
            self.uow.commit()

            return OperatorActionResult(
                action_request_id=request.action_request_id,
                action_type=request.action_type,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage,
                resulting_outcome=resumed_run.stop_outcome,
                resulting_gate=resumed_run.human_gate,
                evidence_reference=validation_run.validation_id,
                payload={"validation_id": validation_run.validation_id, "verdict": verdict.value},
            )

        elif resolution_type == "remediate_preserved":
            contract = sanitized_params.get("contract")
            if not contract:
                return self._record_and_return_rejection(
                    request=request,
                    run=run,
                    error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                    summary="Parameter 'contract' is required for remediation resolution.",
                    sanitized_params=sanitized_params,
                )

            rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
            claim_ctx = rec_svc.acquire_claim(f"run:{run.run_id}")
            if claim_ctx is None:
                return self._record_and_return_rejection(
                    request=request,
                    run=run,
                    error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                    summary=f"Run '{run.run_id}' is claimed elsewhere by another active recovery context.",
                    sanitized_params=sanitized_params,
                )

            resumed_run = self.orchestration_service.remediate_preserved_candidate(
                run.run_id,
                contract_path=contract,
                project_root=self.project_root,
                claim_context=claim_ctx,
            )
            summary = f"Preserved candidate remediation started; generation is now {resumed_run.current_generation}."
            record = OperatorActionRecord(
                action_request_id=request.action_request_id,
                project_id=request.project_id,
                change_name=request.change_name,
                run_id=request.run_id,
                action_type=request.action_type,
                actor_identity=request.actor_identity,
                source_interface=request.source_interface,
                precondition_stage=run.current_stage.value,
                precondition_gate=run.human_gate.value if run.human_gate else None,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage.value,
                resulting_outcome=resumed_run.stop_outcome.value
                if resumed_run.stop_outcome
                else None,
                resulting_gate=resumed_run.human_gate.value if resumed_run.human_gate else None,
                parameters_json=sanitized_params,
                result_payload_json={"new_generation": resumed_run.current_generation},
            )
            self.uow.operator_actions.save(record)
            self.uow.commit()

            return OperatorActionResult(
                action_request_id=request.action_request_id,
                action_type=request.action_type,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage,
                resulting_outcome=resumed_run.stop_outcome,
                resulting_gate=resumed_run.human_gate,
                payload={"new_generation": resumed_run.current_generation},
            )

        elif resolution_type == "continue_preserved" or resolution_type is None:
            candidate_ref = sanitized_params.get("candidate_ref")
            rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
            claim_ctx = rec_svc.acquire_claim(f"run:{run.run_id}")
            if claim_ctx is None:
                return self._record_and_return_rejection(
                    request=request,
                    run=run,
                    error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                    summary=f"Run '{run.run_id}' is claimed elsewhere by another active recovery context.",
                    sanitized_params=sanitized_params,
                )

            resumed_run = self.orchestration_service.resolve_preserved_candidate(
                run.run_id,
                continue_preserved_candidate=True,
                candidate_ref=candidate_ref,
                project_root=self.project_root,
                claim_context=claim_ctx,
            )
            summary = (
                f"Preserved candidate resolved; run stage is now {resumed_run.current_stage.value}."
            )
            record = OperatorActionRecord(
                action_request_id=request.action_request_id,
                project_id=request.project_id,
                change_name=request.change_name,
                run_id=request.run_id,
                action_type=request.action_type,
                actor_identity=request.actor_identity,
                source_interface=request.source_interface,
                precondition_stage=run.current_stage.value,
                precondition_gate=run.human_gate.value if run.human_gate else None,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage.value,
                resulting_outcome=resumed_run.stop_outcome.value
                if resumed_run.stop_outcome
                else None,
                resulting_gate=resumed_run.human_gate.value if resumed_run.human_gate else None,
                parameters_json=sanitized_params,
                result_payload_json={"stage": resumed_run.current_stage.value},
            )
            self.uow.operator_actions.save(record)
            self.uow.commit()

            return OperatorActionResult(
                action_request_id=request.action_request_id,
                action_type=request.action_type,
                status=OperatorActionStatus.COMPLETED,
                summary=summary,
                resulting_stage=resumed_run.current_stage,
                resulting_outcome=resumed_run.stop_outcome,
                resulting_gate=resumed_run.human_gate,
                payload={"stage": resumed_run.current_stage.value},
            )
        else:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.INVALID_ACTION_PARAMETERS,
                summary=f"Unknown gate resolution type '{resolution_type}'.",
                sanitized_params=sanitized_params,
            )

    def _execute_cancel(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        if not run.is_active and run.stop_outcome == OrchestrationStopOutcome.CANCELLED:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Run is already cancelled.",
                sanitized_params=sanitized_params,
            )

        # 1. Converge the linked execution job before changing the run. Both
        # mutations share the UoW and commit together below.
        self._cancel_linked_job(run)

        # 2. Update run state cleanly
        run.is_active = False
        run.stop_outcome = OrchestrationStopOutcome.CANCELLED
        run.stop_reason = f"Cancelled by {request.actor_identity} via {request.source_interface}"
        run.updated_at = utc_now()
        self.uow.orchestration_runs.save(run)

        # 3. Teardown owned container preview if active
        try:
            active_preview = self.uow.preview_sessions.get_active_for_change(
                run.project_id, run.change_name
            )
            if active_preview:
                active_preview.status = PreviewStatus.TERMINATED
                active_preview.terminated_at = utc_now()
                self.uow.preview_sessions.save(active_preview)
        except Exception as exc:
            logger.warning(f"Error tearing down preview on cancellation: {exc}")

        # 4. Emit durable event
        self.uow.events.save(
            Event(
                event_type=EventType.ORCHESTRATION_STOPPED,
                payload={
                    "run_id": run.run_id,
                    "project_id": run.project_id,
                    "change_name": run.change_name,
                    "stage": run.current_stage.value,
                    "stop_outcome": OrchestrationStopOutcome.CANCELLED.value,
                    "stop_reason": run.stop_reason,
                    "cancelled_by": request.actor_identity,
                },
                timestamp=utc_now(),
            )
        )

        summary = (
            f"Run cancelled safely by {request.actor_identity}; candidate and evidence preserved."
        )
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage.value,
            resulting_outcome=OrchestrationStopOutcome.CANCELLED.value,
            resulting_gate=None,
            parameters_json=sanitized_params,
            result_payload_json={"cancelled": True},
        )
        self.uow.operator_actions.save(record)
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=OrchestrationStopOutcome.CANCELLED,
            resulting_gate=None,
            payload={"cancelled": True},
        )

    def reconcile_cancelled_run_linked_job(self, run_id: str) -> OrchestrationRun:
        """Idempotently converge a cancelled run's non-terminal linked Job.

        This deliberately does not replay cancellation side effects or mutate the
        run. It is the narrow historical repair path for a prior version of
        CANCEL that left ``active_job_id`` in the scheduler's active-job set.
        """
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if not run:
            raise ValueError(f"Orchestration run '{run_id}' not found.")
        if run.is_active or run.stop_outcome != OrchestrationStopOutcome.CANCELLED:
            raise ValueError(
                f"Run '{run_id}' is not an inactive cancelled run and cannot be reconciled."
            )

        try:
            self._cancel_linked_job(run)
            self.uow.commit()
        except Exception:
            self.uow.rollback()
            raise

        return self.uow.orchestration_runs.get_by_id(run_id) or run

    def _cancel_linked_job(self, run: OrchestrationRun) -> None:
        """Transition a run's non-terminal linked Job through the Job authority."""
        if not run.active_job_id:
            return

        job = self.uow.jobs.get_by_id(run.active_job_id)
        if not job:
            raise ValueError(
                f"Run '{run.run_id}' references missing active job '{run.active_job_id}'."
            )
        if job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED}:
            return

        self.uow.jobs.transition(
            job.job_id,
            JobStatus.CANCELLED.value,
            error_message=f"Cancelled with orchestration run '{run.run_id}'.",
        )

    def _execute_start_preview(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        project = self.uow.projects.get_by_id(run.project_id)
        if not project or not project.deployment_preview:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="Project does not have preview deployment configured.",
                sanitized_params=sanitized_params,
            )

        if not run.candidate_sha:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="No frozen candidate SHA exists for this run.",
                sanitized_params=sanitized_params,
            )

        session = PreviewSession(
            project_id=run.project_id,
            change_name=run.change_name,
            head_sha=run.candidate_sha,
            base_sha=run.base_sha,
            candidate_generation=run.current_generation,
            status=PreviewStatus.READY,
            preview_url="http://127.0.0.1:8787",
        )
        self.uow.preview_sessions.save(session)
        self.uow.commit()

        summary = f"Preview started successfully (status: {session.status.value}, url: {session.preview_url})."
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage.value,
            resulting_outcome=run.stop_outcome.value if run.stop_outcome else None,
            resulting_gate=run.human_gate.value if run.human_gate else None,
            evidence_reference=session.preview_id,
            parameters_json=sanitized_params,
            result_payload_json={
                "preview_id": session.preview_id,
                "preview_url": session.preview_url,
                "status": session.status.value,
            },
        )
        self.uow.operator_actions.save(record)
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            evidence_reference=session.preview_id,
            payload={
                "preview_id": session.preview_id,
                "preview_url": session.preview_url,
                "status": session.status.value,
            },
        )

    def _execute_teardown_preview(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        active_preview = self.uow.preview_sessions.get_active_for_change(
            run.project_id, run.change_name
        )
        if not active_preview:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_NOT_ALLOWED,
                summary="No active preview session found to teardown.",
                sanitized_params=sanitized_params,
            )

        active_preview.status = PreviewStatus.TERMINATED
        active_preview.terminated_at = utc_now()
        self.uow.preview_sessions.save(active_preview)
        summary = f"Preview session {active_preview.preview_id} torn down cleanly."

        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage.value,
            resulting_outcome=run.stop_outcome.value if run.stop_outcome else None,
            resulting_gate=run.human_gate.value if run.human_gate else None,
            parameters_json=sanitized_params,
            result_payload_json={
                "preview_id": active_preview.preview_id,
                "status": active_preview.status.value,
            },
        )
        self.uow.operator_actions.save(record)
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            payload={
                "preview_id": active_preview.preview_id,
                "status": active_preview.status.value,
            },
        )

    def _execute_recover_locks(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        active_jobs = self.uow.jobs.list_active_jobs()
        related_jobs = [
            j
            for j in active_jobs
            if j.change_name == run.change_name and j.project_id == run.project_id
        ]

        recovered_locks_count = 0
        for job in related_jobs:
            worktree = Path(job.worktree_path) if job.worktree_path else None
            if worktree and worktree.exists():
                results = self.recovery_service.inspect_git_locks(worktree, job)
                for r in results:
                    if r.status.value == "RECOVERED":
                        recovered_locks_count += 1

        summary = f"Recovered {recovered_locks_count} abandoned Git lock(s)."
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage.value,
            resulting_outcome=run.stop_outcome.value if run.stop_outcome else None,
            resulting_gate=run.human_gate.value if run.human_gate else None,
            parameters_json=sanitized_params,
            result_payload_json={"recovered_locks_count": recovered_locks_count},
        )
        self.uow.operator_actions.save(record)
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=run.current_stage,
            resulting_outcome=run.stop_outcome,
            resulting_gate=run.human_gate,
            payload={"recovered_locks_count": recovered_locks_count},
        )

    def _execute_reconcile_post_merge(
        self,
        request: OperatorActionRequest,
        run: OrchestrationRun,
        sanitized_params: dict[str, Any],
    ) -> OperatorActionResult:
        from minime.domain.enums import (
            RecoveryClassification,
            RecoveryDecisionStatus,
            RecoverySource,
        )

        gh_adapter = getattr(
            self.post_merge_service,
            "github_adapter",
            getattr(self.orchestration_service, "github_adapter", None),
        )
        rec_svc = RecoveryConvergenceService(
            self.uow,
            project_root=self.project_root,
            post_merge_service=self.post_merge_service,
            github_adapter=gh_adapter,
        )
        decision = rec_svc.request_run_continuation(
            run_id=run.run_id,
            source=RecoverySource.CONTROL_PLANE,
            requested_action="RECONCILE_POST_MERGE",
        )
        if decision.classification == RecoveryClassification.CLAIMED_ELSEWHERE:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.AUTHORITY_MISMATCH,
                summary=f"Run '{run.run_id}' is claimed elsewhere by another active recovery context.",
                sanitized_params=sanitized_params,
            )
        if decision.status == RecoveryDecisionStatus.BLOCKED:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.ACTION_EXECUTION_FAILED,
                summary=decision.reason_code or "Post-merge reconciliation failed.",
                sanitized_params=sanitized_params,
            )

        summary = "Post-merge reconciliation completed successfully."
        record = OperatorActionRecord(
            action_request_id=request.action_request_id,
            project_id=request.project_id,
            change_name=request.change_name,
            run_id=request.run_id,
            action_type=request.action_type,
            actor_identity=request.actor_identity,
            source_interface=request.source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=run.human_gate.value if run.human_gate else None,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=OrchestrationStage.COMPLETED.value,
            resulting_outcome=OrchestrationStopOutcome.COMPLETED.value,
            resulting_gate=None,
            parameters_json=sanitized_params,
            result_payload_json={
                "decision_status": decision.status.value,
                "classification": decision.classification.value,
            },
        )
        self.uow.operator_actions.save(record)
        self.uow.commit()

        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=summary,
            resulting_stage=OrchestrationStage.COMPLETED,
            resulting_outcome=OrchestrationStopOutcome.COMPLETED,
            payload=record.result_payload_json,
        )

    def list_action_history(self, run_id: str, limit: int = 50) -> list[OperatorActionRecord]:
        """Fetch audit trail of operator actions executed for a run."""
        return self.uow.operator_actions.list_by_run(run_id, limit=limit)

    def resume_saga(self, saga_id: str, actor_identity: str = "operator") -> Any:
        """Manually trigger saga resumption with row-locking idempotency."""
        saga = self.uow.durable_sagas.get_by_id(saga_id)
        if not saga:
            raise ValueError(f"DurableSaga '{saga_id}' not found.")

        rec_svc = RecoveryConvergenceService(self.uow, project_root=self.project_root)
        rec_svc.reconcile_saga(saga_id, source=RecoverySource.CONTROL_PLANE)
        return self.uow.durable_sagas.get_by_id(saga_id) or saga
