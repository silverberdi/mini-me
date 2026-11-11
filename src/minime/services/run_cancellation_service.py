"""Operator-requested cancellation of an active orchestration Run."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from minime.domain.enums import (
    ExternalOutcome,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStopOutcome,
)
from minime.domain.models import OperatorActionRecord, OrchestrationStageEvent
from minime.services.worktree_manager import WorktreeManager


class RunCancellationError(ValueError):
    """The requested Run cannot be safely cancelled in its current state."""


class RunCancellationService:
    def __init__(self, uow: Any):
        self.uow = uow

    async def cancel(
        self,
        *,
        project_id: str,
        run_id: str,
        reason: str,
        actor_identity: str,
        source_interface: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        reason = reason.strip()
        if not reason:
            raise RunCancellationError("A cancellation reason is required.")
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise RunCancellationError("A valid idempotency key is required.")

        prior = self.uow.operator_actions.get_by_request_id(idempotency_key)
        if prior:
            result = self._reuse_prior_action(
                prior,
                project_id=project_id,
                run_id=run_id,
                reason=reason,
            )
            if result.get("workspace_cleanup") == "PENDING":
                return await self._retry_cleanup(prior, result, project_id, run_id)
            return result

        run = self.uow.orchestration_runs.get_for_update(run_id)
        if run is None or run.project_id != project_id:
            raise RunCancellationError("Run not found for this project.")

        # Recheck after acquiring the Run lock so a concurrent identical request
        # observes the first transaction's durable result.
        prior = self.uow.operator_actions.get_by_request_id(idempotency_key)
        if prior:
            result = self._reuse_prior_action(
                prior,
                project_id=project_id,
                run_id=run_id,
                reason=reason,
            )
            if result.get("workspace_cleanup") == "PENDING":
                return await self._retry_cleanup(prior, result, project_id, run_id)
            return result

        if not run.is_active or run.stop_outcome in {
            OrchestrationStopOutcome.COMPLETED,
            OrchestrationStopOutcome.FAILED,
            OrchestrationStopOutcome.CANCELLED,
        }:
            raise RunCancellationError("Run is inactive or already terminal.")
        if run.active_job_id:
            raise RunCancellationError("Run still has an active job; cancellation was not applied.")

        cancelled_at = datetime.now(UTC)
        details = dict(run.stop_details or {})
        details["cancellation"] = {
            "actor": actor_identity,
            "reason": reason,
            "previous_stop_reason": run.stop_reason,
            "cancelled_at": cancelled_at.isoformat(),
            "idempotency_key": idempotency_key,
            "source_interface": source_interface,
        }
        self.uow.orchestration_runs.update_stop_outcome(
            run_id=run_id,
            stop_outcome=OrchestrationStopOutcome.CANCELLED,
            human_gate=None,
            stop_reason=reason,
            stop_details=details,
            is_active=False,
        )

        result: dict[str, Any] = {
            "status": "CANCELLED",
            "project_id": project_id,
            "run_id": run_id,
            "change_name": run.change_name,
            "workspace_cleanup": "PENDING",
        }
        action = OperatorActionRecord(
            action_request_id=idempotency_key,
            project_id=project_id,
            change_name=run.change_name,
            run_id=run_id,
            action_type=OperatorActionType.CANCEL,
            actor_identity=actor_identity,
            source_interface=source_interface,
            precondition_stage=run.current_stage.value,
            precondition_gate=(run.human_gate.value if run.human_gate else None),
            status=OperatorActionStatus.COMPLETED,
            summary="Cancelled an active Run with no active stage job.",
            resulting_stage=run.current_stage.value,
            resulting_outcome=OrchestrationStopOutcome.CANCELLED.value,
            resulting_gate=None,
            parameters_json={"reason": reason},
            result_payload_json=result,
        )
        self.uow.operator_actions.save(action)
        self.uow.orchestration_stage_events.save(
            OrchestrationStageEvent(
                run_id=run_id,
                from_stage=run.current_stage,
                to_stage=run.current_stage,
                event_type="RUN_CANCELLED",
                transition_key=f"run-cancel:{idempotency_key}",
                evidence_references={"actor": actor_identity, "reason": reason},
                actor=actor_identity,
            )
        )
        self.uow.commit()

        try:
            cleanup_status, cleanup_detail = await self._cleanup_owned_worktrees(project_id, run_id)
        except Exception as exc:  # cleanup failure must not undo the durable cancellation
            cleanup_status, cleanup_detail = "PENDING", type(exc).__name__
        result["workspace_cleanup"] = cleanup_status
        if cleanup_detail:
            result["workspace_cleanup_detail"] = cleanup_detail
        action.result_payload_json = result
        if cleanup_status == "PENDING":
            updated = self.uow.orchestration_runs.get_by_id(run_id)
            updated_details = dict(updated.stop_details or {}) if updated else {}
            updated_cancel = dict(updated_details.get("cancellation") or {})
            updated_cancel["workspace_cleanup"] = cleanup_status
            if cleanup_detail:
                updated_cancel["workspace_cleanup_detail"] = cleanup_detail
            updated_details["cancellation"] = updated_cancel
            if updated:
                updated.stop_details = updated_details
                self.uow.orchestration_runs.save(updated)
        self.uow.operator_actions.save(action)
        self.uow.commit()
        return result

    async def _retry_cleanup(
        self,
        action: OperatorActionRecord,
        result: dict[str, Any],
        project_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        try:
            cleanup_status, cleanup_detail = await self._cleanup_owned_worktrees(project_id, run_id)
        except Exception as exc:  # keep the terminal Run and surface a retryable cleanup state
            cleanup_status, cleanup_detail = "PENDING", type(exc).__name__
        result["workspace_cleanup"] = cleanup_status
        if cleanup_detail:
            result["workspace_cleanup_detail"] = cleanup_detail
        else:
            result.pop("workspace_cleanup_detail", None)
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if run:
            details = dict(run.stop_details or {})
            cancellation = dict(details.get("cancellation") or {})
            cancellation["workspace_cleanup"] = cleanup_status
            if cleanup_detail:
                cancellation["workspace_cleanup_detail"] = cleanup_detail
            else:
                cancellation.pop("workspace_cleanup_detail", None)
            details["cancellation"] = cancellation
            run.stop_details = details
            self.uow.orchestration_runs.save(run)
        action.result_payload_json = result
        self.uow.operator_actions.save(action)
        self.uow.commit()
        return result

    @staticmethod
    def _reuse_prior_action(
        action: OperatorActionRecord,
        *,
        project_id: str,
        run_id: str,
        reason: str,
    ) -> dict[str, Any]:
        if (
            action.action_type != OperatorActionType.CANCEL
            or action.project_id != project_id
            or action.run_id != run_id
            or action.parameters_json.get("reason") != reason
        ):
            raise RunCancellationError("Idempotency key is already bound to another action.")
        if action.status != OperatorActionStatus.COMPLETED:
            raise RunCancellationError("The original cancellation action is not complete.")
        return dict(action.result_payload_json or {})

    async def _cleanup_owned_worktrees(self, project_id: str, run_id: str) -> tuple[str, str | None]:
        ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        if ownership_repo is None:
            return "PENDING", "Durable worktree ownership repository is unavailable."
        owners = [
            owner
            for owner in ownership_repo.list_by_project(project_id)
            if owner.run_id == run_id
        ]
        if not owners:
            return "NOT_REQUIRED", None
        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project_id) if binding_repo else None
        if not binding or not binding.managed_repository_root:
            return "PENDING", "Verified managed repository binding is unavailable."

        manager = WorktreeManager(Path(binding.managed_repository_root), uow=self.uow)
        failures: list[str] = []
        for owner in owners:
            if owner.run_id != run_id or owner.project_id != project_id:
                failures.append("A worktree owner did not match the cancelled Run.")
                continue
            outcome = await manager.remove_clean_worktree_path(
                owner.canonical_worktree_path,
                owner.job_id,
                project_id,
            )
            if outcome.outcome != ExternalOutcome.SUCCESS:
                failures.append(outcome.reason_code.value if outcome.reason_code else "cleanup_failed")
        if failures:
            return "PENDING", ", ".join(sorted(set(failures)))
        return "CLEANED", None
