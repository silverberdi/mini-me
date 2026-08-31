"""Headless Textual Pilot integration tests for TUI Queue and Scheduler view."""

from __future__ import annotations

import pytest
from textual.widgets import DataTable, TabbedContent

from minime.domain.enums import QueuePriority, ReadinessState, SchedulerMode
from minime.domain.models import QueueExplainReport, SchedulerStatusView, WorkQueueItem, utc_now
from minime.tui.app import MiniMeTuiApp
from minime.tui.client import TuiQueryClient
from minime.tui.views.queue import QueueView


class MockQueueQueryClient(TuiQueryClient):
    def __init__(self):
        super().__init__()
        self.item1 = WorkQueueItem(
            project_id="mini-me",
            change_name="016-autonomous-queue-work-selection",
            github_issue_number=45,
            priority=QueuePriority.HIGH,
            roadmap_stage=16,
            readiness_state=ReadinessState.READY,
            admission_eligible=True,
            priority_score=5000.0,
        )
        self.status = SchedulerStatusView(
            mode=SchedulerMode.RUN,
            queue_depth=1,
            ready_count=1,
            blocked_count=0,
            active_runs_count=0,
            max_global_jobs=1,
            next_candidate=self.item1,
            recent_decisions=[],
            provider_health={"codex": "AVAILABLE"},
            evaluated_at=utc_now(),
        )
        self.report = QueueExplainReport(
            project_id="mini-me",
            change_name="016-autonomous-queue-work-selection",
            github_issue_number=45,
            readiness_state=ReadinessState.READY,
            admission_eligible=True,
            priority=QueuePriority.HIGH,
            base_score=5000.0,
            aging_bonus=0.0,
            roadmap_precedence_penalty=0.0,
            total_score=5000.0,
            queue_position=1,
            blockers=[],
            refusal_code=None,
            selection_rationale="Ranked #1",
            evaluated_at=utc_now(),
        )

    async def get_overview(self):
        from tests.tui.test_app_views_pilot import create_sample_overview

        return create_sample_overview()

    async def get_change_detail(self, project_id: str, change_name: str):
        return None

    async def get_queue_items(self, project_id=None, ready_only=False):
        return [self.item1]

    async def get_scheduler_status(self, project_id=None):
        return self.status

    async def get_queue_explain(self, project_id, change_name):
        return self.report

    async def trigger_scheduler_tick(self, project_id=None):
        return []


@pytest.mark.asyncio
async def test_tui_queue_view_navigation_and_rendering():
    client = MockQueueQueryClient()
    app = MiniMeTuiApp(query_client=client, refresh_interval=0)

    async with app.run_test() as pilot:
        # Switch to tab 5 (Queue & Scheduler)
        await pilot.press("5")
        tabs = app.query_one("#main-tabs", TabbedContent)
        assert tabs.active == "tab-queue"

        queue_view = app.query_one("#view-queue", QueueView)
        assert queue_view is not None
        assert queue_view.status_view is not None
        assert queue_view.status_view.mode == SchedulerMode.RUN
        assert queue_view.status_view.queue_depth == 1

        # Verify table population
        table = queue_view.query_one("#queue-table", DataTable)
        assert table.row_count == 1

        # Focus table and press enter to select row
        table.focus()
        await pilot.press("enter")
        await pilot.pause()

        # Verify explain panel updated
        assert queue_view.explain_report is not None
        assert queue_view.explain_report.change_name == "016-autonomous-queue-work-selection"
        assert queue_view.explain_report.queue_position == 1
        assert queue_view.explain_report.priority == QueuePriority.HIGH
