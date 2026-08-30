"""Headless Textual Pilot integration tests for mini me TUI console."""

from __future__ import annotations

import pytest
from textual.widgets import DataTable, TabbedContent

from minime.services.dashboard_service import (
    ActiveExecutionDTO,
    AttentionItemDTO,
    AuditSummaryDTO,
    CandidateAuthorityDTO,
    ChangeSummaryDTO,
    CheckResultItemDTO,
    DashboardChangeDetailResponse,
    DashboardOverviewResponse,
    PipelinePhaseDTO,
    PreviewSessionDTO,
    PreviewValidationSummaryDTO,
    ProviderHealthDTO,
    RecentCompletionDTO,
    ReviewSummaryDTO,
    SystemStatusDTO,
    TimelineEventDTO,
    ValidationRunDTO,
    ValidationScenarioDTO,
)
from minime.tui.app import MiniMeTuiApp
from minime.tui.client import TuiQueryClient
from minime.tui.widgets.header import HeaderWidget
from minime.tui.widgets.help_modal import HelpModal


def create_sample_overview() -> DashboardOverviewResponse:
    return DashboardOverviewResponse(
        system_status=SystemStatusDTO(
            healthy=True,
            database_engine="PostgreSQL",
            database_healthy=True,
            database_message="Connected",
            scheduler_mode="RUN",
            queue_depth=1,
            github_app_health="HEALTHY",
            active_runs_count=1,
            total_changes_count=3,
            attention_runs_count=1,
            providers=[
                ProviderHealthDTO(provider_id="codex", status="HEALTHY"),
                ProviderHealthDTO(provider_id="antigravity", status="HEALTHY"),
                ProviderHealthDTO(provider_id="deepseek", status="HEALTHY"),
            ],
        ),
        attention_items=[
            AttentionItemDTO(
                project_id="mini-me",
                change_name="010-governance",
                run_id="run-attn-1",
                stage="REVIEW_FAILED",
                stop_outcome="NEEDS_HUMAN",
                human_gate="RESOLVE_REVIEW_FINDINGS",
                reason="Complementary review flagged material finding",
                remediation_guidance="Resolve flagged security items",
                can_retry=True,
                can_remediate=True,
            )
        ],
        active_executions=[
            ActiveExecutionDTO(
                project_id="mini-me",
                change_name="014-tui-console",
                run_id="run-act-1",
                job_id="job-act-1",
                stage="IMPLEMENTING",
                current_executor="codex",
                generation=1,
                candidate_sha="1111222233334444",
                latest_progress="Writing TUI widgets",
            )
        ],
        recent_completions=[
            RecentCompletionDTO(
                project_id="mini-me",
                change_name="013-container-preview",
                run_id="run-comp-1",
                candidate_sha="9999888877776666",
                generation=1,
                pr_number=41,
                pr_url="https://github.com/silverberdi/mini-me/pull/41",
                review_verdict="READY_TO_MERGE",
                audit_risk="LOW",
            )
        ],
        changes=[
            ChangeSummaryDTO(
                project_id="mini-me",
                change_name="014-tui-console",
                status="RUNNING",
                current_run_id="run-act-1",
                active_job_id="job-act-1",
                current_stage="IMPLEMENTING",
                current_executor="codex",
                generation=1,
                candidate_sha="1111222233334444",
            ),
            ChangeSummaryDTO(
                project_id="mini-me",
                change_name="010-governance",
                status="NEEDS_HUMAN",
                current_stage="REVIEW_FAILED",
                stop_outcome="NEEDS_HUMAN",
            ),
            ChangeSummaryDTO(
                project_id="mini-me",
                change_name="013-container-preview",
                status="COMPLETED",
                current_stage="DONE",
            ),
        ],
    )


