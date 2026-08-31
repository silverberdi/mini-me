"""Contextual actions bar widget for mini me Run Detail view."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Static

from minime.domain.enums import OperatorActionType
from minime.domain.models import ActionDescriptor


class ActionsBarWidget(Widget):
    """Contextual Action Bar widget displaying available governed actions."""

    DEFAULT_CSS = """
    ActionsBarWidget {
        background: #0f172a;
        border: round #38bdf8;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }

    #actions-title {
        color: #38bdf8;
        text-style: bold;
        margin-bottom: 1;
    }

    #actions-button-row {
        height: auto;
        layout: horizontal;
    }

    .action-btn {
        margin-right: 1;
    }

    #actions-feedback {
        margin-top: 1;
        color: #94a3b8;
    }
    """

    actions: reactive[list[ActionDescriptor]] = reactive(list, layout=True)
    run_id: reactive[str | None] = reactive(None)
    last_feedback: reactive[str | None] = reactive(None)

    class ActionTriggered(Message):
        """Message emitted when an operator triggers an action from the bar."""

        def __init__(self, action: OperatorActionType, descriptor: ActionDescriptor | None = None):
            self.action = action
            self.descriptor = descriptor
            super().__init__()

    class OpenActionMenu(Message):
        """Message emitted when opening the full action command menu."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "⚡ OPERATOR CONTROL PLANE ACTIONS [Press 'a' for Actions Menu]", id="actions-title"
            )
            with Horizontal(id="actions-button-row"):
                yield Button(
                    "📋 Actions Menu [a]",
                    id="btn-open-actions",
                    classes="action-btn",
                    variant="primary",
                )
                yield Button("▶ Continue", id="btn-continue", classes="action-btn", disabled=True)
                yield Button("🔁 Retry", id="btn-retry", classes="action-btn", disabled=True)
                yield Button("👥 Reassign", id="btn-reassign", classes="action-btn", disabled=True)
                yield Button(
                    "✔ Resolve Gate", id="btn-resolve", classes="action-btn", disabled=True
                )
                yield Button(
                    "🛑 Cancel",
                    id="btn-cancel",
                    classes="action-btn",
                    variant="error",
                    disabled=True,
                )
            yield Static("", id="actions-feedback")

    def watch_actions(self, val: list[ActionDescriptor]) -> None:
        action_map = {a.action: a for a in val}

        btn_continue = self.query_one("#btn-continue", Button)
        if OperatorActionType.CONTINUE in action_map:
            btn_continue.disabled = not action_map[OperatorActionType.CONTINUE].enabled
        else:
            btn_continue.disabled = True

        btn_retry = self.query_one("#btn-retry", Button)
        if OperatorActionType.RETRY in action_map:
            btn_retry.disabled = not action_map[OperatorActionType.RETRY].enabled
        else:
            btn_retry.disabled = True

        btn_reassign = self.query_one("#btn-reassign", Button)
        if OperatorActionType.REASSIGN in action_map:
            btn_reassign.disabled = not action_map[OperatorActionType.REASSIGN].enabled
        else:
            btn_reassign.disabled = True

        btn_resolve = self.query_one("#btn-resolve", Button)
        if OperatorActionType.RESOLVE_GATE in action_map:
            btn_resolve.disabled = not action_map[OperatorActionType.RESOLVE_GATE].enabled
        else:
            btn_resolve.disabled = True

        btn_cancel = self.query_one("#btn-cancel", Button)
        if OperatorActionType.CANCEL in action_map:
            btn_cancel.disabled = not action_map[OperatorActionType.CANCEL].enabled
        else:
            btn_cancel.disabled = True

    def watch_last_feedback(self, val: str | None) -> None:
        feedback_widget = self.query_one("#actions-feedback", Static)
        if val:
            feedback_widget.update(Text(f"Latest Result: {val}", style="italic cyan"))
        else:
            feedback_widget.update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action_map = {a.action: a for a in self.actions}

        if event.button.id == "btn-open-actions":
            self.post_message(self.OpenActionMenu())
        elif event.button.id == "btn-continue":
            self.post_message(
                self.ActionTriggered(
                    OperatorActionType.CONTINUE, action_map.get(OperatorActionType.CONTINUE)
                )
            )
        elif event.button.id == "btn-retry":
            self.post_message(
                self.ActionTriggered(
                    OperatorActionType.RETRY, action_map.get(OperatorActionType.RETRY)
                )
            )
        elif event.button.id == "btn-reassign":
            self.post_message(
                self.ActionTriggered(
                    OperatorActionType.REASSIGN, action_map.get(OperatorActionType.REASSIGN)
                )
            )
        elif event.button.id == "btn-resolve":
            self.post_message(
                self.ActionTriggered(
                    OperatorActionType.RESOLVE_GATE, action_map.get(OperatorActionType.RESOLVE_GATE)
                )
            )
        elif event.button.id == "btn-cancel":
            self.post_message(
                self.ActionTriggered(
                    OperatorActionType.CANCEL, action_map.get(OperatorActionType.CANCEL)
                )
            )
