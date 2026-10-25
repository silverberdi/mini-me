"""Request normalization and GitHub provenance reconciliation for F4."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable

from minime.domain.enums import ExternalOutcome

_PROVENANCE_PREFIX = "<!-- minime-request-normalization:"


class RequestNormalizationError(RuntimeError):
    """Normalization could not be proven safe or complete."""


@dataclass(frozen=True)
class NormalizedRequest:
    original_body: str
    normalized_body: str
    already_normalized: bool
    criteria: tuple[str, ...] = ()
    semantic_message: str = ""


def looks_like_complete_gherkin(body: str) -> bool:
    """Apply only a conservative syntax signal; meaning remains agent-owned."""
    if not body or not body.strip():
        return False
    lowered = body.lower()
    return bool(re.search(r"(?m)^\s*feature\s*:", lowered)) and all(
        re.search(pattern, lowered)
        for pattern in (
            r"(?m)^\s*scenario\s*:",
            r"(?m)^\s*given\b",
            r"(?m)^\s*when\b",
            r"(?m)^\s*then\b",
        )
    )


def validate_normalized_body(body: str) -> None:
    if not looks_like_complete_gherkin(body):
        raise RequestNormalizationError("Agent normalization is not complete Gherkin.")


class RequestNormalizationService:
    """Keep semantic drafting with the agent and deterministic GitHub effects here."""

    def __init__(
        self,
        github_adapter: Any,
        semantic_normalizer: Callable[[str, str], str] | None = None,
    ) -> None:
        self.github = github_adapter
        self.semantic_normalizer = semantic_normalizer

    def normalize(self, title: str, body: str) -> NormalizedRequest:
        original = body or ""
        if looks_like_complete_gherkin(original):
            return NormalizedRequest(original, original, True)
        if self.semantic_normalizer is None:
            raise RequestNormalizationError(
                "A thinking-agent normalizer is required for informal Requests."
            )
        normalized = self.semantic_normalizer(title, original)
        if not isinstance(normalized, str):
            raise RequestNormalizationError("Thinking agent returned no normalized body.")
        validate_normalized_body(normalized)
        return NormalizedRequest(original, normalized.strip(), False)

    @staticmethod
    def provenance_key(run_id: str, issue_number: int) -> str:
        return f"{run_id}:{issue_number}"

    @staticmethod
    def provenance_comment(original_body: str, key: str) -> str:
        return (
            "## Original Request (preserved verbatim)\n\n"
            f"{original_body}\n\n"
            f"{_PROVENANCE_PREFIX}{key} -->"
        )

    @staticmethod
    def semantic_comment(message: str, key: str) -> str:
        """Wrap agent-authored Spanish communication with a stable idempotency marker."""
        clean = message.strip()
        if not clean or len(clean) > 2000:
            raise RequestNormalizationError("Semantic normalization comment is empty or too long.")
        return f"{clean}\n\n<!-- minime-request-normalization-semantic:{key} -->"

    def publish(
        self,
        repository: str,
        issue_number: int,
        run_id: str,
        normalized: NormalizedRequest,
    ) -> dict[str, Any]:
        current = self.github.get_issue(repository, issue_number)
        if current.outcome != ExternalOutcome.SUCCESS or not isinstance(current.data, dict):
            raise RequestNormalizationError(
                "Remote Issue could not be observed before normalization."
            )
        remote_body = current.data.get("body") or ""
        if remote_body not in {normalized.original_body, normalized.normalized_body}:
            raise RequestNormalizationError(
                "Remote Issue changed concurrently; candidate preserved."
            )
        key = self.provenance_key(run_id, issue_number)
        comment = self.provenance_comment(normalized.original_body, key)
        comment_result = self.github.comment_issue(
            repository, issue_number, comment, f"normalize:{key}"
        )
        if comment_result.outcome != ExternalOutcome.SUCCESS:
            raise RequestNormalizationError(
                "Original Request provenance was not confirmed remotely."
            )
        if normalized.semantic_message.strip():
            semantic_result = self.github.comment_issue(
                repository,
                issue_number,
                self.semantic_comment(normalized.semantic_message, key),
                f"normalize-semantic:{key}",
            )
            if semantic_result.outcome != ExternalOutcome.SUCCESS:
                raise RequestNormalizationError(
                    "Semantic normalization comment was not confirmed remotely."
                )
        if remote_body != normalized.normalized_body:
            version = (current.observed_evidence or {}).get("etag")
            update_result = self.github.update_issue_body(
                repository,
                issue_number,
                normalized.normalized_body,
                expected_version=version,
            )
            if update_result.outcome != ExternalOutcome.SUCCESS:
                raise RequestNormalizationError(
                    "Normalized Issue body was not confirmed remotely."
                )
        confirmed = self.github.get_issue(repository, issue_number)
        if confirmed.outcome != ExternalOutcome.SUCCESS or not isinstance(confirmed.data, dict):
            raise RequestNormalizationError("Normalized Issue confirmation was unobservable.")
        if confirmed.data.get("body") != normalized.normalized_body:
            raise RequestNormalizationError(
                "Remote Issue body differs from the normalized candidate."
            )
        comments = self.github.list_issue_comments(repository, issue_number)
        if comments.outcome != ExternalOutcome.SUCCESS or not any(
            isinstance(item, dict) and key in str(item.get("body", ""))
            for item in (comments.data or [])
        ):
            raise RequestNormalizationError(
                "Original Request provenance comment was not confirmed."
            )
        semantic_key = f"minime-request-normalization-semantic:{key}"
        if normalized.semantic_message.strip() and not any(
            isinstance(item, dict) and semantic_key in str(item.get("body", ""))
            for item in (comments.data or [])
        ):
            raise RequestNormalizationError(
                "Semantic normalization comment was not confirmed."
            )
        return {
            "issue_number": issue_number,
            "run_id": run_id,
            "normalized": not normalized.already_normalized,
            "original_body_sha256": hashlib.sha256(
                normalized.original_body.encode("utf-8")
            ).hexdigest(),
            "normalized_body_sha256": hashlib.sha256(
                normalized.normalized_body.encode("utf-8")
            ).hexdigest(),
            "provenance_key": key,
            "semantic_message": normalized.semantic_message,
        }
