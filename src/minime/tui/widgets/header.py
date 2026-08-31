"""Header widget and system status bar for mini me TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import SystemStatusDTO


class HeaderWidget(Widget):
    """Top-level system status and shortcuts header."""

    DEFAULT_CSS = """
    HeaderWidget {
        height: 3;
        dock: top;
        background: #1e293b;
        color: #f8fafc;
        border-bottom: solid #334155;
        padding: 0 1;
        layout: horizontal;
        align-vertical: middle;
    }
    """

    system_status: reactive[SystemStatusDTO | None] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Static("mini me operator console", id="header-title")
        yield Static("", id="header-meta")
        yield Static(
            "[1] Overview  [2] Changes  [3] Detail  [4] Preview  [?] Help  [q] Quit",
            id="header-shortcuts",
        )

    def watch_system_status(self, status: SystemStatusDTO | None) -> None:
        meta_widget = self.query_one("#header-meta", Static)
        if status is None:
            meta_widget.update(Text("Connecting...", style="dim"))
            return

        db_text = (
            Text(" PostgreSQL ✓ ", style="bold black on green")
            if status.database_healthy
            else Text(" DB DOWN ✗ ", style="bold white on red")
        )

        sched_style = (
            "bold black on green" if status.scheduler_mode == "RUN" else "bold black on yellow"
        )
        sched_text = Text(f" SCHEDULER: {status.scheduler_mode} ", style=sched_style)

        active_text = Text(f" Active: {status.active_runs_count} ", style="bold cyan")
        attn_style = "bold black on yellow" if status.attention_runs_count > 0 else "dim"
        attn_text = Text(f" Attention: {status.attention_runs_count} ", style=attn_style)

        meta = Text.assemble(
            db_text,
            "  ",
            sched_text,
            "  ",
            active_text,
            "  ",
            attn_text,
        )
        meta_widget.update(meta)
