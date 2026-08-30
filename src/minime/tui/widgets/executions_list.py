"""Active executions widget for TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import ActiveExecutionDTO
from minime.tui.models import format_timestamp, get_status_text, sanitize_text, short_sha


class ActiveExecutionsWidget(Widget):
    """Widget displaying currently active jobs and execution progress."""

    DEFAULT_CSS = """
    ActiveExecutionsWidget {
        background: #1e293b;
        border: round #38bdf8;
        padding: 1;
        height: 1fr;
    }

    .exec-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    """

    executions: reactive[list[ActiveExecutionDTO]] = reactive(list)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("ACTIVE EXECUTIONS", classes="panel-title")
            with VerticalScroll(classes="exec-scroll"):
                yield Static("No active executions", id="exec-content")

    def watch_executions(self, val: list[ActiveExecutionDTO]) -> None:
        content = self.query_one("#exec-content", Static)
        if not val:
            content.update(Text("No changes currently running.", style="dim italic"))
            return

        body = Text()
        for idx, exec_item in enumerate(val):
            if idx > 0:
                body.append("\n" + "─" * 40 + "\n\n")

            body.append(f"⚡ {exec_item.project_id} / {exec_item.change_name}\n", style="bold cyan")

            stage_badge = get_status_text(exec_item.stage)
            body.append("  Stage: ")
            body.append_text(stage_badge)
            body.append(f"  Executor: {exec_item.current_executor or '—'}\n", style="white")

            body.append(
                f"  Gen: {exec_item.generation}  Candidate: {short_sha(exec_item.candidate_sha)}  "
                f"Started: {format_timestamp(exec_item.started_at)}\n",
                style="dim",
            )

            if exec_item.latest_progress:
                body.append(f"  Progress: {sanitize_text(exec_item.latest_progress)}\n", style="italic white")

        content.update(body)
