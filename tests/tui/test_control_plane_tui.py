"""TUI Pilot tests for Operator Control Plane integration."""

from __future__ import annotations

import pytest
from textual.widgets import Button

from minime.domain.enums import ActionRiskLevel, OperatorActionStatus, OperatorActionType
from minime.domain.models import ActionDescriptor, OperatorActionRecord, OperatorActionResult
from minime.services.dashboard_service import (
    CandidateAuthorityDTO,
    DashboardChangeDetailResponse,
    DashboardOverviewResponse,
    SystemStatusDTO,
)
from minime.tui.app import MiniMeTuiApp
from minime.tui.client import TuiQueryClient
from minime.tui.views.detail import RunDetailView
from minime.tui.widgets.action_bar import ActionsBarWidget
from minime.tui.widgets.action_history import ActionHistoryWidget
from minime.tui.widgets.action_modal import ActionSelectionModal


class MockControlPlaneTuiClient(TuiQueryClient):
    """Mock query client returning control plane fixtures."""

    def __init__(self):
        super().__init__(uow_factory=None)
        self.actions = [
            ActionDescriptor(
                action=OperatorActionType.CONTINUE,
                display_name="Continue / Resume",
                description="Resume execution from persisted checkpoint",
                enabled=True,
                requires_confirmation=False,
                risk_level=ActionRiskLevel.LOW,
            ),
            ActionDescriptor(
                action=OperatorActionType.CANCEL,
                display_name="Cancel Run",
                description="Cancel active execution",
                enabled=True,
                requires_confirmation=True,
                confirmation_prompt="Are you sure you want to cancel?",
                risk_level=ActionRiskLevel.HIGH,
            ),
        ]
        self.history = [
            OperatorActionRecord(
                action_request_id="req-1",
                project_id="mini-me",
                change_name="015-control-plane",
                run_id="run-tui-1",
                action_type=OperatorActionType.CONTINUE,
                actor_identity="tui_operator",
                source_interface="tui",
                status=OperatorActionStatus.COMPLETED,
                summary="Run resumed successfully",
            )
        ]

    async def get_overview(self) -> DashboardOverviewResponse:
        return DashboardOverviewResponse(
            system_status=SystemStatusDTO(
                healthy=True,
                database_engine="PostgreSQL",
                database_healthy=True,
                database_message="Connected",
                scheduler_mode="RUN",
                queue_depth=0,
                github_app_health="HEALTHY",
                active_runs_count=1,
                total_changes_count=1,
                attention_runs_count=0,
                providers=[],
            ),
            attention_items=[],
            active_executions=[],
            recent_completions=[],
            changes=[],
        )

    async def get_change_detail(
        self, project_id: str, change_name: str
    ) -> DashboardChangeDetailResponse | None:
        return DashboardChangeDetailResponse(
            project_id=project_id,
            change_name=change_name,
            title="015 Control Plane Change",
            summary="Operator control plane",
            status="READY",
            current_stage="IMPLEMENTING",
            current_executor="codex",
            current_generation=1,
            is_active=True,
            candidate_authority=CandidateAuthorityDTO(
                generation=1,
                candidate_sha="abc1234567",
                candidate_sha_short="abc1234",
                base_sha="base1234567",
                base_sha_short="base123",
                is_authorized=True,
                requires_remediation=False,
            ),
            pipeline=[],
            checks=[],
            timeline=[],
            candidate_history=[],
        )

    async def get_latest_run_id_for_change(self, project_id: str, change_name: str) -> str | None:
        return "run-tui-1"

    async def get_available_actions(self, run_id: str) -> list[ActionDescriptor]:
        return self.actions

    async def get_action_history(self, run_id: str, limit: int = 50) -> list[OperatorActionRecord]:
        return self.history

    async def execute_action(self, request) -> OperatorActionResult:
        return OperatorActionResult(
            action_request_id=request.action_request_id,
            action_type=request.action_type,
            status=OperatorActionStatus.COMPLETED,
            summary=f"Action {request.action_type.value} executed successfully.",
        )


@pytest.mark.asyncio
async def test_tui_action_bar_and_history_rendering():
    client = MockControlPlaneTuiClient()
    app = MiniMeTuiApp(query_client=client, refresh_interval=0)

    async with app.run_test() as pilot:
        # Select detail tab
        await app.select_change("mini-me", "015-control-plane")
        app.action_switch_tab("tab-detail")
        await pilot.pause(0.1)

        detail_view = app.query_one("#view-detail", RunDetailView)
        actions_bar = app.query_one("#detail-actions", ActionsBarWidget)
        history_widget = app.query_one("#detail-history", ActionHistoryWidget)
        assert history_widget is not None

        # Check action bar buttons status
        btn_continue = actions_bar.query_one("#btn-continue", Button)
        assert btn_continue.disabled is False

        btn_cancel = actions_bar.query_one("#btn-cancel", Button)
        assert btn_cancel.disabled is False

        btn_retry = actions_bar.query_one("#btn-retry", Button)
        assert btn_retry.disabled is True  # Not in mock actions

        # Check history content rendered
        assert len(detail_view.action_history) == 1


@pytest.mark.asyncio
async def test_tui_action_menu_modal_flow():
    client = MockControlPlaneTuiClient()
    app = MiniMeTuiApp(query_client=client, refresh_interval=0)

    async with app.run_test() as pilot:
        await app.select_change("mini-me", "015-control-plane")
        app.action_switch_tab("tab-detail")
        await pilot.pause(0.1)

        # Press 'a' key to open action menu
        await pilot.press("a")
        await pilot.pause(0.1)

        # Verify ActionSelectionModal is open
        modal = app.screen
        assert isinstance(modal, ActionSelectionModal)

        # Dismiss modal with Escape
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, ActionSelectionModal)
