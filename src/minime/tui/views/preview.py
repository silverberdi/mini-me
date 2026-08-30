"""Preview and guided validation view container for mini me TUI (013 capability)."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import DashboardChangeDetailResponse
from minime.tui.widgets.preview_card import PreviewValidationWidget


class PreviewView(Widget):
    """Container preview and guided validation screen exercising 013 capabilities."""

    DEFAULT_CSS = """
    PreviewView {
        height: 1fr;
        layout: vertical;
    }

    #preview-view-header {
        background: #1e293b;
        border: round #38bdf8;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }
    """

    detail_data: reactive[DashboardChangeDetailResponse | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with Vertical(id="preview-view-container"):
            yield Static("No change selected. Select a change from the Changes tab.", id="preview-view-header")
            yield PreviewValidationWidget(id="preview-view-card")

    def watch_detail_data(self, val: DashboardChangeDetailResponse | None) -> None:
        header = self.query_one("#preview-view-header", Static)
        card = self.query_one("#preview-view-card", PreviewValidationWidget)

        if val is None:
            header.update(Text("No change selected. Select a change from the Changes tab.", style="dim italic"))
            card.summary = None
            return

        header_text = Text()
        header_text.append(f"PREVIEW & VALIDATION: {val.project_id} / {val.change_name}\n", style="bold cyan")
        if val.candidate_authority:
            c = val.candidate_authority
            header_text.append(f"Candidate Gen {c.generation} (SHA: {c.candidate_sha_short})", style="white")
            if c.image_digest:
                header_text.append(f" | Image: {c.image_digest[:16]}", style="dim cyan")
        header.update(header_text)

        card.summary = val.preview_validation
