"""Deterministic checks summary widget for TUI."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import CheckResultItemDTO
from minime.tui.models import format_duration, get_status_text, sanitize_text


class ChecksSummaryWidget(Widget):
    """Widget displaying deterministic check results for current candidate."""

    DEFAULT_CSS = """
    ChecksSummaryWidget {
        background: #1e293b;
        border: round #334155;
        padding: 1;
        margin-bottom: 1;
        height: auto;
        max-height: 16;
    }
    """

    checks: reactive[list[CheckResultItemDTO]] = reactive(list)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("DETERMINISTIC CHECKS", classes="panel-title")
            yield Static("No checks executed yet", id="checks-content")

    def watch_checks(self, val: list[CheckResultItemDTO]) -> None:
        content = self.query_one("#checks-content", Static)
        if not val:
            content.update(Text("No deterministic checks run yet for this candidate.", style="dim italic"))
            return

        table = Table(box=None, show_header=True, expand=True, padding=(0, 1))
        table.add_column("Check Name", style="bold cyan", width=18)
        table.add_column("Status", width=12)
        table.add_column("Exit", width=6)
        table.add_column("Duration", width=10)
        table.add_column("Diagnostic / Command", style="white")

        for c in val:
            status_badge = get_status_text(c.status)
            exit_code_str = str(c.exit_code) if c.exit_code is not None else "—"
            dur_str = format_duration(c.duration_ms)
            diag_str = sanitize_text(c.diagnostic_snippet or c.command)
            table.add_row(c.check_name, status_badge, exit_code_str, dur_str, diag_str)

        content.update(table)
