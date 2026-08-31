"""Unit tests for TuiQueryClient and fallback behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from minime.services.dashboard_service import (
    DashboardChangeDetailResponse,
    DashboardOverviewResponse,
    SystemStatusDTO,
)
from minime.tui.client import TuiQueryClient


@pytest.mark.asyncio
async def test_tui_query_client_overview():
    mock_uow = MagicMock()
    mock_overview = DashboardOverviewResponse(
        system_status=SystemStatusDTO(
            healthy=True,
            database_engine="PostgreSQL",
            database_healthy=True,
            database_message="Connected",
            scheduler_mode="RUN",
            queue_depth=0,
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

    client = TuiQueryClient(uow_factory=lambda: mock_uow)
    # Monkeypatch internal sync call
    client._sync_get_overview = lambda: mock_overview

    res = await client.get_overview()
    assert res.system_status.healthy is True
    assert res.system_status.active_runs_count == 1


@pytest.mark.asyncio
async def test_tui_query_client_detail():
    mock_uow = MagicMock()
    mock_detail = DashboardChangeDetailResponse(
        project_id="mini-me",
        change_name="014-tui",
        status="RUNNING",
        current_stage="IMPLEMENTING",
        pipeline=[],
        checks=[],
    )

    client = TuiQueryClient(uow_factory=lambda: mock_uow)
    client._sync_get_change_detail = lambda p, c: mock_detail

    res = await client.get_change_detail("mini-me", "014-tui")
    assert res is not None
    assert res.project_id == "mini-me"
    assert res.change_name == "014-tui"


@pytest.mark.asyncio
async def test_tui_query_client_disconnected_fallback():
    # Factory that raises an error simulating DB disconnect
    def failing_factory():
        raise RuntimeError("Database connection refused on port 5432")

    client = TuiQueryClient(uow_factory=failing_factory)
    overview = await client.get_overview()

    assert overview.system_status.healthy is False
    assert overview.system_status.database_healthy is False
    assert "Database connection refused" in overview.system_status.database_message
    assert overview.attention_items == []
    assert overview.active_executions == []
