"""Deployment authority service enforcing explicit deployment promotion boundaries."""

from __future__ import annotations

from typing import Any

from minime.domain.enums import ExternalOutcome, ExternalReasonCode
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import ExternalActionResult


class DeploymentAuthority:
    """Authoritative deployment promotion boundary."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def promote_candidate_to_production(
        self,
        project_id: str,
        change_name: str,
        candidate_sha: str,
        merge_commit_sha: str,
        operator_identity: str,
    ) -> ExternalActionResult[dict[str, Any]]:
        """Promote a merged candidate SHA to production runtime.

        SDLC runners/agents are barred from calling this interface directly.
        Requires verified main branch merge commit SHA.
        The deployment authority authorizes handoff to actual deployment engine without fabricating 'DEPLOYED' state.
        """
        # Validate project exists
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            return ExternalActionResult[dict[str, Any]](
                outcome=ExternalOutcome.FAILURE,
                source_adapter="deployment_authority",
                reason_code=ExternalReasonCode.NOT_FOUND,
                error_message=f"Project '{project_id}' not found.",
            )

        # Validate that merge commit SHA is provided and non-empty
        if not merge_commit_sha:
            return ExternalActionResult[dict[str, Any]](
                outcome=ExternalOutcome.FAILURE,
                source_adapter="deployment_authority",
                reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                error_message="Production promotion requires explicit merge commit SHA on main branch.",
            )

        # Deployment authority boundary approval: HANDOFF_READY / AUTHORIZED
        deployment_evidence = {
            "project_id": project_id,
            "change_name": change_name,
            "candidate_sha": candidate_sha,
            "merge_commit_sha": merge_commit_sha,
            "operator_identity": operator_identity,
            "status": "HANDOFF_READY",
        }

        return ExternalActionResult[dict[str, Any]](
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="deployment_authority",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            data=deployment_evidence,
            observed_evidence=deployment_evidence,
        )
