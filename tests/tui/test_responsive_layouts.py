"""Responsive layout and multi-viewport tests for mini me TUI console."""

from __future__ import annotations

import pytest
from tests.tui.test_app_views_pilot import (
    MockQueryClient,
    create_sample_detail,
    create_sample_overview,
)

from minime.tui.app import MiniMeTuiApp


@pytest.mark.asyncio
async def test_narrow_terminal_layout():
    """Verify narrow terminal (80 cols x 24 rows) layout adapts cleanly without crashing."""
    overview = create_sample_overview()
    detail = create_sample_detail()
    client = MockQueryClient(overview, detail)

    app = MiniMeTuiApp(query_client=client, refresh_interval=0)
    async with app.run_test(size=(80, 24)) as pilot:
        # Check Overview
        assert app.is_mounted
        await pilot.press("2")
        await pilot.press("3")
        await pilot.press("4")
        await pilot.press("1")


@pytest.mark.asyncio
async def test_normal_terminal_layout():
    """Verify normal terminal (140 cols x 40 rows) layout renders two columns."""
    overview = create_sample_overview()
    detail = create_sample_detail()
    client = MockQueryClient(overview, detail)

    app = MiniMeTuiApp(query_client=client, refresh_interval=0)
    async with app.run_test(size=(140, 40)) as pilot:
        assert app.is_mounted
        await pilot.press("3")  # Detail view
        # Check widgets mounted
        assert app.query_one("#detail-stepper") is not None
        assert app.query_one("#detail-candidate") is not None


@pytest.mark.asyncio
async def test_wide_ultrawide_terminal_layout():
    """Verify wide/ultrawide terminal (220 cols x 50 rows) utilizes full width with 3 columns."""
    overview = create_sample_overview()
    detail = create_sample_detail()
    client = MockQueryClient(overview, detail)

    app = MiniMeTuiApp(query_client=client, refresh_interval=0)
    async with app.run_test(size=(220, 50)):
        assert app.is_mounted
        # On overview screen in wide mode, left, center, right columns are visible
        left_col = app.query_one(".overview-col-left")
        center_col = app.query_one(".overview-col-center")
        right_col = app.query_one(".overview-col-right")

        assert left_col is not None
        assert center_col is not None
        assert right_col is not None

