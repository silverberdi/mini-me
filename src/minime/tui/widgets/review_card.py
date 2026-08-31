"""Complementary review summary card widget."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import ReviewSummaryDTO
from minime.tui.models import get_status_text, sanitize_text, short_sha


class ReviewSummaryWidget(Widget):
    """Widget displaying complementary review verdict, findings, and stale warnings."""

    DEFAULT_CSS = """
    ReviewSummaryWidget {
        background: #1e293b;
        border: round #334155;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }
    """

    review: reactive[ReviewSummaryDTO | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("COMPLEMENTARY REVIEW", classes="panel-title")
            yield Static("No review recorded", id="review-content")

    def watch_review(self, val: ReviewSummaryDTO | None) -> None:
        content = self.query_one("#review-content", Static)
        if val is None or val.status == "not_started":
            content.update(
                Text("Review not yet started for current candidate.", style="dim italic")
            )
            return

        body = Text()

        # Reviewer & Verdict
        verdict = val.verdict or val.status.upper()
        verdict_badge = get_status_text(verdict)
        body.append("Verdict: ")
        body.append_text(verdict_badge)
        body.append(f"  Reviewer: {val.reviewer_role or '—'}")
        if val.model:
            body.append(f" ({val.model})")
        body.append("\n")

        # Stale / Mixed authorship warnings
        if val.is_stale_to_current_candidate:
            body.append(
                "⚠ STALE REVIEW: Bound to older candidate generation (", style="bold yellow"
            )
            body.append(f"{short_sha(val.candidate_sha)})\n", style="yellow")
        else:
            body.append(f"Bound to candidate SHA: {short_sha(val.candidate_sha)}\n", style="dim")

        if val.is_mixed_authorship:
            body.append("ℹ Mixed-authorship disclosure recorded.\n", style="cyan")

        # Findings Summary
        if val.material_findings_count > 0:
            body.append(f"Material Findings: {val.material_findings_count}\n", style="bold red")
        else:
            body.append("Material Findings: 0 (Clean)\n", style="green")

        if val.summary:
            body.append(f"\nSummary: {sanitize_text(val.summary)}\n", style="white")

        if val.findings:
            body.append("\nFindings Details:\n", style="bold white")
            for f in val.findings[:3]:
                desc = sanitize_text(f.get("description", str(f)))
                sev = f.get("severity", "finding").upper()
                body.append(f"  • [{sev}] {desc}\n", style="yellow")

        content.update(body)
