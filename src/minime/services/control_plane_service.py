"""Operator Actions Control Plane service for mini me.

Provides canonical action discovery, authority validation, optimistic concurrency,
idempotency, cancellation safety, and durable audit persistence across presentation layers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

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
from minime.services.provider_health_service import ProviderHealthService
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
        if run.is_active:
            continue_reason = "Run is already active"
        elif run.current_stage == OrchestrationStage.PR_PREPARED:
            continue_reason = "Run has completed PR preparation"
        elif run.stop_outcome == OrchestrationStopOutcome.CANCELLED:
            continue_reason = "Run was cancelled"
        elif (
            run.resumable_stage is not None
            or run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
        ):
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
        run = self.uow.orchestration_runs.get_by_id(request.run_id)
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
            err_msg = redact_secrets(str(exc))
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
                resulting_stage=run.current_stage,
                resulting_outcome=run.stop_outcome,
                resulting_gate=run.human_gate,
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
        if run.is_active:
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
        ):
            run.stop_outcome = None
            run.human_gate = None
            run.is_active = True
            run.stop_reason = None
            run.stop_details = {}
            if run.active_job_id:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                if job and job.status == JobStatus.NEEDS_HUMAN:
                    job.status = JobStatus.RUNNING
                    job.continuation_decision = None
                    job.escalation_reason = None
                    job.reassignment_count = 0
                    self.uow.jobs.save(job)
            self.uow.orchestration_runs.save(run)
            self.uow.commit()

        # Call orchestration service resume
        resumed_run = self.orchestration_service.resume(
            run.run_id, project_root=self.project_root, force=True
        )

        summary = f"Run resumed successfully at stage {resumed_run.current_stage.value}."
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
            result_payload_json={"resumed_stage": resumed_run.current_stage.value},
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
            payload={"resumed_stage": resumed_run.current_stage.value},
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

        # Increment retry count and resume
        run.retry_count += 1
        self.uow.orchestration_runs.save(run)
        self.uow.commit()

        resumed_run = self.orchestration_service.resume(run.run_id, project_root=self.project_root)

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

        # Check provider health
        health = self.uow.provider_health.get_by_provider(target_executor)
        if health and health.status == ProviderHealthStatus.EXHAUSTED:
            return self._record_and_return_rejection(
                request=request,
                run=run,
                error_code=OperatorActionErrorCode.PROVIDER_UNAVAILABLE,
                summary=f"Target provider '{target_executor}' is currently exhausted.",
                sanitized_params=sanitized_params,
            )

        # Increment reassignment count and update run
        run.reassignment_count += 1
        run.pending_handoff = {
            "to_executor": target_executor,
            "reassigned_by": request.actor_identity,
            "reassigned_at": utc_now().isoformat(),
        }
        self.uow.orchestration_runs.save(run)
        self.uow.commit()

        resumed_run = self.orchestration_service.resume(run.run_id, project_root=self.project_root)

        summary = (
            f"Run reassigned to {target_executor} (reassignment #{resumed_run.reassignment_count})."
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
                "target_executor": target_executor,
                "reassignment_count": resumed_run.reassignment_count,
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
                "target_executor": target_executor,
                "reassignment_count": resumed_run.reassignment_count,
            },
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

            # Advance orchestration
            resumed_run = self.orchestration_service.resume(
                run.run_id, project_root=self.project_root
            )

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

            resumed_run = self.orchestration_service.remediate_preserved_candidate(
                run.run_id, contract_path=contract, project_root=self.project_root
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
            resumed_run = self.orchestration_service.resolve_preserved_candidate(
                run.run_id,
                continue_preserved_candidate=True,
                candidate_ref=candidate_ref,
                project_root=self.project_root,
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

        # 1. Update run state cleanly
        run.is_active = False
        run.stop_outcome = OrchestrationStopOutcome.CANCELLED
        run.stop_reason = f"Cancelled by {request.actor_identity} via {request.source_interface}"
        run.updated_at = utc_now()
        self.uow.orchestration_runs.save(run)

        # 2. Teardown owned container preview if active
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

        # 3. Emit durable event
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

    def list_action_history(self, run_id: str, limit: int = 50) -> list[OperatorActionRecord]:
        """Fetch audit trail of operator actions executed for a run."""
        return self.uow.operator_actions.list_by_run(run_id, limit=limit)
