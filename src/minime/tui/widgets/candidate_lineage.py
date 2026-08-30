"""Candidate lineage and authority hierarchy widget."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import CandidateAuthorityDTO
from minime.tui.models import format_timestamp, short_sha


class CandidateLineageWidget(Widget):
    """Widget displaying authoritative candidate vs superseded historical generations."""

    DEFAULT_CSS = """
    CandidateLineageWidget {
        background: #1e293b;
        border: round #334155;
        padding: 1;
        margin-bottom: 1;
        height: auto;
        max-height: 18;
    }

    .lineage-scroll {
        height: auto;
        max-height: 14;
        overflow-y: auto;
    }
    """

    current_candidate: reactive[CandidateAuthorityDTO | None] = reactive(None)
    history: reactive[list[CandidateAuthorityDTO]] = reactive(list)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("CANDIDATE AUTHORITY & LINEAGE", classes="panel-title")
            with VerticalScroll(classes="lineage-scroll"):
                yield Static("No candidate data", id="lineage-content")

    def _update_view(self) -> None:
        content = self.query_one("#lineage-content", Static)
        if self.current_candidate is None and not self.history:
            content.update(Text("No candidate has been generated yet.", style="dim italic"))
            return

        body = Text()

        # Render current authoritative candidate
        if self.current_candidate:
            c = self.current_candidate
            body.append(f"★ Generation {c.generation} [AUTHORITATIVE CURRENT]\n", style="bold cyan")
            body.append(f"  Head SHA: {c.candidate_sha} ({short_sha(c.candidate_sha)})\n", style="bold green")
            body.append(f"  Base SHA: {c.base_sha} ({short_sha(c.base_sha)})\n", style="white")
            if c.manifest_hash:
                body.append(f"  Manifest Hash: {short_sha(c.manifest_hash, 12)}\n", style="dim")
            if c.image_digest:
                body.append(f"  Image Digest: {short_sha(c.image_digest, 16)}\n", style="cyan")
            if c.changed_files:
                body.append(f"  Changed Files ({len(c.changed_files)}): {', '.join(c.changed_files[:3])}", style="dim")
                if len(c.changed_files) > 3:
                    body.append(f" (+{len(c.changed_files)-3} more)", style="dim")
                body.append("\n")
            body.append(f"  Created: {format_timestamp(c.created_at)}\n", style="dim")

        # Render historical / superseded candidates
        superseded = [h for h in self.history if self.current_candidate is None or h.generation != self.current_candidate.generation]
        if superseded:
            body.append("\n" + "─" * 40 + "\n", style="dim")
            body.append("Historical / Superseded Generations:\n", style="dim bold")
            for h in superseded:
                body.append(
                    f"  • Gen {h.generation}: {short_sha(h.candidate_sha)} (base: {short_sha(h.base_sha)}) "
                    f"— [SUPERSEDED] ({format_timestamp(h.created_at)})\n",
                    style="dim",
                )

        content.update(body)

    def watch_current_candidate(self, val: CandidateAuthorityDTO | None) -> None:
        self._update_view()

    def watch_history(self, val: list[CandidateAuthorityDTO]) -> None:
        self._update_view()
