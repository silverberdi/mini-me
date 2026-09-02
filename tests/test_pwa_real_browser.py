"""Real browser inspection tests for 017 PWA Control Center across viewports."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
import websockets
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.api.app import app, get_uow
from minime.domain.enums import (
    AuditRiskLevel,
    AuditStatus,
    BlockerValidationVerdict,
    ChangeStatus,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    PreviewStatus,
    ProviderHealthStatus,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.models import (
    AuditRecord,
    BlockerClaim,
    Change,
    CheckResult,
    Job,
    OrchestrationCandidate,
    OrchestrationRun,
    PreviewSession,
    Project,
    ProviderHealth,
    Review,
    WorkQueueItem,
)

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def create_seeded_uow() -> InMemoryPersistenceUnitOfWork:
    uow = InMemoryPersistenceUnitOfWork()

    # 1. Project
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    uow.projects.save(project)

    # 2. Changes
    c1 = Change(
        project_id="mini-me",
        name="017-pwa-control-center",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    c2 = Change(
        project_id="mini-me",
        name="016-human-gate-flow",
        status=ChangeStatus.BLOCKED,
        last_readiness_status=ReadinessState.READY,
    )
    c3 = Change(
        project_id="mini-me",
        name="015-widen-transition-key",
        status=ChangeStatus.DONE,
        last_readiness_status=ReadinessState.READY,
    )
    uow.changes.save(c1)
    uow.changes.save(c2)
    uow.changes.save(c3)

    # 3. Runs
    run1 = OrchestrationRun(
        run_id="run-017",
        project_id="mini-me",
        change_name="017-pwa-control-center",
        base_sha="b7fe685ee72a50e72f385932a9f2efd342359806",
        current_stage=OrchestrationStage.RUNNING_CHECKS,
        is_active=True,
    )
    run2 = OrchestrationRun(
        run_id="run-016",
        project_id="mini-me",
        change_name="016-human-gate-flow",
        base_sha="b7fe685ee72a50e72f385932a9f2efd342359806",
        current_stage=OrchestrationStage.PREPARING_PR,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        is_active=False,
    )
    uow.orchestration_runs.save(run1)
    uow.orchestration_runs.save(run2)

    # 4. Jobs
    job1 = Job(
        job_id="job-017",
        project_id="mini-me",
        change_name="017-pwa-control-center",
        status=JobStatus.CHECKS_RUNNING,
        implementer_role="codex",
        candidate_sha="a1b2c3d4e5f67890123456789abcdef012345678",
        base_sha="b7fe685ee72a50e72f385932a9f2efd342359806",
    )
    job2 = Job(
        job_id="job-016",
        project_id="mini-me",
        change_name="016-human-gate-flow",
        status=JobStatus.NEEDS_HUMAN,
        implementer_role="codex",
        candidate_sha="c1d2e3f4a5b67890123456789abcdef012345678",
        base_sha="b7fe685ee72a50e72f385932a9f2efd342359806",
    )
    uow.jobs.save(job1)
    uow.jobs.save(job2)

    # 5. Candidates
    cand1 = OrchestrationCandidate(
        candidate_id="cand-017-1",
        run_id="run-017",
        generation=1,
        candidate_sha="a1b2c3d4e5f67890123456789abcdef012345678",
        base_sha="b7fe685ee72a50e72f385932a9f2efd342359806",
        manifest_hash="m-hash-017",
        is_frozen=False,
    )
    uow.orchestration_candidates.save(cand1)

    # 6. Checks
    chk1 = CheckResult(
        check_id="chk-1",
        job_id="job-017",
        check_name="ruff-lint",
        command="ruff check .",
        exit_code=0,
        duration_ms=450,
        output_snippet="ruff check passed",
    )
    chk2 = CheckResult(
        check_id="chk-2",
        job_id="job-017",
        check_name="unit-tests",
        command="pytest tests/",
        exit_code=0,
        duration_ms=1200,
        output_snippet="2 passed",
    )
    uow.check_results.save(chk1)
    uow.check_results.save(chk2)

    # 7. Review
    rev = Review(
        review_id="rev-017",
        job_id="job-017",
        project_id="mini-me",
        change_name="017-pwa-control-center",
        reviewer_role="antigravity",
        candidate_sha="a1b2c3d4e5f67890123456789abcdef012345678",
        base_sha="b7fe685ee72a50e72f385932a9f2efd342359806",
        status=ReviewStatus.REVIEW_COMPLETED,
        verdict=ReviewVerdict.READY_TO_MERGE,
        summary="Implementation satisfies all responsive and offline PWA requirements.",
    )
    uow.reviews.save(rev)

    # 8. Audit
    audit = AuditRecord(
        audit_id="aud-017",
        job_id="job-017",
        project_id="mini-me",
        change_name="017-pwa-control-center",
        provider="deepseek",
        model="deepseek-chat",
        candidate_sha="a1b2c3d4e5f67890123456789abcdef012345678",
        base_sha="b7fe685ee72a50e72f385932a9f2efd342359806",
        status=AuditStatus.AUDIT_COMPLETED,
        risk=AuditRiskLevel.LOW,
        summary="Zero security vulnerabilities detected. PWA manifests and static assets verified.",
    )
    uow.audits.save(audit)

    # 9. Preview Session
    prev = PreviewSession(
        preview_id="prev-017",
        project_id="mini-me",
        change_name="017-pwa-control-center",
        run_id="run-017",
        candidate_generation=1,
        head_sha="a1b2c3d4e5f67890123456789abcdef012345678",
        base_sha="b7fe685ee72a50e72f385932a9f2efd342359806",
        image_digest="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        status=PreviewStatus.READY,
        container_id="cont-017",
        port_mappings={"8787/tcp": 38787},
        preview_url="http://127.0.0.1:38787",
        probe_healthy=True,
    )
    uow.preview_sessions.save(prev)

    # 10. Work Queue
    wq1 = WorkQueueItem(
        queue_item_id="wq-1",
        project_id="mini-me",
        change_name="017-pwa-control-center",
        admission_eligible=True,
        priority_score=150,
        base_score=100,
        starvation_aging_bonus=50,
    )
    wq2 = WorkQueueItem(
        queue_item_id="wq-2",
        project_id="mini-me",
        change_name="016-human-gate-flow",
        admission_eligible=False,
        is_blocked=True,
        block_reason="Waiting on human gate approval",
        priority_score=80,
        base_score=80,
    )
    uow.work_queue.save(wq1)
    uow.work_queue.save(wq2)

    # 11. Provider Health
    for p in ("codex", "antigravity"):
        uow.provider_health.save(
            ProviderHealth(
                health_id=f"ph-{p}",
                provider=p,
                status=ProviderHealthStatus.AVAILABLE,
                consecutive_failures=0,
            )
        )

    # 12. Blocker Claims for 016
    claim = BlockerClaim(
        claim_id="claim-016",
        job_id="job-016",
        attempt_id="attempt-016-1",
        blocker_type="HUMAN_GATE",
        blocker_fingerprint="human-gate-016",
        validation_verdict=BlockerValidationVerdict.REAL_BLOCKER,
        rationale="Manual operator verification required before merge.",
    )
    uow.blocker_claims.save(claim)

    return uow


class ChromeCDPClient:
    """Helper client to interact with headless Chrome via Chrome DevTools Protocol."""

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self._msg_id = 0

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=20 * 1024 * 1024)

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def send_cmd(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._msg_id += 1
        msg_id = self._msg_id
        payload = {"id": msg_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))
        while True:
            raw = await self.ws.recv()
            resp = json.loads(raw)
            if resp.get("id") == msg_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP error for {method}: {resp['error']}")
                return resp.get("result", {})

    async def set_viewport(
        self, width: int, height: int, mobile: bool = False, device_scale_factor: float = 1.0
    ):
        await self.send_cmd(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": device_scale_factor,
                "mobile": mobile,
                "screenWidth": width,
                "screenHeight": height,
            },
        )
        await self.send_cmd(
            "Emulation.setVisibleSize",
            {"width": width, "height": height},
        )

    async def navigate(self, url: str):
        await self.send_cmd("Page.enable")
        await self.send_cmd("Page.navigate", {"url": url})
        await asyncio.sleep(1.0)

    async def eval_js(self, expression: str) -> Any:
        res = await self.send_cmd(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        result_obj = res.get("result", {})
        if "value" in result_obj:
            return result_obj["value"]
        return result_obj


@pytest.fixture(scope="module")
def browser_test_env():
    """Starts a local uvicorn server with seeded data and a headless Chrome instance."""
    if not Path(CHROME_BIN).exists():
        pytest.skip(f"Google Chrome not installed at {CHROME_BIN}")

    uow = create_seeded_uow()
    app.dependency_overrides[get_uow] = lambda: uow

    server_port = find_free_port()
    cdp_port = find_free_port()

    # Start Uvicorn in background
    config = uvicorn.Config(
        app, host="127.0.0.1", port=server_port, log_level="warning", loop="asyncio"
    )
    server = uvicorn.Server(config)
    import threading

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait for server to start
    for _ in range(30):
        try:
            r = httpx.get(f"http://127.0.0.1:{server_port}/health", timeout=1.0)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.1)

    # Launch Chrome
    user_data_dir = tempfile.mkdtemp(prefix="minime_chrome_test_")
    chrome_proc = subprocess.Popen(
        [
            CHROME_BIN,
            "--headless=new",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            "--disable-gpu",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for Chrome CDP endpoint
    ws_url = None
    for _ in range(50):
        try:
            r = httpx.put(f"http://127.0.0.1:{cdp_port}/json/new", timeout=1.0)
            if r.status_code == 200:
                ws_url = r.json().get("webSocketDebuggerUrl")
                if ws_url:
                    break
            r2 = httpx.get(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.0)
            if r2.status_code == 200:
                pages = [p for p in r2.json() if p.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
        except Exception:
            time.sleep(0.1)

    assert ws_url is not None, "Failed to connect to Chrome DevTools Protocol"

    yield {
        "server_url": f"http://127.0.0.1:{server_port}",
        "ws_url": ws_url,
        "user_data_dir": user_data_dir,
    }

    # Teardown
    chrome_proc.terminate()
    chrome_proc.wait()
    server.should_exit = True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_real_browser_desktop_standard_inspection(browser_test_env: dict[str, Any]) -> None:
    """Inspect Desktop Standard (~1366x768) viewport layout and responsiveness."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(1366, 768)
        await client.navigate(f"{browser_test_env['server_url']}/")
        await asyncio.sleep(1.2)

        # 1. Verify no horizontal overflow
        overflow = await client.eval_js(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert overflow is True, "Desktop Standard layout exhibits horizontal overflow"

        # 2. Verify KPI cards rendering
        kpi_count = await client.eval_js("document.querySelectorAll('.kpi-card').length")
        assert kpi_count == 4, f"Expected 4 KPI cards, found {kpi_count}"

        # 3. Verify Attention Banner renders for 016 human gate
        attention_display = await client.eval_js(
            "window.getComputedStyle(document.getElementById('attentionBanner')).display"
        )
        assert attention_display != "none", "Attention banner should be visible for human gate"

        # 4. Verify Master-Detail split layout is rendered
        master_displayed = await client.eval_js(
            "document.querySelector('.master-panel').offsetParent !== null"
        )
        detail_displayed = await client.eval_js(
            "document.querySelector('.detail-panel').offsetParent !== null"
        )
        assert master_displayed and detail_displayed, (
            "Master and Detail panels should both be visible"
        )

        # 5. Verify Queue prioritization table
        queue_items = await client.eval_js("document.querySelectorAll('.queue-explain').length")
        assert queue_items >= 2, f"Expected >=2 queue candidates, found {queue_items}"

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_ultrawide_desktop_inspection(browser_test_env: dict[str, Any]) -> None:
    """Inspect Ultrawide (>=1920px / 2560x1440) 3-column split layout eliminating dead space."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(2560, 1440)
        await client.navigate(f"{browser_test_env['server_url']}/")
        await asyncio.sleep(1.0)

        # 1. Verify no horizontal overflow
        overflow = await client.eval_js(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert overflow is True, "Ultrawide desktop layout exhibits horizontal overflow"

        # 2. Verify width utilization: dashboard-main uses full available container width
        main_width = await client.eval_js(
            "document.querySelector('.dashboard-main').getBoundingClientRect().width"
        )
        assert (
            main_width >= 2000
        ), f"Dashboard main width ({main_width}px) does not properly utilize ultrawide viewport"

        # 3. Verify Stepper and tabs
        stepper_steps = await client.eval_js("document.querySelectorAll('.step-item').length")
        assert stepper_steps >= 6, f"Expected 6 pipeline steps, found {stepper_steps}"

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_tablet_inspection(browser_test_env: dict[str, Any]) -> None:
    """Inspect Tablet (~1024x768) 2-column responsive layout with collapsible drawers."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(1024, 768)
        await client.navigate(f"{browser_test_env['server_url']}/")
        await asyncio.sleep(1.0)

        # 1. Verify no horizontal overflow
        overflow = await client.eval_js(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert overflow is True, "Tablet layout exhibits horizontal overflow"

        # 2. Verify detail panel and master panel fit without clipping
        master_rect = await client.eval_js(
            "(() => { const r = document.querySelector('.master-panel').getBoundingClientRect(); return {right: r.right}; })()"
        )
        detail_rect = await client.eval_js(
            "(() => { const r = document.querySelector('.detail-panel').getBoundingClientRect(); return {right: r.right}; })()"
        )
        assert master_rect["right"] <= 1024, "Master panel extends beyond tablet viewport"
        assert detail_rect["right"] <= 1024, "Detail panel extends beyond tablet viewport"

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_mobile_inspection(browser_test_env: dict[str, Any]) -> None:
    """Inspect Mobile (~390x844) single-column layout with sticky header and bottom navigation."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(390, 844, mobile=True)
        await client.navigate(f"{browser_test_env['server_url']}/")
        await asyncio.sleep(1.0)

        # 1. Verify no horizontal overflow
        overflow = await client.eval_js(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        overflow_details = await client.eval_js("""
            Array.from(document.querySelectorAll('*')).filter(el => {
                const r = el.getBoundingClientRect();
                return r.right > 390.5 || r.left < -0.5;
            }).slice(0, 8).map(el => ({tag: el.tagName, id: el.id, cls: el.className, right: el.getBoundingClientRect().right}))
        """)
        assert overflow is True, f"Mobile layout exhibits horizontal overflow: {overflow_details}"

        # 2. Verify sticky top header
        header_position = await client.eval_js(
            "window.getComputedStyle(document.querySelector('.top-nav')).position"
        )
        assert header_position == "sticky", "Top navigation header must be sticky on mobile"

        # 3. Verify bottom navigation bar is visible and displayed
        bottom_nav_display = await client.eval_js(
            "window.getComputedStyle(document.querySelector('.bottom-nav')).display"
        )
        assert bottom_nav_display == "flex", "Bottom navigation bar must be visible on mobile"

        # 4. Verify touch targets meet accessible size (>= 40px min-height)
        touch_heights = await client.eval_js("""
            Array.from(document.querySelectorAll('.bottom-nav button')).map(b => b.getBoundingClientRect().height)
        """)
        assert all(
            h >= 40.0 for h in touch_heights
        ), f"Mobile touch targets too small: {touch_heights}"

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_pwa_manifest_and_sw_inspection(
    browser_test_env: dict[str, Any],
) -> None:
    """Verify W3C Web App Manifest and Service Worker registration in real browser."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(1366, 768)
        await client.navigate(f"{browser_test_env['server_url']}/")
        await asyncio.sleep(1.5)

        # 1. Check <link rel="manifest">
        manifest_href = await client.eval_js(
            "document.querySelector('link[rel=\"manifest\"]')?.href"
        )
        assert (
            manifest_href and "manifest.webmanifest" in manifest_href
        ), f"Manifest link missing: {manifest_href}"

        # 2. Fetch manifest content in browser
        manifest_data = await client.eval_js("""
            fetch(document.querySelector('link[rel="manifest"]').href)
                .then(r => r.json())
        """)
        assert manifest_data["name"] == "mini me Control Center"
        assert manifest_data["display"] == "standalone"
        assert any(icon["sizes"] == "192x192" for icon in manifest_data["icons"])
        assert any(icon["sizes"] == "512x512" for icon in manifest_data["icons"])

        # 3. Check Service Worker support
        has_sw = await client.eval_js("'serviceWorker' in navigator")
        assert has_sw is True, "Service Worker API not available in browser"

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_interactive_features(browser_test_env: dict[str, Any]) -> None:
    """Verify interactive workflows: tab switching, theme toggle, and operator confirmation dialog."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(1366, 768)
        await client.navigate(f"{browser_test_env['server_url']}/")
        await asyncio.sleep(1.2)

        # 1. Theme toggle
        initial_theme = await client.eval_js("document.body.className")
        await client.eval_js("document.getElementById('themeToggleBtn').click()")
        new_theme = await client.eval_js("document.body.className")
        assert new_theme != initial_theme, "Theme toggle button failed to change body class"

        # 2. Tab switching
        await client.eval_js("document.querySelector('button[data-tab=\"checksTab\"]').click()")
        checks_active = await client.eval_js(
            "document.getElementById('checksTab').classList.contains('active')"
        )
        assert checks_active is True, "Clicking Checks tab failed to activate checksTab pane"

        # 3. Candidate Authority Tab
        await client.eval_js("document.querySelector('button[data-tab=\"candidateTab\"]').click()")
        cand_active = await client.eval_js(
            "document.getElementById('candidateTab').classList.contains('active')"
        )
        assert cand_active is True, "Clicking Candidate Authority tab failed to activate pane"

        # 4. Action Confirmation Dialog
        dialog_open = await client.eval_js("""
            (() => {
                const dialog = document.getElementById('actionDialog');
                dialog.showModal();
                return dialog.open;
            })()
        """)
        assert dialog_open is True, "Action confirmation modal dialog failed to open"

        dialog_closed = await client.eval_js("""
            (() => {
                const dialog = document.getElementById('actionDialog');
                dialog.querySelector('[data-cancel]').click();
                return !dialog.open;
            })()
        """)
        assert dialog_closed is True, "Action confirmation modal dialog failed to close on cancel"

    finally:
        await client.close()
