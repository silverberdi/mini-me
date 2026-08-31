"""Action Selection and Confirmation modal dialogues for mini me TUI."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static

from minime.domain.enums import OperatorActionType
from minime.domain.models import ActionDescriptor


class ActionSelectionModal(ModalScreen[OperatorActionType | None]):
    """Modal screen for discovering and selecting a governed operator action."""

    DEFAULT_CSS = """
    ActionSelectionModal {
        align: center middle;
    }

    #action-dialog {
        width: 85;
        height: auto;
        max-height: 80%;
        background: #0f172a;
        border: thick #38bdf8;
        padding: 1 2;
    }

    #action-dialog-title {
        color: #38bdf8;
        text-style: bold;
        margin-bottom: 1;
        text-align: center;
    }

    #action-table {
        height: auto;
        max-height: 15;
        margin-bottom: 1;
    }

    #action-dialog-buttons {
        height: auto;
        align: right middle;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("enter", "select_current", "Select", show=True),
    ]

    def __init__(self, actions: list[ActionDescriptor], run_id: str, **kwargs):
        super().__init__(**kwargs)
        self.actions = actions
        self.run_id = run_id

    def compose(self) -> ComposeResult:
        with Vertical(id="action-dialog"):
            yield Static(
                f"⚡ OPERATOR ACTIONS — RUN {self.run_id[:16]}...", id="action-dialog-title"
            )
            yield DataTable(id="action-table")
            with Horizontal(id="action-dialog-buttons"):
                yield Button("Cancel [Esc]", id="btn-cancel-modal", variant="default")

    def on_mount(self) -> None:
        table = self.query_one("#action-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Action", "Status", "Risk", "Description / Disabled Reason")

        for idx, a in enumerate(self.actions):
            status_text = (
                Text("ENABLED", style="bold green")
                if a.enabled
                else Text("DISABLED", style="dim red")
            )
            risk_text = Text(
                a.risk_level.value,
                style="bold red"
                if a.risk_level.value == "HIGH"
                else "yellow"
                if a.risk_level.value == "MEDIUM"
                else "dim",
            )
            desc_text = (
                a.description
                if a.enabled
                else (f"DISABLED: {a.disabled_reason}" if a.disabled_reason else a.description)
            )

            table.add_row(
                a.display_name,
                status_text,
                risk_text,
                desc_text,
                key=a.action.value,
            )

        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        action_val = event.row_key.value
        matched = next((a for a in self.actions if a.action.value == action_val), None)
        if matched and matched.enabled:
            self.dismiss(matched.action)
        elif matched and not matched.enabled:
            self.notify(
                f"Action '{matched.display_name}' is currently disabled: {matched.disabled_reason}",
                severity="warning",
            )

    def action_select_current(self) -> None:
        table = self.query_one("#action-table", DataTable)
        if table.cursor_row is not None and table.cursor_row < len(self.actions):
            selected_action = self.actions[table.cursor_row]
            if selected_action.enabled:
                self.dismiss(selected_action.action)
            else:
                self.notify(
                    f"Action '{selected_action.display_name}' is currently disabled: {selected_action.disabled_reason}",
                    severity="warning",
                )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel-modal":
            self.dismiss(None)


class ActionConfirmationModal(ModalScreen[dict[str, Any] | None]):
    """Modal dialogue prompting confirmation for destructive or material actions."""

    DEFAULT_CSS = """
    ActionConfirmationModal {
        align: center middle;
    }

    #confirm-dialog {
        width: 75;
        height: auto;
        background: #1e1b4b;
        border: thick #ef4444;
        padding: 1 2;
    }

    #confirm-title {
        color: #ef4444;
        text-style: bold;
        margin-bottom: 1;
        text-align: center;
    }

    #confirm-prompt {
        color: #f8fafc;
        margin-bottom: 1;
    }

    #param-container {
        height: auto;
        margin-bottom: 1;
    }

    #confirm-buttons {
        height: auto;
        align: right middle;
    }

    .dialog-btn {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, descriptor: ActionDescriptor, run_id: str, **kwargs):
        super().__init__(**kwargs)
        self.descriptor = descriptor
        self.run_id = run_id

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(
                f"⚠ CONFIRM ACTION: {self.descriptor.display_name.upper()}", id="confirm-title"
            )
            prompt = (
                self.descriptor.confirmation_prompt
                or f"Are you sure you want to execute {self.descriptor.display_name} on run {self.run_id}?"
            )
            yield Static(prompt, id="confirm-prompt")

            with Vertical(id="param-container"):
                if self.descriptor.action == OperatorActionType.REASSIGN:
                    yield Label("Target Executor Role (e.g. codex, antigravity):")
                    yield Input(id="input-executor", placeholder="codex / antigravity", value="")
                elif (
                    self.descriptor.action == OperatorActionType.RESOLVE_GATE
                    and "verdict" in self.descriptor.parameters_schema.get("properties", {})
                ):
                    yield Label("Validation Verdict (PASS / FAIL):")
                    yield Input(id="input-verdict", placeholder="PASS", value="PASS")
                    yield Label("Validation Notes:")
                    yield Input(
                        id="input-notes",
                        placeholder="Notes...",
                        value="Verified in operator console",
                    )
                elif self.descriptor.action == OperatorActionType.RESOLVE_GATE:
                    yield Label("Resolution Type (continue_preserved / remediate_preserved):")
                    yield Input(
                        id="input-res-type",
                        placeholder="continue_preserved",
                        value="continue_preserved",
                    )
                    yield Label("Remediation Contract Path (if remediating):")
                    yield Input(id="input-contract", placeholder="contract.json", value="")

            with Horizontal(id="confirm-buttons"):
                yield Button(
                    "Cancel [Esc]", id="btn-cancel", variant="default", classes="dialog-btn"
                )
                yield Button(
                    "✔ Confirm & Execute",
                    id="btn-confirm",
                    variant="error" if self.descriptor.risk_level.value == "HIGH" else "primary",
                    classes="dialog-btn",
                )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-confirm":
            params: dict[str, Any] = {}
            if self.descriptor.action == OperatorActionType.REASSIGN:
                inp = self.query_one("#input-executor", Input)
                if inp.value.strip():
                    params["target_executor"] = inp.value.strip()
            elif (
                self.descriptor.action == OperatorActionType.RESOLVE_GATE
                and "verdict" in self.descriptor.parameters_schema.get("properties", {})
            ):
                v_inp = self.query_one("#input-verdict", Input)
                n_inp = self.query_one("#input-notes", Input)
                params["verdict"] = v_inp.value.strip().upper() or "PASS"
                params["notes"] = n_inp.value.strip() or "Verified in operator console"
            elif self.descriptor.action == OperatorActionType.RESOLVE_GATE:
                res_inp = self.query_one("#input-res-type", Input)
                c_inp = self.query_one("#input-contract", Input)
                params["resolution_type"] = res_inp.value.strip() or "continue_preserved"
                if c_inp.value.strip():
                    params["contract"] = c_inp.value.strip()

            self.dismiss(params)
