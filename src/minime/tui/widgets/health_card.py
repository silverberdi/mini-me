"""System health and provider status widget."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import SystemStatusDTO
from minime.tui.models import get_status_text


class SystemHealthCard(Widget):
    """Card displaying database, scheduler, GitHub app, and provider health."""

    DEFAULT_CSS = """
    SystemHealthCard {
        background: #1e293b;
        border: round #334155;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }
    """

    status: reactive[SystemStatusDTO | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("SYSTEM HEALTH & CAPACITY", classes="panel-title")
            yield Static("Loading system status...", id="health-content")

    def watch_status(self, val: SystemStatusDTO | None) -> None:
        content = self.query_one("#health-content", Static)
        if val is None:
            content.update(Text("No status available", style="dim"))
            return

        table = Table(box=None, show_header=False, expand=True, padding=(0, 1))
        table.add_column("Key", style="bold cyan", width=18)
        table.add_column("Value", style="white")

        # Database
        db_badge = get_status_text("HEALTHY" if val.database_healthy else "FAILED")
        table.add_row(
            "Database Engine",
            Text.assemble(db_badge, f"  {val.database_engine} ({val.database_message})"),
        )

        # Scheduler
        sched_badge = get_status_text("RUN" if val.scheduler_mode == "RUN" else "WAIT")
        table.add_row(
            "Scheduler Mode", Text.assemble(sched_badge, f"  Queue Depth: {val.queue_depth}")
        )

        # GitHub App
        gh_badge = get_status_text(val.github_app_health)
        table.add_row("GitHub Runtime", gh_badge)

        # Providers
        if val.providers:
            table.add_row("", "")
            table.add_row("Providers", "")
            for p in val.providers:
                p_badge = get_status_text(p.status)
                msg = f" — {p.message}" if p.message else ""
                table.add_row(f"  • {p.provider_id}", Text.assemble(p_badge, msg))
        else:
            table.add_row("Providers", Text("No active providers", style="dim"))

        content.update(table)
