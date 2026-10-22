"""Project-scoped GitHub connection verification."""

from __future__ import annotations

from typing import Any

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import ExternalOutcome
from minime.domain.models import Project
from minime.services.project_credential_store import ProjectCredentialStore


class ProjectConnectionService:
    """Verify each project connection with its own auth instance and repository."""

    def __init__(self, credential_store: ProjectCredentialStore | None = None) -> None:
        self.credential_store = credential_store or ProjectCredentialStore()

    def verify(self, project: Project) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for responsibility in ("tickets", "git_pr"):
            connection = project.provider_connections.get(responsibility)
            if not isinstance(connection, dict) or connection.get("provider_id") != "github":
                results[responsibility] = {
                    "verified": False,
                    "reason": "connection_not_configured",
                }
                continue
            try:
                adapter = GitHubAdapter.for_project_connection(
                    project.project_id, connection, self.credential_store
                )
                result = adapter.verify_connection_permissions(
                    connection.get("repository_url", ""), responsibility
                )
            except (ValueError, RuntimeError):
                results[responsibility] = {
                    "verified": False,
                    "reason": "connection_unavailable",
                }
                continue
            results[responsibility] = {
                "verified": result.outcome == ExternalOutcome.SUCCESS,
                "reason": (
                    "verified"
                    if result.outcome == ExternalOutcome.SUCCESS
                    else result.reason_code.value.lower()
                ),
                "repository": result.data.get("repository") if result.data else None,
                "permissions": result.data.get("permissions") if result.data else None,
            }
        return results
