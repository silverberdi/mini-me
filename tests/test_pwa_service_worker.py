from __future__ import annotations

import re
from pathlib import Path

SERVICE_WORKER = Path(__file__).parents[1] / "src/minime/static/sw.js"
STATIC_ROOT = Path(__file__).parents[1] / "src/minime/static"


def test_service_worker_legacy_purge_contract() -> None:
    """Verify that legacy sw.js unregisters and purges legacy shell caches."""
    source = SERVICE_WORKER.read_text(encoding="utf-8")
    assert "minime-pwa-shell-" in source
    assert "unregister" in source
    assert "skipWaiting" in source


def test_angular_production_service_worker_artifacts_present() -> None:
    """Verify that modern Angular PWA service worker and config are in static assets."""
    ngsw_worker = STATIC_ROOT / "ngsw-worker.js"
    ngsw_json = STATIC_ROOT / "ngsw.json"
    manifest = STATIC_ROOT / "manifest.webmanifest"
    assert ngsw_worker.is_file(), "ngsw-worker.js must be present in static assets"
    assert ngsw_json.is_file(), "ngsw.json must be present in static assets"
    assert manifest.is_file(), "manifest.webmanifest must be present in static assets"
