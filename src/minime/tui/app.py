"""Main Textual application for mini me operator console."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import TabbedContent, TabPane

from minime.domain.interfaces import PersistenceUnitOfWork
from minime.services.dashboard_service import (
    DashboardChangeDetailResponse,
    DashboardOverviewResponse,
)
from minime.tui.client import TuiQueryClient
from minime.tui.views.changes import ChangesView
from minime.tui.views.detail import RunDetailView
from minime.tui.views.overview import OverviewView
from minime.tui.views.preview import PreviewView
from minime.tui.widgets.header import HeaderWidget
from minime.tui.widgets.help_modal import HelpModal

TCSS_PATH = Path(__file__).parent / "styles.tcss"


class MiniMeTuiApp(App[None]):
    """mini me interactive terminal operator console."""

    TITLE = "mini me console"
    CSS_PATH = TCSS_PATH

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False),
        Binding("r", "refresh_data", "Refresh", show=True),
        Binding("1", "switch_tab('tab-overview')", "Overview", show=False),
        Binding("2", "switch_tab('tab-changes')", "Changes", show=False),
        Binding("3", "switch_tab('tab-detail')", "Detail", show=False),
        Binding("4", "switch_tab('tab-preview')", "Preview", show=False),
        Binding("?", "show_help", "Help", show=True),
        Binding("f1", "show_help", "Help", show=False),
        Binding("escape", "handle_escape", "Back", show=False),
    ]

    def __init__(
        self,
        uow_factory: Callable[[], PersistenceUnitOfWork] | None = None,
        query_client: TuiQueryClient | None = None,
        refresh_interval: float = 3.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        if query_client is not None:
            self.client = query_client
        else:
            self.client = TuiQueryClient(uow_factory=uow_factory)
        self.refresh_interval = refresh_interval
        self.selected_project_id: str | None = None
        self.selected_change_name: str | None = None
        self._refresh_timer = None

    def compose(self) -> ComposeResult:
        yield HeaderWidget(id="app-header")
        with Vertical(id="app-body"):
            with TabbedContent(id="main-tabs", initial="tab-overview"):
                with TabPane("Overview", id="tab-overview"):
                    yield OverviewView(id="view-overview")
                with TabPane("Changes & Runs", id="tab-changes"):
                    yield ChangesView(id="view-changes")
                with TabPane("Run Detail & Pipeline", id="tab-detail"):
                    yield RunDetailView(id="view-detail")
                with TabPane("Preview & Validation (013)", id="tab-preview"):
                    yield PreviewView(id="view-preview")

    def on_resize(self, event) -> None:
        width = event.size.width
        self.remove_class("layout-narrow", "layout-normal", "layout-wide")
        if width < 110:
            self.add_class("layout-narrow")
        elif width <= 170:
            self.add_class("layout-normal")
        else:
            self.add_class("layout-wide")

    async def on_mount(self) -> None:
        # Initial layout classification based on current size
        if self.size.width < 110:
            self.add_class("layout-narrow")
        elif self.size.width <= 170:
            self.add_class("layout-normal")
        else:
            self.add_class("layout-wide")

        # Initial refresh
        await self.action_refresh_data()
        # Set recurring refresh timer
        if self.refresh_interval > 0:
            self._refresh_timer = self.set_interval(self.refresh_interval, self._bg_refresh)


    async def _bg_refresh(self) -> None:
        await self.action_refresh_data()

    async def action_refresh_data(self) -> None:
        """Fetch latest overview and detail data from daemon read model."""
        try:
            overview: DashboardOverviewResponse = await self.client.get_overview()
            self._apply_overview(overview)

            # If a change is selected or active executions exist, pick a default change
            if not self.selected_project_id and overview.active_executions:
                first_exec = overview.active_executions[0]
                self.selected_project_id = first_exec.project_id
                self.selected_change_name = first_exec.change_name
            elif not self.selected_project_id and overview.changes:
                first_c = overview.changes[0]
                self.selected_project_id = first_c.project_id
                self.selected_change_name = first_c.change_name

            if self.selected_project_id and self.selected_change_name:
                detail: DashboardChangeDetailResponse | None = await self.client.get_change_detail(
                    self.selected_project_id, self.selected_change_name
                )
                self._apply_detail(detail)
        except Exception as exc:
            self.notify(f"Data refresh warning: {exc}", severity="warning", timeout=3)

    def _apply_overview(self, overview: DashboardOverviewResponse) -> None:
        header = self.query_one("#app-header", HeaderWidget)
        header.system_status = overview.system_status

        overview_view = self.query_one("#view-overview", OverviewView)
        overview_view.overview_data = overview

        changes_view = self.query_one("#view-changes", ChangesView)
        changes_view.changes = overview.changes

    def _apply_detail(self, detail: DashboardChangeDetailResponse | None) -> None:
        if detail is None:
            return

        detail_view = self.query_one("#view-detail", RunDetailView)
        detail_view.detail_data = detail

        preview_view = self.query_one("#view-preview", PreviewView)
        preview_view.detail_data = detail

    def action_switch_tab(self, tab_id: str) -> None:
        """Switch active tab in TabbedContent."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = tab_id

    def action_show_help(self) -> None:
        """Open the keyboard shortcuts help modal."""
        self.push_screen(HelpModal())

    def action_handle_escape(self) -> None:
        """Handle escape key: switch back to overview tab."""
        self.action_switch_tab("tab-overview")

    async def on_changes_view_change_selected(self, message: ChangesView.ChangeSelected) -> None:
        """Handle selection of a change row from Changes table."""
        self.selected_project_id = message.project_id
        self.selected_change_name = message.change_name
        detail = await self.client.get_change_detail(message.project_id, message.change_name)
        self._apply_detail(detail)
        self.action_switch_tab("tab-detail")

    async def select_change(self, project_id: str, change_name: str) -> None:
        """Programmatically select a change and update detail views."""
        self.selected_project_id = project_id
        self.selected_change_name = change_name
        detail = await self.client.get_change_detail(project_id, change_name)
        self._apply_detail(detail)


def run_tui(refresh_interval: float = 3.0) -> None:
    """Launch the mini me TUI application."""
    app = MiniMeTuiApp(refresh_interval=refresh_interval)
    app.run()
