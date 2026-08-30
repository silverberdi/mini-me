"""Run detail and pipeline view container for mini me TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from minime.services.dashboard_service import DashboardChangeDetailResponse
from minime.tui.models import get_status_text, short_sha
from minime.tui.widgets.audit_card import AuditSummaryWidget
from minime.tui.widgets.candidate_lineage import CandidateLineageWidget
from minime.tui.widgets.checks_table import ChecksSummaryWidget
from minime.tui.widgets.pipeline_stepper import PipelineStepperWidget
from minime.tui.widgets.review_card import ReviewSummaryWidget
from minime.tui.widgets.timeline_view import TimelineWidget


class RunDetailView(Widget):
    """Detailed pipeline, candidate lineage, and evidence view for a selected change."""

    DEFAULT_CSS = """
    RunDetailView {
        height: 1fr;
        layout: vertical;
    }

    #detail-header {
        background: #1e293b;
        border: round #38bdf8;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }
    """

    detail_data: reactive[DashboardChangeDetailResponse | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-container"):
            yield Static("No change selected. Select a change from the Changes tab.", id="detail-header")
            with Horizontal(classes="scroll-container"):
                with VerticalScroll(classes="detail-col-main"):
                    yield PipelineStepperWidget(id="detail-stepper")
                    yield ChecksSummaryWidget(id="detail-checks")
                    yield TimelineWidget(id="detail-timeline")

                with VerticalScroll(classes="detail-col-evidence"):
                    yield CandidateLineageWidget(id="detail-candidate")
                    yield ReviewSummaryWidget(id="detail-review")
                    yield AuditSummaryWidget(id="detail-audit")

    def watch_detail_data(self, val: DashboardChangeDetailResponse | None) -> None:
        header = self.query_one("#detail-header", Static)
        if val is None:
            header.update(Text("No change selected. Select a change from the Changes tab.", style="dim italic"))
            return

        # Update metadata header
        body = Text()
        body.append(f"RUN DETAIL: {val.project_id} / {val.change_name}\n", style="bold cyan")

        status_badge = get_status_text(val.status)
        stage_badge = get_status_text(val.current_stage) if val.current_stage else Text("—", style="dim")
        body.append("Status: ")
        body.append_text(status_badge)
        body.append("  Stage: ")
        body.append_text(stage_badge)
        body.append(f"  Executor: {val.current_executor or '—'}\n", style="white")

        if val.stop_outcome or val.human_gate:
            gate_badge = get_status_text(val.stop_outcome or val.human_gate)
            body.append("Human Gate / Blocker: ")
            body.append_text(gate_badge)
            body.append("\n")

        if val.candidate_authority:
            c = val.candidate_authority
            body.append(
                f"Candidate: Gen {c.generation} ({short_sha(c.candidate_sha)}) | Base: {short_sha(c.base_sha)}",
                style="dim",
            )
            if val.github.pr_number:
                body.append(f" | PR #{val.github.pr_number} ({val.github.pr_state or 'open'})", style="cyan")
            body.append("\n")

        header.update(body)

        # Update child widgets
        stepper = self.query_one("#detail-stepper", PipelineStepperWidget)
        stepper.phases = val.pipeline

        checks = self.query_one("#detail-checks", ChecksSummaryWidget)
        checks.checks = val.checks

        timeline = self.query_one("#detail-timeline", TimelineWidget)
        timeline.events = val.timeline

        candidate = self.query_one("#detail-candidate", CandidateLineageWidget)
        candidate.current_candidate = val.candidate_authority
        candidate.history = val.candidate_history

        review = self.query_one("#detail-review", ReviewSummaryWidget)
        review.review = val.review

        audit = self.query_one("#detail-audit", AuditSummaryWidget)
        audit.audit = val.audit
