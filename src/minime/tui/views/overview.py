"""Overview view container for mini me TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget

from minime.services.dashboard_service import DashboardOverviewResponse
from minime.tui.widgets.attention_list import AttentionListWidget
from minime.tui.widgets.completions_list import RecentCompletionsWidget
from minime.tui.widgets.executions_list import ActiveExecutionsWidget
from minime.tui.widgets.health_card import SystemHealthCard


class OverviewView(Widget):
    """Primary operational overview screen."""

    DEFAULT_CSS = """
    OverviewView {
        height: 1fr;
        layout: vertical;
    }
    """

    overview_data: reactive[DashboardOverviewResponse | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with Horizontal(id="overview-container"):
            with Vertical(classes="overview-col-left"):
                yield SystemHealthCard(id="overview-health")
                yield RecentCompletionsWidget(id="overview-completions")

            with Vertical(classes="overview-col-center"):
                yield AttentionListWidget(id="overview-attention")

            with Vertical(classes="overview-col-right"):
                yield ActiveExecutionsWidget(id="overview-executions")

    def watch_overview_data(self, val: DashboardOverviewResponse | None) -> None:
        if val is None:
            return

        health_widget = self.query_one("#overview-health", SystemHealthCard)
        health_widget.status = val.system_status

        completions_widget = self.query_one("#overview-completions", RecentCompletionsWidget)
        completions_widget.completions = val.recent_completions

        attention_widget = self.query_one("#overview-attention", AttentionListWidget)
        attention_widget.items = val.attention_items

        executions_widget = self.query_one("#overview-executions", ActiveExecutionsWidget)
        executions_widget.executions = val.active_executions
