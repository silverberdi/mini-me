"""Attention queue widget displaying blocker and human gate items."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import AttentionItemDTO
from minime.tui.models import format_timestamp, get_status_text, sanitize_text


class AttentionListWidget(Widget):
    """Widget displaying items requiring human intervention or blocker remediation."""

    DEFAULT_CSS = """
    AttentionListWidget {
        background: #1e293b;
        border: round #f59e0b;
        padding: 1;
        height: 1fr;
    }

    .attention-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    """

    items: reactive[list[AttentionItemDTO]] = reactive(list)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("ATTENTION QUEUE (NEEDS OPERATOR)", classes="panel-title")
            with VerticalScroll(classes="attention-scroll"):
                yield Static("No items requiring attention", id="attention-content")

    def watch_items(self, val: list[AttentionItemDTO]) -> None:
        content = self.query_one("#attention-content", Static)
        if not val:
            content.update(Text("✓ No runs require operator attention. System is clear.", style="green italic"))
            return

        body = Text()
        for idx, item in enumerate(val):
            if idx > 0:
                body.append("\n" + "─" * 45 + "\n\n")

            # Header: Project / Change
            body.append(f"⚠ {item.project_id} / {item.change_name}\n", style="bold yellow")

            # Stage & Stop Outcome
            stage_badge = get_status_text(item.stage)
            outcome_badge = get_status_text(item.stop_outcome or item.human_gate or "ATTENTION")
            body.append("  Stage: ")
            body.append_text(stage_badge)
            body.append("  Gate: ")
            body.append_text(outcome_badge)
            body.append(f"  ({format_timestamp(item.updated_at)})\n")

            # Reason
            body.append("  Reason: ", style="bold white")
            body.append(f"{sanitize_text(item.reason)}\n", style="yellow")

            # Remediation Guidance
            if item.remediation_guidance:
                body.append("  Guidance: ", style="bold cyan")
                body.append(f"{sanitize_text(item.remediation_guidance)}\n", style="white")

            # Actions / Capabilities
            actions: list[str] = []
            if item.can_retry:
                actions.append("[Retry Viable]")
            if item.can_remediate:
                actions.append("[Remediation Viable]")
            if item.can_reassign:
                actions.append("[Reassign Viable]")
            if actions:
                body.append(f"  Actions: {' '.join(actions)}\n", style="dim cyan")

        content.update(body)
