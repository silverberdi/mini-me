"""Queue and Scheduler observability view container for mini me TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static

from minime.domain.models import QueueExplainReport, SchedulerStatusView, WorkQueueItem


class QueueView(Widget):
    """Interactive table and explainability view for autonomous queue and scheduler decisions."""

    DEFAULT_CSS = """
    QueueView {
        height: 1fr;
        layout: vertical;
    }

    #queue-header-bar {
        height: 3;
        layout: horizontal;
        align-vertical: middle;
        margin-bottom: 1;
    }

    #queue-summary-box {
        height: 3;
        border: solid $accent;
        padding: 0 1;
        margin-bottom: 1;
    }

    #queue-main-split {
        height: 1fr;
        layout: horizontal;
    }

    #queue-table-container {
        width: 65%;
        height: 100%;
    }

    #queue-explain-panel {
        width: 35%;
        height: 100%;
        border-left: solid $surface;
        padding: 1;
        background: $surface-darken-1;
    }

    .filter-btn {
        margin-right: 1;
    }
    """

    class ItemSelected(Message):
        """Event posted when a queue item row is selected."""

        def __init__(self, project_id: str, change_name: str) -> None:
            super().__init__()
            self.project_id = project_id
            self.change_name = change_name

    class TickRequested(Message):
        """Event posted when the operator clicks 'Tick Now'."""

        def __init__(self) -> None:
            super().__init__()

    queue_items: reactive[list[WorkQueueItem]] = reactive(list)
    status_view: reactive[SchedulerStatusView | None] = reactive(None)
    selected_item: reactive[WorkQueueItem | None] = reactive(None)
    explain_report: reactive[QueueExplainReport | None] = reactive(None)
    filter_mode: reactive[str] = reactive("ALL")  # ALL, READY, BLOCKED

    def compose(self) -> ComposeResult:
        with Vertical(id="queue-container"):
            with Horizontal(id="queue-header-bar"):
                yield Static(Text("Queue Filters: ", style="bold cyan"))
                yield Button(
                    "All Items", id="queue-filter-all", classes="filter-btn", variant="primary"
                )
                yield Button("Ready Only", id="queue-filter-ready", classes="filter-btn")
                yield Button("Blocked Only", id="queue-filter-blocked", classes="filter-btn")
                yield Button(
                    "⚡ Tick Now", id="queue-tick-btn", variant="success", classes="filter-btn"
                )

            yield Static("Loading scheduler status...", id="queue-summary-box")

            with Horizontal(id="queue-main-split"):
                with Vertical(id="queue-table-container"):
                    yield DataTable(id="queue-table", cursor_type="row", zebra_stripes=True)
                with Vertical(id="queue-explain-panel"):
                    yield Static(
                        Text(
                            "Select a queue item to inspect score and blockers.", style="italic dim"
                        ),
                        id="queue-explain-content",
                    )

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.add_columns(
            "#",
            "Priority",
            "Change Name",
            "Issue",
            "Stage",
            "DoR",
            "Score",
            "Eligible",
            "Blocked Reason",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "queue-filter-all":
            self.filter_mode = "ALL"
        elif btn_id == "queue-filter-ready":
            self.filter_mode = "READY"
        elif btn_id == "queue-filter-blocked":
            self.filter_mode = "BLOCKED"
        elif btn_id == "queue-tick-btn":
            self.post_message(self.TickRequested())
            return

        for btn in self.query(Button):
            if btn.id != "queue-tick-btn":
                btn.variant = "default"
        if btn_id != "queue-tick-btn":
            event.button.variant = "primary"

        self._populate_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key.value
        for item in self.queue_items:
            if item.change_name == row_key:
                self.selected_item = item
                self.post_message(self.ItemSelected(item.project_id, item.change_name))
                break

    def watch_queue_items(self, val: list[WorkQueueItem]) -> None:
        self._populate_table()

    def watch_status_view(self, val: SchedulerStatusView | None) -> None:
        self._update_summary()

    def watch_explain_report(self, val: QueueExplainReport | None) -> None:
        self._update_explain_panel()

    def _update_summary(self) -> None:
        try:
            summary_box = self.query_one("#queue-summary-box", Static)
        except Exception:
            return

        if not self.status_view:
            summary_box.update(Text("Scheduler status unavailable", style="dim"))
            return

        st = self.status_view
        txt = Text()
        txt.append("Scheduler Mode: ", style="bold")
        mode_style = "bold green" if st.mode.value == "RUN" else "bold yellow"
        txt.append(f"{st.mode.value}  ", style=mode_style)

        txt.append("Queue Depth: ", style="bold")
        txt.append(f"{st.queue_depth} ", style="bold cyan")
        txt.append(f"(Ready: {st.ready_count}, Blocked: {st.blocked_count})  ", style="dim")

        txt.append("Active Runs: ", style="bold")
        txt.append(
            f"{st.active_runs_count}/{st.max_global_jobs}  ",
            style="bold green" if st.active_runs_count > 0 else "dim",
        )

        if st.next_candidate:
            txt.append("Next Candidate: ", style="bold")
            txt.append(f"{st.next_candidate.change_name} ", style="bold magenta")
            txt.append(f"(Score: {st.next_candidate.priority_score:.1f})", style="magenta")
        else:
            txt.append("Next Candidate: None", style="dim")

        summary_box.update(txt)

    def _populate_table(self) -> None:
        try:
            table = self.query_one("#queue-table", DataTable)
        except Exception:
            return

        table.clear()
        filtered = []
        for item in self.queue_items:
            if self.filter_mode == "READY" and not item.admission_eligible:
                continue
            if self.filter_mode == "BLOCKED" and item.admission_eligible:
                continue
            filtered.append(item)

        for idx, item in enumerate(filtered, start=1):
            prio_style = {
                "CRITICAL": "bold red",
                "HIGH": "bold yellow",
                "NORMAL": "white",
                "LOW": "dim",
            }.get(item.priority.value, "white")

            dor_style = "bold green" if item.readiness_state.value == "READY" else "yellow"
            elig_style = "bold green" if item.admission_eligible else "dim red"

            table.add_row(
                str(idx),
                Text(item.priority.value, style=prio_style),
                item.change_name,
                f"#{item.github_issue_number}" if item.github_issue_number else "-",
                str(item.roadmap_stage) if item.roadmap_stage is not None else "-",
                Text(item.readiness_state.value, style=dor_style),
                f"{item.priority_score:.1f}",
                Text("YES" if item.admission_eligible else "NO", style=elig_style),
                item.blocked_reason or "",
                key=item.change_name,
            )

    def _update_explain_panel(self) -> None:
        try:
            panel = self.query_one("#queue-explain-content", Static)
        except Exception:
            return

        if not self.explain_report:
            panel.update(
                Text(
                    "Select a queue item to inspect score breakdown and blockers.",
                    style="italic dim",
                )
            )
            return

        rep = self.explain_report
        txt = Text()
        txt.append(f"Change: {rep.change_name}\n", style="bold cyan")
        txt.append(f"Rank Position: #{rep.queue_position}\n", style="bold")
        txt.append(f"Priority: {rep.priority.value}\n\n", style="bold yellow")

        txt.append("Score Breakdown:\n", style="bold underline")
        txt.append(f"  • Base Priority Score: {rep.base_score:.1f}\n")
        txt.append(f"  • Aging Starvation Bonus: {rep.aging_bonus:.1f}\n")
        txt.append(f"  • Total Score: {rep.total_score:.1f}\n\n", style="bold green")

        txt.append("Admission Eligibility:\n", style="bold underline")
        txt.append(
            f"  • Status: {'ADMITTED' if rep.admission_eligible else 'REFUSED'}\n",
            style="bold green" if rep.admission_eligible else "bold red",
        )
        if rep.refusal_code:
            txt.append(f"  • Refusal Code: {rep.refusal_code.value}\n", style="bold red")

        if rep.blockers:
            txt.append("\nBlockers / Unmet Criteria:\n", style="bold underline yellow")
            for b in rep.blockers:
                txt.append(f"  • {b}\n", style="yellow")

        txt.append("\nRationale:\n", style="bold underline magenta")
        txt.append(f"{rep.selection_rationale}\n", style="magenta")

        panel.update(txt)
