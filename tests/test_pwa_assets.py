"""Deterministic contract checks for the 017 PWA shell."""

from pathlib import Path

STATIC = Path(__file__).parents[1] / "src" / "minime" / "static"


def test_pwa_shell_assets_and_manifest() -> None:
    for path in (
        STATIC / "css" / "tokens.css",
        STATIC / "css" / "layout.css",
        STATIC / "css" / "components.css",
        STATIC / "js" / "app.js",
        STATIC / "js" / "services" / "api_client.js",
        STATIC / "js" / "components" / "pipeline_stepper.js",
        STATIC / "manifest.webmanifest",
        STATIC / "sw.js",
        STATIC / "icons" / "icon-192.png",
        STATIC / "icons" / "icon-512.png",
    ):
        assert path.exists(), f"missing PWA asset: {path}"

    manifest = (STATIC / "manifest.webmanifest").read_text()
    assert '"name": "mini me Control Center"' in manifest
    assert '"display": "standalone"' in manifest
    assert '"192x192"' in manifest and '"512x512"' in manifest


def test_pwa_client_contracts_and_accessible_shell() -> None:
    index = (STATIC / "index.html").read_text()
    client = (STATIC / "js" / "services" / "api_client.js").read_text()
    sw = (STATIC / "sw.js").read_text()
    assert 'rel="manifest"' in index and 'type="module"' in index
    assert 'id="offlineBanner"' in index and 'id="actionDialog"' in index
    assert "/api/v1/dashboard/overview" in client
    assert "/api/v1/queue" in client
    offline_banner = (STATIC / "js" / "components" / "offline_banner.js").read_text()
    assert "datos operacionales no están actualizados" in offline_banner
    assert "CACHEABLE_PATHS" in sw and "SHELL_ASSETS" in sw
    assert 'const CACHE_PREFIX = "minime-pwa-shell-"' in sw
    assert "/api/" not in sw


def test_pipeline_view_matches_authoritative_dashboard_phases() -> None:
    source = (STATIC / "js" / "components" / "pipeline_stepper.js").read_text()
    for stage in (
        '"readiness"',
        '"implementation"',
        '"checks"',
        '"review"',
        '"audit"',
        '"pr_merge"',
    ):
        assert stage in source
    assert "Matches DashboardService._build_pipeline" in source
