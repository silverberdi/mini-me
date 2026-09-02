"""Static, deterministic coverage for the 017 PWA observable contracts."""

from pathlib import Path

STATIC = Path(__file__).parents[1] / "src" / "minime" / "static"


def read(path: str) -> str:
    return (STATIC / path).read_text()


def test_shell_exposes_observability_and_responsive_surfaces() -> None:
    index = read("index.html")
    for marker in (
        "schedulerModeBadge",
        "dbHealthBadge",
        "autoRefreshToggle",
        "queueList",
        "attentionBanner",
        "actionDialog",
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
    assert "autoRefresh" in read("js/app.js")


def test_evidence_and_preview_contracts_are_explicit() -> None:
    assert "WORKTREE_SETUP" in read("js/components/pipeline_stepper.js")
    assert "CLOSURE" in read("js/components/pipeline_stepper.js")
    assert "SUPERSEDED" in read("js/components/candidate_inspector.js")
    assert "STALE" in read("js/components/candidate_inspector.js")
    assert "image_digest" in read("js/components/preview_panel.js") or "image_digest" in read(
        "js/app.js"
    )
    sw = read("sw.js")
    assert "cache-first" in sw.lower() or "caches.match" in sw
    assert "/api/" in sw and "503" in sw
