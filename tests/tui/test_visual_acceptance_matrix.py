"""Visual acceptance matrix tests covering all 20 required operational states in mini me TUI."""

from __future__ import annotations

import pytest

from minime.services.dashboard_service import (
    ActiveExecutionDTO,
    AttentionItemDTO,
    AuditSummaryDTO,
    CandidateAuthorityDTO,
    ChangeSummaryDTO,
    CheckResultItemDTO,
    DashboardChangeDetailResponse,
    DashboardOverviewResponse,
    GitHubPRSummaryDTO,
    PipelinePhaseDTO,
    PreviewSessionDTO,
    PreviewValidationSummaryDTO,
    ProviderHealthDTO,
    ReviewSummaryDTO,
    SystemStatusDTO,
    ValidationRunDTO,
)
from minime.tui.app import MiniMeTuiApp
from minime.tui.client import TuiQueryClient
from minime.tui.views.changes import ChangesView
from minime.tui.views.detail import RunDetailView
from minime.tui.views.overview import OverviewView
from minime.tui.widgets.attention_list import AttentionListWidget
from minime.tui.widgets.audit_card import AuditSummaryWidget
from minime.tui.widgets.candidate_lineage import CandidateLineageWidget
from minime.tui.widgets.checks_table import ChecksSummaryWidget
from minime.tui.widgets.executions_list import ActiveExecutionsWidget
from minime.tui.widgets.health_card import SystemHealthCard
from minime.tui.widgets.preview_card import PreviewValidationWidget
from minime.tui.widgets.review_card import ReviewSummaryWidget


class MatrixMockQueryClient(TuiQueryClient):
    def __init__(
        self, overview: DashboardOverviewResponse, detail: DashboardChangeDetailResponse | None
    ) -> None:
        super().__init__()
        self._overview = overview
        self._detail = detail

    async def get_overview(self) -> DashboardOverviewResponse:
        return self._overview

    async def get_change_detail(
        self, project_id: str, change_name: str
    ) -> DashboardChangeDetailResponse | None:
        return self._detail


def default_overview_with_change(
    change_name: str = "014-tui", status: str = "RUNNING"
) -> DashboardOverviewResponse:
    return DashboardOverviewResponse(
        system_status=SystemStatusDTO(healthy=True),
        changes=[ChangeSummaryDTO(project_id="mini-me", change_name=change_name, status=status)],
        active_executions=[],
        attention_items=[],
        recent_completions=[],
    )


