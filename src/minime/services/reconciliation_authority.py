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
        issues = github_adapter.search_issues_by_marker(repository, operation_key)
        from minime.domain.enums import ExternalReasonCode
        from minime.domain.models import ExternalActionResult
        if issues:
            matching = issues[0]
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                remote_identifier=str(matching.get("number")),
                data={"number": matching.get("number"), "html_url": matching.get("html_url")},
            )
        return ExternalActionResult(
            outcome=ExternalOutcome.FAILURE,
            source_adapter="github",
            reason_code=ExternalReasonCode.NOT_FOUND,
            error_message=f"No issue found with marker '{operation_key}'",
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
        item_id = github_adapter.lookup_project_item_id_by_issue_url(project_number, owner, issue_url)
        from minime.domain.enums import ExternalReasonCode
        from minime.domain.models import ExternalActionResult
        if item_id:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                remote_identifier=str(item_id),
                data=item_id,
            )
        return ExternalActionResult(
            outcome=ExternalOutcome.FAILURE,
            source_adapter="github",
            reason_code=ExternalReasonCode.NOT_FOUND,
            error_message=f"No project item found for issue URL '{issue_url}'",
        )


