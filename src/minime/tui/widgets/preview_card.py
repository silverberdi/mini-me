"""Container preview and guided UI validation widget (013 capability projection)."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import PreviewValidationSummaryDTO
from minime.tui.models import format_timestamp, get_status_text, sanitize_text, short_sha


class PreviewValidationWidget(Widget):
    """Widget projecting container preview runtime and candidate validation authority."""

    DEFAULT_CSS = """
    PreviewValidationWidget {
        background: #1e293b;
        border: round #38bdf8;
        padding: 1;
        height: 1fr;
    }

    .preview-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    """

    summary: reactive[PreviewValidationSummaryDTO | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("CONTAINER PREVIEW & GUIDED UI VALIDATION (013)", classes="panel-title")
            with VerticalScroll(classes="preview-scroll"):
                yield Static("No preview session active", id="preview-content")

    def watch_summary(self, val: PreviewValidationSummaryDTO | None) -> None:
        content = self.query_one("#preview-content", Static)
        if val is None or (not val.is_preview_required and not val.preview_session):
            content.update(Text("UI preview not required for this change.", style="dim italic"))
            return

        body = Text()

        # Preview Session
        sess = val.preview_session
        if sess:
            status_badge = get_status_text(sess.status)
            body.append("Preview Status: ")
            body.append_text(status_badge)
            body.append(f"  Container: {sess.container_name or '—'}\n", style="white")

            if sess.preview_url:
                body.append(f"Endpoint URL: {sess.preview_url}\n", style="bold cyan")
            elif sess.allocated_port:
                body.append(f"Allocated Port: {sess.allocated_port}\n", style="cyan")

            body.append(
                f"Candidate Head: {short_sha(sess.head_sha)}  Base: {short_sha(sess.base_sha)}\n",
                style="white",
            )
            body.append(f"Image Digest: {short_sha(sess.image_digest, 16)}\n", style="dim cyan")

            if sess.failure_reason:
                body.append(
                    f"Failure Reason: {sanitize_text(sess.failure_reason)}\n", style="bold red"
                )
        else:
            body.append("Preview Status: ")
            body.append_text(get_status_text("NOT_STARTED"))
            body.append("\n")

        # Stale Validation Warning (Non-negotiable requirement)
        if val.is_stale:
            body.append("\n" + "!" * 50 + "\n", style="bold yellow")
            body.append("⚠ STALE VALIDATION DETECTED!\n", style="bold white on yellow")
            body.append(
                "Candidate identity has changed since prior validation. A fresh validation run is required.\n",
                style="yellow",
            )
            body.append("!" * 50 + "\n\n", style="bold yellow")
        elif val.is_authorized:
            body.append(
                "\n✓ Candidate validation AUTHORIZED for human merge.\n\n", style="bold green"
            )

        # Latest Validation Run
        if val.latest_validation:
            v = val.latest_validation
            body.append("Latest Validation Run:\n", style="bold white")
            v_badge = get_status_text(v.verdict)
            body.append("  Verdict: ")
            body.append_text(v_badge)
            body.append(
                f"  Operator: {v.operator or 'operator'}  Time: {format_timestamp(v.created_at)}\n"
            )
            if v.notes:
                body.append(f"  Notes: {sanitize_text(v.notes)}\n", style="italic white")

        # Guided Validation Scenarios
        if val.scenarios:
            body.append(
                f"\nGuided Validation Scenarios ({len(val.scenarios)}):\n", style="bold cyan"
            )
            for idx, sc in enumerate(val.scenarios, 1):
                body.append(f"\n  Scenario {idx}: {sc.title}\n", style="bold white")
                if sc.description:
                    body.append(f"    Description: {sc.description}\n", style="dim")
                if sc.ordered_steps:
                    body.append("    Steps:\n", style="dim cyan")
                    for s_idx, step in enumerate(sc.ordered_steps, 1):
                        body.append(f"      {s_idx}. {step}\n", style="white")
                if sc.expected_result:
                    body.append(f"    Expected Outcome: {sc.expected_result}\n", style="green")
        else:
            body.append("\nNo guided validation scenarios defined.", style="dim")

        content.update(body)
