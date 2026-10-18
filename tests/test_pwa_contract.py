"""Static, deterministic coverage for the 017 PWA observable contracts."""

from pathlib import Path

STATIC = Path(__file__).parents[1] / "src" / "minime" / "static"


def read(path: str) -> str:
    return (STATIC / path).read_text()


def test_shell_exposes_observability_and_responsive_surfaces() -> None:
    index = read("index.html")
    assert '<html lang="es">' in index
    assert '<script src="/static/js/dashboard.js"></script>' not in index
    assert index.count('<script type="module" src="/static/js/app.js"></script>') == 1
    for marker in (
        "schedulerModeBadge",
        "dbHealthBadge",
        "autoRefreshToggle",
        "queueList",
        "attentionBanner",
        "actionDialog",
        "actionParamDialog",
        "efficiencyTab",
        "actionHistoryTab",
        "bottom-nav",
    ):
        assert marker in index
    css = read("css/layout.css") + read("css/components.css") + read("css/tokens.css")
    for marker in (
        "@media",
        "max-width: 767px",
        "grid-template-columns",
        "focus-visible",
        "min-height: 44px",
    ):
        assert marker in css


def test_telemetry_and_control_plane_clients_use_canonical_routes() -> None:
    client = read("js/services/api_client.js")
    for route in (
        "/api/v1/dashboard/overview",
        "/api/v1/queue",
        "/api/v1/orchestration/runs",
        "/api/v1/control-plane/actions/available",
        "/api/v1/control-plane/actions/execute",
        "/api/v1/validations/submit",
    ):
        assert route in client
    assert "initDashboard" in read("js/app.js")
    dashboard = read("js/dashboard.js")
    assert "setupAutoRefresh" in dashboard
    assert "initDashboard" in dashboard
    assert 'cache: "no-store"' in client
    assert 'credentials: "same-origin"' in client
    assert "scheduler_service" in read("js/views/operational_panels_view.js")


def test_evidence_and_preview_contracts_are_explicit() -> None:
    stepper = read("js/components/pipeline_stepper.js")
    # DashboardService is the stage authority; the view must not synthesize
    # legacy stages that are absent from that read model.
    for stage in (
        '"readiness"',
        '"implementation"',
        '"checks"',
        '"review"',
        '"audit"',
        '"pr_merge"',
    ):
        assert stage in stepper
    assert "SUPERSEDED" in read("js/components/candidate_inspector.js")
    assert "STALE" in read("js/components/candidate_inspector.js")
    assert "image_digest" in read("js/components/preview_panel.js") or "image_digest" in read(
        "js/app.js"
    )
    sw = read("sw.js")
    assert "CACHEABLE_PATHS" in sw and "SHELL_ASSETS" in sw
    assert 'const CACHE_PREFIX = "minime-pwa-shell-"' in sw
    assert "CACHE_NAME = `${CACHE_PREFIX}v2`" in sw
    assert "503" not in sw
