"""Provider-agnostic Request lifecycle management (F7).

Governs Request creation, editing, deactivation, reactivation, and soft-deletion,
enforcing strict admission boundaries (unstarted requests can be mutated; active
requests accept clarifications only via HUMAN_REQUIRED; completed requests are
immutable).
"""

from __future__ import annotations

from typing import Any

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import ExternalOutcome
from minime.domain.exceptions import RequestMutationNotAllowedError
from minime.services.request_normalization import RequestNormalizationService


class RequestLifecycleService:
    def __init__(
        self,
        uow: Any,
        github_adapter: GitHubAdapter | None = None,
        normalizer: RequestNormalizationService | None = None,
    ) -> None:
        self.uow = uow
        self.github_adapter = github_adapter or GitHubAdapter()
        self.normalizer = normalizer

    def _assert_can_mutate(self, project_id: str, issue_number: int) -> None:
        """Enforce admission boundary."""
        if hasattr(self.uow, "orchestration_runs"):
            runs = (
                self.uow.orchestration_runs.list_by_project(project_id)
                if hasattr(self.uow.orchestration_runs, "list_by_project")
                else []
            )
            for run in runs:
                details = getattr(run, "stop_details", {}) or {}
                if details.get("issue_number") == issue_number:
                    if getattr(run, "is_active", False):
                        raise RequestMutationNotAllowedError(
                            f"Request #{issue_number} is currently active and can only be clarified via HUMAN_REQUIRED."
                        )
                    stage = getattr(run, "current_stage", None)
                    outcome = getattr(run, "stop_outcome", None)
                    if outcome == "COMPLETED" or stage in ("COMPLETED", "PR2_MERGED"):
                        raise RequestMutationNotAllowedError(
                            f"Request #{issue_number} is completed and immutable."
                        )

    def create_request(
        self,
        project_id: str,
        title: str,
        description: str,
        acceptance_criteria: str | None = None,
    ) -> dict[str, Any]:
        """Create a new human request, delegating normalization exclusively to F4 normalizer."""
        if not title or not title.strip():
            raise ValueError("Request title cannot be empty.")
        if not description or not description.strip():
            raise ValueError("Request description cannot be empty.")
        if not acceptance_criteria or not acceptance_criteria.strip():
            raise ValueError("Request acceptance criteria cannot be empty.")

        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        # Preserve verbatim raw human input
        raw_body = f"{description.strip()}\n\n## Criterios de Aceptación\n{acceptance_criteria.strip()}"

        # Delegate normalization and Gherkin generation exclusively to existing F4 normalizer
        normalizer = self.normalizer or RequestNormalizationService(self.github_adapter)
        norm = normalizer.normalize(title.strip(), raw_body)
        body = norm.normalized_body

        res = self.github_adapter.create_issue(
            repository=project.repository,
            title=title.strip(),
            body=body,
            labels=["request", "unadmitted"],
        )
        if res.outcome != ExternalOutcome.SUCCESS:
            raise RuntimeError(f"Failed to create remote request: {res.error_message}")
        return res.data if isinstance(res.data, dict) else {"url": res.data}

    def edit_request(
        self,
        project_id: str,
        issue_number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        expected_version: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Edit an unstarted request with optimistic concurrency and idempotency."""
        self._assert_can_mutate(project_id, issue_number)
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        res = self.github_adapter.update_issue_state(
            repository=project.repository,
            issue_number=issue_number,
            title=title,
            body=body,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        if res.outcome != ExternalOutcome.SUCCESS:
            raise RuntimeError(f"Failed to edit request #{issue_number}: {res.error_message}")
        return res.data

    def deactivate_request(
        self,
        project_id: str,
        issue_number: int,
        *,
        expected_version: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Deactivate an unstarted request by attaching 'disabled' label."""
        self._assert_can_mutate(project_id, issue_number)
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        res = self.github_adapter.update_issue_state(
            repository=project.repository,
            issue_number=issue_number,
            labels=["disabled"],
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        if res.outcome != ExternalOutcome.SUCCESS:
            raise RuntimeError(f"Failed to deactivate request #{issue_number}: {res.error_message}")
        return res.data

    def reactivate_request(
        self,
        project_id: str,
        issue_number: int,
        *,
        expected_version: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Reactivate a disabled request by removing 'disabled' label."""
        self._assert_can_mutate(project_id, issue_number)
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        res = self.github_adapter.update_issue_state(
            repository=project.repository,
            issue_number=issue_number,
            labels=[],
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        if res.outcome != ExternalOutcome.SUCCESS:
            raise RuntimeError(f"Failed to reactivate request #{issue_number}: {res.error_message}")
        return res.data

    def soft_delete_request(
        self,
        project_id: str,
        issue_number: int,
        *,
        expected_version: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Soft-delete an unstarted request, preserving audit trail but excluding from FIFO."""
        self._assert_can_mutate(project_id, issue_number)
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        res = self.github_adapter.update_issue_state(
            repository=project.repository,
            issue_number=issue_number,
            labels=["deleted"],
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        if res.outcome != ExternalOutcome.SUCCESS:
            raise RuntimeError(f"Failed to soft delete request #{issue_number}: {res.error_message}")
        return res.data
