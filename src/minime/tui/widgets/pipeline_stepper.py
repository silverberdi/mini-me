"""Pipeline stage stepper widget for mini me TUI."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import PipelinePhaseDTO
from minime.tui.models import get_phase_text, get_status_text, sanitize_text


class PipelineStepperWidget(Widget):
    """Widget displaying 6-phase pipeline progression and active status."""

    DEFAULT_CSS = """
    PipelineStepperWidget {
        background: #1e293b;
        border: round #334155;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }
    """

    phases: reactive[list[PipelinePhaseDTO]] = reactive(list)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("PIPELINE EXECUTION PROGRESSION", classes="panel-title")
            yield Static("No pipeline data", id="pipeline-content")

    def watch_phases(self, val: list[PipelinePhaseDTO]) -> None:
        content = self.query_one("#pipeline-content", Static)
        if not val:
            content.update(Text("No active pipeline execution.", style="dim italic"))
            return

        table = Table(box=None, show_header=True, expand=True, padding=(0, 1))
        table.add_column("Phase", style="bold", width=22)
        table.add_column("Status", width=16)
        table.add_column("Summary / Diagnostic", style="white")

        for p in val:
            phase_cell = get_phase_text(p.display_name, p.status)
            status_cell = get_status_text(p.status)
            summary_cell = sanitize_text(p.summary)
            table.add_row(phase_cell, status_cell, summary_cell)

        content.update(table)
