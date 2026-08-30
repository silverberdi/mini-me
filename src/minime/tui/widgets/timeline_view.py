"""Chronological transition timeline widget."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import TimelineEventDTO
from minime.tui.models import format_timestamp, sanitize_text


class TimelineWidget(Widget):
    """Widget displaying chronological state transitions and lifecycle events."""

    DEFAULT_CSS = """
    TimelineWidget {
        background: #1e293b;
        border: round #334155;
        padding: 1;
        height: 1fr;
    }

    .timeline-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    """

    events: reactive[list[TimelineEventDTO]] = reactive(list)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("TRANSITION TIMELINE & EVENTS", classes="panel-title")
            with VerticalScroll(classes="timeline-scroll"):
                yield Static("No transition history recorded", id="timeline-content")

    def watch_events(self, val: list[TimelineEventDTO]) -> None:
        content = self.query_one("#timeline-content", Static)
        if not val:
            content.update(Text("No timeline events recorded yet.", style="dim italic"))
            return

        body = Text()
        for idx, evt in enumerate(reversed(val)):  # newest first
            if idx > 0:
                body.append("\n" + "·" * 35 + "\n")

            time_str = format_timestamp(evt.timestamp)
            actor_str = f" [{evt.actor}]" if evt.actor else ""
            body.append(f"• {evt.event_type}{actor_str} ({time_str})\n", style="bold cyan")

            if evt.from_stage and evt.to_stage:
                body.append(f"  Transition: {evt.from_stage} -> {evt.to_stage}\n", style="yellow")

            body.append(f"  {sanitize_text(evt.summary)}\n", style="white")

        content.update(body)