@pytest.mark.asyncio
async def test_matrix_state_01_normal_system_overview():
    """State 1: Normal system overview."""
    overview = DashboardOverviewResponse(
        system_status=SystemStatusDTO(
            healthy=True,
            database_engine="PostgreSQL",
            database_healthy=True,
            database_message="Connected",
            scheduler_mode="RUN",
            queue_depth=0,
            active_runs_count=1,
            total_changes_count=2,
            attention_runs_count=0,
            providers=[ProviderHealthDTO(provider_id="codex", status="HEALTHY")],
        ),
        attention_items=[],
        active_executions=[
            ActiveExecutionDTO(
                project_id="mini-me",
                change_name="014-tui",
                run_id="run-1",
                stage="IMPLEMENTING",
                current_executor="codex",
            )
        ],
        recent_completions=[],
        changes=[ChangeSummaryDTO(project_id="mini-me", change_name="014-tui", status="RUNNING")],
    )
    detail = DashboardChangeDetailResponse(
        project_id="mini-me", change_name="014-tui", status="RUNNING"
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test():
        card = app.query_one(SystemHealthCard)
        assert card.status is not None
        assert card.status.healthy is True


@pytest.mark.asyncio
async def test_matrix_state_02_multiple_active_known_changes():
    """State 2: Multiple active/known changes."""
    overview = DashboardOverviewResponse(
        system_status=SystemStatusDTO(healthy=True),
        changes=[
            ChangeSummaryDTO(project_id="mini-me", change_name="014-tui", status="RUNNING"),
            ChangeSummaryDTO(project_id="mini-me", change_name="015-control", status="READY"),
            ChangeSummaryDTO(project_id="mini-me", change_name="013-preview", status="COMPLETED"),
        ],
    )
    detail = DashboardChangeDetailResponse(
        project_id="mini-me", change_name="014-tui", status="RUNNING"
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("2")
        changes_view = app.query_one(ChangesView)
        assert len(changes_view.changes) == 3


@pytest.mark.asyncio
async def test_matrix_state_03_active_run():
    """State 3: Active run in progress."""
    overview = DashboardOverviewResponse(
        system_status=SystemStatusDTO(healthy=True),
        active_executions=[
            ActiveExecutionDTO(
                project_id="mini-me",
                change_name="014-tui",
                run_id="run-1",
                stage="CHECKS_RUNNING",
                current_executor="antigravity",
                latest_progress="Running deterministic checks",
            )
        ],
        changes=[ChangeSummaryDTO(project_id="mini-me", change_name="014-tui", status="RUNNING")],
    )
    detail = DashboardChangeDetailResponse(
        project_id="mini-me", change_name="014-tui", status="RUNNING"
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test():
        exec_widget = app.query_one(ActiveExecutionsWidget)
        assert len(exec_widget.executions) == 1
        assert exec_widget.executions[0].stage == "CHECKS_RUNNING"


@pytest.mark.asyncio
async def test_matrix_state_04_ready_change():
    """State 4: READY change discovered."""
    overview = DashboardOverviewResponse(
        system_status=SystemStatusDTO(healthy=True),
        changes=[ChangeSummaryDTO(project_id="mini-me", change_name="015-actions", status="READY")],
    )
    detail = DashboardChangeDetailResponse(
        project_id="mini-me", change_name="015-actions", status="READY"
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("2")
        from textual.widgets import Button

        btn = app.query_one("#filter-ready", Button)
        btn.press()
        await pilot.pause()
        changes_view = app.query_one(ChangesView)
        assert changes_view.active_filter == "READY"


@pytest.mark.asyncio
async def test_matrix_state_05_needs_human():
    """State 5: NEEDS_HUMAN attention gate."""
    overview = DashboardOverviewResponse(
        system_status=SystemStatusDTO(healthy=True),
        attention_items=[
            AttentionItemDTO(
                project_id="mini-me",
                change_name="014-tui",
                run_id="run-1",
                stage="REVIEW_FAILED",
                stop_outcome="NEEDS_HUMAN",
                human_gate="RESOLVE_REVIEW_FINDINGS",
                reason="Reviewer requested material architectural correction",
                can_remediate=True,
            )
        ],
        changes=[
            ChangeSummaryDTO(project_id="mini-me", change_name="014-tui", status="NEEDS_HUMAN")
        ],
    )
    detail = DashboardChangeDetailResponse(
        project_id="mini-me", change_name="014-tui", status="NEEDS_HUMAN"
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test():
        attn = app.query_one(AttentionListWidget)
        assert len(attn.items) == 1
        assert attn.items[0].stop_outcome == "NEEDS_HUMAN"


@pytest.mark.asyncio
async def test_matrix_state_06_waiting():
    """State 6: WAITING for provider capacity."""
    overview = DashboardOverviewResponse(
        system_status=SystemStatusDTO(healthy=True, scheduler_mode="WAIT"),
        attention_items=[
            AttentionItemDTO(
                project_id="mini-me",
                change_name="014-tui",
                run_id="run-1",
                stage="WAITING_CAPACITY",
                stop_outcome="WAITING",
                reason="Both primary providers exhausted; waiting for quota reset",
            )
        ],
        changes=[ChangeSummaryDTO(project_id="mini-me", change_name="014-tui", status="WAITING")],
    )
    detail = DashboardChangeDetailResponse(
        project_id="mini-me", change_name="014-tui", status="WAITING"
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test():
        attn = app.query_one(AttentionListWidget)
        assert attn.items[0].stage == "WAITING_CAPACITY"


@pytest.mark.asyncio
async def test_matrix_state_07_failed_checks():
    """State 7: Failed checks diagnostic presentation."""
    overview = default_overview_with_change("014-tui", "FAILED")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="FAILED",
        pipeline=[
            PipelinePhaseDTO(
                name="checks",
                display_name="3. Deterministic Checks",
                status="failed",
                summary="pytest failed (1 error)",
            )
        ],
        checks=[
            CheckResultItemDTO(
                check_name="pytest",
                command="pytest tests/tui/",
                status="FAIL",
                exit_code=1,
                duration_ms=1200,
                diagnostic_snippet="AssertionError: Expected 2 columns, got 1",
            )
        ],
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("3")
        checks_widget = app.query_one(ChecksSummaryWidget)
        assert len(checks_widget.checks) == 1
        assert checks_widget.checks[0].status == "FAIL"


@pytest.mark.asyncio
async def test_matrix_state_08_review_approved():
    """State 8: Review approved (READY_TO_MERGE)."""
    overview = default_overview_with_change("014-tui", "RUNNING")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="RUNNING",
        review=ReviewSummaryDTO(
            reviewer_role="antigravity",
            status="completed",
            verdict="READY_TO_MERGE",
            material_findings_count=0,
            summary="Approved without findings",
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("3")
        review_widget = app.query_one(ReviewSummaryWidget)
        assert review_widget.review.verdict == "READY_TO_MERGE"


@pytest.mark.asyncio
async def test_matrix_state_09_review_rejected():
    """State 9: Review rejected (CHANGES_REQUIRED)."""
    overview = default_overview_with_change("014-tui", "NEEDS_HUMAN")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="NEEDS_HUMAN",
        review=ReviewSummaryDTO(
            reviewer_role="antigravity",
            status="completed",
            verdict="CHANGES_REQUIRED",
            material_findings_count=1,
            findings=[
                {"description": "Missing secret redaction on token display", "severity": "material"}
            ],
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("3")
        review_widget = app.query_one(ReviewSummaryWidget)
        assert review_widget.review.verdict == "CHANGES_REQUIRED"
        assert review_widget.review.material_findings_count == 1


@pytest.mark.asyncio
async def test_matrix_state_10_deepseek_pass():
    """State 10: DeepSeek audit pass (Low Risk)."""
    overview = default_overview_with_change("014-tui", "RUNNING")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="RUNNING",
        audit=AuditSummaryDTO(
            provider="deepseek",
            status="completed",
            risk="low",
            material_findings_count=0,
            summary="Zero material vulnerabilities identified",
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("3")
        audit_widget = app.query_one(AuditSummaryWidget)
        assert audit_widget.audit.risk == "low"


@pytest.mark.asyncio
async def test_matrix_state_11_deepseek_material_finding():
    """State 11: DeepSeek audit material finding (High Risk)."""
    overview = default_overview_with_change("014-tui", "NEEDS_HUMAN")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="NEEDS_HUMAN",
        audit=AuditSummaryDTO(
            provider="deepseek",
            status="completed",
            risk="high",
            material_findings_count=1,
            findings=[{"description": "Insecure subprocess shell invocation", "severity": "high"}],
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("3")
        audit_widget = app.query_one(AuditSummaryWidget)
        assert audit_widget.audit.risk == "high"


@pytest.mark.asyncio
async def test_matrix_state_12_preview_building():
    """State 12: Preview BUILDING."""
    overview = default_overview_with_change("014-tui", "RUNNING")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="RUNNING",
        preview_validation=PreviewValidationSummaryDTO(
            is_preview_required=True,
            preview_session=PreviewSessionDTO(
                preview_id="prev-1",
                status="BUILDING",
                head_sha="sha1",
                head_sha_short="sha1",
                base_sha="sha0",
                base_sha_short="sha0",
                image_digest="",
            ),
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("4")
        preview_card = app.query_one(PreviewValidationWidget)
        assert preview_card.summary.preview_session.status == "BUILDING"


@pytest.mark.asyncio
async def test_matrix_state_13_preview_ready():
    """State 13: Preview READY."""
    overview = default_overview_with_change("014-tui", "RUNNING")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="RUNNING",
        preview_validation=PreviewValidationSummaryDTO(
            is_preview_required=True,
            preview_session=PreviewSessionDTO(
                preview_id="prev-1",
                status="READY",
                head_sha="sha1",
                head_sha_short="sha1",
                base_sha="sha0",
                base_sha_short="sha0",
                image_digest="sha256:abcd",
                preview_url="http://127.0.0.1:8787/preview/prev-1",
                allocated_port=8088,
            ),
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("4")
        preview_card = app.query_one(PreviewValidationWidget)
        assert preview_card.summary.preview_session.status == "READY"
        assert preview_card.summary.preview_session.allocated_port == 8088


@pytest.mark.asyncio
async def test_matrix_state_14_validation_pass():
    """State 14: Validation PASS."""
    overview = default_overview_with_change("014-tui", "RUNNING")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="RUNNING",
        preview_validation=PreviewValidationSummaryDTO(
            is_preview_required=True,
            is_authorized=True,
            is_stale=False,
            latest_validation=ValidationRunDTO(
                validation_id="val-1",
                verdict="PASS",
                head_sha="sha1",
                head_sha_short="sha1",
                base_sha="sha0",
                base_sha_short="sha0",
                image_digest="sha256:abcd",
                is_stale=False,
            ),
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("4")
        preview_card = app.query_one(PreviewValidationWidget)
        assert preview_card.summary.latest_validation.verdict == "PASS"
        assert preview_card.summary.is_authorized is True


@pytest.mark.asyncio
async def test_matrix_state_15_validation_fail():
    """State 15: Validation FAIL."""
    overview = default_overview_with_change("014-tui", "NEEDS_HUMAN")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="NEEDS_HUMAN",
        preview_validation=PreviewValidationSummaryDTO(
            is_preview_required=True,
            is_authorized=False,
            is_stale=False,
            latest_validation=ValidationRunDTO(
                validation_id="val-1",
                verdict="FAIL",
                head_sha="sha1",
                head_sha_short="sha1",
                base_sha="sha0",
                base_sha_short="sha0",
                image_digest="sha256:abcd",
                notes="Layout broke on narrow viewport",
            ),
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("4")
        preview_card = app.query_one(PreviewValidationWidget)
        assert preview_card.summary.latest_validation.verdict == "FAIL"


@pytest.mark.asyncio
async def test_matrix_state_16_validation_stale():
    """State 16: Validation STALE."""
    overview = default_overview_with_change("014-tui", "NEEDS_HUMAN")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="NEEDS_HUMAN",
        preview_validation=PreviewValidationSummaryDTO(
            is_preview_required=True,
            is_authorized=False,
            is_stale=True,
            latest_validation=ValidationRunDTO(
                validation_id="val-1",
                verdict="PASS",
                head_sha="sha_old",
                head_sha_short="sha_old",
                base_sha="sha0",
                base_sha_short="sha0",
                image_digest="sha256:abcd",
                is_stale=True,
            ),
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("4")
        preview_card = app.query_one(PreviewValidationWidget)
        assert preview_card.summary.is_stale is True


@pytest.mark.asyncio
async def test_matrix_state_17_historical_superseded_candidate():
    """State 17: Historical / Superseded candidate lineage."""
    overview = default_overview_with_change("014-tui", "RUNNING")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="RUNNING",
        candidate_authority=CandidateAuthorityDTO(
            generation=2,
            candidate_sha="sha_gen2",
            candidate_sha_short="gen2",
            base_sha="base",
            base_sha_short="base",
        ),
        candidate_history=[
            CandidateAuthorityDTO(
                generation=1,
                candidate_sha="sha_gen1",
                candidate_sha_short="gen1",
                base_sha="base",
                base_sha_short="base",
                is_superseded=True,
            ),
            CandidateAuthorityDTO(
                generation=2,
                candidate_sha="sha_gen2",
                candidate_sha_short="gen2",
                base_sha="base",
                base_sha_short="base",
            ),
        ],
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("3")
        lineage = app.query_one(CandidateLineageWidget)
        assert lineage.current_candidate.generation == 2
        assert len(lineage.history) == 2


@pytest.mark.asyncio
async def test_matrix_state_18_pr_open():
    """State 18: PR open."""
    overview = default_overview_with_change("014-tui", "READY_FOR_HUMAN_MERGE")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="READY_FOR_HUMAN_MERGE",
        github=GitHubPRSummaryDTO(
            pr_number=42,
            pr_url="https://github.com/silverberdi/mini-me/pull/42",
            pr_state="open",
            is_merged=False,
            candidate_bound=True,
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("3")
        detail_view = app.query_one(RunDetailView)
        assert detail_view.detail_data.github.pr_number == 42
        assert detail_view.detail_data.github.is_merged is False


@pytest.mark.asyncio
async def test_matrix_state_19_pr_merged():
    """State 19: PR merged."""
    overview = default_overview_with_change("014-tui", "COMPLETED")
    detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="COMPLETED",
        github=GitHubPRSummaryDTO(
            pr_number=42,
            pr_url="https://github.com/silverberdi/mini-me/pull/42",
            pr_state="closed",
            is_merged=True,
            merge_commit_sha="merge123456",
            candidate_bound=True,
        ),
    )
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test() as pilot:
        await pilot.press("3")
        detail_view = app.query_one(RunDetailView)
        assert detail_view.detail_data.github.is_merged is True


@pytest.mark.asyncio
async def test_matrix_state_20_no_active_work():
    """State 20: No active work / clean state."""
    overview = DashboardOverviewResponse(
        system_status=SystemStatusDTO(healthy=True, active_runs_count=0, attention_runs_count=0),
        attention_items=[],
        active_executions=[],
        recent_completions=[],
        changes=[],
    )
    detail = None
    app = MiniMeTuiApp(query_client=MatrixMockQueryClient(overview, detail), refresh_interval=0)
    async with app.run_test():
        overview_view = app.query_one(OverviewView)
        assert overview_view.overview_data.active_executions == []
        assert overview_view.overview_data.attention_items == []
