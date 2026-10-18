"""Real browser inspection tests for 017 PWA Control Center across viewports."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
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


def get_chrome_bin() -> str | None:
    candidates = [
        os.environ.get("CHROME_BIN"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


CHROME_BIN = get_chrome_bin()


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
    if not CHROME_BIN or not Path(CHROME_BIN).exists():
        pytest.skip("Google Chrome/Chromium not installed")

    uow = create_seeded_uow()
    app.dependency_overrides[get_uow] = lambda: uow

    from minime.services.auth_service import AuthorizedOperatorService, SessionManager

    op_svc = AuthorizedOperatorService(uow)
    op_svc.seed_operator("operator@example.com", display_name="Lead Operator")
    op_svc.seed_operator("second-operator@example.com", display_name="Second Operator")
    session_mgr = SessionManager(uow)
    raw_token, _ = session_mgr.create_session("operator@example.com")
    second_token, _ = session_mgr.create_session("second-operator@example.com")

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
            "--no-sandbox",
            "--disable-dev-shm-usage",
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
        "session_token": raw_token,
        "second_session_token": second_token,
        "uow": uow,
    }

    # Teardown
    chrome_proc.terminate()
    chrome_proc.wait()
    server.should_exit = True
    app.dependency_overrides.clear()


async def authenticate_browser(
    client: ChromeCDPClient, server_url: str, session_token: str
) -> None:
    await client.navigate(f"{server_url}/")
    await asyncio.sleep(0.3)
    await client.eval_js(f'document.cookie = "minime_session={session_token}; path=/;";')
    await client.navigate(f"{server_url}/")
    await asyncio.sleep(0.8)


@pytest.mark.asyncio
async def test_real_browser_unauthenticated_login_screen(browser_test_env: dict[str, Any]) -> None:
    """Verify that unauthenticated browser requests display the login screen with zero operational telemetry."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        # Clear cookies
        await client.navigate(f"{browser_test_env['server_url']}/")
        await client.eval_js(
            'document.cookie = "minime_session=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";'
        )
        await client.navigate(f"{browser_test_env['server_url']}/")
        await asyncio.sleep(0.8)

        # Login section must be visible
        login_display = await client.eval_js(
            "window.getComputedStyle(document.getElementById('loginSection')).display"
        )
        assert login_display != "none", "Login screen should be visible when unauthenticated"

        # Authenticated content must be hidden
        auth_content_display = await client.eval_js(
            "window.getComputedStyle(document.getElementById('authenticatedContent')).display"
        )
        assert auth_content_display == "none", "Authenticated content must be hidden prior to login"

        # Google login link must point to Google login endpoint
        login_href = await client.eval_js(
            "document.getElementById('googleLoginLink').getAttribute('href')"
        )
        assert "/api/v1/auth/google/login" in login_href

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_desktop_standard_inspection(browser_test_env: dict[str, Any]) -> None:
    """Inspect Desktop Standard (~1366x768) viewport layout and responsiveness."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(1366, 768)
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )

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
            "document.querySelector('#viewExecutions .master-panel').offsetParent !== null"
        )
        detail_displayed = await client.eval_js(
            "document.querySelector('#viewExecutions .detail-panel').offsetParent !== null"
        )
        assert master_displayed and detail_displayed, (
            "Master and Detail panels should both be visible"
        )

        # 5. Verify Queue prioritization table
        queue_items = await client.eval_js(
            "document.querySelectorAll('#queueList .queue-item').length"
        )
        assert queue_items >= 2, f"Expected >=2 queue candidates, found {queue_items}"

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_authenticated_landing_is_operational_center_with_unknown_policy_until_read(
    browser_test_env: dict[str, Any],
) -> None:
    """Initial navigation must not present the backlog or unobserved policy as current."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )
        landing = await client.eval_js(
            "({activeView: document.querySelector('.main-view-pane.active')?.id, "
            "selectedTab: document.querySelector('.main-tab-btn[aria-selected=\\\"true\\\"]')?.id, "
            "autoPrepare: document.getElementById('badgeAutoPrepare').dataset.state, "
            "autoAdmit: document.getElementById('badgeAutoAdmit').dataset.state, "
            "concurrency: document.getElementById('badgeConcurrency').dataset.state})"
        )
        assert landing["activeView"] == "viewExecutions"
        assert landing["selectedTab"] == "navTabExecutions"
        assert landing["autoPrepare"] == "UNKNOWN"
        assert landing["autoAdmit"] == "UNKNOWN"
        assert landing["concurrency"] == "UNKNOWN"

        expected = await client.eval_js(
            "fetch('/api/v1/projects/mini-me', {credentials: 'same-origin', cache: 'no-store'})"
            ".then(response => response.json()).then(project => ({"
            "autoPrepare: `Preparación automática: ${project.auto_prepare ? 'ACTIVADA' : 'DESACTIVADA'}`, "
            "autoAdmit: `Admisión automática: ${project.auto_admit ? 'ACTIVADA' : 'DESACTIVADA'}`, "
            "concurrency: `Concurrencia: ${project.max_concurrent_jobs}`}))"
        )
        await client.eval_js("document.getElementById('navTabBacklog').click()")
        await asyncio.sleep(0.2)
        actual = await client.eval_js(
            "({autoPrepare: document.getElementById('badgeAutoPrepare').textContent, "
            "autoAdmit: document.getElementById('badgeAutoAdmit').textContent, "
            "concurrency: document.getElementById('badgeConcurrency').textContent})"
        )
        assert actual == expected
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_ultrawide_desktop_inspection(browser_test_env: dict[str, Any]) -> None:
    """Inspect Ultrawide (>=1920px / 2560x1440) 3-column split layout eliminating dead space."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(2560, 1440)
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )

        # 1. Verify no horizontal overflow
        overflow = await client.eval_js(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert overflow is True, "Ultrawide desktop layout exhibits horizontal overflow"

        # 2. Verify width utilization: dashboard-main uses full available container width
        main_width = await client.eval_js(
            "document.querySelector('.dashboard-main').getBoundingClientRect().width"
        )
        assert main_width >= 2000, (
            f"Dashboard main width ({main_width}px) does not properly utilize ultrawide viewport"
        )

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
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )

        # 1. Verify no horizontal overflow
        overflow = await client.eval_js(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert overflow is True, "Tablet layout exhibits horizontal overflow"

        # 2. Verify detail panel and master panel fit without clipping
        master_rect = await client.eval_js(
            "(() => { const r = document.querySelector('#viewExecutions .master-panel').getBoundingClientRect(); return {right: r.right}; })()"
        )
        detail_rect = await client.eval_js(
            "(() => { const r = document.querySelector('#viewExecutions .detail-panel').getBoundingClientRect(); return {right: r.right}; })()"
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
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )

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
        assert all(h >= 40.0 for h in touch_heights), (
            f"Mobile touch targets too small: {touch_heights}"
        )

    finally:
        await client.close()


@pytest.mark.asyncio
async def test_control_center_viewport_evidence(browser_test_env: dict[str, Any]) -> None:
    """Capture real-Chrome layout evidence; seeded operational values are test-only."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        from minime.services.auth_service import SessionManager

        session_mgr = SessionManager(browser_test_env["uow"])
        session_token, _ = session_mgr.create_session("operator@example.com")
        await authenticate_browser(client, browser_test_env["server_url"], session_token)
        await client.eval_js("document.getElementById('navTabExecutions').click()")
        evidence_dir = (
            Path(__file__).parents[1]
            / "openspec/changes/pwa-control-center-ux-convergence/evidence/browser"
        )
        evidence_dir.mkdir(parents=True, exist_ok=True)
        viewports = (
            (1440, 900, False, "desktop-1440x900-mock-seeded.png"),
            (1024, 768, False, "tablet-1024x768-mock-seeded.png"),
            (768, 1024, True, "tablet-768x1024-mock-seeded.png"),
            (390, 844, True, "mobile-390x844-mock-seeded.png"),
            (360, 800, True, "mobile-360x800-mock-seeded.png"),
        )
        for width, height, mobile, filename in viewports:
            await client.set_viewport(width, height, mobile=mobile)
            await asyncio.sleep(0.2)
            overflow = await client.eval_js(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            assert overflow is True, f"Horizontal overflow at {width}x{height}"
            if 768 <= width < 1200:
                tablet = await client.eval_js(
                    "(() => { const rail = document.querySelector('.main-nav-tabs'); "
                    "const split = document.querySelector('#viewExecutions .content-split'); "
                    "return {rail: rail.getBoundingClientRect().width, position: getComputedStyle(rail).position, "
                    "display: getComputedStyle(split).display, master: split.querySelector('.master-panel').getBoundingClientRect().left, "
                    "detail: split.querySelector('.detail-panel').getBoundingClientRect().left}; })()"
                )
                assert tablet["rail"] == 64 and tablet["position"] == "fixed", (
                    f"Tablet navigation must use the compact fixed rail: {tablet}"
                )
                assert tablet["display"] == "grid" and tablet["detail"] > tablet["master"], (
                    f"Tablet must preserve master-detail operation: {tablet}"
                )
            if width < 768:
                layout = await client.eval_js(
                    "(() => { const split = document.querySelector('#viewExecutions .content-split'); "
                    "return {display: getComputedStyle(split).display, "
                    "detail: split.querySelector('.detail-panel').getBoundingClientRect().top, "
                    "master: split.querySelector('.master-panel').getBoundingClientRect().top}; })()"
                )
                assert layout["display"] == "flex" and layout["detail"] < layout["master"], (
                    f"Mobile must prioritize the execution detail: {layout}"
                )
                toolbar_visible = await client.eval_js(
                    "getComputedStyle(document.querySelector('#viewExecutions #actionToolbar')).display !== 'none'"
                )
                assert toolbar_visible is False, "Mobile must not expose direct operator actions"
            screenshot = await client.send_cmd(
                "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
            )
            (evidence_dir / filename).write_bytes(base64.b64decode(screenshot["data"]))
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_desktop_layout_preferences_are_bounded_and_operator_scoped(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(1440, 900)
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )

        first_operator = await client.eval_js("""
          (() => {
            const grid = document.querySelector('#viewExecutions .content-split:not(.backlog-split)');
            const separator = document.getElementById('paneSeparator');
            separator.focus();
            separator.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowRight', bubbles:true}));
            const width = parseFloat(getComputedStyle(grid).getPropertyValue('--master-pane-width'));
            const available = grid.clientWidth - 52;
            const keys = Object.keys(localStorage).filter(key => key.startsWith('minime:desktop-layout:v1:'));
            return {width, available, keys, saved: keys.map(key => JSON.parse(localStorage.getItem(key)))};
          })()
        """)
        assert first_operator["width"] >= 240
        assert first_operator["width"] <= first_operator["available"] * 0.7
        assert len(first_operator["keys"]) == 1
        assert "operator@example.com" not in first_operator["keys"][0]
        assert set(first_operator["saved"][0]) == {"version", "ratio", "collapsed"}
        first_key = first_operator["keys"][0]

        await client.eval_js("document.getElementById('collapseMasterPane').click()")
        assert (
            await client.eval_js(
                "document.querySelector('#viewExecutions .content-split').classList.contains('master-collapsed')"
            )
            is True
        )
        await client.eval_js("""
          (async () => {
            const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode('second-operator@example.com'));
            const namespace = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
            localStorage.setItem(`minime:desktop-layout:v1:${namespace}`, JSON.stringify({version:99, ratio:0.99, collapsed:true}));
          })()
        """)
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["second_session_token"]
        )
        second_operator = await client.eval_js("""
          (() => {
            const grid = document.querySelector('#viewExecutions .content-split:not(.backlog-split)');
            const keys = Object.keys(localStorage).filter(key => key.startsWith('minime:desktop-layout:v1:'));
            return {email: document.getElementById('operatorEmailText').textContent,
              collapsed: grid.classList.contains('master-collapsed'), keys,
              width: parseFloat(getComputedStyle(grid).getPropertyValue('--master-pane-width')),
              available: grid.clientWidth - 52,
              saved: keys.map(key => JSON.parse(localStorage.getItem(key)))};
          })()
        """)
        assert second_operator["email"] == "second-operator@example.com", second_operator
        assert second_operator["collapsed"] is False
        assert second_operator["width"] >= 240
        assert second_operator["width"] <= second_operator["available"] * 0.7
        await client.eval_js("""
          (() => {
            const separator = document.getElementById('paneSeparator');
            separator.focus();
            separator.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowLeft', bubbles:true}));
          })()
        """)
        second_keys = await client.eval_js(
            "Object.keys(localStorage).filter(key => key.startsWith('minime:desktop-layout:v1:'))"
        )
        assert len(second_keys) == 2 and first_key in second_keys
        second_key = next(key for key in second_keys if key != first_key)
        await client.eval_js("document.getElementById('resetPaneLayout').click()")
        remaining_keys = await client.eval_js(
            "Object.keys(localStorage).filter(key => key.startsWith('minime:desktop-layout:v1:'))"
        )
        assert remaining_keys == [first_key]

        assert second_key != first_key
        assert all(
            set(item) == {"version", "ratio", "collapsed"} for item in second_operator["saved"]
        )

        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )
        assert (
            await client.eval_js(
                "document.querySelector('#viewExecutions .content-split').classList.contains('master-collapsed')"
            )
            is True
        )
        await client.eval_js("document.getElementById('collapseMasterPane').click()")
        assert (
            await client.eval_js(
                "document.querySelector('#viewExecutions .content-split').classList.contains('master-collapsed')"
            )
            is False
        )
        await client.set_viewport(1024, 768)
        await asyncio.sleep(0.2)
        tablet = await client.eval_js("""
          (() => {
            const grid = document.querySelector('#viewExecutions .content-split:not(.backlog-split)');
            return {collapsed: grid.classList.contains('master-collapsed'),
              customWidth: grid.style.getPropertyValue('--master-pane-width'),
              detailLeft: grid.querySelector('.detail-panel').getBoundingClientRect().left,
              masterLeft: grid.querySelector('.master-panel').getBoundingClientRect().left};
          })()
        """)
        assert tablet["collapsed"] is False
        assert tablet["customWidth"] == ""
        assert tablet["detailLeft"] > tablet["masterLeft"]

        await client.set_viewport(390, 844, mobile=True)
        await asyncio.sleep(0.2)
        mobile = await client.eval_js("""
          (() => {
            const grid = document.querySelector('#viewExecutions .content-split:not(.backlog-split)');
            return {collapsed: grid.classList.contains('master-collapsed'),
              customWidth: grid.style.getPropertyValue('--master-pane-width'),
              display: getComputedStyle(grid).display,
              detailTop: grid.querySelector('.detail-panel').getBoundingClientRect().top,
              masterTop: grid.querySelector('.master-panel').getBoundingClientRect().top};
          })()
        """)
        assert mobile["collapsed"] is False
        assert mobile["customWidth"] == ""
        assert mobile["display"] == "flex" and mobile["detailTop"] < mobile["masterTop"]
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
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )
        await asyncio.sleep(1.5)

        # 1. Check <link rel="manifest">
        manifest_href = await client.eval_js(
            "document.querySelector('link[rel=\"manifest\"]')?.href"
        )
        assert manifest_href and "manifest.webmanifest" in manifest_href, (
            f"Manifest link missing: {manifest_href}"
        )

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
async def test_real_browser_api_cache_isolation_across_operator_sessions(
    browser_test_env: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "true")
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )
        cached = await client.eval_js(
            "Promise.race([navigator.serviceWorker.ready.then(() => 'READY'), new Promise(resolve => setTimeout(() => resolve('TIMEOUT'), 5000))])"
        )
        registration_state = await client.eval_js(
            "navigator.serviceWorker.getRegistration().then(async registration => ({registration: Boolean(registration), installing: registration?.installing?.state || null, waiting: registration?.waiting?.state || null, active: registration?.active?.state || null, workerStatus: await fetch('/sw.js').then(response => response.status)}))"
        )
        failed_assets = []
        cache_add_all_result = None
        if cached != "READY":
            static_root = Path(__file__).parents[1] / "src" / "minime" / "static"
            worker_source = (static_root / "sw.js").read_text(encoding="utf-8")
            match = re.search(r"const SHELL_ASSETS = \[(.*?)\];", worker_source, re.DOTALL)
            paths = re.findall(r'"([^\"]+)"', match.group(1)) if match else []
            cache_add_all_result = await client.eval_js(
                f"Promise.race([caches.open('minime-pwa-diagnostic').then(cache => cache.addAll({json.dumps(paths)}).then(() => 'OK').catch(error => `${{error.name}}: ${{error.message}}`)), new Promise(resolve => setTimeout(() => resolve('TIMEOUT'), 3000))])"
            )
            failed_assets = await client.eval_js(
                f"(async () => {{ const cache = await caches.open('minime-pwa-diagnostic'); const result = await Promise.all({json.dumps(paths)}.map(async path => {{ try {{ const response = await fetch(path); if (!response.ok) throw new Error(`HTTP ${{response.status}}`); await cache.put(path, response.clone()); return null; }} catch (error) {{ return [path, error.name + ': ' + error.message]; }} }})); await caches.delete('minime-pwa-diagnostic'); return result.filter(Boolean); }})()"
            )
        assert cached == "READY", (
            f"Service Worker did not become ready: {cached}; state={registration_state}; addAll={cache_add_all_result}; failed_assets={failed_assets}"
        )
        overview_status = await client.eval_js(
            "fetch('/api/v1/dashboard/overview', {credentials:'same-origin',cache:'no-store'})"
            ".then(response => response.status)"
        )
        assert overview_status == 200
        paths = await client.eval_js("""
            caches.keys().then(async names => {
              const owned = names.filter(name => name.startsWith('minime-pwa-shell-'));
              const entries = await Promise.all(owned.map(async name =>
                (await caches.open(name)).keys().then(requests => requests.map(request => new URL(request.url).pathname))
              ));
              return {owned, paths: entries.flat()};
            })
        """)
        assert paths["owned"]
        assert any(path.startswith("/static/") for path in paths["paths"])
        assert not any(path.startswith("/api/") for path in paths["paths"])

        mutation_status = await client.eval_js("""
          fetch('/api/v1/control-plane/actions/execute', {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'}, body: '{}'
          }).then(response => response.status)
        """)
        assert mutation_status == 422, (
            "Control Plane mutation probe must reach authenticated API validation"
        )

        logout_status = await client.eval_js("""
          (() => new Promise(resolve => {
            const originalFetch = window.fetch.bind(window);
            window.fetch = (input, init) => originalFetch(input, init).then(response => {
              if (String(input).includes('/api/v1/auth/logout')) resolve(response.status);
              return response;
            });
            document.getElementById('logoutBtn').click();
            setTimeout(() => resolve(null), 3000);
          }))()
        """)
        assert logout_status == 200
        expired_status = await client.eval_js(
            "fetch('/api/v1/dashboard/overview', {credentials:'same-origin'}).then(response => response.status)"
        )
        assert expired_status == 401
        from minime.services.auth_service import SessionManager

        unauthorized_token, _ = SessionManager(browser_test_env["uow"]).create_session(
            "not-allowlisted@example.com"
        )
        await client.eval_js(f"document.cookie = 'minime_session={unauthorized_token}; path=/;'")
        forbidden_status = await client.eval_js(
            "fetch('/api/v1/dashboard/overview', {credentials:'same-origin'}).then(response => response.status)"
        )
        assert forbidden_status == 403
        post_logout_paths = await client.eval_js("""
          caches.keys().then(async names => {
            const entries = await Promise.all(names.filter(name => name.startsWith('minime-pwa-shell-')).map(async name =>
              (await caches.open(name)).keys().then(requests => requests.map(request => new URL(request.url).pathname))
            ));
            return entries.flat();
          })
        """)
        assert not any(path.startswith("/api/") for path in post_logout_paths)
        await client.eval_js(
            f"document.cookie = 'minime_session={browser_test_env['second_session_token']}; path=/;'"
        )
        await client.navigate(f"{browser_test_env['server_url']}/")
        await asyncio.sleep(0.3)
        operator = await client.eval_js("document.getElementById('operatorEmailText').textContent")
        assert operator == "second-operator@example.com"
        final_paths = await client.eval_js("""
            caches.keys().then(async names => {
              const entries = await Promise.all(names.filter(name => name.startsWith('minime-pwa-shell-')).map(async name =>
                (await caches.open(name)).keys().then(requests => requests.map(request => new URL(request.url).pathname))
              ));
              return entries.flat();
            })
        """)
        assert not any(path.startswith("/api/") for path in final_paths)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_offline_state_and_reconnection_refresh(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )
        await client.send_cmd("Network.enable", {})
        await client.send_cmd(
            "Network.emulateNetworkConditions",
            {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0},
        )
        await asyncio.sleep(0.2)
        offline = await client.eval_js(
            "({online: navigator.onLine, banner: document.getElementById('offlineBanner').classList.contains('is-visible'), state: document.getElementById('overviewFreshness').dataset.state})"
        )
        assert offline == {"online": False, "banner": True, "state": "STALE"}

        mutation = await client.eval_js("""
          window.__requestCount = 0;
          const originalFetch = window.fetch;
          window.fetch = (...args) => { window.__requestCount += 1; return originalFetch(...args); };
          import('/static/js/services/api_client.js').then(({api}) =>
            api.execute('run-offline-test', {action: 'CONTINUE'})
              .then(() => ({status: 200, requests: window.__requestCount}))
              .catch(error => ({status: error.status, requests: window.__requestCount}))
          )
        """)
        assert mutation == {"status": 503, "requests": 0}

        await client.send_cmd(
            "Network.emulateNetworkConditions",
            {
                "offline": False,
                "latency": 0,
                "downloadThroughput": 10_000_000,
                "uploadThroughput": 10_000_000,
            },
        )
        await asyncio.sleep(0.8)
        recovered = await client.eval_js(
            "({online: navigator.onLine, banner: document.getElementById('offlineBanner').classList.contains('is-visible'), state: document.getElementById('overviewFreshness').dataset.state})"
        )
        assert recovered["online"] is True
        assert recovered["banner"] is False
        assert recovered["state"] == "OBSERVED"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_auth_expiry_hides_operational_state(
    browser_test_env: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "true")
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        from minime.services.auth_service import SessionManager

        session_mgr = SessionManager(browser_test_env["uow"])
        session_token, _ = session_mgr.create_session("operator@example.com")
        await authenticate_browser(client, browser_test_env["server_url"], session_token)
        before = "none"
        for _ in range(20):
            before = await client.eval_js(
                "window.getComputedStyle(document.getElementById('authenticatedContent')).display"
            )
            if before != "none":
                break
            await asyncio.sleep(0.1)
        assert before != "none"

        assert session_mgr.revoke_session_by_token(session_token)
        auth_status = await client.eval_js(
            "fetch('/api/v1/dashboard/overview').then(response => response.status)"
        )
        assert auth_status in {401, 403}
        await client.eval_js("document.getElementById('refreshBtn').click()")
        await asyncio.sleep(0.5)
        state = await client.eval_js(
            "({content: getComputedStyle(document.getElementById('authenticatedContent')).display, login: getComputedStyle(document.getElementById('loginSection')).display, active: document.getElementById('kpiActiveVal').textContent})"
        )
        assert state["content"] == "none"
        assert state["login"] != "none"
        assert state["active"] == "—"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_backlog_view_uses_explicit_evidence_and_escapes_content(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        rendered = await client.eval_js("""
          (async () => {
            const {renderBacklogTable, renderBacklogDetail} = await import('/static/js/views/backlog_view.js');
            const escapeHtml = value => String(value ?? '').replace(/[&<>\"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#039;'}[ch]));
            const table = {innerHTML: ''};
            const item = {item_key:'TASK-1', title:'<script>bad</script>', status:'BACKLOG', priority:'MEDIUM', source:'MANUAL', project_id:'project-1'};
            renderBacklogTable({root:table,items:[item],filter:'ALL',query:'',selectedItem:null,escapeHtml,getStatusBadgeClass:()=>'badge-discovered'});
            const element = () => ({textContent:'',innerHTML:'',className:'',style:{}});
            const elements = Object.fromEntries(['placeholder','content','title','status','priority','key','source','readiness','startButton','needsHumanCard','humanQuestionsList','description','criteria','dorOverall','dorGrid','openSpec','issue','projectItem','run'].map(key => [key,element()]));
            renderBacklogDetail({item,elements,escapeHtml,sanitizeUrl:()=> '#',renderMarkdownText:value=>escapeHtml(value),getStatusBadgeClass:()=>'badge-discovered'});
            return {html:table.innerHTML, dor:elements.dorGrid.innerHTML, overview:elements.dorOverall.textContent};
          })()
        """)
        assert "&lt;script&gt;bad&lt;/script&gt;" in rendered["html"]
        assert "<script>" not in rendered["html"]
        assert 'data-backlog-action="prepare"' in rendered["html"]
        assert 'data-state="unknown"' in rendered["dor"]
        assert "Definición de Ready satisfecha" in rendered["dor"]
        assert rendered["overview"] == "ESTADO DESCONOCIDO"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_candidate_review_and_check_views_preserve_identity_states(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        rendered = await client.eval_js("""
          (async () => {
            const views = await import('/static/js/views/evidence_views.js');
            const node = () => ({innerHTML:'',textContent:'',style:{}});
            const review = node(), audit = node(), candidate = node(), history = node(), checks = node(), count = node();
            views.renderReviewEvidence({container:review,review:{status:'completed',verdict:'READY_FOR_HUMAN_MERGE',candidate_sha:'old-sha'},candidate:{candidate_sha:'new-sha'}});
            views.renderAuditEvidence({container:audit,audit:{status:'completed',risk:null,findings:[]},candidate:{candidate_sha:'new-sha'}});
            views.renderCandidateEvidence({summary:candidate,history,detail:{candidate_authority:null,candidate_history:[]}});
            views.renderChecksEvidence({count,container:checks,checks:null});
            return {review:review.innerHTML,audit:audit.innerHTML,candidate:candidate.innerHTML,checks:checks.innerHTML,count:count.textContent};
          })()
        """)
        assert "OBSOLETA" in rendered["review"]
        assert 'class="badge badge-ready"' not in rendered["review"]
        assert "DESCONOCIDA" in rendered["audit"]
        assert "RIESGO: UNKNOWN" in rendered["audit"]
        assert "No hay una generación de candidato finalizada" in rendered["candidate"]
        assert "No hay resultados de verificaciones determinísticas" in rendered["checks"]
        assert rendered["count"] == "—"
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


@pytest.mark.asyncio
async def test_real_browser_020_operator_tabs_and_param_modals(
    browser_test_env: dict[str, Any],
) -> None:
    """Verify 020 Efficiency Tab, Action History Tab, and Action Param Dialog."""
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(1920, 1080)
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )

        # 1. Efficiency Tab
        await client.eval_js("document.querySelector('button[data-tab=\"efficiencyTab\"]').click()")
        eff_active = await client.eval_js(
            "document.getElementById('efficiencyTab').classList.contains('active')"
        )
        assert eff_active is True, "Clicking Efficiency tab failed to activate efficiencyTab pane"

        # 2. Action History Tab
        await client.eval_js(
            "document.querySelector('button[data-tab=\"actionHistoryTab\"]').click()"
        )
        history_active = await client.eval_js(
            "document.getElementById('actionHistoryTab').classList.contains('active')"
        )
        assert history_active is True, (
            "Clicking Action History tab failed to activate actionHistoryTab pane"
        )

        # 3. Action Param Dialog
        param_dialog_open = await client.eval_js("""
            (() => {
                const dialog = document.getElementById('actionParamDialog');
                dialog.showModal();
                return dialog.open;
            })()
        """)
        assert param_dialog_open is True, "Action param dialog failed to open"

        param_dialog_closed = await client.eval_js("""
            (() => {
                const dialog = document.getElementById('actionParamDialog');
                dialog.querySelector('[data-param-cancel]').click();
                return !dialog.open;
            })()
        """)
        assert param_dialog_closed is True, "Action param dialog failed to close on cancel"

    finally:
        await client.close()
