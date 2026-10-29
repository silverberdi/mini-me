"""F1 checks for the retired PWA execution surface."""

from __future__ import annotations

from pathlib import Path


def test_pwa_bootstrap_is_read_only_and_does_not_load_legacy_controllers() -> None:
    static_dir = Path(__file__).parent.parent / "src" / "minime" / "static"
    index = (static_dir / "index.html").read_text(encoding="utf-8")
    bootstrap = (static_dir / "js" / "app.js").read_text(encoding="utf-8")
    dashboard = (static_dir / "js" / "dashboard.js").read_text(encoding="utf-8")
    service_worker = (static_dir / "sw.js").read_text(encoding="utf-8")
    legacy_clients = (
        static_dir / "js" / "controllers" / "backlog_controller.js",
        static_dir / "js" / "controllers" / "projects_controller.js",
        static_dir / "js" / "views" / "backlog_view.js",
        static_dir / "js" / "views" / "projects_view.js",
    )

    assert "mini me" in index
    assert 'src="/static/js/app.js"' in index
    assert "createRouter" in bootstrap
    assert "Trabajo actual" in dashboard or "initDashboard" in dashboard
    assert "/api/v1/auth/me" in bootstrap
    assert "innerHTML" not in dashboard
    assert all(not path.exists() for path in legacy_clients)
    for retired_control in (
        "onboardProjectForm",
        "onboardProjectBtn",
        "backlogActionToolbar",
        "discoverBacklogBtn",
        "startWorkBtn",
        "autoRefreshToggle",
        "navTabProjects",
    ):
        assert retired_control not in index

    assert "/api/v1/dashboard/overview" not in dashboard
    assert "/api/v1/queue" not in dashboard
    assert "/api/v1/orchestration" not in dashboard

    assert "dashboard.js" in service_worker
    assert "f5" in service_worker