def create_sample_detail() -> DashboardChangeDetailResponse:
    return DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui-console",
        status="RUNNING",
        run_id="run-act-1",
        job_id="job-act-1",
        current_stage="IMPLEMENTING",
        current_executor="codex",
        pipeline=[
            PipelinePhaseDTO(name="readiness", display_name="1. Readiness", status="passed", summary="DoR verified"),
            PipelinePhaseDTO(name="implementation", display_name="2. Implementation", status="running", summary="Executing Codex implementer"),
            PipelinePhaseDTO(name="checks", display_name="3. Deterministic Checks", status="not_started", summary="Awaiting implementation"),
            PipelinePhaseDTO(name="review", display_name="4. Complementary Review", status="not_started", summary="Awaiting checks"),
            PipelinePhaseDTO(name="audit", display_name="5. DeepSeek Audit", status="not_started", summary="Awaiting review"),
            PipelinePhaseDTO(name="pr_merge", display_name="6. PR & Merge Gate", status="not_started", summary="Awaiting audit"),
        ],
        candidate_authority=CandidateAuthorityDTO(
            generation=1,
            candidate_sha="11112222333344445555666677778888",
            candidate_sha_short="11112222",
            base_sha="aaaabbbbccccddddeeeeffff00001111",
            base_sha_short="aaaabbbb",
            manifest_hash="manifes12345",
            image_digest="sha256:imgdigest1234567890",
            changed_files=["src/minime/tui/app.py", "src/minime/tui/styles.tcss"],
        ),
        candidate_history=[],
        checks=[
            CheckResultItemDTO(
                check_name="ruff",
                command="ruff check .",
                status="PASS",
                exit_code=0,
                duration_ms=250,
                diagnostic_snippet="All checks passed.",
            ),
            CheckResultItemDTO(
                check_name="pytest",
                command="pytest",
                status="PASS",
                exit_code=0,
                duration_ms=1800,
                diagnostic_snippet="12 passed in 1.8s",
            ),
        ],
        review=ReviewSummaryDTO(
            reviewer_role="antigravity",
            model="gemini-1.5-pro",
            status="completed",
            verdict="READY_TO_MERGE",
            candidate_sha="11112222333344445555666677778888",
            material_findings_count=0,
            summary="All specs and safety policies met.",
        ),
        audit=AuditSummaryDTO(
            provider="deepseek",
            status="completed",
            risk="low",
            candidate_sha="11112222333344445555666677778888",
            material_findings_count=0,
            summary="Independent audit clean.",
        ),
        preview_validation=PreviewValidationSummaryDTO(
            is_preview_required=True,
            is_authorized=False,
            is_stale=False,
            preview_session=PreviewSessionDTO(
                preview_id="prev-1",
                status="READY",
                head_sha="11112222333344445555666677778888",
                head_sha_short="11112222",
                base_sha="aaaabbbbccccddddeeeeffff00001111",
                base_sha_short="aaaabbbb",
                image_digest="sha256:imgdigest1234567890",
                preview_url="http://127.0.0.1:8787/preview/prev-1",
                allocated_port=8088,
                container_name="minime-preview-mini-me-014-gen1",
            ),
            latest_validation=ValidationRunDTO(
                validation_id="val-1",
                verdict="PASS",
                head_sha="11112222333344445555666677778888",
                head_sha_short="11112222",
                base_sha="aaaabbbbccccddddeeeeffff00001111",
                base_sha_short="aaaabbbb",
                image_digest="sha256:imgdigest1234567890",
                is_stale=False,
                operator="human-operator",
                notes="Console UI responsive across all layouts",
            ),
            scenarios=[
                ValidationScenarioDTO(
                    scenario_id="sc-1",
                    title="Validate TUI Overview & Keybindings",
                    description="Open console and switch tabs",
                    ordered_steps=["Launch console", "Press 2 for changes", "Press 3 for detail", "Press ? for help"],
                    expected_result="All views render cleanly with zero broken borders",
                )
            ],
        ),
        timeline=[
            TimelineEventDTO(
                event_id="evt-1",
                timestamp="2026-08-30T14:00:00Z",
                event_type="STAGE_TRANSITION",
                from_stage="DISCOVERED",
                to_stage="IMPLEMENTING",
                actor="daemon",
                summary="Run started autonomous implementation",
            )
        ],
    )


class MockQueryClient(TuiQueryClient):
    def __init__(self, overview: DashboardOverviewResponse, detail: DashboardChangeDetailResponse) -> None:
        super().__init__()
        self._overview = overview
        self._detail = detail

    async def get_overview(self) -> DashboardOverviewResponse:
        return self._overview

    async def get_change_detail(self, project_id: str, change_name: str) -> DashboardChangeDetailResponse | None:
        return self._detail


@pytest.mark.asyncio
async def test_tui_app_initial_mount_and_overview():
    overview = create_sample_overview()
    detail = create_sample_detail()
    client = MockQueryClient(overview, detail)

    app = MiniMeTuiApp(query_client=client, refresh_interval=0)
    async with app.run_test():
        # Check Header
        header = app.query_one(HeaderWidget)
        assert header.system_status is not None
        assert header.system_status.active_runs_count == 1
        assert header.system_status.attention_runs_count == 1

        # Check Active Tab is Overview
        tabs = app.query_one(TabbedContent)
        assert tabs.active == "tab-overview"



@pytest.mark.asyncio
async def test_tui_app_tab_navigation_and_shortcuts():
    overview = create_sample_overview()
    detail = create_sample_detail()
    client = MockQueryClient(overview, detail)

    app = MiniMeTuiApp(query_client=client, refresh_interval=0)
    async with app.run_test() as pilot:
        tabs = app.query_one(TabbedContent)

        # Press '2' -> Changes tab
        await pilot.press("2")
        assert tabs.active == "tab-changes"

        # Press '3' -> Detail tab
        await pilot.press("3")
        assert tabs.active == "tab-detail"

        # Press '4' -> Preview tab
        await pilot.press("4")
        assert tabs.active == "tab-preview"

        # Press '1' -> Overview tab
        await pilot.press("1")
        assert tabs.active == "tab-overview"

        # Press '?' -> Open Help Modal
        await pilot.press("question_mark")
        assert len(app.screen_stack) > 1
        assert isinstance(app.screen, HelpModal)

        # Dismiss modal with 'escape'
        await pilot.press("escape")
        assert not isinstance(app.screen, HelpModal)


@pytest.mark.asyncio
async def test_tui_app_changes_table_selection():
    overview = create_sample_overview()
    detail = create_sample_detail()
    client = MockQueryClient(overview, detail)

    app = MiniMeTuiApp(query_client=client, refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("2")  # go to changes tab
        table = app.query_one("#changes-table", DataTable)
        assert table.row_count == 3

        # Focus table and press enter to select current row
        table.focus()
        await pilot.press("enter")
        # Selecting row switches to tab-detail
        tabs = app.query_one(TabbedContent)
        assert tabs.active == "tab-detail"


@pytest.mark.asyncio
async def test_tui_app_preview_projection_and_stale_detection():
    overview = create_sample_overview()
    detail = create_sample_detail()
    # Mark preview validation as STALE
    detail.preview_validation.is_stale = True

    client = MockQueryClient(overview, detail)
    app = MiniMeTuiApp(query_client=client, refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("4")  # Preview tab
        from minime.tui.widgets.preview_card import PreviewValidationWidget
        card = app.query_one("#preview-view-card", PreviewValidationWidget)
        assert card is not None
        assert card.summary is not None
        assert card.summary.is_stale is True
        assert card.summary.preview_session.status == "READY"
        assert card.summary.preview_session.allocated_port == 8088

