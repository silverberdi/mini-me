"""GitHub App-authorized work-binding and Git operations."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

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


@dataclass(frozen=True)
class _GitAuthBundle:
    args: tuple[str, ...]
    secrets: tuple[str, ...]


class GitHubAppAuth:
    """Create App JWTs and exchange them for volatile installation tokens."""

    def __init__(
        self,
        app_id: str | int | None = None,
        installation_id: str | int | None = None,
        private_key_path: str | Path | None = None,
        *,
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
        self.client = client or httpx.Client(base_url=api_base_url, timeout=15.0)
        self._now = now
        self._cached: _CachedInstallationToken | None = None

    @property
    def mode(self) -> str:
        return "github_app_installation"

    def _credentials(self) -> tuple[str, str, str]:
        if not self.app_id or not self.installation_id or not self.private_key_path:
            raise GitHubAuthorizationError("GitHub App credentials are not configured.")
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
        self._cached = _CachedInstallationToken(token, expires_at.astimezone(UTC))
        return token


def _safe_error(value: str, secrets: list[str] | None = None) -> str:
    return redact_secrets(value, secrets)


class GitHubAdapter(GitHubAdapterInterface):
    """GitHub REST and Git adapter under the configured App installation."""

    def __init__(self, token: str | None = None, *, auth: GitHubAppAuth | None = None):
        # ``token`` is accepted for old test construction but is never runtime authority.
        self.auth = auth or GitHubAppAuth()

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
            return self.auth.client.request(method, path, headers=self._headers(), **kwargs)
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
                    reason_code=ExternalReasonCode.RATE_LIMITED if response.status_code == 429 else ExternalReasonCode.UNOBSERVABLE,
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
                    reason_code=ExternalReasonCode.RATE_LIMITED if response.status_code == 429 else ExternalReasonCode.UNOBSERVABLE,
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
        self, repository: str, state: str = "open", limit: int = 50
    ) -> ExternalActionResult[list[dict[str, Any]]]:
        """List issues for a repository."""
        try:
            repo = self._repo(repository)
            response = self._request(
                "GET",
                f"/repos/{repo}/issues",
                params={"state": state, "per_page": limit},
            )
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, list):
                    items = [item for item in payload if not item.get("pull_request")]
                    return ExternalActionResult(
                        outcome=ExternalOutcome.SUCCESS,
                        source_adapter="github_rest",
                        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                        retry_safety=RetrySafety.SAFE,
                        data=items,
                    )
            if response.status_code in (401, 403):
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_rest",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    data=[],
                    provider_detail=f"HTTP {response.status_code}",
                )
        except GitHubAuthorizationError as exc:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.SAFE,
                data=[],
                provider_detail=str(exc),
            )
        except Exception as exc:
            logger.debug(f"Failed to list issues via GitHub API: {exc}")

        # Fallback to gh CLI if available
        try:
            repo = self._repo(repository)
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
                    str(limit),
                    "--json",
                    "number,title,body,labels,state",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                items = json.loads(result.stdout)
                if isinstance(items, list):
                    return ExternalActionResult(
                        outcome=ExternalOutcome.SUCCESS,
                        source_adapter="github_cli",
                        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                        retry_safety=RetrySafety.SAFE,
                        data=items,
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

    def list_project_items(
        self, project_number: int = 2, owner: str = "silverberdi", limit: int = 50
    ) -> ExternalActionResult[list[dict[str, Any]]]:
        """List items in a GitHub Project V2."""
        try:
            result = subprocess.run(
                [
                    "gh",
                    "project",
                    "item-list",
                    str(project_number),
                    "--owner",
                    owner,
                    "--limit",
                    str(limit),
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                items = data.get("items", [])
                return ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="github_cli",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.SAFE,
                    data=items if isinstance(items, list) else [],
                )
            stderr = result.stderr.strip()
            if "could not resolve" in stderr.lower() or "not found" in stderr.lower():
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_cli",
                    reason_code=ExternalReasonCode.NOT_FOUND,
                    retry_safety=RetrySafety.SAFE,
                    data=[],
                    provider_detail=stderr,
                )
            if "auth" in stderr.lower() or "unauthorized" in stderr.lower() or "401" in stderr or "403" in stderr:
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_cli",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.SAFE,
                    data=[],
                    provider_detail=stderr,
                )
        except Exception as exc:
            logger.debug(f"Failed to list project items via gh CLI: {exc}")

        return ExternalActionResult(
            outcome=ExternalOutcome.UNKNOWN,
            source_adapter="github_cli",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.SAFE,
            data=[],
            error_message="GitHub project item list unobservable.",
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
            if list_res.outcome == ExternalOutcome.FAILURE and list_res.reason_code == ExternalReasonCode.AUTH_REQUIRED:
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

    def add_issue_to_project(
        self, project_number: int, owner: str, issue_url: str, operation_key: str | None = None
    ) -> ExternalActionResult[str]:
        """Add an issue URL to a GitHub Project V2 and return the project item ID."""
        list_res = self.list_project_items(project_number, owner)
        if list_res.outcome == ExternalOutcome.UNKNOWN:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_cli",
                reason_code=list_res.reason_code or ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                error_message=f"Pre-observation of project items unobservable: {list_res.error_message}",
                operation_key=operation_key,
            )
        if list_res.outcome == ExternalOutcome.AMBIGUOUS:
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="github_cli",
                reason_code=list_res.reason_code or ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.SAFE,
                error_message=f"Pre-observation of project items ambiguous: {list_res.error_message}",
                operation_key=operation_key,
            )
        if list_res.outcome == ExternalOutcome.FAILURE and list_res.reason_code == ExternalReasonCode.AUTH_REQUIRED:
            return ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github_cli",
                reason_code=ExternalReasonCode.AUTH_REQUIRED,
                retry_safety=RetrySafety.SAFE,
                provider_detail=list_res.provider_detail,
                error_message=f"GitHub Project authorization rejected during pre-observation: {list_res.error_message}",
                operation_key=operation_key,
            )
        if list_res.outcome == ExternalOutcome.SUCCESS and list_res.data:
            for item in list_res.data:
                content = item.get("content", {})
                if content.get("url") == issue_url or item.get("url") == issue_url:
                    item_id = item.get("id")
                    if item_id:
                        return ExternalActionResult(
                            outcome=ExternalOutcome.SUCCESS,
                            source_adapter="github_cli",
                            reason_code=ExternalReasonCode.REUSED_EXISTING,
                            retry_safety=RetrySafety.UNSAFE,
                            data=item_id,
                            external_id=item_id,
                            operation_key=operation_key,
                        )

        try:
            result = subprocess.run(
                [
                    "gh",
                    "project",
                    "item-add",
                    str(project_number),
                    "--owner",
                    owner,
                    "--url",
                    issue_url,
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                item_id = data.get("id")
                if item_id:
                    return ExternalActionResult(
                        outcome=ExternalOutcome.SUCCESS,
                        source_adapter="github_cli",
                        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                        retry_safety=RetrySafety.UNSAFE,
                        data=item_id,
                        external_id=item_id,
                        operation_key=operation_key,
                    )
            stderr = result.stderr.strip()
            if "401" in stderr or "403" in stderr or "auth" in stderr.lower() or "unauthorized" in stderr.lower():
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_cli",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.UNSAFE,
                    provider_detail=stderr,
                    error_message=f"GitHub Project authorization rejected: {stderr}",
                    operation_key=operation_key,
                )
        except Exception as exc:
            logger.debug("Failed adding issue to project via gh CLI: %s", exc)

        return ExternalActionResult(
            outcome=ExternalOutcome.AMBIGUOUS,
            source_adapter="github_cli",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.UNKNOWN,
            error_message="Adding issue to project is unobservable.",
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
        self, repository: str, branch: str, base: str, title: str, body: str, head_sha: str
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
                error_message=existing.error_message or "PR lookup unobservable; creation POST blocked.",
            )
        if existing.outcome == ExternalOutcome.AMBIGUOUS:
            return ExternalActionResult(
                outcome=ExternalOutcome.AMBIGUOUS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.CONFLICT,
                retry_safety=RetrySafety.UNKNOWN,
                error_message=existing.error_message or "Ambiguous PR lookup state; creation POST blocked.",
            )
        if existing.outcome != ExternalOutcome.FAILURE or existing.reason_code != ExternalReasonCode.NOT_FOUND:
            return ExternalActionResult(
                outcome=ExternalOutcome.UNKNOWN,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                retry_safety=RetrySafety.UNKNOWN,
                error_message="PR lookup outcome was not authoritative NOT_FOUND; creation POST blocked.",
            )

        try:
            response = self._request(
                "POST",
                f"/repos/{repo}/pulls",
                json={"title": title, "body": body, "head": branch, "base": base},
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
            return _GitAuthBundle((), ())
        if not remote_url.startswith(("http://", "https://")):
            raise GitHubAuthorizationError("GitHub App authorization requires an HTTPS Git remote.")
        token = self._token()
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        basic = f"Basic {encoded}"
        header = f"http.extraHeader=Authorization: {basic}"
        return _GitAuthBundle(
            args=("-c", "credential.helper=", "-c", header),
            secrets=(token, encoded, basic, header),
        )

    @staticmethod
    def _run_git(
        args: list[str], *, cwd: Path, timeout: int, secrets: list[str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        failure: RuntimeError | None = None
        try:
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
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

    def update_project_item_status(
        self, project_number: int, owner: str, item_id: str, status: str = "Done"
    ) -> ExternalActionResult[bool]:
        try:
            res = subprocess.run(
                [
                    "gh",
                    "project",
                    "item-edit",
                    "--id",
                    item_id,
                    "--project-id",
                    str(project_number),
                    "--field-id",
                    "Status",
                    "--text",
                    status,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                items_res = self.list_project_items(project_number, owner)
                if items_res.outcome == ExternalOutcome.SUCCESS and items_res.data:
                    observed = False
                    for itm in items_res.data:
                        itm_id = str(itm.get("id") or "")
                        if itm_id == str(item_id):
                            st = str(itm.get("status") or itm.get("fieldValues", {}).get("Status") or "")
                            if st.lower() == status.lower() or status.lower() in st.lower():
                                observed = True
                                break
                    if observed:
                        logger.info("Project item %s updated to status %s.", item_id, status)
                        return ExternalActionResult(
                            outcome=ExternalOutcome.SUCCESS,
                            source_adapter="github_cli",
                            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                            retry_safety=RetrySafety.UNSAFE,
                            data=True,
                            external_id=item_id,
                        )
                    return ExternalActionResult(
                        outcome=ExternalOutcome.FAILURE,
                        source_adapter="github_cli",
                        reason_code=ExternalReasonCode.CONFLICT,
                        retry_safety=RetrySafety.UNSAFE,
                        data=False,
                        error_message=f"Project item '{item_id}' status postcondition '{status}' not observed after edit.",
                    )
                return ExternalActionResult(
                    outcome=ExternalOutcome.AMBIGUOUS,
                    source_adapter="github_cli",
                    reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                    retry_safety=RetrySafety.UNKNOWN,
                    data=False,
                    error_message="Project item status update postcondition unobservable after edit command.",
                )
            stderr = res.stderr.strip()
            if "401" in stderr or "403" in stderr or "auth" in stderr.lower() or "unauthorized" in stderr.lower():
                return ExternalActionResult(
                    outcome=ExternalOutcome.FAILURE,
                    source_adapter="github_cli",
                    reason_code=ExternalReasonCode.AUTH_REQUIRED,
                    retry_safety=RetrySafety.UNSAFE,
                    data=False,
                    provider_detail=stderr,
                    error_message=f"Project item status edit unauthorized: {stderr}",
                )
        except Exception as exc:
            logger.debug("Update project item status failed: %s", exc)

        return ExternalActionResult(
            outcome=ExternalOutcome.AMBIGUOUS,
            source_adapter="github_cli",
            reason_code=ExternalReasonCode.UNOBSERVABLE,
            retry_safety=RetrySafety.UNKNOWN,
            data=False,
            error_message="Project item status update unobservable.",
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
                if head_res.outcome == ExternalOutcome.FAILURE and head_res.reason_code == ExternalReasonCode.NOT_FOUND:
                    return ExternalActionResult(
                        outcome=ExternalOutcome.SUCCESS,
                        source_adapter="github_rest",
                        reason_code=ExternalReasonCode.ALREADY_ABSENT,
                        retry_safety=RetrySafety.UNSAFE,
                        data=True,
                    )
                if head_res.outcome == ExternalOutcome.FAILURE and head_res.reason_code == ExternalReasonCode.AUTH_REQUIRED:
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
