"""Project-scoped GitHub connection verification."""

from __future__ import annotations

from typing import Any

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import ExternalOutcome
from minime.domain.models import ExternalActionResult, Project
from minime.services.project_credential_store import ProjectCredentialStore


class ProjectConnectionService:
    """Verify each project connection with its own auth instance and repository."""

    def __init__(self, credential_store: ProjectCredentialStore | None = None) -> None:
        self.credential_store = credential_store or ProjectCredentialStore()

    def adapter_for(self, project: Project, responsibility: str) -> GitHubAdapter:
        """Resolve a fresh GitHub adapter for exactly one configured responsibility."""
        if responsibility not in {"tickets", "git_pr"}:
            raise ValueError("Unknown project connection responsibility")
        connection = project.provider_connections.get(responsibility)
        if not isinstance(connection, dict) or connection.get("provider_id") != "github":
            raise ValueError(f"Project {responsibility} connection is not configured")
        repository = connection.get("repository_url")
        if not isinstance(repository, str) or not repository.strip():
            raise ValueError(f"Project {responsibility} connection has no repository identity")
        # GitHubAdapter creates an isolated auth/token cache for this project/app.
        return GitHubAdapter.for_project_connection(
            project.project_id, connection, self.credential_store
        )

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
                adapter = self.adapter_for(project, responsibility)
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

    def require_git_pr_write(self, project: Project) -> GitHubAdapter:
        """Return the bound GitHub adapter only after proving its current write grants.

        Bootstrap/incremental publishers must use this gate before branch or
        pull-request mutations. Unknown permission evidence is treated as denial.
        """
        adapter = self.adapter_for(project, "git_pr")
        repository = project.provider_connections["git_pr"]["repository_url"]
        result = adapter.verify_connection_permissions(repository, "git_pr")
        if result.outcome != ExternalOutcome.SUCCESS:
            raise PermissionError(
                "GitHub Git/PR connection is not authorized for mutations: "
                + result.reason_code.value.lower()
            )
        return adapter

    def create_remote_branch(
        self, project: Project, branch: str, base_sha: str
    ) -> ExternalActionResult[str]:
        """Create/reconcile a project branch only after live permission verification."""
        adapter = self.require_git_pr_write(project)
        repository = project.provider_connections["git_pr"]["repository_url"]
        return adapter.create_remote_branch(repository, branch, base_sha)

    def get_repository_branch_head(
        self, project: Project, branch: str
    ) -> ExternalActionResult[str]:
        """Observe a requested project branch after verifying its exact Git/PR grant."""
        adapter = self.require_git_pr_write(project)
        repository = project.provider_connections["git_pr"]["repository_url"]
        return adapter.get_repository_branch_head(repository, branch)

    def create_pull_request(
        self,
        project: Project,
        branch: str,
        title: str,
        body: str,
        head_sha: str,
        *,
        draft: bool = True,
    ) -> ExternalActionResult[dict[str, Any]]:
        """Publish a PR only after live permission verification for this project."""
        adapter = self.require_git_pr_write(project)
        repository = project.provider_connections["git_pr"]["repository_url"]
        return adapter.create_pull_request(
            repository,
            branch,
            project.base_branch,
            title,
            body,
            head_sha,
            draft=draft,
        )
