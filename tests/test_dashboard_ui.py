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
    detail_view = (static_dir / "js" / "controllers" / "detail_view_controller.js").read_text(
        encoding="utf-8"
    )
    assert "createDetailViewController" in js_content
    assert "renderPipelineStepper" in detail_view
    execution_view = (static_dir / "js" / "controllers" / "execution_view_controller.js").read_text(
        encoding="utf-8"
    )
    assert "createExecutionViewController" in js_content
    assert "function refreshOnce()" in execution_view
    assert "let overviewData" not in js_content
    assert "createThemeController" in js_content
    assert "createNavigationController" in js_content
    navigation_controller = (
        static_dir / "js" / "controllers" / "navigation_controller.js"
    ).read_text(encoding="utf-8")
    assert "let currentView = 'viewExecutions'" in navigation_controller
    assert "function switchView(viewName)" in navigation_controller
    backlog_controller = (static_dir / "js" / "controllers" / "backlog_controller.js").read_text(
        encoding="utf-8"
    )
    assert "project?.auto_prepare" in backlog_controller
    assert "project?.auto_admit" in backlog_controller
    assert "project?.max_concurrent_jobs" in backlog_controller
    assert not (static_dir / "js" / "state" / "store.js").exists()
    assert "state/store.js" not in (static_dir / "sw.js").read_text(encoding="utf-8")
    assert "AppState" not in js_content
    for retired in (
        "js/components/attention_banner.js",
        "js/components/efficiency_panel.js",
        "js/components/runs_table.js",
        "js/views/history_view.js",
        "js/views/settings_view.js",
    ):
        assert not (static_dir / retired).exists()
        assert retired not in (static_dir / "sw.js").read_text(encoding="utf-8")
    assert "head_sha: candSha || 'HEAD'" not in js_content
    assert "base_sha: baseSha || 'main'" not in js_content
    preview_view = (static_dir / "js" / "views" / "preview_view.js").read_text(encoding="utf-8")
    assert "const identityValid" in preview_view
    assert "session.head_sha === headSha" in preview_view
    assert "session.base_sha === baseSha" in preview_view
    assert "session.candidate_generation" in preview_view
    assert "previewActions.submitValidation" in preview_view
    assert "window.minime" not in js_content
    assert "window.selectChange" not in js_content
    assert "onclick=" not in js_content
    assert "data-project-action" in (static_dir / "js" / "views" / "projects_view.js").read_text(
        encoding="utf-8"
    )
