"""Deterministic contract checks for the read-only F1/F2 PWA shell."""

from pathlib import Path

STATIC = Path(__file__).parents[1] / "src" / "minime" / "static"


def test_pwa_shell_assets_and_manifest() -> None:
    for path in (
        STATIC / "css" / "tokens.css",
        STATIC / "css" / "layout.css",
        STATIC / "css" / "components.css",
        STATIC / "js" / "app.js",
        STATIC / "js" / "dashboard.js",
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
    sw = (STATIC / "sw.js").read_text()
    assert 'rel="manifest"' in index and 'type="module"' in index
    assert 'id="googleLoginLink"' in index
    assert 'id="authenticatedContent"' in index
    assert "onboardProjectForm" not in index
    assert "discoverBacklogBtn" not in index
    assert "actionDialog" not in index
    assert {
        path.relative_to(STATIC).as_posix()
        for path in (STATIC / "js").rglob("*.js")
    } == {"js/app.js", "js/dashboard.js"}
    assert "CACHEABLE_PATHS" in sw and "SHELL_ASSETS" in sw
    assert 'const CACHE_PREFIX = "minime-pwa-shell-"' in sw
    assert "/api/" not in sw
