"""Changes and runs table view container for mini me TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static

from minime.services.dashboard_service import ChangeSummaryDTO
from minime.tui.models import ChangeFilter, format_timestamp, get_status_text, short_sha


class ChangesView(Widget):
    """Interactive table view for discovered and active changes."""

    DEFAULT_CSS = """
    ChangesView {
        height: 1fr;
        layout: vertical;
    }

    #changes-filter-bar {
        height: 3;
        layout: horizontal;
        align-vertical: middle;
        margin-bottom: 1;
    }

    .filter-btn {
        margin-right: 1;
    }
    """

    class ChangeSelected(Message):
        """Event posted when a change row is selected."""

        def __init__(self, project_id: str, change_name: str) -> None:
            super().__init__()
            self.project_id = project_id
            self.change_name = change_name

    changes: reactive[list[ChangeSummaryDTO]] = reactive(list)
    active_filter: reactive[ChangeFilter] = reactive(ChangeFilter.ALL)

    def compose(self) -> ComposeResult:
        with Vertical(id="changes-container"):
            with Horizontal(id="changes-filter-bar"):
                yield Static(Text("Filters: ", style="bold cyan"))
                yield Button("All", id="filter-all", classes="filter-btn", variant="primary")
                yield Button("Active", id="filter-active", classes="filter-btn")
                yield Button("Attention", id="filter-attention", classes="filter-btn")
                yield Button("Ready", id="filter-ready", classes="filter-btn")
                yield Button("Completed", id="filter-completed", classes="filter-btn")

            yield DataTable(id="changes-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one("#changes-table", DataTable)
        table.add_columns(
            "Project",
            "Change Name",
            "Status",
            "Stage",
            "Executor",
            "Gen",
            "Candidate SHA",
            "PR #",
            "Updated",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "filter-all":
            self.active_filter = ChangeFilter.ALL
        elif btn_id == "filter-active":
            self.active_filter = ChangeFilter.ACTIVE
        elif btn_id == "filter-attention":
            self.active_filter = ChangeFilter.ATTENTION
        elif btn_id == "filter-ready":
            self.active_filter = ChangeFilter.READY
        elif btn_id == "filter-completed":
            self.active_filter = ChangeFilter.COMPLETED

        # Reset button variants
        for btn in self.query(Button):
            btn.variant = "default"
        event.button.variant = "primary"
        self._populate_table()

    def watch_changes(self, val: list[ChangeSummaryDTO]) -> None:
        self._populate_table()

    def _matches_filter(self, c: ChangeSummaryDTO) -> bool:
        st = c.status.upper()
        if self.active_filter == ChangeFilter.ALL:
            return True
        elif self.active_filter == ChangeFilter.ACTIVE:
            return st in {"RUNNING", "EXECUTING", "IMPLEMENTING"}
        elif self.active_filter == ChangeFilter.ATTENTION:
            return st in {"NEEDS_HUMAN", "WAITING", "FAILED", "BLOCKED"}
        elif self.active_filter == ChangeFilter.READY:
            return st == "READY"
        elif self.active_filter == ChangeFilter.COMPLETED:
            return st == "COMPLETED"
        return True

    def _populate_table(self) -> None:
        try:
            table = self.query_one("#changes-table", DataTable)
        except Exception:
            return

        table.clear()
        filtered = [c for c in self.changes if self._matches_filter(c)]

        for c in filtered:
            status_badge = get_status_text(c.status)
            stage_badge = (
                get_status_text(c.current_stage) if c.current_stage else Text("—", style="dim")
            )
            executor_str = c.current_executor or "—"
            gen_str = str(c.generation) if c.generation is not None else "—"
            sha_str = short_sha(c.candidate_sha)
            pr_str = f"#{c.github_pr_number}" if c.github_pr_number else "—"
            upd_str = format_timestamp(c.updated_at)

            # Store key as (project_id, change_name)
            row_key = f"{c.project_id}::{c.change_name}"
            table.add_row(
                c.project_id,
                c.change_name,
                status_badge,
                stage_badge,
                executor_str,
                gen_str,
                sha_str,
                pr_str,
                upd_str,
                key=row_key,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            parts = str(event.row_key.value).split("::")
            if len(parts) == 2:
                self.post_message(self.ChangeSelected(parts[0], parts[1]))
