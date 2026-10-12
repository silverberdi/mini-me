"""Resolve the durable executor choice for one linked run/job pair."""

from __future__ import annotations

from typing import Any

from minime.domain.enums import OperatorActionStatus, OperatorActionType
from minime.domain.models import Job, OrchestrationRun


def effective_job_executor(
    uow: Any, run: OrchestrationRun | None, job: Job
) -> tuple[str | None, Any | None, bool]:
    """Return the executor and applicable handoff, respecting newer human intent.

    OperatorActionRecord is the durable idempotency/audit authority for explicit
    REASSIGN. An older automatic handoff remains evidence but cannot supersede a
    later, successfully applied human choice.
    """
    handoffs = [
        handoff for handoff in uow.job_handoffs.list_by_job(job.job_id) if not handoff.is_consumed
    ]
    handoff = max(handoffs, key=lambda item: item.created_at) if handoffs else None

    if run is not None:
        actions = uow.operator_actions.list_by_run(run.run_id)
        reassignments = [
            action
            for action in actions
            if action.action_type == OperatorActionType.REASSIGN
            and action.status == OperatorActionStatus.COMPLETED
            and action.project_id == run.project_id
            and action.change_name == run.change_name
            and action.job_id == job.job_id
            and action.result_payload_json.get("executor_assignment_applied") is True
            and isinstance(action.result_payload_json.get("target_executor"), str)
        ]
        reassignment = (
            max(reassignments, key=lambda action: action.created_at) if reassignments else None
        )
        if reassignment and (handoff is None or reassignment.created_at > handoff.created_at):
            return reassignment.result_payload_json["target_executor"], None, True

    if handoff is not None:
        return handoff.to_executor, handoff, False
    return job.current_executor, None, False
