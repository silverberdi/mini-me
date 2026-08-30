"""Tests for UI assets and HTML template structure."""

from __future__ import annotations

from pathlib import Path


def test_ui_assets_exist_and_are_complete() -> None:
    static_dir = Path(__file__).parent.parent / "src" / "minime" / "static"
    index_file = static_dir / "index.html"
    css_file = static_dir / "css" / "dashboard.css"
    js_file = static_dir / "js" / "dashboard.js"

    assert index_file.exists(), "index.html missing"
    assert css_file.exists(), "dashboard.css missing"
    assert js_file.exists(), "dashboard.js missing"

    index_content = index_file.read_text(encoding="utf-8")
    assert "mini me" in index_content
    assert "pipeline-stepper" in index_content
    assert "attention-banner" in index_content
    assert "kpi-grid" in index_content
    assert "changesTable" in index_content
    assert "detailPanel" in index_content

    css_content = css_file.read_text(encoding="utf-8")
    assert "theme-dark" in css_content
    assert "theme-light" in css_content
    assert "pipeline-stepper" in css_content
    assert "@media" in css_content

    js_content = js_file.read_text(encoding="utf-8")
    assert "/api/v1/dashboard/overview" in js_content
    assert "renderPipelineStepper" in js_content
    assert "toggleTheme" in js_content
