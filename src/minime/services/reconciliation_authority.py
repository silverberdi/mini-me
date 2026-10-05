"""Reconciliation Authority for observe-before-repeat external action reconciliation."""

from __future__ import annotations

import logging
from typing import Any

from minime.domain.enums import EventType, ExternalOutcome
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import Event, OrchestrationExternalAction

logger = logging.getLogger(__name__)


class ReconciliationAuthority:
    """Canonical authority for observe-before-repeat reconciliation of saga external actions."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def reconcile_observe_before_repeat(
        self,
        action_key: str,
        observed_result: Any,
        original_mutation_retry_authorized: bool = False,
    ) -> OrchestrationExternalAction:
        """Delegate to OrchestrationExternalActionRepository.reconcile_observe_before_repeat while preserving Stage B fail-closed evidence contracts."""
        action = self.uow.orchestration_external_actions.reconcile_observe_before_repeat(
            action_key=action_key,
            observed_result=observed_result,
            original_mutation_retry_authorized=original_mutation_retry_authorized,
        )

        event = Event(
            project_id="system",
            change_id=action_key,
            event_type=EventType.DURABLE_SAGA_ACTION_RECONCILED.value,
            payload={
                "action_key": action_key,
                "status": action.status.value,
                "remote_identifier": action.remote_identifier,
                "reconciled_at": action.reconciled_at.isoformat() if action.reconciled_at else None,
            },
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.info(
            "Reconciled action '%s': status -> %s (remote_id=%s)",
            action_key,
            action.status.value,
            action.remote_identifier,
        )
        return action

    def reconcile_issue_creation(
        self,
        github_adapter: Any,
        repository: str,
        operation_key: str,
        title: str,
    ) -> Any:
        """Search issues using exact comment marker `<!-- minime-opkey: <op_key> -->`. Title matching is forbidden."""
        from minime.domain.enums import ExternalReasonCode
        from minime.domain.models import ExternalActionResult

        marker = f"<!-- minime-opkey: {operation_key} -->"
        try:
            res = github_adapter.list_issues(repository, state="all")
            if res.outcome == ExternalOutcome.SUCCESS and res.data is not None:
                for issue in res.data:
                    body = issue.get("body") or ""
                    if marker in body:
                        num = issue.get("number")
                        url = (
                            issue.get("html_url") or f"https://github.com/{repository}/issues/{num}"
                        )
                        return ExternalActionResult(
                            outcome=ExternalOutcome.SUCCESS,
                            source_adapter="github",
                            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                            data={"number": num, "html_url": url},
                            external_id=str(num),
                        )
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    error_message=f"No issue found with marker '{operation_key}'",
                )
            elif res.outcome != ExternalOutcome.SUCCESS:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    error_message=str(
                        getattr(res, "error_message", "Listing issues returned non-success outcome.")
                    ),
                )
        except Exception as exc:
            logger.warning(
                "Failed to list issues during reconciliation for '%s': %s", operation_key, exc
            )
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                error_message=f"Exception during issue list reconciliation: {exc}",
            )

        return ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="github",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            error_message=f"Unobservable issue listing for '{operation_key}'",
        )

    def reconcile_project_item_add(
        self,
        github_adapter: Any,
        project_number: int,
        owner: str,
        issue_url: str,
        operation_key: str,
    ) -> Any:
        """Look up project item ID by exact issue URL. Fuzzy title search is forbidden."""
        from minime.domain.enums import ExternalReasonCode
        from minime.domain.models import ExternalActionResult

        try:
            res = github_adapter.list_project_items(project_number=project_number, owner=owner)
            if res.outcome == ExternalOutcome.SUCCESS and res.data is not None:
                for item in res.data:
                    content_url = (
                        item.get("issue_url")
                        or item.get("content_url")
                        or (
                            item.get("content", {}).get("url")
                            if isinstance(item.get("content"), dict)
                            else None
                        )
                    )
                    if content_url == issue_url:
                        item_id = item.get("id") or item.get("item_id")
                        return ExternalActionResult(
                            outcome=ExternalOutcome.SUCCESS,
                            source_adapter="github",
                            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                            data=item_id,
                            external_id=str(item_id),
                        )
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    error_message=f"No project item found for issue URL '{issue_url}'",
                )
            elif res.outcome != ExternalOutcome.SUCCESS:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    error_message=getattr(
                        res, "error_message", "Listing project items returned non-success outcome."
                    ),
                )
        except Exception as exc:
            logger.warning(
                "Failed to list project items during reconciliation for '%s': %s", issue_url, exc
            )
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                error_message=f"Exception during project item list reconciliation: {exc}",
            )

        return ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="github",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            error_message=f"Unobservable project item listing for '{issue_url}'",
        )
