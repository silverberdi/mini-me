"""Minimal PR preparation service delivering structured PR title and body without auto-closing directives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from minime.logging import get_logger

logger = get_logger("services.pr_preparer")

AUTO_CLOSE_KEYWORDS = re.compile(
    r"\b(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#\d+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PrPreparationInput:
    project_id: str
    repository: str
    pr_type: str  # "implementation" or "documentation"
    issue_number: int
    issue_title: str
    base_branch: str
    candidate_branch: str
    candidate_sha: str
    change_name: str
    change_summary: str
    test_evidence: str
    complexity: str = "moderate"
    semantic_title: str | None = None
    semantic_body: str | None = None


@dataclass(frozen=True)
class PreparedPullRequest:
    title: str
    body: str
    pr_type: str
    candidate_sha: str
    issue_number: int


class PrPreparerService:
    """Service to format and prepare Pull Request title and description conforming to F3 rules."""

    def __init__(
        self,
        semantic_provider: Callable[[PrPreparationInput], tuple[str, str]] | None = None,
    ) -> None:
        self.semantic_provider = semantic_provider

    def prepare_pull_request(self, pr_input: PrPreparationInput) -> PreparedPullRequest:
        """Validate agent-authored content, with F3-compatible fallback for old callers."""
        self._validate_identity(pr_input)
        if self.semantic_provider is not None:
            semantic_title, semantic_body = self.semantic_provider(pr_input)
            title = semantic_title.strip() if isinstance(semantic_title, str) else ""
            body = semantic_body.strip() if isinstance(semantic_body, str) else ""
            if not title or not body:
                raise ValueError("Semantic provider returned incomplete PR content")
        elif pr_input.semantic_title is not None or pr_input.semantic_body is not None:
            if not pr_input.semantic_title or not pr_input.semantic_body:
                raise ValueError("Semantic PR content must contain both title and body")
            title = pr_input.semantic_title.strip()
            body = pr_input.semantic_body.strip()
        elif pr_input.pr_type == "implementation":
            title = f"feat({pr_input.change_name}): {pr_input.issue_title} (Addresses #{pr_input.issue_number})"
            body = (
                f"## Summary of Implementation\n\n"
                f"{pr_input.change_summary.strip()}\n\n"
                f"### Reference\n"
                f"- Addresses #{pr_input.issue_number}\n"
                f"- OpenSpec Change: `{pr_input.change_name}`\n"
                f"- Complexity: `{pr_input.complexity}`\n\n"
                f"### Verification and Test Evidence\n"
                f"```text\n{pr_input.test_evidence.strip()}\n```\n\n"
                f"> [!NOTE]\n"
                f"> This is Phase 1 (Implementation PR). Remote issue #{pr_input.issue_number} will remain open "
                f"until Phase 2 documentation sync and archive completes."
            )
        elif pr_input.pr_type == "documentation":
            title = f"docs({pr_input.change_name}): close and sync OpenSpec specs (Ref #{pr_input.issue_number})"
            body = (
                f"## Documentation Closure and Specification Sync\n\n"
                f"{pr_input.change_summary.strip()}\n\n"
                f"### Reference\n"
                f"- Ref #{pr_input.issue_number}\n"
                f"- OpenSpec Change: `{pr_input.change_name}`\n\n"
                f"> [!NOTE]\n"
                f"> This is Phase 2 (Documentation PR). Merge of this PR signals completion and authorizes mini me "
                f"to close remote issue #{pr_input.issue_number}."
            )
        else:
            raise ValueError(f"Unsupported pr_type '{pr_input.pr_type}'. Must be 'implementation' or 'documentation'.")

        self.validate_no_auto_closing_keywords(title)
        self.validate_no_auto_closing_keywords(body)

        return PreparedPullRequest(
            title=title,
            body=body,
            pr_type=pr_input.pr_type,
            candidate_sha=pr_input.candidate_sha,
            issue_number=pr_input.issue_number,
        )

    @staticmethod
    def _validate_identity(pr_input: PrPreparationInput) -> None:
        if not pr_input.project_id.strip() or not pr_input.repository.strip():
            raise ValueError("PR identity requires project and repository")
        if not pr_input.base_branch.strip() or not pr_input.candidate_branch.strip():
            raise ValueError("PR identity requires base and candidate branches")
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", pr_input.candidate_sha):
            raise ValueError("PR identity requires a verified candidate SHA")
        if pr_input.issue_number < 1 or not pr_input.change_name.strip():
            raise ValueError("PR identity requires a valid Issue and Change")

    @staticmethod
    def validate_no_auto_closing_keywords(content: str) -> None:
        match = AUTO_CLOSE_KEYWORDS.search(content)
        if match:
            raise ValueError(
                f"Security violation: PR content contains prohibited auto-closing directive '{match.group(0)}'. "
                f"Use informative references like 'Addresses #...' or 'Ref #...' instead."
            )
