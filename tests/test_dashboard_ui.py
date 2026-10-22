"""F1 checks for the retired PWA execution surface."""

from __future__ import annotations

from pathlib import Path


def test_pwa_bootstrap_is_read_only_and_does_not_load_legacy_controllers() -> None:
    static_dir = Path(__file__).parent.parent / "src" / "minime" / "static"
    index = (static_dir / "index.html").read_text(encoding="utf-8")
    bootstrap = (static_dir / "js" / "app.js").read_text(encoding="utf-8")
    dashboard = (static_dir / "js" / "dashboard.js").read_text(encoding="utf-8")
    service_worker = (static_dir / "sw.js").read_text(encoding="utf-8")

    assert "mini me" in index
    assert 'src="/static/js/app.js"' in index
    assert "initDashboard" in bootstrap
    assert "Observabilidad en transición" in dashboard
    assert "/api/v1/auth/me" in dashboard
    assert "No se iniciará ningún trabajo" in dashboard
    assert "innerHTML" not in dashboard
    assert "identity.textContent" in dashboard

    for legacy in (
        "backlog_controller",
        "lifecycle_controller",
        "execution_view_controller",
        "control_plane_client",
        "/api/v1/dashboard/overview",
        "/api/v1/queue",
        "/api/v1/orchestration",
    ):
        assert legacy not in dashboard
        assert legacy not in service_worker

    assert "dashboard.js" in service_worker
    assert "f1" in service_worker
