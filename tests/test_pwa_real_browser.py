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
    ProjectBinding,
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
    for change_name in (c1.name, c2.name, c3.name):
        uow.bindings.save(
            ProjectBinding(
                project_id="mini-me",
                repository="silverberdi/mini-me",
                openspec_change_name=change_name,
            )
        )

    # 3. Runs
    run1 = OrchestrationRun(
        run_id="run-017",
        project_id="mini-me",
        change_name="017-pwa-control-center",
        base_sha="b7fe685ee72a50e72f385932a9f2efd342359806",
        current_stage=OrchestrationStage.RUNNING_CHECKS,
        active_job_id="job-017",
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
        repository_identity = await client.eval_js("""
            ({name: document.getElementById('dtRepository').textContent,
              state: document.getElementById('dtRepository').dataset.state})
        """)
        assert repository_identity == {"name": "silverberdi/mini-me", "state": "VALID"}

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
        # This module-scoped browser fixture is shared by later tests. Logout
        # correctly revokes its original token, so rotate the fixture's token
        # to a newly issued session rather than letting later cases inherit a
        # revoked credential and mistake the authenticated dashboard for an
        # overview rendering regression.
        from minime.services.auth_service import SessionManager

        next_token, _ = SessionManager(browser_test_env["uow"]).create_session(
            "operator@example.com"
        )
        browser_test_env["session_token"] = next_token
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
async def test_real_browser_lifecycle_controller_has_one_refresh_and_listener_owner(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )
        result = await client.eval_js("""
          (async () => {
            const {createLifecycleController} = await import('/static/js/controllers/lifecycle_controller.js');
            class Events {
              listeners = new Map();
              addEventListener(name, handler) {
                const registered = this.listeners.get(name) || [];
                registered.push(handler);
                this.listeners.set(name, registered);
              }
              dispatch(name, event = {}) { (this.listeners.get(name) || []).forEach(handler => handler(event)); }
              count(name) { return (this.listeners.get(name) || []).length; }
            }
            const windowRef = new Events();
            let timerCallback;
            let nextTimer = 0;
            let clears = 0;
            windowRef.setInterval = callback => { timerCallback = callback; return ++nextTimer; };
            windowRef.clearInterval = () => { clears += 1; };
            const documentRef = new Events();
            documentRef.hidden = false;
            const values = new Map();
            const storage = {getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value)};
            const refreshButton = new Events();
            const refreshIntervalSelect = new Events();
            refreshIntervalSelect.value = '10';
            const autoRefreshToggle = new Events();
            autoRefreshToggle.checked = true;
            const refreshTimer = {textContent: ''};
            let refreshCurrent = 0;
            let refreshOverview = 0;
            let reconnect = 0;
            let offline = 0;
            let stale = 0;
            const controller = createLifecycleController({
              windowRef, documentRef,
              refreshCurrentView: () => { refreshCurrent += 1; },
              refreshAfterReconnect: () => { reconnect += 1; },
              refreshOverview: () => { refreshOverview += 1; },
              setOfflineBanner: value => { offline += value ? 1 : -1; },
              markFreshnessStale: () => { stale += 1; },
              getCurrentView: () => 'viewExecutions',
              onResize: () => {}, refreshButton, refreshIntervalSelect, autoRefreshToggle,
              refreshTimer, storage,
            });
            controller.bind();
            controller.bind();
            controller.start();
            controller.start();
            const listenerCounts = {
              online: windowRef.count('online'), offline: windowRef.count('offline'),
              visibility: documentRef.count('visibilitychange'), refresh: refreshButton.count('click'),
            };
            refreshButton.dispatch('click');
            windowRef.dispatch('offline');
            windowRef.dispatch('online');
            documentRef.hidden = true;
            documentRef.dispatch('visibilitychange');
            const hiddenCountdown = refreshTimer.textContent;
            documentRef.hidden = false;
            documentRef.dispatch('visibilitychange');
            const visibleCountdown = refreshTimer.textContent;
            autoRefreshToggle.checked = false;
            autoRefreshToggle.dispatch('change');
            const stoppedLabel = refreshTimer.textContent;
            autoRefreshToggle.checked = true;
            autoRefreshToggle.dispatch('change');
            refreshIntervalSelect.value = '30';
            refreshIntervalSelect.dispatch('change', {target: refreshIntervalSelect});
            const persistedInterval = values.get('minime_dashboard_interval');
            refreshIntervalSelect.value = '999';
            refreshIntervalSelect.dispatch('change', {target: refreshIntervalSelect});
            const rejectedInterval = refreshIntervalSelect.value;
            const beforeHiddenTick = refreshOverview;
            documentRef.hidden = true;
            timerCallback();
            const hiddenTickDidNotRefresh = refreshOverview === beforeHiddenTick;
            controller.stop();
            return {
              listenerCounts, refreshCurrent, reconnect, offline, stale, hiddenCountdown,
              visibleCountdown, stoppedLabel, persistedInterval, rejectedInterval,
              hiddenTickDidNotRefresh, clears, activeView: 'viewExecutions',
            };
          })()
        """)
        assert result["listenerCounts"] == {
            "online": 1,
            "offline": 1,
            "visibility": 1,
            "refresh": 1,
        }
        assert result["refreshCurrent"] == 1
        assert result["reconnect"] == 1
        assert result["offline"] == 0
        assert result["stale"] == 1
        assert result["hiddenCountdown"] == "10s"
        assert result["visibleCountdown"] == "10s"
        assert result["stoppedLabel"] == "desactivada"
        assert result["persistedInterval"] == "30"
        assert result["rejectedInterval"] == "30"
        assert result["hiddenTickDidNotRefresh"] is True
        assert result["clears"] >= 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_projects_domain_navigation_and_context_use_authoritative_api(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )
        await client.eval_js("document.getElementById('navTabProjects').click()")
        await asyncio.sleep(0.25)
        project = await client.eval_js("""
          (() => {
            const card = document.querySelector('#projectsGridContainer .project-card');
            return {
              title: card?.querySelector('.project-name')?.textContent,
              repository: card?.querySelector('.meta-row .font-mono')?.textContent,
              actions: [...(card?.querySelectorAll('[data-project-action]') || [])].map(button => button.dataset.projectAction),
              selectedProject: document.getElementById('projectSelect').value,
            };
          })()
        """)
        assert project["title"] == "mini me"
        assert project["repository"] == "silverberdi/mini-me"
        assert project["actions"] == ["inspect", "discover", "backlog"]
        assert project["selectedProject"] == "mini-me"

        await client.eval_js("document.querySelector('[data-project-action=backlog]').click()")
        await asyncio.sleep(0.2)
        selected_view = await client.eval_js("""
          ({
            backlogActive: document.getElementById('viewBacklog').classList.contains('active'),
            selectedProject: document.getElementById('projectSelect').value,
            displayedProject: document.getElementById('backlogProjectDisplay').textContent,
          })
        """)
        assert selected_view["backlogActive"] is True
        assert selected_view["selectedProject"] == "mini-me"
        assert selected_view["displayedProject"] == "Proyecto: mini-me"

        await client.eval_js("document.getElementById('logoutBtn').click()")
        await asyncio.sleep(0.1)
        cleared = await client.eval_js("""
          (() => ({
            loginVisible: document.getElementById('loginSection').style.display !== 'none',
            selectedProject: document.getElementById('projectSelect').value,
            projectCards: document.querySelectorAll('#projectsGridContainer .project-card').length,
            backlogText: document.getElementById('backlogTableBody').textContent,
            backlogPrivateTitle: document.getElementById('bkTitle').textContent,
          }))()
        """)
        assert cleared["loginVisible"] is True
        assert cleared["selectedProject"] == ""
        assert cleared["projectCards"] == 0
        assert "selecciona un proyecto autorizado" in cleared["backlogText"].lower()
        assert cleared["backlogPrivateTitle"] == "—"
        # This module-scoped browser fixture is shared by later tests. The
        # logout above correctly revokes its original session; issue a fresh
        # test session only after asserting that protected state was cleared.
        from minime.services.auth_service import SessionManager

        next_token, _ = SessionManager(browser_test_env["uow"]).create_session(
            "operator@example.com"
        )
        browser_test_env["session_token"] = next_token
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_backlog_controller_owns_work_item_form_and_submission(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        result = await client.eval_js("""
          (async () => {
            const {createBacklogController} = await import('/static/js/controllers/backlog_controller.js');
            const modal = document.createElement('dialog');
            const form = document.createElement('form');
            const button = document.createElement('button');
            const field = () => document.createElement('input');
            const title = field();
            const key = field();
            const priority = field();
            const description = field();
            const criteria = document.createElement('textarea');
            const heading = document.createElement('h2');
            const submit = document.createElement('button');
            submit.type = 'submit';
            form.append(title,key,priority,description,criteria,submit);
            modal.append(heading,form);
            document.body.append(modal);
            const calls = {requests:[],selected:[],notices:[]};
            const tableBody = document.createElement('tbody');
            const placeholder = document.createElement('div');
            const detailContent = document.createElement('section');
            const controller = createBacklogController({
              fetchRequest: async (url,init) => {
                calls.requests.push({url,init});
                const body = init?.method === 'POST'
                  ? {item_key:'new-work'}
                  : url.endsWith('/backlog')
                    ? [{item_key:'new-work',title:'A bounded operational item',priority:'HIGH',status:'BACKLOG',acceptance_criteria:['first condition','second condition']}]
                    : {auto_prepare:false,auto_admit:false,max_concurrent_jobs:2};
                return {ok:true,status:200,json:async () => body};
              },
              notify: (message,kind) => calls.notices.push({message,kind}),
              getProjectId: () => 'project-bound',
              refreshProjects: async () => {}, onUnauthorized: () => {}, onStarted: () => {}, confirmAction: () => true,
              escapeHtml: value => String(value ?? ''), sanitizeUrl: value => value,
              getStatusBadgeClass: () => 'badge-muted', onOpenRun: () => {},
              elements:{tableBody,placeholder,detail:{content:detailContent}},
              workItemForm:{modal,form,title:heading,itemTitle:title,itemKey:key,priority,description,criteria},
            });
            const eventBindings = {
              searchInput:null,statusPills:[],tableBody,newItemButton:button,cancelButton:null,
              itemModal:modal,itemForm:form,discoverButton:null,prepareButton:null,startButton:null,
              editButton:null,deleteButton:null,answerForm:null,answerInput:null,runArtifact:null,
              clearAnswer:()=>{},
            };
            controller.bindEvents(eventBindings);
            controller.bindEvents(eventBindings);
            button.click();
            title.value = 'A bounded operational item';
            key.value = 'bounded-item';
            priority.value = 'HIGH';
            description.value = 'deterministic description';
            criteria.value = '- first condition\\n- second condition';
            form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
            await new Promise(resolve => setTimeout(resolve,20));
            const call = calls.requests[0];
            return {calls,heading:heading.textContent,modalOpen:modal.open,payload:JSON.parse(call.init.body),selected:controller.getSelectedItem()?.item_key};
          })()
        """)
        assert result["heading"] == "Crear trabajo"
        assert result["selected"] == "new-work"
        assert [call["url"] for call in result["calls"]["requests"]] == [
            "/api/v1/projects/project-bound/backlog",
            "/api/v1/projects/project-bound",
            "/api/v1/projects/project-bound/backlog",
        ]
        assert result["calls"]["requests"][0]["url"] == "/api/v1/projects/project-bound/backlog"
        assert result["payload"] == {
            "item_key": "bounded-item",
            "title": "A bounded operational item",
            "priority": "HIGH",
            "description": "deterministic description",
            "acceptance_criteria": ["first condition", "second condition"],
        }
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_backlog_clarification_submits_question_and_answer_to_authority(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        result = await client.eval_js("""
          (async () => {
            const {createBacklogController} = await import('/static/js/controllers/backlog_controller.js');
            const question = 'Which supported base branch should this use?';
            let current = {item_key:'needs-clarification',title:'Clarify an intake decision',status:'NEEDS_HUMAN',human_questions:[question],description:'The base branch is ambiguous.'};
            const calls = [];
            const fetchRequest = async (url, init={}) => {
              calls.push({url,init});
              if (url.endsWith('/projects/project-bound')) return {ok:true,json:async()=>({auto_prepare:false,auto_admit:false,max_concurrent_jobs:2})};
              if (url.endsWith('/backlog') && !init.method) return {ok:true,json:async()=>[current]};
              if (url.endsWith('/answer') && init.method === 'POST') {
                const payload = JSON.parse(init.body);
                current = {...current,status:'PREPARING',human_questions:[],human_answers:[payload]};
                return {ok:true,json:async()=>current};
              }
              throw new Error(`Unexpected request ${init.method || 'GET'} ${url}`);
            };
            const form = document.createElement('form');
            const answerInput = document.createElement('textarea');
            const answerTarget = document.createElement('input');
            const tableBody = document.createElement('tbody');
            const placeholder = document.createElement('div');
            const content = document.createElement('section');
            const notices = [];
            const controller = createBacklogController({
              fetchRequest, notify:(message,kind)=>notices.push({message,kind}),
              getProjectId:()=> 'project-bound', refreshProjects:async()=>{}, onUnauthorized:()=>{},
              onStarted:()=>{}, confirmAction:()=>true, escapeHtml:value=>String(value??''),
              sanitizeUrl:value=>value, getStatusBadgeClass:()=> 'badge-muted', onOpenRun:()=>{},
              elements:{tableBody,placeholder,detail:{content,answerTarget}}, workItemForm:null,
            });
            await controller.load();
            controller.bindEvents({searchInput:null,statusPills:[],tableBody,newItemButton:null,cancelButton:null,itemModal:null,itemForm:null,discoverButton:null,prepareButton:null,startButton:null,editButton:null,deleteButton:null,answerForm:form,answerInput,answerTarget,runArtifact:null,clearAnswer:()=>{answerInput.value='';answerTarget.value='';}});
            answerInput.value = 'Use main after confirming the repository binding.';
            form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
            for (let index=0; index<20 && controller.getSelectedItem()?.status !== 'PREPARING'; index++) await new Promise(resolve=>setTimeout(resolve,10));
            const posted = calls.find(call=>call.url.endsWith('/answer'));
            return {questionTarget:answerTarget.value,payload:posted && JSON.parse(posted.init.body),status:controller.getSelectedItem()?.status,notices};
          })()
        """)
        assert result["payload"] == {
            "question": "Which supported base branch should this use?",
            "answer": "Use main after confirming the repository binding.",
        }
        assert result["status"] == "PREPARING"
        assert result["questionTarget"] == ""
        assert result["notices"][-1]["message"].startswith("Aclaración registrada")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_status_view_keeps_authoritative_states_distinct(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        states = [
            "RUNNING",
            "PAUSED",
            "WAITING_CAPACITY",
            "NEEDS_HUMAN",
            "UNKNOWN",
            "AUTH_REQUIRED",
            "RECOVERY",
            "READY_FOR_HUMAN_MERGE",
        ]
        rendered = await client.eval_js(f"""
          (async () => {{
            const {{getStatusBadgeClass}} = await import('/static/js/views/status_view.js');
            const {{renderChangesView}} = await import('/static/js/views/runs_view.js');
            const root = document.createElement('tbody');
            const states = {json.dumps(states)};
            renderChangesView({{
              root,
              changes: states.map((status, index) => ({{project_id:'p',change_name:`c-${{index}}`,status}})),
              filter: 'ALL', query: '', selected: null, alreadyAutoSelected: true,
              statusClass: getStatusBadgeClass, formatTime: () => 'hace 0 s', onSelect: () => {{}}
            }});
            return [...root.querySelectorAll('tr[data-project-id]')].map(row => ({{
              status: row.querySelector('.badge').textContent,
              className: row.querySelector('.badge').className,
            }}));
          }})()
        """)
        assert [item["status"] for item in rendered] == states
        by_state = {item["status"]: item["className"] for item in rendered}
        assert "badge-paused" in by_state["PAUSED"]
        assert "badge-unknown" in by_state["UNKNOWN"]
        assert "badge-recovery" in by_state["RECOVERY"]
        assert "badge-needs-human" in by_state["AUTH_REQUIRED"]
        # Text remains the canonical backend state even where visual tokens share a color family.
        assert by_state["WAITING_CAPACITY"] != by_state["RUNNING"]
        assert by_state["READY_FOR_HUMAN_MERGE"] != by_state["NEEDS_HUMAN"]
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
async def test_real_browser_action_controller_refreshes_the_selected_snake_case_identity(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        result = await client.eval_js("""
          (async () => {
            const { createActionController, visibleControlPlaneActions } = await import('/static/js/controllers/action_controller.js');
            const calls = { request: null, notices: [], overview: 0, detail: [] };
            const controller = createActionController({
              execute: async (runId, request) => { calls.request = {runId, request}; return {status:'ACCEPTED'}; },
              notify: (message, kind) => calls.notices.push({message, kind}),
              refreshOverview: async () => { calls.overview += 1; },
              refreshSelectedDetail: async () => { calls.detail.push(['project-real', 'change-real']); },
              getActor: () => 'operator@example.test',
            });
            await controller.executeAction({
              run_id:'run-exact', project_id:'project-real', change_name:'change-real',
              current_stage:'IMPLEMENTING', candidate_authority:{generation:4,candidate_sha:'candidate-sha'},
            }, 'CONTINUE');
            return {
              calls,
              visibleActions: visibleControlPlaneActions([
                {action:'CONTINUE', enabled:true},
                {action:'MERGE', enabled:true},
                {action_type:'merge_pull_request', enabled:true},
              ]).map(action => action.action || action.action_type),
            };
          })()
        """)
        calls = result["calls"]
        assert calls["request"]["runId"] == "run-exact"
        assert calls["request"]["request"]["project_id"] == "project-real"
        assert calls["request"]["request"]["change_name"] == "change-real"
        assert calls["request"]["request"]["expected_generation"] == 4
        assert calls["request"]["request"]["expected_candidate_sha"] == "candidate-sha"
        assert calls["overview"] == 1
        assert calls["detail"] == [["project-real", "change-real"]]
        assert calls["notices"][-1]["kind"] == "success"
        assert result["visibleActions"] == ["CONTINUE"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_action_controller_owns_discovery_toolbar_and_single_listener(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        result = await client.eval_js("""
          (async () => {
            const {createActionController} = await import('/static/js/controllers/action_controller.js');
            const toolbar = document.createElement('div');
            const calls = {discovery: [], execution: []};
            let releaseStaleDiscovery;
            const detail = {run_id:'run-owned', project_id:'project-real', change_name:'change-real', current_stage:'IMPLEMENTING'};
            const controller = createActionController({
              toolbar,
              discover: async runId => {
                calls.discovery.push(runId);
                if (runId === 'run-stale') return new Promise(resolve => { releaseStaleDiscovery = resolve; });
                if (runId === 'run-current') return [{action:'CONTINUE', enabled:true, display_name:'Actual'}];
                return [
                  {action:'CONTINUE', enabled:true, display_name:'Continuar'},
                  {action:'MERGE', enabled:true, display_name:'No debe mostrarse'},
                ];
              },
              execute: async (runId, request) => { calls.execution.push({runId, request}); return {status:'ACCEPTED'}; },
              notify: () => {}, refreshOverview: async () => {}, refreshSelectedDetail: async () => {},
              getActor: () => 'operator@example.test',
            });
            controller.bindToolbar();
            controller.bindToolbar();
            await controller.renderToolbar(detail);
            const buttons = [...toolbar.querySelectorAll('[data-action]')].map(button => button.dataset.action);
            toolbar.querySelector('[data-action="CONTINUE"]').click();
            await new Promise(resolve => setTimeout(resolve, 0));
            const staleRender = controller.renderToolbar({...detail, run_id:'run-stale'});
            await Promise.resolve();
            await controller.renderToolbar({...detail, run_id:'run-current'});
            releaseStaleDiscovery([{action:'CANCEL', enabled:true, display_name:'Obsoleta'}]);
            await staleRender;
            return {
              calls, buttons,
              buttonsAfterRace:[...toolbar.querySelectorAll('[data-action]')].map(button => button.dataset.action),
            };
          })()
        """)
        assert result["calls"]["discovery"] == ["run-owned", "run-stale", "run-current"]
        assert result["buttons"] == ["CONTINUE"]
        assert len(result["calls"]["execution"]) == 1
        request = result["calls"]["execution"][0]["request"]
        assert request["project_id"] == "project-real"
        assert request["change_name"] == "change-real"
        assert request["run_id"] == "run-owned"
        assert request["action_type"] == "CONTINUE"
        assert result["buttonsAfterRace"] == ["CONTINUE"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_toast_controller_owns_safe_message_and_single_timer(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        outcome = await client.eval_js("""
          (async () => {
            const {createToastController} = await import('/static/js/components/toast.js');
            const toast = document.getElementById('toastNotification') || document.createElement('div');
            if (!toast.isConnected) {
              toast.id = 'toastNotification';
              document.body.appendChild(toast);
            }
            const timers = new Map();
            const cleared = [];
            let nextTimer = 0;
            const windowRef = {
              setTimeout(callback, delay) { const id = ++nextTimer; timers.set(id, {callback, delay}); return id; },
              clearTimeout(id) { cleared.push(id); timers.delete(id); },
            };
            const showToast = createToastController({documentRef: document, windowRef});
            showToast('<img src=x onerror=alert(1)>', 'error');
            const firstText = toast.textContent;
            const firstHtml = toast.innerHTML;
            showToast('Actualizado', 'success');
            return {
              firstText, firstHtml, text:toast.textContent, className:toast.className,
              display:toast.style.display, timerCount:timers.size,
              timerDelay:[...timers.values()][0]?.delay, cleared,
            };
          })()
        """)
        assert outcome["firstText"] == "<img src=x onerror=alert(1)>"
        assert "<img" not in outcome["firstHtml"]
        assert outcome["text"] == "Actualizado"
        assert outcome["className"] == "toast-notification toast-success"
        assert outcome["display"] == "block"
        assert outcome["timerCount"] == 1
        assert outcome["timerDelay"] == 4000
        assert outcome["cleared"] == [1]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_execution_view_controller_ignores_stale_change_detail_response(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        result = await client.eval_js("""
          (async () => {
            const {createExecutionViewController} = await import('/static/js/controllers/execution_view_controller.js');
            const content = document.createElement('section');
            const placeholder = document.createElement('div');
            const rendered = [];
            let releaseOld;
            const controller = createExecutionViewController({
              fetchRequest: url => url.includes('/old-change')
                ? new Promise(resolve => { releaseOld = resolve; })
                : Promise.resolve({ok:true,status:200,json:async () => ({project_id:'project',change_name:'new-change'})}),
              elements:{detailContent:content,detailPlaceholder:placeholder},
              setOfflineBanner:()=>{},onUnauthorized:()=>{},getNavigationState:()=>null,
              renderDetail:detail=>rendered.push(detail.change_name),statusClass:()=>'',formatRelativeTime:()=>'',
            });
            controller.selectChange('project','old-change');
            await Promise.resolve();
            controller.selectChange('project','new-change');
            await new Promise(resolve => setTimeout(resolve,0));
            releaseOld({ok:true,status:200,json:async () => ({project_id:'project',change_name:'old-change'})});
            await new Promise(resolve => setTimeout(resolve,0));
            return {rendered,selected:controller.selectedChange};
          })()
        """)
        assert result == {
            "rendered": ["new-change"],
            "selected": {"project_id": "project", "change_name": "new-change"},
        }
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_detail_telemetry_ignores_responses_for_previous_selection(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        outcome = await client.eval_js("""
          (async () => {
            const {createDetailTelemetryController} = await import('/static/js/controllers/detail_telemetry_controller.js');
            const efficiency = document.createElement('div');
            const history = document.createElement('div');
            let finishOldEfficiency;
            let finishOldHistory;
            const controller = createDetailTelemetryController({
              efficiencyContainer: efficiency,
              historyContainer: history,
              formatTimestamp: value => value || '—',
              fetchRequest: url => {
                if (url.includes('/old-change')) return new Promise(resolve => { finishOldEfficiency = resolve; });
                return Promise.resolve({ok:true,json:async () => ({total_attempts:2, primary_model:'new-model', evaluated_at:'now'})});
              },
              loadActionHistory: runId => runId === 'old-run'
                ? new Promise(resolve => { finishOldHistory = resolve; })
                : Promise.resolve([{action_type:'CONTINUE', actor_identity:'new-operator', status:'SUCCESS'}]),
            });
            const oldRender = controller.renderFor({project_id:'p',change_name:'old-change',run_id:'old-run'});
            await Promise.resolve();
            await controller.renderFor({project_id:'p',change_name:'new-change',run_id:'new-run'});
            finishOldEfficiency({ok:true,json:async () => ({total_attempts:999,primary_model:'stale-model'})});
            finishOldHistory([{action_type:'STALE_ACTION',actor_identity:'stale-operator',status:'SUCCESS'}]);
            await oldRender;
            return {efficiency:efficiency.textContent,history:history.textContent,html:efficiency.innerHTML};
          })()
        """)
        assert "new-model" in outcome["efficiency"]
        assert "999" not in outcome["efficiency"]
        assert "new-operator" in outcome["history"]
        assert "stale-operator" not in outcome["history"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_preview_controller_requires_exact_preview_and_records_completed_scenarios(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.navigate(f"{browser_test_env['server_url']}/")
        outcome = await client.eval_js("""
          (async () => {
            const { createPreviewController } = await import('/static/js/controllers/preview_controller.js');
            const calls = { requests: [], notices: [] };
            const controller = createPreviewController({
              fetchRequest: async (url, init) => {
                calls.requests.push({url, init});
                return {ok:true, json:async () => ({validation_id:'validation-1'})};
              },
              notify: (message, kind) => calls.notices.push({message, kind}),
              refresh: async () => {},
              getActor: () => 'authenticated@example.test',
            });
            const detail = {project_id:'p-1', change_name:'change-1', run_id:'run-1'};
            const candidate = {head_sha:'head-1', base_sha:'base-1', generation:2};
            const session = {preview_id:'preview-1', head_sha:'head-1', base_sha:'base-1', candidate_generation:2, image_digest:'sha256:image', status:'READY'};
            const container = {querySelectorAll: (selector) => selector === '.scenario-step-check' ? [{dataset:{scenarioId:'s-1'},checked:true}] : []};
            await controller.submitValidation({detail,session,candidate,scenarios:[{scenario_id:'s-1',required:true}],container,verdict:'PASS',notes:'verified',allowed:true});
            const afterValid = calls.requests.length;
            await controller.submitValidation({detail,session:{...session,head_sha:'old-head'},candidate,scenarios:[],container,verdict:'PASS',notes:'stale',allowed:true});
            return {calls, afterValid};
          })()
        """)
        assert outcome["afterValid"] == 1
        assert len(outcome["calls"]["requests"]) == 1
        payload = json.loads(outcome["calls"]["requests"][0]["init"]["body"])
        assert payload["project_id"] == "p-1"
        assert payload["head_sha"] == "head-1"
        assert payload["base_sha"] == "base-1"
        assert payload["candidate_generation"] == 2
        assert payload["image_digest"] == "sha256:image"
        assert payload["scenario_results"] == [{"scenario_id": "s-1", "status": "PASS"}]
        assert "operator" not in payload
        assert "no corresponde exactamente" in outcome["calls"]["notices"][-1]["message"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_selected_change_renders_candidate_bound_preview_and_detail_tabs(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )
        detail = await client.eval_js(
            "fetch('/api/v1/dashboard/changes/mini-me/017-pwa-control-center', {cache:'no-store'}).then(r => r.json())"
        )
        assert detail["project_id"] == "mini-me"
        assert detail["change_name"] == "017-pwa-control-center"
        assert detail["preview_validation"]["preview_session"]["candidate_generation"] == 1
        assert (
            detail["preview_validation"]["preview_session"]["head_sha"]
            == detail["candidate_authority"]["candidate_sha"]
        )

        row_clicked = False
        for _ in range(20):
            row_clicked = await client.eval_js("""
              (() => {
                const row = [...document.querySelectorAll('#changesTableBody tr[data-project-id]')]
                  .find(item => item.dataset.projectId === 'mini-me' && item.dataset.changeName === '017-pwa-control-center');
                if (!row) return false;
                row.click();
                return true;
              })()
            """)
            if row_clicked:
                break
            await asyncio.sleep(0.1)
        assert row_clicked is True, await client.eval_js("""
          ({view: document.querySelector('.main-view-pane.active')?.id,
            operator: document.getElementById('operatorEmailText')?.textContent,
            rows: document.getElementById('changesTableBody')?.innerText,
            errors: window.__pwaErrors || []})
        """)

        selected = None
        for _ in range(20):
            selected = await client.eval_js("""
              ({project: document.getElementById('dtProject').textContent,
                change: document.getElementById('dtChangeName').textContent})
            """)
            if selected["project"] == "mini-me" and selected["change"] == "017-pwa-control-center":
                break
            await asyncio.sleep(0.1)
        assert selected == {"project": "mini-me", "change": "017-pwa-control-center"}

        has_candidate = await client.eval_js(
            "document.getElementById('candidateDetailsContainer').textContent.length > 0"
        )
        assert has_candidate is True

        identity = await client.eval_js("""
          ({
            project: document.getElementById('dtProject').textContent,
            repository: document.getElementById('dtRepository').textContent,
            change: document.getElementById('dtChangeName').textContent,
            run: document.getElementById('overviewMetaGrid').textContent,
            job: document.getElementById('overviewMetaGrid').textContent,
            generation: document.getElementById('dtGeneration').textContent,
            candidate: document.getElementById('dtCandidateSha').dataset.fullSha,
            pipeline: document.getElementById('pipelineStepper').textContent,
          })
        """)
        assert identity["project"] == detail["project_id"]
        assert identity["repository"] == detail["repository_identity"]
        assert identity["change"] == detail["change_name"]
        assert detail["run_id"] in identity["run"] and detail["job_id"] in identity["job"]
        assert identity["generation"] == f"gen-{detail['candidate_authority']['generation']}"
        assert identity["candidate"] == detail["candidate_authority"]["candidate_sha"]
        assert identity["pipeline"].strip()

        await client.eval_js(
            "document.querySelector('button[data-tab=\\\"candidateTab\\\"]').click()"
        )
        candidate = await client.eval_js(
            "document.getElementById('candidateDetailsContainer').textContent"
        )
        assert detail["candidate_authority"]["candidate_sha"] in candidate, await client.eval_js(
            "({errors:window.__pwaErrors,detail:document.getElementById('detailContent').textContent,rows:document.getElementById('changesTableBody').innerText})"
        )

        await client.eval_js(
            "document.querySelector('button[data-tab=\\\"previewTab\\\"]').click()"
        )
        preview = await client.eval_js(
            "({status:document.getElementById('previewContainerStatus').textContent, submitDisabled:document.getElementById('submitValidationBtn').disabled})"
        )
        assert "READY" in preview["status"]
        assert preview["submitDisabled"] is False

        await client.eval_js("document.querySelector('button[data-tab=\\\"reviewTab\\\"]').click()")
        review = await client.eval_js(
            "document.getElementById('reviewDetailsContainer').textContent"
        )
        if detail["review"]["status"] == "not_started":
            assert "aún no se ha ejecutado" in review
        else:
            assert detail["review"]["candidate_sha"][:8] in review

        detail_sections = [
            ("overview", "overviewTab", "overviewMetaGrid"),
            ("checks", "checksTab", "checksListContainer"),
            ("audit", "auditTab", "auditDetailsContainer"),
            ("github", "githubTab", "githubDetailsContainer"),
            ("efficiency", "efficiencyTab", "efficiencyDetailsContainer"),
            ("history", "actionHistoryTab", "actionHistoryContentContainer"),
            ("timeline", "timelineTab", "timelineListContainer"),
        ]
        rendered_sections = {}
        for index, (name, _tab, content_id) in enumerate(detail_sections):
            await client.eval_js(
                f"document.querySelectorAll('.detail-tabs .tab-btn')[{index}].click()"
            )
            await asyncio.sleep(0.1)
            rendered_sections[name] = await client.eval_js(
                f"document.getElementById('{content_id}').textContent.trim()"
            )
        assert "run-017" in rendered_sections["overview"]
        assert "ruff-lint" in rendered_sections["checks"]
        assert "unit-tests" in rendered_sections["checks"]
        assert rendered_sections["audit"]
        assert rendered_sections["github"]
        assert rendered_sections["efficiency"]
        assert rendered_sections["history"]
        assert rendered_sections["timeline"]
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
