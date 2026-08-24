"""GitHub work-binding adapter and durable identifiers."""

from __future__ import annotations

from typing import Any

from minime.domain.enums import EventType, PullRequestLookupState
from minime.domain.interfaces import GitHubAdapterInterface
from minime.domain.models import Event, PullRequestLookupResult, utc_now
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

    def get_pull_request(
        self, repository: str, branch: str, base: str = "main"
    ) -> PullRequestLookupResult:
        """Lookup a PR with an explicit authoritative remote state."""
        import json
        import subprocess

        try:
            cmd = [
                "gh",
                "pr",
                "list",
                "--repo",
                repository,
                "--head",
                branch,
                "--base",
                base,
                "--state",
                "all",
                "--limit",
                "20",
                "--json",
                "number,url,headRefOid,baseRefName,headRefName,state,title,body",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                return PullRequestLookupResult(
                    state=PullRequestLookupState.UNOBSERVABLE,
                    detail=res.stderr or res.stdout or "gh pr list failed",
                )
            records = json.loads(res.stdout or "[]")
            if not isinstance(records, list):
                return PullRequestLookupResult(
                    state=PullRequestLookupState.AMBIGUOUS,
                    detail="gh returned a non-list PR result.",
                )
            if not records:
                return PullRequestLookupResult(state=PullRequestLookupState.NOT_FOUND)
            if len(records) > 1:
                return PullRequestLookupResult(
                    state=PullRequestLookupState.AMBIGUOUS,
                    detail=f"Found {len(records)} plausible pull requests.",
                )
            data = records[0]
            return PullRequestLookupResult(
                state=PullRequestLookupState.FOUND_EXACT,
                pull_request={
                    "repository": repository,
                    "number": data.get("number"),
                    "url": data.get("url"),
                    "head_sha": data.get("headRefOid"),
                    "head_branch": data.get("headRefName"),
                    "base_branch": data.get("baseRefName"),
                    "state": data.get("state"),
                    "title": data.get("title"),
                    "body": data.get("body"),
                },
            )
        except Exception as exc:
            logger.warning(f"Error querying PR for branch '{branch}' in '{repository}': {exc}")
            return PullRequestLookupResult(
                state=PullRequestLookupState.UNOBSERVABLE,
                detail=str(exc),
            )

    def create_pull_request(
        self,
        repository: str,
        branch: str,
        base: str,
        title: str,
        body: str,
        head_sha: str,
    ) -> dict[str, Any]:
        """Create a new PR for the branch against base in the given repository."""
        import subprocess

        try:
            cmd = [
                "gh",
                "pr",
                "create",
                "--repo",
                repository,
                "--base",
                base,
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode != 0:
                raise RuntimeError(f"gh pr create failed: {res.stderr or res.stdout}")
            lookup = self.get_pull_request(repository, branch, base)
            if lookup.state == PullRequestLookupState.FOUND_EXACT and lookup.pull_request:
                return lookup.pull_request
            raise RuntimeError(
                f"GitHub created the PR but lookup returned {lookup.state.value}: {lookup.detail or 'no authoritative PR record.'}"
            )
        except Exception as exc:
            logger.warning(f"Error creating PR for branch '{branch}' in '{repository}': {exc}")
            raise

    def push_branch(
        self,
        worktree_path: str,
        remote: str,
        branch: str,
        candidate_sha: str,
    ) -> bool:
        """Push candidate branch to remote."""
        import subprocess

        try:
            from pathlib import Path

            repo = Path(worktree_path).resolve()
            if not (repo / ".git").exists() and not (repo / "HEAD").exists():
                raise RuntimeError(f"Push context is not a Git repository: {repo}")
            verify = subprocess.run(
                ["git", "rev-parse", "--verify", f"{candidate_sha}^{{commit}}"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if verify.returncode != 0 or verify.stdout.strip() != candidate_sha:
                raise RuntimeError(
                    f"Candidate SHA '{candidate_sha}' is not resolvable from repository '{repo}'."
                )
            cmd = ["git", "push", remote, f"{candidate_sha}:refs/heads/{branch}"]
            res = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=30)
            if res.returncode != 0:
                raise RuntimeError(f"git push failed: {res.stderr or res.stdout}")
            return True
        except Exception as exc:
            logger.warning(f"Error pushing branch '{branch}' to '{remote}': {exc}")
            raise

    def get_remote_branch_head(
        self, repository: str, branch: str, remote: str = "origin"
    ) -> str | None:
        """Query a remote branch from the explicitly registered local repository root."""
        import subprocess
        from pathlib import Path

        try:
            repo = Path(repository).resolve()
            if not repo.exists() or not repo.is_dir():
                raise RuntimeError(f"Registered repository path does not exist: {repo}")
            top = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if top.returncode != 0 or Path(top.stdout.strip()).resolve() != repo:
                raise RuntimeError(f"Registered repository path is not a Git root: {repo}")
            cmd = ["git", "ls-remote", "--heads", remote, f"refs/heads/{branch}"]
            res = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=15)
            if res.returncode != 0:
                raise RuntimeError(f"git ls-remote failed: {res.stderr or res.stdout}")
            output = res.stdout.strip()
            if output:
                parts = output.split()
                if parts:
                    return parts[0]
            return None
        except Exception as exc:
            logger.warning(f"Error querying remote branch head '{branch}' in '{remote}': {exc}")
            raise
