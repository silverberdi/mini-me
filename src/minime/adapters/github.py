"""GitHub work-binding adapter and durable identifiers."""

from __future__ import annotations

from typing import Any

from minime.domain.enums import EventType
from minime.domain.interfaces import GitHubAdapterInterface
from minime.domain.models import Event, utc_now
from minime.logging import get_logger
from minime.services.project_service import normalize_repository_identity

logger = get_logger("adapters.github")


class GitHubAdapter(GitHubAdapterInterface):
    """Adapter for GitHub work tracking (Issues, Projects) and durable binding."""

    def __init__(self, token: str | None = None):
        self.token = token

    def validate_issue_binding(
        self,
        expected_repository: str,
        issue_number: int,
        github_repository: str | None = None,
    ) -> tuple[bool, str | None]:
        """Validate that a GitHub Issue actually belongs to the project's bound repository.

        Repository authority comes strictly from the durable project binding, never
        from presentation metadata or external claims.
        """
        if github_repository is not None:
            norm_expected = normalize_repository_identity(expected_repository)
            norm_actual = normalize_repository_identity(github_repository)
            if norm_expected != norm_actual:
                return False, (
                    f"Repository mismatch: GitHub Issue #{issue_number} is in repository "
                    f"'{norm_actual}', but project is bound to '{norm_expected}'."
                )

        if issue_number <= 0:
            return False, f"Invalid issue number: {issue_number} must be positive."

        return True, None

    def record_sync_failure(
        self,
        project_id: str,
        change_id: str | None,
        operation: str,
        error_message: str,
    ) -> Event:
        """Record an observable and reconcilable synchronization failure."""
        logger.warning(
            f"GitHub sync failure for project '{project_id}' during '{operation}': {error_message}"
        )
        return Event(
            event_type=EventType.SYNC_FAILED,
            project_id=project_id,
            change_id=change_id,
            operation_id=operation,
            payload={
                "operation": operation,
                "error": error_message,
                "reconcilable": True,
            },
            timestamp=utc_now(),
        )

    def record_sync_reconciled(
        self,
        project_id: str,
        change_id: str | None,
        operation: str,
        details: dict[str, Any] | None = None,
    ) -> Event:
        """Record a successful reconciliation after a prior synchronization failure."""
        logger.info(f"GitHub sync reconciled for project '{project_id}' during '{operation}'")
        return Event(
            event_type=EventType.SYNC_RECONCILED,
            project_id=project_id,
            change_id=change_id,
            operation_id=operation,
            payload={
                "operation": operation,
                "details": details or {},
                "reconciled": True,
            },
            timestamp=utc_now(),
        )
