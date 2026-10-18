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
    first_navigation_tab = index_content.index('id="navTabExecutions"')
    assert first_navigation_tab < index_content.index('id="navTabBacklog"')
    assert (
        'data-main-view="viewExecutions"'
        in index_content[first_navigation_tab : first_navigation_tab + 250]
    )
    assert "Preparación automática: DESCONOCIDO" in index_content
    assert "Admisión automática: DESCONOCIDO" in index_content
    assert "Concurrencia: DESCONOCIDO" in index_content
    assert 'value="mini-me" selected' not in index_content
    assert 'data-kpi="active">0' not in index_content
    assert 'data-kpi="queue">0' not in index_content
    assert "Preparación automática: ON" not in index_content
    assert "Admisión automática: ON" not in index_content

    css_content = css_file.read_text(encoding="utf-8")
    assert "theme-dark" in css_content
    assert "theme-light" in css_content
    assert "pipeline-stepper" in css_content
    assert "@media" in css_content

    js_content = js_file.read_text(encoding="utf-8")
    api_client = (static_dir / "js" / "services" / "api_client.js").read_text(encoding="utf-8")
    assert "/api/v1/dashboard/overview" in api_client
    assert "renderPipelineStepper" in js_content
    assert "createThemeController" in js_content
    assert "createNavigationController" in js_content
    navigation_controller = (
        static_dir / "js" / "controllers" / "navigation_controller.js"
    ).read_text(encoding="utf-8")
    assert "let currentView = 'viewExecutions'" in navigation_controller
    assert "function switchView(viewName)" in navigation_controller
    assert "project?.auto_prepare" in js_content
    assert "project?.auto_admit" in js_content
    assert "project?.max_concurrent_jobs" in js_content
    assert "head_sha: candSha || 'HEAD'" not in js_content
    assert "base_sha: baseSha || 'main'" not in js_content
    assert "const previewIdentityValid" in js_content
    assert "window.minime" not in js_content
    assert "window.selectChange" not in js_content
    assert "onclick=" not in js_content
    assert "data-project-action" in (static_dir / "js" / "views" / "projects_view.js").read_text(
        encoding="utf-8"
    )
