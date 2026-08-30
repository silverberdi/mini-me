"""Recent completions widget for TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import RecentCompletionDTO
from minime.tui.models import format_timestamp, get_risk_text, get_status_text, short_sha


class RecentCompletionsWidget(Widget):
    """Widget displaying recently merged or completed changes."""

    DEFAULT_CSS = """
    RecentCompletionsWidget {
        background: #1e293b;
        border: round #22c55e;
        padding: 1;
        height: 1fr;
    }

    .completions-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    """

    completions: reactive[list[RecentCompletionDTO]] = reactive(list)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("RECENT COMPLETIONS", classes="panel-title")
            with VerticalScroll(classes="completions-scroll"):
                yield Static("No recent completions", id="completions-content")

    def watch_completions(self, val: list[RecentCompletionDTO]) -> None:
        content = self.query_one("#completions-content", Static)
        if not val:
            content.update(Text("No completed runs recorded yet.", style="dim italic"))
            return

        body = Text()
        for idx, comp in enumerate(val):
            if idx > 0:
                body.append("\n" + "─" * 40 + "\n\n")

            body.append(f"✓ {comp.project_id} / {comp.change_name}\n", style="bold green")

            body.append(
                f"  Gen: {comp.generation}  Candidate: {short_sha(comp.candidate_sha)}  "
                f"Completed: {format_timestamp(comp.completed_at)}\n",
                style="white",
            )

            pr_info = f"PR #{comp.pr_number}" if comp.pr_number else "No PR"
            body.append(f"  {pr_info}  Review: ", style="dim")
            body.append_text(get_status_text(comp.review_verdict or "PASSED"))
            body.append("  Audit: ")
            body.append_text(get_risk_text(comp.audit_risk or "LOW"))
            body.append("\n")

        content.update(body)
