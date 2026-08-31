"""Action History audit widget for mini me Run Detail view."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.domain.enums import OperatorActionStatus
from minime.domain.models import OperatorActionRecord


class ActionHistoryWidget(Widget):
    """Widget displaying durable audit history of operator mutations for a run."""

    DEFAULT_CSS = """
    ActionHistoryWidget {
        background: #1e293b;
        border: round #64748b;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }

    #action-history-title {
        color: #38bdf8;
        text-style: bold;
        margin-bottom: 1;
    }
    """

    history: reactive[list[OperatorActionRecord]] = reactive(list, layout=True)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("📜 OPERATOR ACTION AUDIT HISTORY", id="action-history-title")
            yield Static("No operator actions recorded yet.", id="action-history-content")

    def watch_history(self, val: list[OperatorActionRecord]) -> None:
        content = self.query_one("#action-history-content", Static)
        if not val:
            content.update(Text("No operator actions recorded yet.", style="dim italic"))
            return

        table = Table(box=None, expand=True, show_header=True, header_style="bold cyan")
        table.add_column("Time (UTC)", style="dim", width=18)
        table.add_column("Action", style="bold white", width=16)
        table.add_column("Actor", style="yellow", width=12)
        table.add_column("Src", style="dim", width=6)
        table.add_column("Status", width=12)
        table.add_column("Summary / Details", style="white")

        for r in val:
            status_style = (
                "bold green"
                if r.status == OperatorActionStatus.COMPLETED
                else "bold red"
                if r.status in {OperatorActionStatus.REJECTED, OperatorActionStatus.FAILED}
                else "yellow"
            )
            time_str = (
                r.created_at.strftime("%H:%M:%S")
                if hasattr(r.created_at, "strftime")
                else str(r.created_at)[:19]
            )

            table.add_row(
                time_str,
                r.action_type.value if hasattr(r.action_type, "value") else str(r.action_type),
                r.actor_identity,
                r.source_interface,
                Text(
                    r.status.value if hasattr(r.status, "value") else str(r.status),
                    style=status_style,
                ),
                r.summary or (r.error_code.value if r.error_code else "—"),
            )

        content.update(table)
