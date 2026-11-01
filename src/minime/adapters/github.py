"""GitHub App-authorized work-binding and Git operations."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse

import httpx
import jwt

from minime.domain.enums import (
    EventType,
    ExternalOutcome,
    ExternalReasonCode,
    PullRequestLookupState,
    RetrySafety,
)
from minime.domain.interfaces import GitHubAdapterInterface
from minime.domain.models import Event, ExternalActionResult, PullRequestLookupResult, utc_now
from minime.logging import get_logger, redact_secrets
from minime.services.project_service import normalize_repository_identity

logger = get_logger("adapters.github")


class GitHubAuthorizationError(RuntimeError):
    """The configured GitHub App cannot authorize the requested operation."""


class GitHubRemoteError(RuntimeError):
    """GitHub is temporarily unobservable for the requested operation."""


@dataclass
class _CachedInstallationToken:
    value: str
    expires_at: datetime
    permissions: dict[str, str] | None = None


@dataclass(frozen=True)
class _GitAuthBundle:
    args: tuple[str, ...]
    secrets: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)


class GitHubAppAuth:
    """Create App JWTs and exchange them for volatile installation tokens."""

    def __init__(
        self,
        app_id: str | int | None = None,
        installation_id: str | int | None = None,
        private_key_path: str | Path | None = None,
        private_key_material: str | None = None,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        now: Callable[[], float] = time.time,
        api_base_url: str = "https://api.github.com",
    ) -> None:
        self.app_id = str(
            app_id if app_id is not None else os.environ.get("MINIME_GITHUB_APP_ID", "")
        )
        self.installation_id = str(
            installation_id
            if installation_id is not None
            else os.environ.get("MINIME_GITHUB_INSTALLATION_ID", "")
        )
        self.private_key_path = str(
            private_key_path
            if private_key_path is not None
            else os.environ.get("MINIME_GITHUB_PRIVATE_KEY_PATH", "")
        )
        self.private_key_material = private_key_material
        self.client = client or httpx.Client(base_url=api_base_url, timeout=15.0)
        self._now = now
        self._cached: _CachedInstallationToken | None = None
        self._token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not self._token:
            try:
                self._token = (
                    subprocess.check_output(["gh", "auth", "token"], timeout=3).decode().strip()
                )
            except Exception:
                pass

    @property
    def mode(self) -> str:
        return "github_app_installation"

    def _credentials(self) -> tuple[str, str, str]:
        if (
            not self.app_id
            or not self.installation_id
            or not (self.private_key_material or self.private_key_path)
        ):
            raise GitHubAuthorizationError("GitHub App credentials are not configured.")
        if self.private_key_material is not None:
            key = self.private_key_material
        else:
            try:
                key = Path(self.private_key_path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                raise GitHubAuthorizationError("GitHub App private key is inaccessible.") from None
        if not key.strip():
            raise GitHubAuthorizationError("GitHub App private key is empty.")
        return self.app_id, self.installation_id, key

    def create_jwt(self) -> str:
        app_id, _, private_key = self._credentials()
        now = int(self._now())
        try:
            return jwt.encode(
                {"iat": now - 60, "exp": now + 540, "iss": app_id}, private_key, algorithm="RS256"
            )
        except Exception:
            raise GitHubAuthorizationError(
                "GitHub App private key is invalid for RS256 signing."
            ) from None

    def get_installation_token(self) -> str:
        now = datetime.fromtimestamp(self._now(), tz=UTC)
        if self._cached and (self._cached.expires_at - now).total_seconds() >= 60:
            return self._cached.value
        if self._token and not (
            self.app_id
            and self.installation_id
            and (self.private_key_material or self.private_key_path)
        ):
            return self._token
        _, installation_id, _ = self._credentials()
        try:
            response = self.client.post(
                f"/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {self.create_jwt()}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except (httpx.HTTPError, OSError):
            raise GitHubAuthorizationError(
                "GitHub App installation token exchange was unobservable."
            ) from None
        if response.status_code not in (200, 201):
            category = "unauthorized" if response.status_code in (401, 403) else "exchange_failed"
            raise GitHubAuthorizationError(
                f"GitHub App installation authorization failed ({category}, HTTP {response.status_code})."
            )
        try:
            payload = response.json()
            token = payload["token"]
            expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
            if not isinstance(token, str) or not token or expires_at.tzinfo is None:
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            raise GitHubAuthorizationError("GitHub App token response was invalid.") from None
        permissions = payload.get("permissions")
        normalized_permissions = (
            {str(name): str(level).lower() for name, level in permissions.items()}
            if isinstance(permissions, dict)
            else None
        )
        self._cached = _CachedInstallationToken(
            token, expires_at.astimezone(UTC), normalized_permissions
        )
        return token


def _safe_error(value: str, secrets: list[str] | None = None) -> str:
    return redact_secrets(value, secrets)


def _github_permission_satisfies(actual: str | None, required: str) -> bool:
    if required == "read":
        return actual in {"read", "write"}
    if required == "write":
        return actual == "write"
    return actual == required


def _is_valid_git_branch(branch: str) -> bool:
    if not isinstance(branch, str) or not branch or branch.startswith("-"):
        return False
    try:
        result = subprocess.run(
            ["git", "check-ref-format", "--branch", branch],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _is_git_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value))


class GitHubAdapter(GitHubAdapterInterface):
    """GitHub REST and Git adapter under the configured App installation."""

    def __init__(self, token: str | None = None, *, auth: GitHubAppAuth | None = None):
        self.auth = auth or GitHubAppAuth(token=token)

    @classmethod
    def for_project_connection(
        cls, project_id: str, connection: dict[str, Any], credential_store=None
    ) -> "GitHubAdapter":
        """Bind an adapter instance to one project connection and isolated token cache."""
        auth_mode = connection.get("auth_mode")
        if auth_mode == "environment_app":
            return cls()
        if auth_mode != "project_app":
            raise GitHubAuthorizationError(
                "Project GitHub connection has an unsupported auth mode."
            )
        secret_reference = connection.get("secret_reference")
        if not isinstance(secret_reference, str) or credential_store is None:
            raise GitHubAuthorizationError("Project GitHub App credentials are unavailable.")
        try:
            credentials = credential_store.load_github_app(project_id, secret_reference)
        except (OSError, ValueError):
            raise GitHubAuthorizationError(
                "Project GitHub App credentials are unavailable."
            ) from None
        auth = GitHubAppAuth(
            app_id=credentials["app_id"],
            installation_id=credentials["installation_id"],
            private_key_material=credentials["private_key"],
        )
        return cls(auth=auth)

    def _token(self) -> str:
        return self.auth.get_installation_token()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _repo(repository: str) -> str:
        normalized = normalize_repository_identity(repository)
        if not re.fullmatch(r"[^/]+/[^/]+", normalized):
            raise ValueError(f"Invalid GitHub repository identity: {normalized}")
        return normalized

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            headers = self._headers()
            extra_headers = kwargs.pop("headers", None)
            if isinstance(extra_headers, dict):
                headers.update({str(key): str(value) for key, value in extra_headers.items()})
            return self.auth.client.request(method, path, headers=headers, **kwargs)
        except (httpx.HTTPError, OSError):
            raise GitHubRemoteError("GitHub API is unobservable.") from None

    def verify_repository(self, repository: str) -> ExternalActionResult[bool]:
        try:
            repo = self._repo(repository)
            response = self._request("GET", f"/repos/{repo}")
            if response.status_code == 404:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message=f"Repository '{repo}' does not exist or is not accessible.",
                )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub App is unauthorized for the bound repository.",
                )
            if response.status_code >= 500 or response.status_code == 429:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.RATE_LIMITED
                    if response.status_code == 429
                    else ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub repository verification is unobservable.",
                )
            if response.status_code >= 400:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message=f"Repository verification failed (HTTP {response.status_code}).",
                )
            try:
                actual = normalize_repository_identity(response.json()["full_name"])
            except (KeyError, TypeError, ValueError):
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.MALFORMED_RESPONSE,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message="GitHub repository response was invalid.",
                )
            if actual != repo:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Repository mismatch: GitHub returned '{actual}', expected '{repo}'.",
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=True,
            )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.SAFE,
                data=False,
                provider_detail=str(exc),
                error_message=str(exc),
            )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                data=False,
                provider_detail=str(exc),
                error_message=str(exc),
            )

    def get_repository_default_branch(self, repository: str) -> ExternalActionResult[str]:
        """Read the exact repository identity and its provider-declared default branch."""
        try:
            repo = self._repo(repository)
            response = self._request("GET", f"/repos/{repo}")
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    error_message="GitHub App is unauthorized to inspect repository settings.",
                )
            if response.status_code == 404:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    retry_safety=RetrySafety.SAFE,
                    error_message="Configured GitHub repository was not found or is inaccessible.",
                )
            if response.status_code >= 400:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub repository settings are unobservable.",
                )
            data = response.json()
            actual = self._repo(str(data.get("full_name", "")))
            branch = data.get("default_branch")
            valid_branch = isinstance(branch, str) and _is_valid_git_branch(branch)
            if actual != repo or not valid_branch:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.SAFE,
                    error_message="GitHub repository identity or default branch is invalid.",
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=branch,
            )
        except (GitHubAuthorizationError, GitHubRemoteError, ValueError, TypeError):
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                error_message="GitHub repository default branch could not be verified.",
            )

    def _observe_remote_branch_sha(self, repository: str, branch: str) -> ExternalActionResult[str]:
        repo = self._repo(repository)
        if not _is_valid_git_branch(branch):
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.SAFE,
                error_message="Requested GitHub branch name is invalid.",
            )
        path = f"/repos/{repo}/git/ref/heads/{quote(branch, safe='/')}"
        try:
            response = self._request("GET", path)
            if response.status_code == 404:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    retry_safety=RetrySafety.SAFE,
                    error_message="GitHub branch does not exist.",
                )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    error_message="GitHub App is unauthorized to inspect the requested branch.",
                )
            if response.status_code >= 400:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub branch state is unobservable.",
                )
            payload = response.json()
            sha = (payload.get("object") or {}).get("sha")
            expected_ref = f"refs/heads/{branch}"
            if payload.get("ref") != expected_ref or not _is_git_sha(sha):
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                    retry_safety=RetrySafety.SAFE,
                    error_message="GitHub returned incomplete branch identity evidence.",
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=sha,
            )
        except (GitHubAuthorizationError, GitHubRemoteError, ValueError, TypeError):
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                error_message="GitHub branch state is unobservable.",
            )

    def get_repository_branch_head(self, repository: str, branch: str) -> ExternalActionResult[str]:
        """Read an exact remote branch head without requiring a local clone."""
        return self._observe_remote_branch_sha(repository, branch)

    def create_remote_branch(
        self, repository: str, branch: str, base_sha: str
    ) -> ExternalActionResult[str]:
        """Create a branch from a proven commit and reconcile uncertain POST outcomes."""
        repo = self._repo(repository)
        if not _is_valid_git_branch(branch) or not _is_git_sha(base_sha):
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.SAFE,
                error_message="Branch creation requires a valid branch name and observed commit SHA.",
            )
        before = self._observe_remote_branch_sha(repo, branch)
        if before.outcome == ExternalOutcome.SUCCESS:
            if before.data == base_sha:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.REUSED_EXISTING,
                    retry_safety=RetrySafety.SAFE,
                    data=base_sha,
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.SAFE,
                data=before.data,
                error_message="Requested branch already exists at a different commit.",
            )
        if before.reason_code != ExternalReasonCode.NOT_FOUND:
            return before
        try:
            response = self._request(
                "POST",
                f"/repos/{repo}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": base_sha},
            )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.UNSAFE,
                    error_message="GitHub App is unauthorized to create the requested branch.",
                )
            observed = self._observe_remote_branch_sha(repo, branch)
            if observed.outcome == ExternalOutcome.SUCCESS and observed.data == base_sha:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=(
                        ExternalReasonCode.EXECUTION_SUCCESS
                        if response.status_code in (200, 201)
                        else ExternalReasonCode.REUSED_EXISTING
                    ),
                    retry_safety=RetrySafety.UNSAFE,
                    data=base_sha,
                )
            if observed.outcome == ExternalOutcome.SUCCESS:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.UNSAFE,
                    data=observed.data,
                    error_message="Created branch head does not match the requested base commit.",
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                retry_safety=RetrySafety.UNKNOWN,
                error_message="Branch creation outcome is unobservable; retry requires reconciliation.",
            )
        except (GitHubAuthorizationError, GitHubRemoteError, ValueError):
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                error_message="Branch creation outcome is unobservable; retry requires reconciliation.",
            )

    def verify_connection_permissions(
        self, repository: str, responsibility: str
    ) -> ExternalActionResult[dict[str, Any]]:
        """Check the bound repo and App token grants without performing a mutation."""
        required_by_responsibility = {
            "tickets": {"issues": "read"},
            "git_pr": {"contents": "write", "pull_requests": "write"},
        }
        required = required_by_responsibility.get(responsibility)
        if required is None:
            raise ValueError("Unknown GitHub connection responsibility")
        identity = self.verify_repository(repository)
        if identity.outcome != ExternalOutcome.SUCCESS:
            return ExternalActionResult(
                outcome=identity.outcome,
                source_adapter="github_rest",
                reason_code=identity.reason_code,
                retry_safety=identity.retry_safety,
                error_message=identity.error_message,
                provider_detail=identity.provider_detail,
            )
        try:
            self._token()
        except GitHubAuthorizationError:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.SAFE,
                error_message="GitHub App authorization is unavailable.",
            )
        cached = getattr(self.auth, "_cached", None)
        permissions = cached.permissions if cached else None
        if permissions is None:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                retry_safety=RetrySafety.SAFE,
                error_message="GitHub App permission grants were not observable; connection is not verified.",
            )
        missing = [
            name
            for name, required_level in required.items()
            if not _github_permission_satisfies(permissions.get(name), required_level)
        ]
        if missing:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.SAFE,
                error_message=(
                    f"GitHub App lacks required permissions for {responsibility}: "
                    + ", ".join(missing)
                ),
                provider_detail="required_permissions_missing",
            )
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data={
                "repository": self._repo(repository),
                "responsibility": responsibility,
                "permissions": {name: permissions[name] for name in required},
            },
        )

    def validate_issue_binding(
        self, expected_repository: str, issue_number: int, github_repository: str | None = None
    ) -> ExternalActionResult[bool]:
        try:
            repo = self._repo(expected_repository)
            if issue_number <= 0:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Invalid issue number: {issue_number} must be positive.",
                )
            if (
                github_repository is not None
                and normalize_repository_identity(github_repository) != repo
            ):
                actual = normalize_repository_identity(github_repository)
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Repository mismatch: GitHub Issue #{issue_number} belongs to '{actual}', not '{repo}'.",
                )
            response = self._request("GET", f"/repos/{repo}/issues/{issue_number}")
            if response.status_code == 404:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message=f"GitHub Issue #{issue_number} does not exist in repository '{repo}'.",
                )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub App is unauthorized to validate the bound Issue.",
                )
            if response.status_code >= 500 or response.status_code == 429:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.RATE_LIMITED
                    if response.status_code == 429
                    else ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub Issue validation is unobservable.",
                )
            if response.status_code >= 400:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message=f"GitHub Issue validation is unobservable (HTTP {response.status_code}).",
                )
            try:
                payload = response.json()
                actual = self._issue_repository_identity(payload)
            except (KeyError, TypeError, ValueError, AttributeError):
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.MALFORMED_RESPONSE,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"GitHub Issue #{issue_number} response was invalid.",
                )
            if actual != repo:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.SAFE,
                    data=False,
                    error_message=f"Repository mismatch: GitHub Issue #{issue_number} belongs to '{actual}', not '{repo}'.",
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=True,
            )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.SAFE,
                data=False,
                provider_detail=str(exc),
                error_message=str(exc),
            )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                data=False,
                provider_detail=str(exc),
                error_message=str(exc),
            )

    def list_issues(
        self, repository: str, state: str = "open", limit: int | None = None
    ) -> ExternalActionResult[list[dict[str, Any]]]:
        """List issues for a repository with exhaustive pagination support."""
        try:
            repo = self._repo(repository)
            all_items: list[dict[str, Any]] = []
            page = 1
            per_page = 100 if (limit is None or limit > 100) else max(1, limit)
            rest_success = False

            while True:
                response = self._request(
                    "GET",
                    f"/repos/{repo}/issues",
                    params={"state": state, "per_page": per_page, "page": page},
                )
                if response.status_code == 200:
                    payload = response.json()
                    if isinstance(payload, list):
                        rest_success = True
                        items = [item for item in payload if not item.get("pull_request")]
                        all_items.extend(items)
                        if limit is not None and len(all_items) >= limit:
                            all_items = all_items[:limit]
                            break
                        if len(payload) < per_page:
                            break
                        page += 1
                        continue
                    break
                if response.status_code in (401, 403):
                    return ExternalActionResult(
                        outcome=ExternalOutcome.FAILURE,
                        source_adapter="github_rest",
                        reason_code=ExternalReasonCode.AUTH_REQUIRED,
                        retry_safety=RetrySafety.SAFE,
                        data=[],
                        provider_detail=f"HTTP {response.status_code}",
                        error_message="GitHub App is unauthorized to list issues.",
                    )
                break

            if rest_success:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.SAFE,
                    data=all_items,
                )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.SAFE,
                data=[],
                provider_detail=str(exc),
                error_message=str(exc),
            )
        except Exception as exc:
            logger.debug(f"Failed to list issues via GitHub API: {exc}")

        # Fallback to gh CLI if available
        try:
            repo = self._repo(repository)
            cli_limit = str(limit) if limit is not None else "1000"
            result = subprocess.run(
                [
                    "gh",
                    "issue",
                    "list",
                    "--repo",
                    repo,
                    "--state",
                    state,
                    "--limit",
                    cli_limit,
                    "--json",
                    "number,title,body,labels,state,createdAt,updatedAt",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                items = json.loads(result.stdout)
                if isinstance(items, list):
                    normalized_items = []
                    for item in items:
                        normalized = dict(item)
                        if "createdAt" in normalized and "created_at" not in normalized:
                            normalized["created_at"] = normalized["createdAt"]
                        if "updatedAt" in normalized and "updated_at" not in normalized:
                            normalized["updated_at"] = normalized["updatedAt"]
                        normalized_items.append(normalized)
                    if limit is not None:
                        normalized_items = normalized_items[:limit]
                    return ExternalActionResult(
                        outcome=ExternalOutcome.SUCCESS,
                        source_adapter="github_cli",
                        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                        retry_safety=RetrySafety.SAFE,
                        data=normalized_items,
                    )
        except Exception as exc:
            logger.debug(f"Failed to list issues via gh CLI: {exc}")

        return ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.SAFE,
            data=[],
            error_message="Failed to list issues from remote GitHub.",
        )

    def create_issue(
        self,
        repository: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
        operation_key: str | None = None,
    ) -> ExternalActionResult[dict[str, Any]]:
        """Create a GitHub Issue idempotently with deterministic operation_key comment marker deduplication."""
        repo = self._repo(repository)
        marker = f"<!-- minime-opkey: {operation_key} -->" if operation_key else None
        formatted_body = f"{body}\n\n{marker}" if marker and marker not in body else body

        # 1. Search for existing issue with exact operation_key comment marker
        if operation_key:
            list_res = self.list_issues(repo, state="all", limit=100)
            if list_res.outcome == ExternalOutcome.UNKNOWN:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=list_res.reason_code or ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    error_message=f"Pre-observation of issues unobservable for operation_key '{operation_key}': {list_res.error_message}",
                    operation_key=operation_key,
                )
            if list_res.outcome == ExternalOutcome.AMBIGUOUS:
                return ExternalActionResult(
                    outcome=ExternalOutcome.AMBIGUOUS,
                    source_adapter="github_rest",
                    reason_code=list_res.reason_code or ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    error_message=f"Pre-observation of issues ambiguous for operation_key '{operation_key}': {list_res.error_message}",
                    operation_key=operation_key,
                )
            if (
                list_res.outcome == ExternalOutcome.FAILURE
                and list_res.reason_code == ExternalReasonCode.AUTH_REQUIRED
            ):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    provider_detail=list_res.provider_detail,
                    error_message=f"GitHub API authorization failed during issue pre-observation: {list_res.error_message}",
                    operation_key=operation_key,
                )
            if list_res.outcome == ExternalOutcome.SUCCESS and list_res.data:
                for issue in list_res.data:
                    issue_body = issue.get("body") or ""
                    if marker and marker in issue_body:
                        num = issue.get("number")
                        html_url = issue.get("html_url")
                        if not num or not html_url:
                            return ExternalActionResult(
                                outcome=ExternalOutcome.AMBIGUOUS,
                                source_adapter="github_rest",
                                reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                                retry_safety=RetrySafety.UNKNOWN,
                                error_message=f"Observed matching issue for operation_key '{operation_key}' missing required identity fields.",
                                operation_key=operation_key,
                            )
                        logger.info(
                            "Reusing existing GitHub Issue #%s for operation_key '%s'",
                            num,
                            operation_key,
                        )
                        issue_dict = {
                            "number": num,
                            "title": issue.get("title"),
                            "body": issue.get("body"),
                            "html_url": html_url,
                            "labels": issue.get("labels", []),
                        }
                        return ExternalActionResult(
                            outcome=ExternalOutcome.SUCCESS,
                            source_adapter="github_rest",
                            reason_code=ExternalReasonCode.REUSED_EXISTING,
                            retry_safety=RetrySafety.UNSAFE,
                            data=issue_dict,
                            external_id=str(num),
                            operation_key=operation_key,
                        )

        # 2. REST API creation
        try:
            payload: dict[str, Any] = {"title": title, "body": formatted_body}
            if labels:
                payload["labels"] = labels
            response = self._request("POST", f"/repos/{repo}/issues", json=payload)
            if response.status_code in (200, 201):
                data = response.json()
                num = data.get("number")
                html_url = data.get("html_url")
                if not num or not html_url:
                    return ExternalActionResult(
                        outcome=ExternalOutcome.AMBIGUOUS,
                        source_adapter="github_rest",
                        reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                        retry_safety=RetrySafety.UNKNOWN,
                        error_message="GitHub Issue response missing required number or html_url.",
                        operation_key=operation_key,
                    )
                issue_dict = {
                    "number": num,
                    "title": data.get("title"),
                    "body": data.get("body"),
                    "html_url": html_url,
                    "labels": data.get("labels", []),
                }
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.UNSAFE,
                    data=issue_dict,
                    external_id=str(num),
                    operation_key=operation_key,
                )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.UNSAFE,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub API authorization failed for issue creation.",
                    operation_key=operation_key,
                )
            if response.status_code in (400, 422):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.UNSAFE,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message=f"GitHub Issue creation payload rejected (HTTP {response.status_code}).",
                    operation_key=operation_key,
                )
            # HTTP 5xx or unobserved response after POST attempt -> AMBIGUOUS (DO NOT execute 2nd mutation fallback)
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                provider_detail=f"HTTP {response.status_code}",
                error_message=f"GitHub Issue creation status unobservable (HTTP {response.status_code}).",
                operation_key=operation_key,
            )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.UNSAFE,
                provider_detail=str(exc),
                error_message=str(exc),
                operation_key=operation_key,
            )
        except Exception as exc:
            logger.debug("Failed creating issue via GitHub API: %s", exc)
            # REST HTTP POST request attempt failed with exception -> AMBIGUOUS (DO NOT execute 2nd mutation fallback)
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                provider_detail=str(exc),
                error_message=f"GitHub Issue creation unobservable after POST attempt: {exc}",
                operation_key=operation_key,
            )

    @staticmethod
    def _issue_repository_identity(payload: dict[str, Any]) -> str:
        """Extract a trustworthy repository identity from standard Issue JSON."""
        repository_url = payload.get("repository_url")
        if isinstance(repository_url, str):
            parsed = urlparse(repository_url)
            if parsed.scheme == "https" and parsed.netloc == "api.github.com":
                match = re.fullmatch(r"/repos/([^/]+)/([^/]+)", parsed.path.rstrip("/"))
                if match:
                    return f"{match.group(1)}/{match.group(2)}"

        nested = payload.get("repository")
        if isinstance(nested, dict) and isinstance(nested.get("full_name"), str):
            identity = normalize_repository_identity(nested["full_name"])
            if re.fullmatch(r"[^/]+/[^/]+", identity):
                return identity
        raise ValueError("GitHub Issue response has no trustworthy repository identity.")

    def record_sync_failure(
        self, project_id: str, change_id: str | None, operation: str, error_message: str
    ) -> Event:
        safe = _safe_error(error_message)
        logger.warning(
            "GitHub sync failure for project '%s' during '%s': %s", project_id, operation, safe
        )
        return Event(
            event_type=EventType.SYNC_FAILED,
            project_id=project_id,
            change_id=change_id,
            operation_id=operation,
            payload={"operation": operation, "error": safe, "reconcilable": True},
            timestamp=utc_now(),
        )

    def record_sync_reconciled(
        self,
        project_id: str,
        change_id: str | None,
        operation: str,
        details: dict[str, Any] | None = None,
    ) -> Event:
        logger.info("GitHub sync reconciled for project '%s' during '%s'", project_id, operation)
        return Event(
            event_type=EventType.SYNC_RECONCILED,
            project_id=project_id,
            change_id=change_id,
            operation_id=operation,
            payload={"operation": operation, "details": details or {}, "reconciled": True},
            timestamp=utc_now(),
        )

    def _get_pull_request_lookup(
        self, repository: str, branch: str, base: str = "main"
    ) -> PullRequestLookupResult:
        repo = self._repo(repository)
        owner = repo.split("/", 1)[0]
        try:
            response = self._request(
                "GET",
                f"/repos/{repo}/pulls",
                params={"head": f"{owner}:{branch}", "base": base, "state": "all", "per_page": 20},
            )
            if response.status_code in (401, 403):
                raise GitHubAuthorizationError(
                    "GitHub App is unauthorized for pull-request lookup."
                )
            if (
                response.status_code == 404
                or response.status_code >= 500
                or response.status_code == 429
            ):
                return PullRequestLookupResult(
                    state=PullRequestLookupState.UNOBSERVABLE,
                    detail="GitHub PR lookup is unobservable.",
                )
            if response.status_code >= 400:
                return PullRequestLookupResult(
                    state=PullRequestLookupState.UNOBSERVABLE,
                    detail=f"GitHub PR lookup failed (HTTP {response.status_code}).",
                )
            records = response.json()
            if not isinstance(records, list):
                return PullRequestLookupResult(
                    state=PullRequestLookupState.AMBIGUOUS,
                    detail="GitHub returned an invalid PR list.",
                )
            if not records:
                return PullRequestLookupResult(state=PullRequestLookupState.NOT_FOUND)
            if len(records) != 1 or not isinstance(records[0], dict):
                return PullRequestLookupResult(
                    state=PullRequestLookupState.AMBIGUOUS,
                    detail=f"Found {len(records)} plausible pull requests.",
                )
            data = records[0]
            head = data.get("head") or {}
            base_data = data.get("base") or {}
            if not all(
                (
                    data.get("number"),
                    data.get("html_url"),
                    head.get("sha"),
                    head.get("ref"),
                    base_data.get("ref"),
                )
            ):
                return PullRequestLookupResult(
                    state=PullRequestLookupState.AMBIGUOUS, detail="GitHub PR record is incomplete."
                )
            if head["ref"] != branch or base_data["ref"] != base:
                return PullRequestLookupResult(
                    state=PullRequestLookupState.AMBIGUOUS,
                    detail="GitHub PR record does not match the requested branch and base.",
                )
            return PullRequestLookupResult(
                state=PullRequestLookupState.FOUND_EXACT,
                pull_request={
                    "repository": repo,
                    "number": data["number"],
                    "url": data["html_url"],
                    "head_sha": head["sha"],
                    "head_branch": head["ref"],
                    "base_branch": base_data["ref"],
                    "state": data.get("state"),
                    "title": data.get("title"),
                    "body": data.get("body"),
                },
            )
        except GitHubAuthorizationError:
            raise
        except (GitHubRemoteError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            return PullRequestLookupResult(
                state=PullRequestLookupState.UNOBSERVABLE, detail=_safe_error(str(exc))
            )

    def get_pull_request(
        self, repository: str, branch: str, base: str = "main"
    ) -> ExternalActionResult[dict[str, Any]]:
        lookup = self._get_pull_request_lookup(repository, branch, base)
        if lookup.state == PullRequestLookupState.FOUND_EXACT and lookup.pull_request:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=lookup.pull_request,
                external_id=str(lookup.pull_request.get("number")),
            )
        if lookup.state == PullRequestLookupState.NOT_FOUND:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.NOT_FOUND,
                retry_safety=RetrySafety.SAFE,
                error_message="Pull request not found.",
            )
        if lookup.state == PullRequestLookupState.UNOBSERVABLE:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                error_message=lookup.detail or "Pull request lookup unobservable.",
            )
        return ExternalActionResult(
            outcome=ExternalOutcome.AMBIGUOUS,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.CONFLICT,
            retry_safety=RetrySafety.UNKNOWN,
            error_message=lookup.detail or "Ambiguous pull request state.",
        )

    def create_pull_request(
        self,
        repository: str,
        branch: str,
        base: str,
        title: str,
        body: str,
        head_sha: str,
        draft: bool = True,
    ) -> ExternalActionResult[dict[str, Any]]:
        repo = self._repo(repository)
        existing = self.get_pull_request(repo, branch, base)
        if existing.outcome == ExternalOutcome.SUCCESS and existing.data:
            if existing.data.get("head_sha") == head_sha:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.REUSED_EXISTING,
                    retry_safety=RetrySafety.UNSAFE,
                    data=existing.data,
                    external_id=str(existing.data.get("number")),
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.UNSAFE,
                data=existing.data,
                error_message=f"Existing PR head '{existing.data.get('head_sha')}' differs from candidate SHA '{head_sha}'.",
            )
        if existing.outcome == ExternalOutcome.UNKNOWN:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                error_message=existing.error_message
                or "PR lookup unobservable; creation POST blocked.",
            )
        if existing.outcome == ExternalOutcome.AMBIGUOUS:
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.UNKNOWN,
                error_message=existing.error_message
                or "Ambiguous PR lookup state; creation POST blocked.",
            )
        if (
            existing.outcome != ExternalOutcome.FAILURE
            or existing.reason_code != ExternalReasonCode.NOT_FOUND
        ):
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                error_message="PR lookup outcome was not authoritative NOT_FOUND; creation POST blocked.",
            )

        try:
            payload: dict[str, Any] = {"title": title, "body": body, "head": branch, "base": base}
            if draft:
                payload["draft"] = True
            response = self._request(
                "POST",
                f"/repos/{repo}/pulls",
                json=payload,
            )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.UNSAFE,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub App is unauthorized for pull-request creation.",
                )
            if response.status_code not in (200, 201):
                try:
                    payload = response.json()
                    detail = payload.get("message") if isinstance(payload, dict) else None
                    errors = payload.get("errors") if isinstance(payload, dict) else None
                    if errors:
                        detail = f"{detail}; errors={errors}"
                except (ValueError, TypeError):
                    detail = response.text[:500]
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.UNSAFE,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message=f"GitHub rejected pull-request creation (HTTP {response.status_code}): {detail or 'no diagnostic body'}",
                )
            if response.status_code in (200, 201):
                data = response.json()
                returned_sha = data["head"]["sha"]
                pr_dict = {
                    "repository": repo,
                    "number": data["number"],
                    "url": data["html_url"],
                    "head_sha": returned_sha,
                    "head_branch": data["head"]["ref"],
                    "base_branch": data["base"]["ref"],
                    "state": data.get("state"),
                    "title": data.get("title"),
                    "body": data.get("body"),
                }
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.UNSAFE,
                    data=pr_dict,
                    external_id=str(data["number"]),
                )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.UNSAFE,
                provider_detail=str(exc),
                error_message=str(exc),
            )
        except Exception as exc:
            logger.debug("Failed creating pull request via GitHub API: %s", exc)

        return ExternalActionResult(
            outcome=ExternalOutcome.AMBIGUOUS,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.TIMEOUT,
            retry_safety=RetrySafety.UNKNOWN,
            error_message="Pull request creation unobservable after POST attempt.",
        )

    @staticmethod
    def _is_local_remote(remote_url: str) -> bool:
        return not (remote_url.startswith(("http://", "https://", "ssh://", "git@")))

    def _git_auth_bundle(self, remote_url: str) -> _GitAuthBundle:
        if self._is_local_remote(remote_url):
            return _GitAuthBundle((), (), {})
        if not remote_url.startswith(("http://", "https://")):
            raise GitHubAuthorizationError("GitHub App authorization requires an HTTPS Git remote.")
        token = self._token()
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        basic = f"Basic {encoded}"
        header = f"http.extraHeader=Authorization: {basic}"
        auth_env = {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "",
            "GIT_CONFIG_KEY_1": "http.extraHeader",
            "GIT_CONFIG_VALUE_1": f"Authorization: {basic}",
        }
        return _GitAuthBundle(
            args=(),
            secrets=(token, encoded, basic, header),
            env=auth_env,
        )

    def git_auth_environment(self, remote_url: str) -> dict[str, str]:
        """Return ephemeral Git config for clone/fetch under this App identity."""
        return dict(self._git_auth_bundle(remote_url).env)

    @staticmethod
    def _run_git(
        args: list[str],
        *,
        cwd: Path,
        timeout: int,
        secrets: list[str] | None = None,
        auth_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        failure: RuntimeError | None = None
        try:
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            if auth_env:
                env.update(auth_env)
            if secrets:
                for variable in (
                    "GIT_TRACE",
                    "GIT_TRACE_PACKET",
                    "GIT_TRACE_CURL",
                    "GIT_CURL_VERBOSE",
                    "GIT_TRANSPORT_TRACE",
                ):
                    env.pop(variable, None)
            return subprocess.run(
                args, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
            )
        except subprocess.TimeoutExpired:
            failure = RuntimeError("Git command timed out.")
        except subprocess.SubprocessError:
            failure = RuntimeError("Git command failed before completion.")
        except OSError:
            failure = RuntimeError("Git command could not be started.")
        except Exception:
            failure = RuntimeError("Git command failed before completion.")
        if failure is not None:
            raise failure

    def push_branch(
        self, worktree_path: str, remote: str, branch: str, candidate_sha: str
    ) -> ExternalActionResult[str]:
        repo = Path(worktree_path).resolve()
        if not (repo / ".git").exists() and not (repo / "HEAD").exists():
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.NOT_FOUND,
                retry_safety=RetrySafety.UNSAFE,
                error_message=f"Push context is not a Git repository: {repo}",
            )
        remote_proc = self._run_git(["git", "remote", "get-url", remote], cwd=repo, timeout=5)
        if remote_proc.returncode != 0:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.NOT_FOUND,
                retry_safety=RetrySafety.UNSAFE,
                error_message="Registered Git remote could not be resolved.",
            )
        remote_url = remote_proc.stdout.strip()
        verify = self._run_git(
            ["git", "rev-parse", "--verify", f"{candidate_sha}^{{commit}}"], cwd=repo, timeout=10
        )
        if verify.returncode != 0 or verify.stdout.strip() != candidate_sha:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.NOT_FOUND,
                retry_safety=RetrySafety.UNSAFE,
                error_message=f"Candidate SHA '{candidate_sha}' is not resolvable from repository '{repo}'.",
            )
        try:
            auth = self._git_auth_bundle(remote_url)
            result = self._run_git(
                ["git", *auth.args, "push", remote, f"{candidate_sha}:refs/heads/{branch}"],
                cwd=repo,
                timeout=30,
                secrets=list(auth.secrets),
                auth_env=auth.env,
            )
            if result.returncode == 0:
                obs_res = self.get_remote_branch_head(worktree_path, branch, remote=remote)
                if obs_res.outcome == ExternalOutcome.SUCCESS and obs_res.data:
                    if obs_res.data == candidate_sha:
                        return ExternalActionResult(
                            outcome=ExternalOutcome.SUCCESS,
                            source_adapter="git_cli",
                            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                            retry_safety=RetrySafety.UNSAFE,
                            data=candidate_sha,
                        )
                    return ExternalActionResult(
                        outcome=ExternalOutcome.FAILURE,
                        source_adapter="git_cli",
                        reason_code=ExternalReasonCode.CONFLICT,
                        retry_safety=RetrySafety.UNSAFE,
                        data=obs_res.data,
                        error_message=f"Pushed branch remote SHA '{obs_res.data}' does not match candidate SHA '{candidate_sha}'.",
                    )
                return ExternalActionResult(
                    outcome=ExternalOutcome.AMBIGUOUS,
                    source_adapter="git_cli",
                    reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                    retry_safety=RetrySafety.UNKNOWN,
                    error_message="Remote branch head postcondition unobservable after git push command.",
                )
            stderr = _safe_error(result.stderr or result.stdout, list(auth.secrets))
            if "401" in stderr or "403" in stderr or "denied" in stderr.lower():
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="git_cli",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.UNSAFE,
                    provider_detail=stderr,
                    error_message=f"git push authorization failed: {stderr}",
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                provider_detail=stderr,
                error_message=f"git push failed: {stderr}",
            )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.UNSAFE,
                provider_detail=str(exc),
                error_message=str(exc),
            )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.TIMEOUT,
                retry_safety=RetrySafety.UNKNOWN,
                provider_detail=str(exc),
                error_message=str(exc),
            )

    def get_remote_branch_head(
        self, repository: str, branch: str, remote: str = "origin"
    ) -> ExternalActionResult[str]:
        repo = Path(repository).resolve()
        if not repo.exists() or not repo.is_dir():
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.NOT_FOUND,
                retry_safety=RetrySafety.SAFE,
                error_message=f"Registered repository path does not exist: {repo}",
            )
        top = self._run_git(["git", "rev-parse", "--show-toplevel"], cwd=repo, timeout=5)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != repo:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.NOT_FOUND,
                retry_safety=RetrySafety.SAFE,
                error_message=f"Registered repository path is not a Git root: {repo}",
            )
        remote_proc = self._run_git(["git", "remote", "get-url", remote], cwd=repo, timeout=5)
        if remote_proc.returncode != 0:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.NOT_FOUND,
                retry_safety=RetrySafety.SAFE,
                error_message="Registered Git remote could not be resolved.",
            )
        remote_url = remote_proc.stdout.strip()
        try:
            auth = self._git_auth_bundle(remote_url)
            result = self._run_git(
                ["git", *auth.args, "ls-remote", "--heads", remote, f"refs/heads/{branch}"],
                cwd=repo,
                timeout=15,
                secrets=list(auth.secrets),
                auth_env=auth.env,
            )
            if result.returncode == 0:
                stdout = result.stdout.strip()
                if stdout:
                    head_sha = stdout.split()[0]
                    return ExternalActionResult(
                        outcome=ExternalOutcome.SUCCESS,
                        source_adapter="git_cli",
                        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                        retry_safety=RetrySafety.SAFE,
                        data=head_sha,
                    )
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="git_cli",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    retry_safety=RetrySafety.SAFE,
                    data=None,
                    error_message=f"Branch '{branch}' is absent on remote '{remote}'.",
                )
            stderr = _safe_error(result.stderr or result.stdout, list(auth.secrets))
            if "401" in stderr or "403" in stderr or "denied" in stderr.lower():
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="git_cli",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    provider_detail=stderr,
                    error_message=f"ls-remote authorization failed: {stderr}",
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                provider_detail=stderr,
                error_message=f"ls-remote failed: {stderr}",
            )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.SAFE,
                provider_detail=str(exc),
                error_message=str(exc),
            )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="git_cli",
                reason_code=ExternalReasonCode.TIMEOUT,
                retry_safety=RetrySafety.SAFE,
                provider_detail=str(exc),
                error_message=str(exc),
            )

    def get_pull_request_details(
        self, repository: str, pr_number: int
    ) -> ExternalActionResult[dict[str, Any]]:
        repo = self._repo(repository)
        try:
            response = self._request("GET", f"/repos/{repo}/pulls/{pr_number}")
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub App is unauthorized for pull-request lookup.",
                )
            if response.status_code == 404:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    retry_safety=RetrySafety.SAFE,
                    error_message=f"Pull request #{pr_number} not found in '{repo}'.",
                )
            if response.status_code >= 400:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message=f"GitHub PR lookup failed (HTTP {response.status_code}).",
                )
            data = response.json()
            head = data.get("head") or {}
            base_data = data.get("base") or {}
            merged_by = data.get("merged_by")
            pr_details = {
                "repository": repo,
                "number": data.get("number"),
                "node_id": data.get("node_id"),
                "url": data.get("html_url"),
                "state": data.get("state"),
                "is_merged": bool(data.get("merged", False)),
                "merged_at": data.get("merged_at"),
                "merged_by": merged_by,
                "merged_by_login": merged_by.get("login") if isinstance(merged_by, dict) else None,
                "merge_commit_sha": data.get("merge_commit_sha"),
                "head_sha": head.get("sha"),
                "head_branch": head.get("ref"),
                "base_sha": base_data.get("sha"),
                "base_branch": base_data.get("ref"),
                "title": data.get("title"),
                "is_draft": bool(data.get("draft", False)),
            }
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=pr_details,
                external_id=str(data.get("number")),
            )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.SAFE,
                provider_detail=str(exc),
                error_message=str(exc),
            )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                provider_detail=str(exc),
                error_message=str(exc),
            )

    def mark_pull_request_ready(
        self, repository: str, pr_number: int, expected_head_sha: str
    ) -> ExternalActionResult[dict[str, Any]]:
        """Convert an exact open draft PR to ready-for-review and verify it remotely."""
        current = self.get_pull_request_details(repository, pr_number)
        if current.outcome is not ExternalOutcome.SUCCESS or not isinstance(current.data, dict):
            return current
        if current.data.get("is_merged") or current.data.get("state") != "open":
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.UNSAFE,
                error_message="Pull request is not open and cannot be made ready.",
            )
        if current.data.get("head_sha") != expected_head_sha:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.UNSAFE,
                error_message="Pull request head SHA differs from the reconciled candidate.",
            )
        if not current.data.get("is_draft"):
            return current
        repo = self._repo(repository)
        try:
            response = self._request(
                "PATCH", f"/repos/{repo}/pulls/{pr_number}", json={"draft": False}
            )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.UNSAFE,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub App is unauthorized to update pull requests.",
                )
            if response.status_code not in (200, 201):
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.UNKNOWN,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub did not confirm pull-request readiness.",
                )
            data = response.json()
            returned_sha = (data.get("head") or {}).get("sha")
            if data.get("draft") is False and returned_sha == expected_head_sha:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.UNSAFE,
                    data={**current.data, "is_draft": False, "head_sha": returned_sha},
                    external_id=str(pr_number),
                )
            node_id = current.data.get("node_id")
            if not node_id:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.UNKNOWN,
                    error_message="GitHub readiness response did not match the candidate and has no PR identity.",
                )
            graphql = self._request(
                "POST",
                "/graphql",
                json={
                    "query": (
                        "mutation($pullRequestId:ID!){"
                        "markPullRequestReadyForReview(input:{pullRequestId:$pullRequestId}){"
                        "pullRequest{isDraft headRefOid}}}"
                    ),
                    "variables": {"pullRequestId": node_id},
                },
            )
            if graphql.status_code not in (200, 201):
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_graphql",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.UNKNOWN,
                    provider_detail=f"HTTP {graphql.status_code}",
                    error_message="GitHub did not confirm pull-request readiness.",
                )
            graph_data = graphql.json()
            if graph_data.get("errors"):
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_graphql",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.UNKNOWN,
                    error_message="GitHub GraphQL did not confirm pull-request readiness.",
                )
            ready = ((graph_data.get("data") or {}).get("markPullRequestReadyForReview") or {}).get(
                "pullRequest"
            ) or {}
            if ready.get("isDraft") is not False or ready.get("headRefOid") != expected_head_sha:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_graphql",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.UNKNOWN,
                    error_message="GitHub GraphQL readiness response did not match the candidate.",
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github_graphql",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.UNSAFE,
                data={**current.data, "is_draft": False, "head_sha": returned_sha},
                external_id=str(pr_number),
            )
        except (GitHubAuthorizationError, GitHubRemoteError, httpx.HTTPError) as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                error_message="GitHub readiness result is unobservable.",
                provider_detail=_safe_error(str(exc)),
            )

    def merge_pull_request(
        self,
        repository: str,
        pr_number: int,
        candidate_sha: str | None = None,
        commit_title: str | None = None,
        commit_message: str | None = None,
        merge_method: str = "merge",
    ) -> ExternalActionResult[dict[str, Any]]:
        """Merge a pull request via GitHub REST API with candidate SHA verification."""
        repo = self._repo(repository)
        payload: dict[str, Any] = {"merge_method": merge_method}
        if candidate_sha:
            payload["sha"] = candidate_sha
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message

        try:
            response = self._request("PUT", f"/repos/{repo}/pulls/{pr_number}/merge", json=payload)
            if response.status_code == 200:
                data = response.json()
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.SAFE,
                    data=data,
                    external_id=str(pr_number),
                )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    provider_detail=f"HTTP {response.status_code}: {response.text}",
                    error_message=f"GitHub App is unauthorized to merge pull request #{pr_number}.",
                )
            if response.status_code == 405:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.POLICY_DENIED,
                    retry_safety=RetrySafety.SAFE,
                    provider_detail=f"HTTP 405: {response.text}",
                    error_message=f"Pull request #{pr_number} cannot be merged (branch protections or merge conflict).",
                )
            if response.status_code == 409:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.SAFE,
                    provider_detail=f"HTTP 409: {response.text}",
                    error_message=f"Pull request #{pr_number} head SHA conflict or modified on remote.",
                )
            if response.status_code == 404:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    retry_safety=RetrySafety.SAFE,
                    error_message=f"Pull request #{pr_number} not found in '{repo}'.",
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                provider_detail=f"HTTP {response.status_code}: {response.text}",
                error_message=f"Merge failed for PR #{pr_number} (HTTP {response.status_code}).",
            )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.SAFE,
                provider_detail=str(exc),
                error_message=str(exc),
            )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                provider_detail=str(exc),
                error_message=str(exc),
            )

    def get_issue(self, repository: str, issue_number: int) -> ExternalActionResult[dict[str, Any]]:
        repo = self._repo(repository)
        try:
            response = self._request("GET", f"/repos/{repo}/issues/{issue_number}")
            if response.status_code == 404:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    retry_safety=RetrySafety.UNSAFE,
                    data={},
                    error_message=f"GitHub Issue #{issue_number} not found in '{repo}'.",
                )
            if response.status_code == 200:
                data = response.json()
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.SAFE,
                    data=data,
                    observed_evidence={
                        "etag": response.headers.get("etag"),
                        "updated_at": data.get("updated_at"),
                        "issue_number": data.get("number"),
                        "repository": data.get("repository_url", "").rsplit("/repos/", 1)[-1]
                        if isinstance(data.get("repository_url"), str)
                        else repo,
                    },
                )
        except Exception as exc:
            logger.debug(f"Failed to get issue #{issue_number}: {exc}")

        return ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.SAFE,
            data={},
            error_message=f"Failed to get issue #{issue_number} from remote GitHub.",
        )

    def list_issue_comments(
        self, repository: str, issue_number: int
    ) -> ExternalActionResult[list[dict[str, Any]]]:
        """Read all comments needed for provenance reconciliation, without posting."""
        repo = self._repo(repository)
        if issue_number < 1:
            raise ValueError("Issue number must be positive")
        comments: list[dict[str, Any]] = []
        for page in range(1, 21):
            try:
                response = self._request(
                    "GET",
                    f"/repos/{repo}/issues/{issue_number}/comments",
                    params={"per_page": 100, "page": page},
                )
            except (GitHubAuthorizationError, GitHubRemoteError) as exc:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.UNKNOWN,
                    error_message=str(exc),
                )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    error_message="GitHub App is unauthorized to inspect Issue comments.",
                )
            if response.status_code != 200:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.UNKNOWN,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="Issue comments are unobservable.",
                )
            try:
                page_items = response.json()
            except ValueError:
                page_items = None
            if not isinstance(page_items, list):
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.MALFORMED_RESPONSE,
                    retry_safety=RetrySafety.UNKNOWN,
                    error_message="Issue comments response was invalid.",
                )
            comments.extend(item for item in page_items if isinstance(item, dict))
            if len(page_items) < 100:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.SAFE,
                    data=comments,
                )
        return ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.UNKNOWN,
            error_message="Issue comment history exceeds safe reconciliation limit.",
        )

    def update_issue_body(
        self,
        repository: str,
        issue_number: int,
        body: str,
        *,
        expected_body: str | None = None,
    ) -> ExternalActionResult[dict[str, Any]]:
        """Publish only after verifying the exact original body.

        GitHub Issues PATCH does not support If-Match; sending it fails with
        HTTP 400. Read again immediately before PATCH and confirm the body
        after writing. This is not an atomic compare-and-swap, so an
        unobservable result always requires read-based reconciliation.
        """
        repo = self._repo(repository)
        if issue_number < 1 or not isinstance(body, str) or not body.strip():
            raise ValueError("Issue body requires a positive number and non-empty text")
        if expected_body is None:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.SAFE,
                error_message="Issue body update requires the observed original body.",
            )

        current = self.get_issue(repository, issue_number)
        if (
            current.outcome is not ExternalOutcome.SUCCESS
            or not isinstance(current.data, dict)
            or current.data.get("number") != issue_number
            or not isinstance(current.data.get("body"), str)
        ):
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                error_message="Issue body cannot be verified before update; PATCH blocked.",
            )

        if current.data["body"] == body:
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=current.data,
                observed_evidence={"already_published": True},
            )
        if current.data["body"] != expected_body:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.SAFE,
                error_message="Issue body changed since it was read; PATCH blocked.",
            )

        try:
            response = self._request(
                "PATCH",
                f"/repos/{repo}/issues/{issue_number}",
                json={"body": body},
            )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.UNSAFE,
                error_message=str(exc),
            )
        except GitHubRemoteError:
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                error_message="Issue body update result is unobservable.",
            )
        if response.status_code in (409, 412):
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.SAFE,
                provider_detail=f"HTTP {response.status_code}",
                error_message="Issue changed concurrently; normalization must reconcile before retrying.",
            )
        if response.status_code in (401, 403):
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.UNSAFE,
                error_message="GitHub App is unauthorized to update Issue body.",
            )
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if (
                isinstance(payload, dict)
                and payload.get("number") == issue_number
                and payload.get("body") == body
            ):
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.UNSAFE,
                    data=payload,
                    observed_evidence={"etag": response.headers.get("etag")},
                )
        return ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.UNKNOWN,
            provider_detail=f"HTTP {response.status_code}",
            error_message="GitHub did not confirm the Issue body update.",
        )

    def comment_issue(
        self, repository: str, issue_number: int, body: str, operation_key: str
    ) -> ExternalActionResult[dict[str, Any]]:
        """Post one operation-keyed Issue comment, reconciling a prior ambiguous result."""
        repo = self._repo(repository)
        if issue_number < 1 or not body.strip():
            raise ValueError("Issue comment requires a positive Issue number and non-empty body")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", operation_key):
            raise ValueError("Issue comment requires a safe operation key")
        marker = f"<!-- minime-operation:{operation_key} -->"

        # GitHub has no idempotency key for Issue comments. A stable body marker
        # lets retries observe a completed POST before attempting another one.
        for page in range(1, 21):
            try:
                response = self._request(
                    "GET",
                    f"/repos/{repo}/issues/{issue_number}/comments",
                    params={"per_page": 100, "page": page},
                )
            except GitHubAuthorizationError as exc:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    error_message=str(exc),
                )
            except GitHubRemoteError:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.UNKNOWN,
                    error_message="Issue comment history is unobservable; POST blocked.",
                )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="GitHub App is unauthorized to inspect Issue comments.",
                )
            if response.status_code != 200:
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.UNKNOWN,
                    provider_detail=f"HTTP {response.status_code}",
                    error_message="Issue comment idempotency could not be verified; POST blocked.",
                )
            try:
                comments = response.json()
            except ValueError:
                comments = None
            if not isinstance(comments, list):
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.MALFORMED_RESPONSE,
                    retry_safety=RetrySafety.UNKNOWN,
                    error_message="Issue comment history response was invalid; POST blocked.",
                )
            existing = next(
                (
                    comment
                    for comment in comments
                    if isinstance(comment, dict)
                    and isinstance(comment.get("body"), str)
                    and marker in comment["body"]
                ),
                None,
            )
            if existing:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.REUSED_EXISTING,
                    retry_safety=RetrySafety.UNSAFE,
                    data=existing,
                    external_id=str(existing.get("id", "")) or None,
                )
            if len(comments) < 100:
                break
        else:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                error_message="Issue comment history exceeds the safe reconciliation limit; POST blocked.",
            )

        try:
            response = self._request(
                "POST",
                f"/repos/{repo}/issues/{issue_number}/comments",
                json={"body": f"{body.rstrip()}\n\n{marker}"},
            )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.UNSAFE,
                error_message=str(exc),
            )
        except GitHubRemoteError:
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                error_message="Issue comment POST result is unobservable; retry will reconcile by operation key.",
            )
        if response.status_code in (200, 201):
            try:
                comment = response.json()
            except ValueError:
                comment = None
            if isinstance(comment, dict) and comment.get("id") is not None:
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.UNSAFE,
                    data=comment,
                    external_id=str(comment["id"]),
                )
        return ExternalActionResult(
            outcome=ExternalOutcome.AMBIGUOUS,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.UNKNOWN,
            provider_detail=f"HTTP {response.status_code}",
            error_message="Issue comment POST result is unobservable; retry will reconcile by operation key.",
        )

    def close_issue(
        self, repository: str, issue_number: int, comment: str | None = None
    ) -> ExternalActionResult[bool]:
        repo = self._repo(repository)
        try:
            response = self._request("GET", f"/repos/{repo}/issues/{issue_number}")
            if response.status_code == 404:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    retry_safety=RetrySafety.UNSAFE,
                    data=False,
                    error_message=f"GitHub Issue #{issue_number} not found in '{repo}'.",
                )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.UNSAFE,
                    data=False,
                    error_message="GitHub App unauthorized to read Issue.",
                )
            if response.status_code == 200:
                data = response.json()
                if data.get("state") == "closed":
                    logger.info("GitHub Issue #%d in '%s' is already closed.", issue_number, repo)
                    return ExternalActionResult(
                        outcome=ExternalOutcome.SUCCESS,
                        source_adapter="github_rest",
                        reason_code=ExternalReasonCode.ALREADY_CLOSED,
                        retry_safety=RetrySafety.UNSAFE,
                        data=True,
                        external_id=str(issue_number),
                    )

            patch_res = self._request(
                "PATCH",
                f"/repos/{repo}/issues/{issue_number}",
                json={"state": "closed", "state_reason": "completed"},
            )
            if patch_res.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.UNSAFE,
                    data=False,
                    provider_detail=f"HTTP {patch_res.status_code}",
                    error_message="GitHub App is unauthorized to close issues.",
                )
            if patch_res.status_code in (200, 204):
                if comment:
                    try:
                        self._request(
                            "POST",
                            f"/repos/{repo}/issues/{issue_number}/comments",
                            json={"body": comment},
                        )
                    except Exception as exc:
                        logger.debug("Failed to post comment on issue #%d: %s", issue_number, exc)
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.UNSAFE,
                    data=True,
                    external_id=str(issue_number),
                )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.UNSAFE,
                data=False,
                provider_detail=str(exc),
                error_message=str(exc),
            )
        except Exception as exc:
            logger.debug("Close issue failed: %s", exc)

        return ExternalActionResult(
            outcome=ExternalOutcome.AMBIGUOUS,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.UNKNOWN,
            data=False,
            error_message="GitHub Issue closure unobservable after request attempt.",
        )

    def delete_remote_branch(
        self, repository: str, branch: str, remote: str = "origin"
    ) -> ExternalActionResult[bool]:
        repo = self._repo(repository)
        try:
            res = self._request("DELETE", f"/repos/{repo}/git/refs/heads/{branch}")
            if res.status_code in (200, 204):
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.UNSAFE,
                    data=True,
                )
            if res.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.UNSAFE,
                    data=False,
                    provider_detail=f"HTTP {res.status_code}",
                    error_message="GitHub App unauthorized to delete remote branch.",
                )
            if res.status_code == 404:
                # Require positive ls-remote confirmation under valid authorization
                head_res = self.get_remote_branch_head(repository, branch, remote)
                if (
                    head_res.outcome == ExternalOutcome.FAILURE
                    and head_res.reason_code == ExternalReasonCode.NOT_FOUND
                ):
                    return ExternalActionResult(
                        outcome=ExternalOutcome.SUCCESS,
                        source_adapter="github_rest",
                        reason_code=ExternalReasonCode.ALREADY_ABSENT,
                        retry_safety=RetrySafety.UNSAFE,
                        data=True,
                    )
                if (
                    head_res.outcome == ExternalOutcome.FAILURE
                    and head_res.reason_code == ExternalReasonCode.AUTH_REQUIRED
                ):
                    return ExternalActionResult(
                        outcome=ExternalOutcome.FAILURE,
                        source_adapter="github_rest",
                        reason_code=ExternalReasonCode.AUTH_REQUIRED,
                        retry_safety=RetrySafety.UNSAFE,
                        data=False,
                        error_message="Authorization failure during branch absence check.",
                    )
                return ExternalActionResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.UNKNOWN,
                    data=False,
                    error_message="Remote branch deletion returned 404 but branch absence could not be authoritatively verified.",
                )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.UNSAFE,
                data=False,
                provider_detail=str(exc),
                error_message=str(exc),
            )
        except Exception as exc:
            logger.debug("Delete remote branch failed: %s", exc)

        return ExternalActionResult(
            outcome=ExternalOutcome.AMBIGUOUS,
            source_adapter="github_rest",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.UNKNOWN,
            data=False,
            error_message="Remote branch deletion unobservable after DELETE attempt.",
        )

    def update_issue_state(
        self,
        repository: str,
        issue_number: int,
        *,
        state: str | None = None,
        labels: list[str] | None = None,
        title: str | None = None,
        body: str | None = None,
        expected_version: str | None = None,
        idempotency_key: str | None = None,
    ) -> ExternalActionResult[dict[str, Any]]:
        repo = self._repo(repository)

        # 1. Re-read before write: verify remote issue state and ETag/version
        try:
            get_resp = self._request("GET", f"/repos/{repo}/issues/{issue_number}")
            if get_resp.status_code != 200:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    retry_safety=RetrySafety.SAFE,
                    error_message=f"Failed to re-read issue #{issue_number} before write: HTTP {get_resp.status_code}",
                    operation_key=idempotency_key,
                )
            current_issue = get_resp.json()
            remote_etag = get_resp.headers.get("ETag") or current_issue.get("updated_at")

            # Remote version/ETag optimistic concurrency check
            if expected_version is not None and expected_version not in (remote_etag, current_issue.get("updated_at")):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.SAFE,
                    error_message=f"Remote version conflict on issue #{issue_number}: expected {expected_version}, found {remote_etag}",
                    operation_key=idempotency_key,
                )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                error_message=f"Re-read error: {exc}",
                operation_key=idempotency_key,
            )

        payload: dict[str, Any] = {}
        if state is not None:
            payload["state"] = state
        if labels is not None:
            payload["labels"] = labels
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body

        req_headers = {}
        # GitHub Issues PATCH does not support If-Match
        pass

        try:
            resp = self._request("PATCH", f"/repos/{repo}/issues/{issue_number}", json=payload, headers=req_headers)
            if resp.status_code == 200:
                data = resp.json()
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.SAFE,
                    data=data,
                    observed_evidence={
                        "remote_etag": resp.headers.get("ETag") or data.get("updated_at"),
                        "status_code": 200,
                    },
                    operation_key=idempotency_key,
                )
            if resp.status_code == 412:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.CONFLICT,
                    retry_safety=RetrySafety.SAFE,
                    error_message=f"Precondition Failed: issue #{issue_number} was mutated concurrently.",
                    operation_key=idempotency_key,
                )
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.SAFE,
                error_message=f"Failed to update issue state: HTTP {resp.status_code} {resp.text}",
                operation_key=idempotency_key,
            )
        except Exception as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                error_message=str(exc),
                operation_key=idempotency_key,
            )

