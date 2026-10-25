"""Minimal PR preparation service delivering structured PR title and body without auto-closing directives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class PreparedPullRequest:
    title: str
    body: str
    pr_type: str
    candidate_sha: str
    issue_number: int


class PrPreparerService:
    """Service to format and prepare Pull Request title and description conforming to F3 rules."""

    def prepare_pull_request(self, pr_input: PrPreparationInput) -> PreparedPullRequest:
        """Generate structured PR content ensuring strict omission of auto-closing keywords."""
        if pr_input.pr_type == "implementation":
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
    def validate_no_auto_closing_keywords(content: str) -> None:
        match = AUTO_CLOSE_KEYWORDS.search(content)
        if match:
            raise ValueError(
                f"Security violation: PR content contains prohibited auto-closing directive '{match.group(0)}'. "
                f"Use informative references like 'Addresses #...' or 'Ref #...' instead."
            )
