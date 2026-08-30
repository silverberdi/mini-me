"""Keyboard shortcuts and help modal for mini me TUI."""

from __future__ import annotations

from rich.table import Table
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class HelpModal(ModalScreen[None]):
    """Modal screen displaying keyboard shortcuts and help guide."""

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
        background: rgba(15, 23, 42, 0.75);
    }

    #help-box {
        background: #1e293b;
        border: thick #38bdf8;
        width: 68;
        height: auto;
        padding: 1 2;
    }

    #help-title {
        text-style: bold;
        color: #38bdf8;
        border-bottom: solid #334155;
        margin-bottom: 1;
    }

    #help-close-btn {
        margin-top: 1;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static("mini me Console — Keyboard Shortcuts", id="help-title")
            table = Table(box=None, show_header=True, expand=True)
            table.add_column("Key", style="bold cyan", width=16)
            table.add_column("Action", style="white")

            table.add_row("1", "Switch to Overview tab")
            table.add_row("2", "Switch to Changes & Runs tab")
            table.add_row("3", "Switch to Run Detail & Pipeline tab")
            table.add_row("4", "Switch to Preview & Validation tab (013)")
            table.add_row("r", "Refresh data immediately from daemon")
            table.add_row("j / Down", "Navigate down in lists and tables")
            table.add_row("k / Up", "Navigate up in lists and tables")
            table.add_row("Enter", "Select highlighted change / drill-down")
            table.add_row("Esc", "Return to Overview / dismiss modal")
            table.add_row("? / F1", "Show this help dialog")
            table.add_row("q / Ctrl+C", "Quit console")

            yield Static(table)
            yield Button("Dismiss (Esc)", id="help-close-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

    def on_key(self, event) -> None:
        if event.key in {"escape", "enter", "q"}:
            self.dismiss()
