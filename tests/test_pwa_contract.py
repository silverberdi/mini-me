"""Static, deterministic coverage for the 017 PWA observable contracts."""

import re
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
    lifecycle = read("js/controllers/lifecycle_controller.js")
    assert "initDashboard" in dashboard
    assert "createLifecycleController" in dashboard
    assert "function bind()" in lifecycle
    assert "function start()" in lifecycle
    assert "function stop()" in lifecycle
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
    evidence_views = read("js/views/evidence_views.js")
    assert "candidate.is_superseded" in evidence_views
    assert "is_stale_to_current_candidate" in evidence_views
    assert "review.candidate_sha !== candidate.candidate_sha" in evidence_views
    preview_view = read("js/views/preview_view.js")
    assert "session.image_digest" in preview_view
    assert "session.head_sha === headSha" in preview_view
    sw = read("sw.js")
    assert "CACHEABLE_PATHS" in sw and "SHELL_ASSETS" in sw
    assert 'const CACHE_PREFIX = "minime-pwa-shell-"' in sw
    assert "CACHE_NAME = `${CACHE_PREFIX}v2`" in sw
    for orphan in (
        "components/header.js",
        "components/candidate_inspector.js",
        "components/preview_panel.js",
        "views/queue_view.js",
    ):
        assert not (STATIC / "js" / orphan).exists(), orphan
        assert f"/static/js/{orphan}" not in sw


def test_frontend_has_no_direct_host_mutation_provider_or_merge_entrypoint() -> None:
    scripts = "\n".join(path.read_text() for path in (STATIC / "js").rglob("*.js"))
    forbidden = re.compile(
        r"(?im)(?:\bsystemctl\b|\bchild_process\b|\bsubprocess\b|"
        r"\bcodex\s+exec\b|\bagy\s+exec\b|\bgit\s+push\b|"
        r"api\.deepseek\.com|openrouter\.ai|/pulls?/[^\s'\"]+/merge)"
    )
    assert forbidden.search(scripts) is None


def test_native_module_runtime_has_one_bootstrap_and_no_orphaned_javascript_assets() -> None:
    index = read("index.html")
    bootstrap = read("js/app.js")
    root = STATIC / "js"
    assert index.count('<script type="module" src="/static/js/app.js"></script>') == 1
    assert '<script src="/static/js/dashboard.js"></script>' not in index
    assert bootstrap.count('import { initDashboard } from "./dashboard.js";') == 1
    assert "let initialized = false;" in bootstrap
    assert bootstrap.count("DOMContentLoaded") == 1
    assert "addEventListener" not in read("js/dashboard.js")

    import_pattern = re.compile(r"(?:from|import)\s*\(?\s*[\"']([^\"']+\.js)[\"']")
    reachable: set[Path] = set()
    pending = [root / "app.js"]
    while pending:
        module = pending.pop()
        if module in reachable:
            continue
        assert module.is_file(), f"broken runtime import: {module}"
        reachable.add(module)
        for specifier in import_pattern.findall(module.read_text(encoding="utf-8")):
            if specifier.startswith("."):
                dependency = (module.parent / specifier).resolve()
                assert dependency.is_relative_to(root.resolve()), specifier
                pending.append(dependency)

    javascript = {path.resolve() for path in root.rglob("*.js")}
    assert reachable == javascript, {
        "unreachable": sorted(
            str(path.relative_to(root.resolve())) for path in javascript - reachable
        ),
        "missing": sorted(str(path.relative_to(root.resolve())) for path in reachable - javascript),
    }
    sw = read("sw.js")
    cached_modules = {
        (root / path).resolve() for path in re.findall(r'"/static/js/([^\"]+\.js)"', sw)
    }
    assert reachable <= cached_modules


def test_domain_listener_owners_are_idempotent_and_tab_semantics_are_complete() -> None:
    for path, guard in (
        ("js/controllers/lifecycle_controller.js", "if (bound) return;"),
        ("js/controllers/navigation_controller.js", "if (bound) return;"),
        ("js/controllers/backlog_controller.js", "if (bound) return;"),
        ("js/controllers/projects_controller.js", "if (bound) return;"),
        ("js/controllers/action_controller.js", "toolbarBound) return;"),
    ):
        assert guard in read(path), path
    navigation = read("js/controllers/navigation_controller.js")
    for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
        assert key in navigation
    index = read("index.html")
    assert 'aria-controls="viewExecutions"' in index
    assert 'aria-labelledby="navTabExecutions"' in index
    assert 'aria-controls="candidateTab"' in index
    assert 'aria-labelledby="tabCandidate"' in index
