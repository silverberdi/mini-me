"""Real browser inspection tests for 017 PWA Control Center across viewports."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
import websockets
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.api.app import app, get_intake_service, get_onboarding_service, get_uow
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
        await client.set_viewport(1440, 900)
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
        evidence_dir = Path(
            os.environ.get(
                "MINIME_PWA_EVIDENCE_DIR",
                str(
                    Path(__file__).parents[1]
                    / "openspec/changes/pwa-control-center-ux-convergence/evidence/browser"
                ),
            )
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
            clipped = await client.eval_js("""
              (() => [...document.querySelectorAll(`#detailPanel h1, #detailPanel h2, #detailPanel .step-label,
                  #detailPanel .badge, #viewExecutions .attention-banner h2`)]
                .filter(node => node.getClientRects().length)
                .filter(node => {
                  const style = getComputedStyle(node);
                  return (style.textOverflow === 'ellipsis' || style.overflowX === 'hidden')
                    && node.scrollWidth > node.clientWidth + 1;
                }).map(node => ({selector:node.tagName.toLowerCase() + '.' + node.className,
                  text:node.innerText, width:node.clientWidth, scrollWidth:node.scrollWidth})) )()
            """)
            assert clipped == [], (
                f"Essential text is destructively clipped at {width}x{height}: {clipped}"
            )
            geometry = await client.eval_js(
                "(() => { const rect = selector => { const node = document.querySelector(selector); "
                "const box = node.getBoundingClientRect(); return {top: box.top, left: box.left, "
                "width: box.width, height: box.height, display: getComputedStyle(node).display}; }; "
                "return {detail: rect('#viewExecutions .detail-panel'), "
                "attention: rect('#viewExecutions .attention-banner'), "
                "queue: rect('#viewExecutions .queue-panel')}; })()"
            )
            assert geometry["detail"]["display"] != "none" and geometry["detail"]["height"] > 0, (
                f"Selected Run detail must remain visible at {width}x{height}: {geometry}"
            )
            if width >= 1200:
                assert geometry["detail"]["top"] < geometry["queue"]["top"], (
                    f"Desktop Run hero must precede queue and attention panels: {geometry}"
                )
            if width < 768:
                assert (
                    geometry["detail"]["top"]
                    < geometry["attention"]["top"]
                    < geometry["queue"]["top"]
                ), f"Mobile must prioritize the selected Run before attention and queue: {geometry}"
            if 768 <= width < 1200:
                tablet = await client.eval_js(
                    "(() => { const rail = document.querySelector('.main-nav-tabs'); "
                    "const split = document.querySelector('#viewExecutions .content-split'); "
                    "const view = document.getElementById('viewExecutions'); "
                    "return {viewDisplay: getComputedStyle(view).display, inlineDisplay: view.style.display, "
                    "rail: rail.getBoundingClientRect().width, position: getComputedStyle(rail).position, "
                    "display: getComputedStyle(split).display, master: split.querySelector('.master-panel').getBoundingClientRect().left, "
                    "detail: split.querySelector('.detail-panel').getBoundingClientRect().left}; })()"
                )
                assert tablet["rail"] == 64 and tablet["position"] == "fixed", (
                    f"Tablet navigation must use the compact fixed rail: {tablet}"
                )
                assert (
                    tablet["viewDisplay"] == "grid"
                    and tablet["display"] == "contents"
                    and tablet["detail"] > tablet["master"]
                ), f"Tablet must preserve master-detail operation: {tablet}"
                if width < 1200:
                    compact_list = await client.eval_js("""
                      (() => ({tableWidth: document.getElementById('changesTable').clientWidth,
                        tableScrollWidth: document.getElementById('changesTable').scrollWidth,
                        header: getComputedStyle(document.querySelector('#changesTable thead')).display,
                        projectColumn: getComputedStyle(document.querySelector('#changesTableBody tr[data-project-id] td:nth-child(3)')).display,
                        nameColumn: getComputedStyle(document.querySelector('#changesTableBody tr[data-project-id] td:nth-child(2)')).display}))()
                    """)
                    assert compact_list["tableScrollWidth"] <= compact_list["tableWidth"]
                    assert (
                        compact_list["header"] == "none"
                        and compact_list["projectColumn"] == "none"
                        and compact_list["nameColumn"] != "none"
                    ), compact_list
            if width < 768:
                layout = await client.eval_js(
                    "(() => { const split = document.querySelector('#viewExecutions .content-split'); "
                    "return {display: getComputedStyle(split).display, "
                    "detail: split.querySelector('.detail-panel').getBoundingClientRect().top, "
                    "master: split.querySelector('.master-panel').getBoundingClientRect().top}; })()"
                )
                assert layout["display"] == "contents" and layout["detail"] < layout["master"], (
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

        await client.set_viewport(1440, 900)
        selected_row = await client.eval_js("""
          (() => { const row = [...document.querySelectorAll('#changesTableBody tr[data-project-id]')]
            .find(item => item.dataset.changeName === '017-pwa-control-center');
            row?.click(); return Boolean(row); })()
        """)
        assert selected_row, "The active Change fixture should provide an inspectable Run drawer."
        drawer = None
        for _ in range(30):
            drawer = await client.eval_js("""
              (() => { const node = document.getElementById('detailPanel'); const rect = node.getBoundingClientRect();
                return {open: node.classList.contains('drawer-open'), left: rect.left, width: rect.width,
                  viewport: innerWidth, backdrop: !document.getElementById('detailDrawerBackdrop').hidden}; })()
            """)
            if drawer["open"]:
                break
            await asyncio.sleep(0.05)
        assert (
            drawer["open"]
            and drawer["backdrop"]
            and drawer["width"] <= drawer["viewport"] * 0.56 + 1
        ), drawer
        assert drawer["left"] >= drawer["viewport"] * 0.44 - 1, drawer
        for _ in range(30):
            toolbar_text = await client.eval_js(
                "document.getElementById('actionToolbar').innerText"
            )
            if "Cargando acciones" not in toolbar_text:
                break
            await asyncio.sleep(0.05)
        drawer_capture = await client.send_cmd(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
        )
        (evidence_dir / "desktop-running-run-drawer-mock-seeded.png").write_bytes(
            base64.b64decode(drawer_capture["data"])
        )
        await client.eval_js("document.getElementById('closeDetailDrawer').click()")
        closed = None
        for _ in range(20):
            closed = await client.eval_js("""
              ({open: document.getElementById('detailPanel').classList.contains('drawer-open'),
                backdrop: !document.getElementById('detailDrawerBackdrop').hidden,
                focus: document.activeElement.getAttribute('data-change-name')})
            """)
            if closed["focus"]:
                break
            await asyncio.sleep(0.02)
        assert closed == {"open": False, "backdrop": False, "focus": "017-pwa-control-center"}, (
            closed
        )
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
            const visible = getComputedStyle(separator).display !== 'none' && !separator.hidden;
            const display = getComputedStyle(grid).display;
            const clientWidth = grid.clientWidth;
            separator.focus();
            separator.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowRight', bubbles:true}));
            const width = parseFloat(getComputedStyle(grid).getPropertyValue('--master-pane-width'));
            const available = grid.clientWidth - 52;
            const keys = Object.keys(localStorage).filter(key => key.startsWith('minime:desktop-layout:v1:'));
            return {width, available, keys, visible, display, clientWidth,
              ariaNow: Number(separator.getAttribute('aria-valuenow')),
              saved: keys.map(key => JSON.parse(localStorage.getItem(key)))};
          })()
        """)
        assert first_operator["display"] == "grid" and first_operator["clientWidth"] > 1000
        assert first_operator["visible"] is True
        assert first_operator["width"] >= 240
        assert first_operator["width"] <= first_operator["available"] * 0.7
        assert first_operator["ariaNow"] == first_operator["width"]
        assert len(first_operator["keys"]) == 1
        assert "operator@example.com" not in first_operator["keys"][0]
        assert set(first_operator["saved"][0]) == {"version", "ratio", "collapsed"}
        first_key = first_operator["keys"][0]

        home_width = await client.eval_js("""
          (() => { const separator = document.getElementById('paneSeparator');
            separator.focus(); separator.dispatchEvent(new KeyboardEvent('keydown', {key:'Home', bubbles:true}));
            return {width:Number(separator.getAttribute('aria-valuenow')), min:Number(separator.getAttribute('aria-valuemin'))}; })()
        """)
        assert home_width["width"] == home_width["min"] == 240
        end_width = await client.eval_js("""
          (() => { const separator = document.getElementById('paneSeparator');
            separator.focus(); separator.dispatchEvent(new KeyboardEvent('keydown', {key:'End', bubbles:true}));
            const grid = document.querySelector('#viewExecutions .content-split:not(.backlog-split)');
            return {width:Number(separator.getAttribute('aria-valuenow')),
              max:Number(separator.getAttribute('aria-valuemax')), available:grid.clientWidth - 52}; })()
        """)
        assert end_width["width"] == end_width["max"]
        assert end_width["width"] <= end_width["available"] * 0.7 + 1

        await client.eval_js("""
          (() => { const separator = document.getElementById('paneSeparator');
            separator.focus(); separator.dispatchEvent(new KeyboardEvent('keydown', {key:'Home', bubbles:true})); })()
        """)
        pointer_start = await client.eval_js("""
          (() => { const node = document.getElementById('paneSeparator');
            window.__pointerEvents = {down:0,move:0,up:0};
            node.addEventListener('pointerdown', () => window.__pointerEvents.down++);
            node.addEventListener('pointermove', () => window.__pointerEvents.move++);
            node.addEventListener('pointerup', () => window.__pointerEvents.up++);
            const rect = node.getBoundingClientRect();
            return {x:rect.left + rect.width / 2, y:rect.top + Math.min(60, rect.height / 2),
              before:Number(node.getAttribute('aria-valuenow')),rect:{left:rect.left,top:rect.top,width:rect.width,height:rect.height},
              hit:document.elementFromPoint(rect.left + rect.width / 2, rect.top + Math.min(60, rect.height / 2))?.id,
              visible:getComputedStyle(node).display,hidden:node.hidden}; })()
        """)
        await client.send_cmd(
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": pointer_start["x"], "y": pointer_start["y"]},
        )
        await client.send_cmd(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": pointer_start["x"],
                "y": pointer_start["y"],
                "button": "left",
                "clickCount": 1,
            },
        )
        await client.send_cmd(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": pointer_start["x"] + 96,
                "y": pointer_start["y"],
                "button": "left",
                "buttons": 1,
            },
        )
        await client.send_cmd(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": pointer_start["x"] + 96,
                "y": pointer_start["y"],
                "button": "left",
                "clickCount": 1,
            },
        )
        pointer_width = await client.eval_js(
            "Number(document.getElementById('paneSeparator').getAttribute('aria-valuenow'))"
        )
        pointer_events = await client.eval_js("window.__pointerEvents")
        assert pointer_width > pointer_start["before"], {
            "start": pointer_start,
            "after": pointer_width,
            "events": pointer_events,
        }
        assert (
            pointer_events["down"] >= 1
            and pointer_events["move"] >= 1
            and pointer_events["up"] >= 1
        )

        await client.eval_js("document.getElementById('collapseMasterPane').click()")
        assert (
            await client.eval_js(
                "document.querySelector('#viewExecutions .content-split').classList.contains('master-collapsed')"
            )
            is True
        )
        await client.navigate(f"{browser_test_env['server_url']}/")
        await asyncio.sleep(0.5)
        first_operator_reload = await client.eval_js("""
          (() => ({email:document.getElementById('operatorEmailText').textContent,
            collapsed:document.querySelector('#viewExecutions .content-split').classList.contains('master-collapsed'),
            preference:JSON.parse(localStorage.getItem(Object.keys(localStorage).find(key => key.startsWith('minime:desktop-layout:v1:')) || 'null'))}))()
        """)
        assert first_operator_reload["email"] == "operator@example.com"
        assert first_operator_reload["collapsed"] is True
        assert first_operator_reload["preference"]["collapsed"] is True
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

        await client.set_viewport(1920, 1080)
        await asyncio.sleep(0.2)
        ultrawide = await client.eval_js("""
          (() => { const grid = document.querySelector('#viewExecutions .content-split:not(.backlog-split)');
            const separator = document.getElementById('paneSeparator');
            return {width:Number(separator.getAttribute('aria-valuenow')),
              available:grid.clientWidth - 52, display:getComputedStyle(grid).display,
              visible:getComputedStyle(separator).display !== 'none' && !separator.hidden}; })()
        """)
        assert ultrawide["display"] == "grid" and ultrawide["visible"] is True
        assert 240 <= ultrawide["width"] <= ultrawide["available"] * 0.7 + 1

        await client.set_viewport(768, 1024, mobile=True)
        await asyncio.sleep(0.2)
        portrait_tablet = await client.eval_js("""
          (() => { const grid = document.querySelector('#viewExecutions .content-split:not(.backlog-split)');
            return {customWidth:grid.style.getPropertyValue('--master-pane-width'),
              display:getComputedStyle(grid).display, separatorHidden:document.getElementById('paneSeparator').hidden}; })()
        """)
        assert portrait_tablet == {
            "customWidth": "",
            "display": "contents",
            "separatorHidden": True,
        }

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
        assert mobile["display"] == "contents" and mobile["detailTop"] < mobile["masterTop"]

        await client.set_viewport(360, 800, mobile=True)
        phone_small = await client.eval_js("""
          (() => { const grid = document.querySelector('#viewExecutions .content-split:not(.backlog-split)');
            return {customWidth:grid.style.getPropertyValue('--master-pane-width'),
              display:getComputedStyle(grid).display, separatorHidden:document.getElementById('paneSeparator').hidden}; })()
        """)
        assert phone_small == {"customWidth": "", "display": "contents", "separatorHidden": True}
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
async def test_real_browser_onboarding_creates_canonical_disposable_binding(
    browser_test_env: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real Projects form must onboard a local Git remote through canonical services."""
    from tests.conftest import InMemoryPersistenceUnitOfWork, ReadinessGitHubStub

    from minime.services.auth_service import AuthorizedOperatorService, SessionManager
    from minime.services.intake_service import IntakeService
    from minime.services.project_onboarding_service import ProjectOnboardingService
    from minime.services.workspace_guard import ManagedWorkspaceGuard

    runtime_root = tmp_path / "runtime"
    (runtime_root / "openspec").mkdir(parents=True)
    (runtime_root / "docs").mkdir()
    (runtime_root / "docs" / "ROADMAP.md").write_text("# Runtime roadmap\n", encoding="utf-8")
    trusted_root = tmp_path / "managed"
    trusted_root.mkdir()
    remote_bare = tmp_path / "e2e-project.git"
    seed_repository = tmp_path / "seed"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote_bare)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "clone", str(remote_bare), str(seed_repository)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "config", "user.name", "PWA E2E"], cwd=seed_repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "pwa-e2e@example.test"], cwd=seed_repository, check=True
    )
    (seed_repository / "README.md").write_text("# Disposable project\n", encoding="utf-8")
    (seed_repository / "openspec").mkdir()
    (seed_repository / "docs").mkdir()
    (seed_repository / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n- e2e-onboarding: Exercise canonical onboarding\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "README.md", "openspec", "docs"], cwd=seed_repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Seed disposable PWA onboarding repository"],
        cwd=seed_repository,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=seed_repository,
        check=True,
        capture_output=True,
        text=True,
    )

    uow = InMemoryPersistenceUnitOfWork()
    AuthorizedOperatorService(uow).seed_operator("operator@example.com", display_name="E2E")
    session_token, _ = SessionManager(uow).create_session("operator@example.com")
    github_stub = ReadinessGitHubStub()
    service = ProjectOnboardingService(
        uow,
        project_root=runtime_root,
        github_adapter=github_stub,
        trusted_managed_root=trusted_root,
    )
    intake_service = IntakeService(uow, project_root=runtime_root, github_adapter=github_stub)
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setitem(app.dependency_overrides, get_uow, lambda: uow)
    monkeypatch.setitem(app.dependency_overrides, get_onboarding_service, lambda: service)
    monkeypatch.setitem(app.dependency_overrides, get_intake_service, lambda: intake_service)

    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await authenticate_browser(client, browser_test_env["server_url"], session_token)
        await client.eval_js("document.getElementById('navTabProjects').click()")
        await client.eval_js("document.getElementById('onboardProjectBtn').click()")
        await client.eval_js("document.getElementById('onboardProjectId').value='pwa-binding-e2e'")
        await client.eval_js(
            "document.getElementById('onboardDisplayName').value='PWA Binding E2E'"
        )
        await client.eval_js(
            f"document.getElementById('onboardRepository').value={json.dumps(str(remote_bare))}"
        )
        await client.eval_js("document.getElementById('onboardProjectForm').requestSubmit()")
        for _ in range(50):
            state = await client.eval_js("""
              ({card: document.querySelector('#projectsGridContainer .project-card')?.innerText || '',
                toast: document.getElementById('toastNotification').textContent,
                selected: document.getElementById('projectSelect').value})
            """)
            if "PWA Binding E2E" in state["card"]:
                break
            await asyncio.sleep(0.1)

        binding = uow.project_managed_repository_bindings.get_by_project_id("pwa-binding-e2e")
        managed_root = trusted_root / "pwa-binding-e2e"
        assert binding is not None and binding.is_valid
        assert Path(binding.managed_repository_root) == managed_root
        assert Path(binding.worktree_parent_dir) == managed_root / ".minime" / "worktrees"
        assert state["selected"] == "pwa-binding-e2e"
        assert "PWA Binding E2E" in state["card"]
        assert "registrado" in state["toast"].lower()
        assert (managed_root / binding.ownership_marker_filename).is_file()
        guard = ManagedWorkspaceGuard(
            uow, runtime_root=runtime_root, trusted_managed_root=trusted_root
        )
        marker_valid, marker_reason, _, _ = guard.verify_managed_repository_ownership_marker(
            managed_root,
            "pwa-binding-e2e",
            str(remote_bare),
            binding.ownership_marker_filename,
        )
        assert marker_valid, marker_reason
        marker_data = json.loads((managed_root / binding.ownership_marker_filename).read_text())
        assert marker_data["project_id"] == "pwa-binding-e2e"
        assert marker_data["canonical_repository_identity"] == str(remote_bare)
        assert subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=managed_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() == str(remote_bare)

        await client.eval_js("document.getElementById('navTabBacklog').click()")
        await client.eval_js("document.getElementById('newWorkItemBtn').click()")
        await client.eval_js(
            "document.getElementById('newWorkItemTitle').value='Bound intake item'"
        )
        await client.eval_js("document.getElementById('newWorkItemKey').value='bound-intake-item'")
        await client.eval_js(
            "document.getElementById('newWorkItemDescription').value='Created through the authenticated UI.'"
        )
        await client.eval_js(
            "document.getElementById('newWorkItemCriteria').value='- Visible in authoritative backlog'"
        )
        await client.eval_js("document.getElementById('newWorkItemForm').requestSubmit()")
        for _ in range(50):
            created = uow.backlog_items.get_by_project_and_key(
                "pwa-binding-e2e", "bound-intake-item"
            )
            if created:
                break
            await asyncio.sleep(0.1)
        assert created is not None
        assert created.title == "Bound intake item"
        for _ in range(50):
            rendered_backlog = await client.eval_js(
                "document.getElementById('backlogTableBody').textContent"
            )
            if "bound-intake-item" in rendered_backlog:
                break
            await asyncio.sleep(0.1)
        assert "bound-intake-item" in rendered_backlog
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
            "WAITING_CAPACITY",
            "NEEDS_HUMAN",
            "UNKNOWN",
            "AUTH_REQUIRED",
            "RECOVERY",
            "READY_FOR_HUMAN_MERGE",
            "CANCELLED",
            "<img src=x onerror=alert(1)>",
        ]
        rendered = await client.eval_js(f"""
          (async () => {{
            const {{getStatusBadgeClass}} = await import('/static/js/views/status_view.js');
            const {{renderChangesView}} = await import('/static/js/views/runs_view.js');
            const {{renderPipelineStepper}} = await import('/static/js/components/pipeline_stepper.js');
            const root = document.createElement('tbody');
            const states = {json.dumps(states)};
            renderChangesView({{
              root,
              changes: [...states.map((status, index) => ({{project_id:'p',change_name:`c-${{index}}`,status}})), {{project_id:'p',change_name:'missing-status'}}],
              filter: 'ALL', query: '', selected: null, alreadyAutoSelected: true,
              statusClass: getStatusBadgeClass, formatTime: () => 'hace 0 s', onSelect: () => {{}}
            }});
            const rows = [...root.querySelectorAll('tr[data-project-id]')].map(row => ({{
              status: row.querySelector('.badge').textContent,
              className: row.querySelector('.badge').className,
            }}));
            const attentionRoot = document.createElement('tbody');
            renderChangesView({{root:attentionRoot,changes:[
              {{project_id:'p',change_name:'capacity',status:'WAITING_CAPACITY'}},
              {{project_id:'p',change_name:'recovery',status:'RECOVERY'}},
              {{project_id:'p',change_name:'running',status:'RUNNING'}}
            ],filter:'ATTENTION',query:'',selected:null,alreadyAutoSelected:true,statusClass:getStatusBadgeClass,formatTime:()=>'',onSelect:()=>{{}}}});
            const pipelineRoot = document.createElement('div');
            renderPipelineStepper(pipelineRoot, [
              {{name:'implementation',display_name:'Implementation',status:'running'}},
              {{name:'checks',display_name:'Checks',status:'not_started'}}
            ], {{stopOutcome:'CANCELLED'}});
            return {{rows, escapedElements:root.querySelectorAll('img').length,
              attention:[...attentionRoot.querySelectorAll('tr[data-project-id]')].map(row=>row.dataset.changeName),
              cancelledPipeline:{{active:pipelineRoot.querySelector('.step-item.running')?.innerText || '',
                stopped:pipelineRoot.querySelector('.step-item.stopped')?.innerText || '',
                phaseStatus:pipelineRoot.querySelector('.step-item.stopped')?.dataset.phaseStatus}}}};
          }})()
        """)
        assert [item["status"] for item in rendered["rows"]] == [*states, "UNKNOWN"]
        assert rendered["escapedElements"] == 0
        assert set(rendered["attention"]) == {"capacity", "recovery"}
        by_state = {item["status"]: item["className"] for item in rendered["rows"]}
        assert "badge-unknown" in by_state["UNKNOWN"]
        assert "badge-recovery" in by_state["RECOVERY"]
        assert "badge-needs-human" in by_state["AUTH_REQUIRED"]
        assert "badge-cancelled" in by_state["CANCELLED"]
        assert rendered["cancelledPipeline"]["active"] == ""
        assert "Implementation · última etapa" in rendered["cancelledPipeline"]["stopped"]
        assert rendered["cancelledPipeline"]["phaseStatus"] == "running"
        # Text remains the canonical backend state even where visual tokens share a color family.
        assert by_state["WAITING_CAPACITY"] != by_state["RUNNING"]
        assert by_state["READY_FOR_HUMAN_MERGE"] != by_state["NEEDS_HUMAN"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_keyboard_tabs_focus_names_and_reduced_motion(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await client.set_viewport(1440, 900)
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )
        names = await client.eval_js("""
          (() => Array.from(document.querySelectorAll('button, input, select, textarea, a[href], [role="separator"]'))
            .filter(node => node.getClientRects().length)
            .filter(node => {
              if (node.getAttribute('aria-hidden') === 'true') return false;
              const labelled = node.getAttribute('aria-label') || node.getAttribute('aria-labelledby')
                || node.title || node.labels?.length || node.innerText?.trim() || node.alt;
              return !labelled;
            }).map(node => `${node.tagName.toLowerCase()}#${node.id}.${node.className}`))()
        """)
        assert names == [], f"Visible controls without an accessible name: {names}"

        focus_start = await client.eval_js("""
          (() => { const tab = document.getElementById('navTabExecutions'); tab.focus();
            return {active: document.activeElement.id, display: getComputedStyle(tab).display,
              authenticated: getComputedStyle(document.getElementById('authenticatedContent')).display}; })()
        """)
        assert focus_start["active"] == "navTabExecutions" and focus_start["display"] != "none"
        assert focus_start["authenticated"] == "block"
        await client.send_cmd(
            "Input.dispatchKeyEvent",
            {
                "type": "rawKeyDown",
                "key": "ArrowRight",
                "code": "ArrowRight",
                "windowsVirtualKeyCode": 39,
            },
        )
        await client.send_cmd(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": "ArrowRight",
                "code": "ArrowRight",
                "windowsVirtualKeyCode": 39,
            },
        )
        main_tab = await client.eval_js("""
          ({id: document.activeElement.id, selected: document.activeElement.getAttribute('aria-selected'),
            tabIndex: document.activeElement.tabIndex,
            focused: getComputedStyle(document.activeElement).boxShadow !== 'none'})
        """)
        assert main_tab == {
            "id": "navTabBacklog",
            "selected": "true",
            "tabIndex": 0,
            "focused": True,
        }

        await client.eval_js(
            "document.getElementById('navTabExecutions').click(); document.getElementById('tabOverview').focus()"
        )
        await client.send_cmd(
            "Input.dispatchKeyEvent",
            {
                "type": "rawKeyDown",
                "key": "ArrowRight",
                "code": "ArrowRight",
                "windowsVirtualKeyCode": 39,
            },
        )
        await client.send_cmd(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": "ArrowRight",
                "code": "ArrowRight",
                "windowsVirtualKeyCode": 39,
            },
        )
        detail_tab = await client.eval_js("""
          ({id: document.activeElement.id, selected: document.activeElement.getAttribute('aria-selected'),
            tabIndex: document.activeElement.tabIndex,
            controls: document.activeElement.getAttribute('aria-controls'),
            panelLabel: document.getElementById(document.activeElement.getAttribute('aria-controls'))
              ?.getAttribute('aria-labelledby')})
        """)
        assert detail_tab == {
            "id": "tabCandidate",
            "selected": "true",
            "tabIndex": 0,
            "controls": "candidateTab",
            "panelLabel": "tabCandidate",
        }

        await client.send_cmd(
            "Emulation.setEmulatedMedia",
            {
                "features": [{"name": "prefers-reduced-motion", "value": "reduce"}],
            },
        )
        motion = await client.eval_js("""
          (() => {
            const node = document.createElement('div');
            node.className = 'pipeline-nine-stage';
            node.innerHTML = '<span class="step is-active">Active</span>';
            document.body.append(node);
            const style = getComputedStyle(node.firstElementChild);
            return {reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
              animation: parseFloat(style.animationDuration), transition: parseFloat(style.transitionDuration)};
          })()
        """)
        assert motion["reduced"] is True
        assert motion["animation"] <= 0.00001 and motion["transition"] <= 0.00001

        await client.eval_js("document.getElementById('navTabExecutions').focus()")
        dialog_state = await client.eval_js("""
          (async () => {
            const {openConfirmModal} = await import('/static/js/components/action_dialog.js');
            const opened = openConfirmModal({title:'Confirmar', description:'Acción de prueba',
              warning:'Solo demostración', meta:{run_id:'qa-run'}, onConfirm:()=>{}});
            const dialog = document.getElementById('actionDialog');
            return {opened, modal:dialog.open && dialog.matches(':modal'),
              focusedInside:dialog.contains(document.activeElement),
              labelledBy:dialog.getAttribute('aria-labelledby'),
              initialFocus:document.activeElement.matches('[data-cancel], [data-confirm]')};
          })()
        """)
        assert dialog_state == {
            "opened": True,
            "modal": True,
            "focusedInside": True,
            "labelledBy": "actionDialogTitle",
            "initialFocus": True,
        }
        await client.send_cmd(
            "Input.dispatchKeyEvent",
            {
                "type": "rawKeyDown",
                "key": "Escape",
                "code": "Escape",
                "windowsVirtualKeyCode": 27,
            },
        )
        await client.send_cmd(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": "Escape",
                "code": "Escape",
                "windowsVirtualKeyCode": 27,
            },
        )
        focus_restored = await client.eval_js(
            "({closed:!document.getElementById('actionDialog').open, focused:document.activeElement.id})"
        )
        assert focus_restored == {"closed": True, "focused": "navTabExecutions"}
    finally:
        await client.send_cmd("Emulation.setEmulatedMedia", {"features": []})
        await client.close()


@pytest.mark.asyncio
async def test_control_center_accessibility_and_theme_contrast_at_approved_viewports(
    browser_test_env: dict[str, Any],
) -> None:
    client = ChromeCDPClient(browser_test_env["ws_url"])
    await client.connect()
    try:
        await authenticate_browser(
            client, browser_test_env["server_url"], browser_test_env["session_token"]
        )
        await client.eval_js("document.getElementById('navTabExecutions').click()")
        viewports = (
            (1440, 900, False),
            (1024, 768, False),
            (768, 1024, True),
            (390, 844, True),
            (360, 800, True),
        )
        for width, height, mobile in viewports:
            await client.set_viewport(width, height, mobile=mobile)
            for theme in ("theme-dark", "theme-light"):
                await client.eval_js(
                    f"document.body.classList.remove('theme-dark','theme-light'); "
                    f"document.body.classList.add('{theme}')"
                )
                findings = await client.eval_js("""
                  (() => {
                    const visible = node => !!node.getClientRects().length
                      && getComputedStyle(node).visibility !== 'hidden';
                    const unnamed = [...document.querySelectorAll('button,input,select,textarea,a[href],[role="separator"]')]
                      .filter(visible).filter(node => !node.getAttribute('aria-hidden')
                        && !(node.getAttribute('aria-label') || node.getAttribute('aria-labelledby')
                          || node.title || node.labels?.length || node.innerText?.trim() || node.alt))
                      .map(node => `${node.tagName.toLowerCase()}#${node.id}.${node.className}`);
                    const linear = channel => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
                    const rgb = value => {
                      if (value.startsWith('#')) {
                        const hex = value.slice(1);
                        const full = hex.length === 3 ? [...hex].map(char => char + char).join('') : hex;
                        return [0,2,4].map(index => linear(parseInt(full.slice(index,index + 2),16) / 255));
                      }
                      return value.match(/[\\d.]+/g).slice(0,3).map(Number).map(channel => {
                        return linear(channel / 255);
                      });
                    };
                    const ratio = (foreground, background) => {
                      const [f,b] = [rgb(foreground), rgb(background)].map(channels =>
                        channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722);
                      return (Math.max(f,b) + .05) / (Math.min(f,b) + .05);
                    };
                    const root = getComputedStyle(document.body);
                    const main = root.getPropertyValue('--text-main').trim();
                    const muted = root.getPropertyValue('--text-muted').trim();
                    const background = root.getPropertyValue('--bg-card').trim();
                    const contrast = {main: ratio(main, background), muted: ratio(muted, background)};
                    const targets = [...document.querySelectorAll('.bottom-nav button')].filter(visible)
                      .map(node => ({label: node.getAttribute('aria-label') || node.innerText.trim(),
                        height: node.getBoundingClientRect().height, width: node.getBoundingClientRect().width}));
                    return {unnamed, contrast, targets,
                      noHorizontalOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
                      mainLandmark: document.querySelectorAll('main[role="main"]').length};
                  })()
                """)
                assert findings["unnamed"] == [], (
                    f"Unnamed controls at {width}x{height}/{theme}: {findings}"
                )
                assert findings["noHorizontalOverflow"] and findings["mainLandmark"] == 1
                assert min(findings["contrast"].values()) >= 4.5, (
                    f"Theme token text contrast below WCAG AA at {width}x{height}/{theme}: {findings}"
                )
                if mobile:
                    assert all(target["height"] >= 44 for target in findings["targets"]), (
                        f"Mobile bottom-nav target below 44px at {width}x{height}/{theme}: {findings}"
                    )

        # Reflow checks at 200%-equivalent CSS widths for the two larger target
        # viewports. Mobile already exercises the 320-CSS-pixel reflow floor.
        for width, height in ((720, 450), (512, 384), (320, 800)):
            await client.set_viewport(width, height, mobile=width <= 390)
            reflow = await client.eval_js("""
              (() => {
                const visible = node => node.getClientRects().length > 0;
                const main = document.querySelector('main[role="main"]');
                const namedControls = [...document.querySelectorAll('button, input, select, a[href]')]
                  .filter(visible).filter(node => !node.getAttribute('aria-hidden'));
                const tabStrip = document.querySelector('.detail-tabs');
                return {
                  width: document.documentElement.clientWidth,
                  scrollWidth: document.documentElement.scrollWidth,
                  mainVisible: Boolean(main && visible(main)),
                  controlsOutsideViewport: namedControls.filter(node => {
                    if (node.closest('.detail-tabs')) return false;
                    const rect = node.getBoundingClientRect();
                    return rect.left < 0 || rect.right > document.documentElement.clientWidth;
                  }).map(node => `${node.tagName.toLowerCase()}#${node.id}.${node.className}`),
                  tabStripIsScrollable: Boolean(tabStrip && getComputedStyle(tabStrip).overflowX === 'auto'
                    && tabStrip.scrollWidth >= tabStrip.clientWidth),
                };
              })()
            """)
            assert reflow["scrollWidth"] <= reflow["width"] and reflow["mainVisible"], reflow
            assert reflow["controlsOutsideViewport"] == [], reflow
            assert reflow["tabStripIsScrollable"], reflow
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_browser_authenticated_control_plane_cancel_persists_in_disposable_postgres(
    browser_test_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise authenticated UI + Control Plane against isolated durable PostgreSQL."""
    from sqlalchemy.engine import make_url

    from minime.db.repository import PostgresPersistenceUnitOfWork
    from minime.db.session import db_manager, verify_physical_schema_invariants
    from minime.domain.enums import ChangeStatus, JobStatus, OrchestrationStage, ReadinessState
    from minime.domain.models import Change, Job, OrchestrationRun, Project, ProjectBinding
    from minime.services.auth_service import AuthorizedOperatorService, SessionManager
    from minime.services.container_preview_service import ContainerPreviewService

    database_url = os.environ.get("MINIME_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("A disposable PostgreSQL URL is required for the authenticated browser E2E.")
    parsed = make_url(database_url)
    assert parsed.host in {"127.0.0.1", "localhost"}, (
        "Refusing to use a non-loopback or non-disposable PostgreSQL target."
    )
    assert parsed.database.startswith("minime_pwa_") and parsed.database != "minime"
    postgres_container = os.environ.get("MINIME_TEST_POSTGRES_CONTAINER", "")
    assert postgres_container.startswith("minime-pwa-acceptance-"), (
        "A test-owned disposable PostgreSQL container is required for the container preview."
    )
    inspect_db = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            postgres_container,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    container_db_host = inspect_db.stdout.strip()
    assert ipaddress.ip_address(container_db_host).is_private, (
        "The preview database must be reachable only through a private Docker bridge address."
    )
    container_database_url = parsed.set(host=container_db_host, port=5432).render_as_string(
        hide_password=False
    )

    old_url = db_manager._database_url
    old_engine = db_manager._engine
    old_sessionmaker = db_manager._sessionmaker
    old_overrides = dict(app.dependency_overrides)
    preview_service = ContainerPreviewService()
    preview_session = None
    if old_engine is not None:
        old_engine.dispose()
    db_manager._engine = None
    db_manager._sessionmaker = None
    db_manager._database_url = database_url
    monkeypatch.setenv("MINIME_DATABASE_URL", database_url)
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "true")
    monkeypatch.setenv("MINIME_AUTHORIZED_OPERATORS", "")

    try:
        engine = db_manager.engine
        schema = verify_physical_schema_invariants(engine)
        assert schema.valid, f"Disposable PostgreSQL schema is not at the canonical head: {schema}"

        seed_session = db_manager.sessionmaker()
        uow = PostgresPersistenceUnitOfWork(seed_session)
        suffix = uuid.uuid4().hex[:12]
        project_id = f"qa-pwa-{suffix}"
        change_name = f"control-center-action-{suffix}"
        secondary_change_name = f"control-center-read-integrity-{suffix}"
        run_id = f"qa-run-{suffix}"
        job_id = f"qa-job-{suffix}"
        operator_email = f"pwa-e2e-{suffix}@example.invalid"
        base_sha = "a" * 40
        uow.projects.save(
            Project(
                project_id=project_id,
                display_name=f"PWA disposable acceptance {suffix}",
                repository=f"silverberdi/pwa-acceptance-{suffix}",
                base_branch="main",
            )
        )
        uow.changes.save(
            Change(
                project_id=project_id,
                name=change_name,
                status=ChangeStatus.IN_PROGRESS,
                last_readiness_status=ReadinessState.READY,
            )
        )
        uow.changes.save(
            Change(
                project_id=project_id,
                name=secondary_change_name,
                status=ChangeStatus.IN_PROGRESS,
                last_readiness_status=ReadinessState.READY,
            )
        )
        uow.bindings.save(
            ProjectBinding(
                project_id=project_id,
                repository=f"silverberdi/pwa-acceptance-{suffix}",
                openspec_change_name=change_name,
            )
        )
        uow.bindings.save(
            ProjectBinding(
                project_id=project_id,
                repository=f"silverberdi/pwa-acceptance-{suffix}",
                openspec_change_name=secondary_change_name,
            )
        )
        uow.jobs.save(
            Job(
                job_id=job_id,
                project_id=project_id,
                change_name=change_name,
                status=JobStatus.RUNNING,
                implementer_role="codex",
                current_executor="codex",
                base_sha=base_sha,
            )
        )
        uow.orchestration_runs.save(
            OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name=change_name,
                base_sha=base_sha,
                current_stage=OrchestrationStage.IMPLEMENTING,
                active_job_id=job_id,
                is_active=True,
            )
        )
        AuthorizedOperatorService(uow).seed_operator(operator_email, display_name="Disposable QA")
        session_token, _ = SessionManager(uow).create_session(operator_email)
        forbidden_token, _ = SessionManager(uow).create_session(
            f"not-allowlisted-{suffix}@example.invalid"
        )
        uow.commit()
        persisted_seed = uow.orchestration_runs.get_by_id(run_id)
        assert persisted_seed is not None and persisted_seed.is_active
        assert persisted_seed.current_stage == OrchestrationStage.IMPLEMENTING
        seed_session.close()

        candidate_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=10
        ).strip()
        base_sha = subprocess.check_output(
            ["git", "merge-base", "HEAD", "origin/main"], text=True, timeout=10
        ).strip()
        image_tag = f"minime-pwa-e2e:{candidate_sha[:12]}"
        image_digest = await preview_service.build_image(Path(__file__).parents[1], image_tag)
        preview_session = PreviewSession(
            preview_id=f"pwa-e2e-{suffix}",
            project_id=project_id,
            change_name=change_name,
            run_id=run_id,
            job_id=job_id,
            candidate_generation=1,
            head_sha=candidate_sha,
            base_sha=base_sha,
            image_digest=image_digest,
            container_name=f"minime-pwa-e2e-{suffix}",
        )
        container_id, preview_url, host_port = await preview_service.start_preview_container(
            preview_session,
            image_digest,
            internal_port=8787,
            env_vars={
                "MINIME_DATABASE_URL": container_database_url,
                "MINIME_EXPECTED_DATABASE": parsed.database,
                "MINIME_AUTH_ENABLED": "true",
                "MINIME_AUTHORIZED_OPERATORS": "",
                "MINIME_RUNTIME_ROOT": "/tmp/minime-preview-runtime",
            },
        )
        preview_session.container_id = container_id
        preview_session.preview_url = preview_url
        preview_session.allocated_port = host_port
        preview_healthy = await preview_service.probe_health(
            preview_url, health_path="/health", max_attempts=40
        )
        if not preview_healthy:
            preview_logs = subprocess.run(
                ["docker", "logs", container_id],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            sanitized_logs = preview_service._sanitize_text(
                (preview_logs.stdout + "\n" + preview_logs.stderr)[-6000:]
            )
            raise AssertionError(f"Candidate container did not become healthy:\n{sanitized_logs}")
        image_user = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.User}}", container_id],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        assert image_user == "minime", (
            f"Preview must run as its dedicated non-root user: {image_user!r}"
        )

        # Exercise the production dependency/middleware path: both close their own
        # sessions instead of retaining test-managed UoWs across browser requests.
        app.dependency_overrides.pop(get_uow, None)
        client = ChromeCDPClient(browser_test_env["ws_url"])
        await client.connect()
        try:
            await client.send_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": f"""
              (() => {{
                const state = window.__pwaReadIntegrity = {{mode:'normal', path:null, releaseDelayed:null}};
                const originalFetch = window.fetch.bind(window);
                window.fetch = (input, init) => {{
                  const url = new URL(typeof input === 'string' ? input : input.url, location.href);
                  const responsePromise = originalFetch(input, init);
                  if (url.pathname !== state.path) return responsePromise;
                  if (state.mode === 'malformed') {{
                    state.mode = 'normal';
                    return responsePromise.then(async response => {{
                      await response.clone().arrayBuffer();
                      return new Response(JSON.stringify({{project_id:'{project_id}',change_name:'{secondary_change_name}'}}),
                        {{status:200,headers:{{'Content-Type':'application/json'}}}});
                    }});
                  }}
                  if (state.mode === 'delay') {{
                    state.mode = 'delaying';
                    return responsePromise.then(response => new Promise(resolve => {{
                      state.releaseDelayed = () => {{ state.releaseDelayed = null; state.mode = 'normal'; resolve(response); }};
                    }}));
                  }}
                  return responsePromise;
                }};
              }})();
            """
                },
            )
            await client.navigate(preview_url + "/")
            await authenticate_browser(client, preview_url, session_token)
            api_identity = await client.eval_js(
                """
              (async () => {
                const [overview, detail, unauthenticated] = await Promise.all([
                  fetch('/api/v1/dashboard/overview', {cache:'no-store'}),
                  fetch('/api/v1/dashboard/runs/%s', {cache:'no-store'}),
                  fetch('/api/v1/dashboard/overview', {credentials:'omit',cache:'no-store'})
                ]);
                const [overviewBody, detailBody] = await Promise.all([overview.json(), detail.json()]);
                const forbidden = await fetch('/api/v1/dashboard/overview', {
                  credentials:'omit',cache:'no-store',headers:{Authorization:'Bearer %s'}
                });
                return {overviewStatus:overview.status, projects:overviewBody.changes?.filter(item=>item.project_id === '%s').map(item=>item.project_id) || [],
                  detailStatus:detail.status, runId:detailBody.run_id, projectId:detailBody.project_id,
                  changeName:detailBody.change_name, candidate:detailBody.candidate_authority?.candidate_sha || null,
                  schedulerFreshness:overviewBody.system_status?.scheduler_service?.freshness,
                  schedulerActive:overviewBody.system_status?.scheduler_service?.active_state,
                  unauthenticatedStatus:unauthenticated.status, forbiddenStatus:forbidden.status};
              })()
            """
                % (run_id, forbidden_token, project_id)
            )
            assert api_identity == {
                "overviewStatus": 200,
                "projects": [project_id, project_id],
                "detailStatus": 200,
                "runId": run_id,
                "projectId": project_id,
                "changeName": change_name,
                "candidate": None,
                "schedulerFreshness": "UNKNOWN",
                "schedulerActive": "UNKNOWN",
                "unauthenticatedStatus": 401,
                "forbiddenStatus": 403,
            }, api_identity

            # A malformed authenticated 200 for the overview cannot be treated
            # as fresh data or leave operational rows from the prior read visible.
            await client.eval_js("""
              (() => { window.__pwaReadIntegrity.path = '/api/v1/dashboard/overview';
                window.__pwaReadIntegrity.mode = 'malformed';
                document.getElementById('refreshBtn').click(); })()
            """)
            malformed_overview = None
            for _ in range(40):
                malformed_overview = await client.eval_js("""
                  (() => ({freshness:document.getElementById('overviewFreshness').dataset.state,
                    rows:document.getElementById('changesTableBody').innerText,
                    detail:document.getElementById('detailPanel').innerText,
                    contentDisplay:getComputedStyle(document.getElementById('detailContent')).display}))()
                """)
                if malformed_overview["freshness"] == "UNKNOWN":
                    break
                await asyncio.sleep(0.05)
            assert malformed_overview and malformed_overview["freshness"] == "UNKNOWN", (
                malformed_overview
            )
            assert "Datos operacionales no disponibles" in malformed_overview["rows"]
            assert (
                run_id not in malformed_overview["detail"]
                and job_id not in malformed_overview["detail"]
            )
            assert malformed_overview["contentDisplay"] == "none"
            await client.eval_js("""window.__pwaReadIntegrity.path = null;
              document.getElementById('refreshBtn').click();""")
            for _ in range(40):
                restored_overview = await client.eval_js("""
                  ({freshness:document.getElementById('overviewFreshness').dataset.state,
                    rows:document.getElementById('changesTableBody').innerText})
                """)
                if (
                    restored_overview["freshness"] == "OBSERVED"
                    and change_name in restored_overview["rows"]
                ):
                    break
                await asyncio.sleep(0.05)
            assert (
                restored_overview["freshness"] == "OBSERVED"
                and change_name in restored_overview["rows"]
            ), restored_overview

            # Exercise offline degradation on the actual containerized FastAPI
            # preview. The backend observation is UNKNOWN in this container,
            # and no offline mutation may be queued or replayed after reconnect.
            await client.send_cmd("Network.enable", {})
            await client.send_cmd(
                "Network.emulateNetworkConditions",
                {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0},
            )
            await asyncio.sleep(0.2)
            offline_state = await client.eval_js("""
              (() => ({online:navigator.onLine,
                banner:document.getElementById('offlineBanner').classList.contains('is-visible'),
                freshness:document.getElementById('overviewFreshness').dataset.state}))()
            """)
            assert offline_state == {"online": False, "banner": True, "freshness": "STALE"}, (
                offline_state
            )
            offline_mutation = await client.eval_js(
                """
              fetch('/api/v1/runs/%s/actions/CANCEL', {method:'POST',
                credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'})
                .then(response=>({status:response.status}))
                .catch(error=>({failed:true,name:error.name}))
            """
                % run_id
            )
            assert offline_mutation.get("failed") is True, offline_mutation
            await client.send_cmd(
                "Network.emulateNetworkConditions",
                {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
            )
            refreshed = None
            for _ in range(40):
                refreshed = await client.eval_js("""
                  ({online:navigator.onLine,
                    freshness:document.getElementById('overviewFreshness').dataset.state,
                    banner:document.getElementById('offlineBanner').classList.contains('is-visible')})
                """)
                if refreshed == {"online": True, "freshness": "OBSERVED", "banner": False}:
                    break
                await asyncio.sleep(0.1)
            assert refreshed == {"online": True, "freshness": "OBSERVED", "banner": False}, (
                refreshed
            )
            verify_offline_session = db_manager.sessionmaker()
            offline_uow = PostgresPersistenceUnitOfWork(verify_offline_session)
            offline_run = offline_uow.orchestration_runs.get_by_id(run_id)
            offline_actions = offline_uow.operator_actions.list_by_run(run_id, limit=10)
            verify_offline_session.close()
            assert offline_run is not None and offline_run.is_active
            assert offline_actions == [], "Offline mutation must not replay after reconnect."

            await client.set_viewport(1440, 900)
            await client.eval_js("document.getElementById('navTabExecutions').click()")
            selected = await client.eval_js(
                """
              (() => { const row = [...document.querySelectorAll('#viewExecutions .master-panel tr')]
                .find(item => item.innerText.includes('%s'));
                if (row) row.click();
                return Boolean(row); })()
            """
                % change_name
            )
            assert selected, {
                "error": "The real PostgreSQL-backed Change row was not rendered/selectable.",
                "master": await client.eval_js(
                    "document.querySelector('#viewExecutions .master-panel')?.innerText || 'missing master panel'"
                ),
                "overview": await client.eval_js(
                    "fetch('/api/v1/dashboard/overview').then(async r=>({status:r.status,body:await r.text()}))"
                ),
                "runs": await client.eval_js(
                    "fetch('/api/v1/orchestration/runs').then(async r=>({status:r.status,body:await r.text()}))"
                ),
                "body": await client.eval_js(
                    "document.getElementById('authenticatedContent').innerText.slice(0,1000)"
                ),
            }

            selected_detail = ""
            selected_row = await client.eval_js(f"""
              (() => [...document.querySelectorAll('#changesTableBody tr[data-project-id]')]
                .find(item => item.dataset.changeName === {json.dumps(change_name)})?.classList.contains('selected'))()
            """)
            assert selected_row, (
                "The landing must select the durable Run without opening its drawer."
            )

            # Capture exact-candidate screenshots from the authenticated container
            # preview before exercising malformed/stale response fault injection.
            # The rows are disposable QA records, not production observations.
            preview_evidence_dir = Path(
                os.environ.get(
                    "MINIME_PWA_PREVIEW_EVIDENCE_DIR",
                    str(
                        Path(__file__).parents[1]
                        / "openspec/changes/pwa-control-center-ux-convergence/evidence/browser"
                    ),
                )
            )
            preview_evidence_dir.mkdir(parents=True, exist_ok=True)
            # Reference 01 is the operational landing with a selected real Run
            # in the master list and no detail panel competing for dashboard space.
            # Reference 03 opens that exact durable selection explicitly.
            await client.set_viewport(1440, 900)
            drawer_open = await client.eval_js(
                "document.getElementById('detailPanel').classList.contains('drawer-open')"
            )
            detail_display = await client.eval_js(
                "getComputedStyle(document.getElementById('detailPanel')).display"
            )
            assert not drawer_open and detail_display == "none", {
                "drawer_open": drawer_open,
                "detail_display": detail_display,
            }
            await asyncio.sleep(0.15)
            capture = await client.send_cmd(
                "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
            )
            (
                preview_evidence_dir / "visual-review-active-desktop-1440x900-landing.png"
            ).write_bytes(base64.b64decode(capture["data"]))
            await client.eval_js(f"""
              (() => [...document.querySelectorAll('#changesTableBody tr[data-project-id]')]
                .find(item => item.dataset.changeName === {json.dumps(change_name)})?.click())()
            """)
            for _ in range(40):
                selected_detail = await client.eval_js(
                    "document.getElementById('detailPanel').innerText"
                )
                drawer_open = await client.eval_js(
                    "document.getElementById('detailPanel').classList.contains('drawer-open')"
                )
                if drawer_open and change_name in selected_detail and run_id in selected_detail:
                    break
                await asyncio.sleep(0.05)
            assert drawer_open and change_name in selected_detail and run_id in selected_detail, (
                "Desktop drawer must open from and remain bound to the selected durable Run."
            )
            await asyncio.sleep(0.15)
            capture = await client.send_cmd(
                "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
            )
            (preview_evidence_dir / "visual-review-active-desktop-1440x900-drawer.png").write_bytes(
                base64.b64decode(capture["data"])
            )
            preview_viewports = (
                (1024, 768, False, "visual-review-active-tablet-1024x768.png"),
                (768, 1024, True, "visual-review-active-tablet-768x1024.png"),
                (390, 844, True, "visual-review-active-mobile-390x844.png"),
                (360, 800, True, "visual-review-active-mobile-360x800.png"),
            )
            for width, height, mobile, filename in preview_viewports:
                await client.set_viewport(width, height, mobile=mobile)
                await client.eval_js("window.scrollTo({top:0,behavior:'instant'})")
                await asyncio.sleep(0.15)
                capture = await client.send_cmd(
                    "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                )
                (preview_evidence_dir / filename).write_bytes(base64.b64decode(capture["data"]))
            await client.set_viewport(1440, 900)

            # A malformed authenticated 200 response must not leave the previously
            # selected Run/Job visible or create a plausible partial detail.
            read_path = f"/api/v1/dashboard/changes/{project_id}/{secondary_change_name}"
            await client.eval_js(f"""
              (() => {{ window.__pwaReadIntegrity.path = {json.dumps(read_path)};
                window.__pwaReadIntegrity.mode = 'malformed';
                const row = [...document.querySelectorAll('#changesTableBody tr[data-project-id]')]
                  .find(item => item.dataset.changeName === {json.dumps(secondary_change_name)});
                row?.click(); return Boolean(row); }})()
            """)
            malformed_state = None
            for _ in range(40):
                malformed_state = await client.eval_js("""
                  (() => ({contentDisplay:getComputedStyle(document.getElementById('detailContent')).display,
                    placeholder:document.getElementById('detailPlaceholder').textContent,
                    detail:document.getElementById('detailPanel').innerText,
                    runId:document.getElementById('dtChangeName').textContent}))()
                """)
                if "Detalle no disponible" in malformed_state["placeholder"]:
                    break
                await asyncio.sleep(0.05)
            assert malformed_state and "Detalle no disponible" in malformed_state["placeholder"], (
                malformed_state
            )
            assert malformed_state["contentDisplay"] == "none"
            assert (
                run_id not in malformed_state["detail"] and job_id not in malformed_state["detail"]
            )

            # Hold a real authenticated response for the old selection while a
            # second real read wins. Releasing the old response cannot restore it.
            original_path = f"/api/v1/dashboard/changes/{project_id}/{change_name}"
            await client.eval_js(f"""
              (() => {{ window.__pwaReadIntegrity.path = {json.dumps(original_path)};
                window.__pwaReadIntegrity.mode = 'delay';
                const row = [...document.querySelectorAll('#changesTableBody tr[data-project-id]')]
                  .find(item => item.dataset.changeName === {json.dumps(change_name)});
                row?.click(); return Boolean(row); }})()
            """)
            delayed_started = False
            for _ in range(40):
                delayed_started = await client.eval_js(
                    "Boolean(window.__pwaReadIntegrity.releaseDelayed)"
                )
                if delayed_started:
                    break
                await asyncio.sleep(0.05)
            assert delayed_started, "Expected authenticated old-selection response was not delayed."
            await client.eval_js(f"""
              (() => {{ window.__pwaReadIntegrity.path = null;
                const row = [...document.querySelectorAll('#changesTableBody tr[data-project-id]')]
                  .find(item => item.dataset.changeName === {json.dumps(secondary_change_name)});
                row?.click(); return Boolean(row); }})()
            """)
            second_selection = None
            for _ in range(40):
                second_selection = await client.eval_js("""
                  (() => ({title:document.getElementById('dtChangeName').textContent,
                    detail:document.getElementById('detailPanel').innerText,
                    placeholder:document.getElementById('detailPlaceholder').textContent}))()
                """)
                if secondary_change_name in second_selection["detail"]:
                    break
                await asyncio.sleep(0.05)
            assert second_selection and secondary_change_name in second_selection["detail"], (
                second_selection
            )
            await client.eval_js("window.__pwaReadIntegrity.releaseDelayed()")
            await asyncio.sleep(0.1)
            final_selection = await client.eval_js("""
              (() => ({title:document.getElementById('dtChangeName').textContent,
                detail:document.getElementById('detailPanel').innerText}))()
            """)
            assert secondary_change_name in final_selection["detail"]
            assert (
                run_id not in final_selection["detail"] and job_id not in final_selection["detail"]
            )
            await client.eval_js(f"""
              (() => [...document.querySelectorAll('#changesTableBody tr[data-project-id]')]
                .find(item => item.dataset.changeName === {json.dumps(change_name)})?.click())()
            """)
            for _ in range(40):
                selected_detail = await client.eval_js(
                    "document.getElementById('detailPanel').innerText"
                )
                if change_name in selected_detail and run_id in selected_detail:
                    break
                await asyncio.sleep(0.05)

            action_button = None
            for _ in range(40):
                action_button = await client.eval_js("""
                  (() => { const button = document.querySelector('#actionToolbar [data-action="CANCEL"]');
                    return button ? {text: button.textContent.trim(), disabled: button.disabled, title: button.title} : null; })()
                """)
                if action_button and not action_button["disabled"]:
                    break
                await asyncio.sleep(0.1)
            action_disclosure = await client.eval_js("""
              (() => ({open:document.getElementById('operatorActions').open,
                summary:document.querySelector('#operatorActions summary').innerText,
                buttons:[...document.querySelectorAll('#actionToolbar [data-action]')]
                  .every(button => getComputedStyle(button).display !== 'none')}))()
            """)
            assert action_disclosure["open"] is False, action_disclosure
            await client.eval_js("document.querySelector('#operatorActions summary').click()")
            assert await client.eval_js("document.getElementById('operatorActions').open")
            assert (
                action_button
                and action_button["text"] == "Cancel Run"
                and not action_button["disabled"]
            ), {
                "action": action_button,
                "cancel_descriptor": await client.eval_js(
                    "fetch('/api/v1/runs/%s/actions').then(async r=>(await r.json()).find(a=>a.action==='CANCEL'))"
                    % run_id
                ),
                "run_state": await client.eval_js(
                    "fetch('/api/v1/orchestration/%s/status').then(async r=>{const d=await r.json(); "
                    "return {run_id:d.run_id,current_stage:d.current_stage,is_active:d.is_active,"
                    "stop_outcome:d.stop_outcome}})" % run_id
                ),
            }
            confirmation_opened = await client.eval_js("""
              (() => { document.querySelector('#actionToolbar [data-action="CANCEL"]').click();
                const dialog = document.getElementById('actionDialog');
                return {open:dialog.open, title:dialog.querySelector('[data-dialog-title]').textContent}; })()
            """)
            assert confirmation_opened == {"open": True, "title": "Cancel Run"}, confirmation_opened
            await client.eval_js("document.getElementById('confirmActionBtn').click()")

            final_state = None
            for _ in range(40):
                final_state = await client.eval_js("""
                  ({toast: document.getElementById('toastNotification').textContent,
                    badge: document.querySelector('#viewExecutions .detail-panel .badge')?.textContent || '',
                    status: document.querySelector('#viewExecutions .detail-panel')?.innerText || ''})
                """)
                verify_session = db_manager.sessionmaker()
                verify_uow = PostgresPersistenceUnitOfWork(verify_session)
                run = verify_uow.orchestration_runs.get_by_id(run_id)
                job = verify_uow.jobs.get_by_id(job_id)
                records = verify_uow.operator_actions.list_by_run(run_id, limit=1)
                record = records[0] if records else None
                verify_session.close()
                if run and not run.is_active:
                    break
                await asyncio.sleep(0.1)

            for _ in range(40):
                if "Ejecutando" not in final_state["toast"] and (
                    "CANCELLED" in final_state["status"] or "CANCELLED" in final_state["toast"]
                ):
                    break
                await asyncio.sleep(0.1)
                final_state = await client.eval_js("""
                  ({toast: document.getElementById('toastNotification').textContent,
                    status: document.querySelector('#viewExecutions .detail-panel')?.innerText || ''})
                """)

            assert (
                run is not None and not run.is_active and run.stop_outcome.value == "CANCELLED"
            ), {
                "run_active": run.is_active if run else None,
                "run_outcome": run.stop_outcome.value if run and run.stop_outcome else None,
                "job_status": job.status.value if job else None,
                "action_record": record.model_dump(mode="json") if record else None,
                "toast": final_state["toast"],
                "dialog_open": await client.eval_js("document.getElementById('actionDialog').open"),
                "action_button": action_button,
            }
            assert job is not None and job.status == JobStatus.CANCELLED
            assert (
                record is not None
                and record.run_id == run_id
                and record.status.value == "COMPLETED"
            )
            assert "Acción CANCEL completada" in final_state["toast"]
            assert "CANCELLED" in final_state["status"] or "CANCELLED" in final_state["toast"]

            cancelled_presentation = await client.eval_js("""
              (() => ({badgeClass:document.getElementById('dtStatusBadge').className,
                stageLabel:document.getElementById('dtStageLabel').innerText,
                overviewLabel:document.querySelector('#overviewMetaGrid .meta-box-label').innerText,
                activePipeline:document.querySelector('#pipelineStepper .step-item.running')?.innerText || '',
                lastPipeline:document.querySelector('#pipelineStepper .step-item.stopped')?.innerText || ''}))()
            """)
            assert "badge-cancelled" in cancelled_presentation["badgeClass"]
            assert cancelled_presentation["stageLabel"] == "Última etapa:"
            assert cancelled_presentation["overviewLabel"].lower() == "última etapa observada"
            assert cancelled_presentation["activePipeline"] == ""
            assert "última etapa" in cancelled_presentation["lastPipeline"].lower()

            await client.set_viewport(390, 844, mobile=True)
            await asyncio.sleep(0.12)
            toast_geometry = await client.eval_js("""
              (() => { const toast=document.getElementById('toastNotification').getBoundingClientRect();
                const nav=document.querySelector('.bottom-nav').getBoundingClientRect();
                return {toastBottom:toast.bottom, navTop:nav.top, visible:getComputedStyle(document.getElementById('toastNotification')).display !== 'none'}; })()
            """)
            assert (
                toast_geometry["visible"]
                and toast_geometry["toastBottom"] <= toast_geometry["navTop"]
            ), toast_geometry
            toast_capture = await client.send_cmd(
                "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
            )
            (preview_evidence_dir / "visual-review-cancelled-mobile-390x844-toast.png").write_bytes(
                base64.b64decode(toast_capture["data"])
            )

            stale = await client.eval_js(
                """
              (async () => {
                const response = await fetch('/api/v1/runs/%s/actions/CANCEL', {
                  method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'},
                  body: JSON.stringify({action_request_id: crypto.randomUUID(), project_id:'%s',
                    change_name:'%s', run_id:'%s', action_type:'CANCEL', parameters:{},
                    actor_identity:'pwa-e2e', source_interface:'pwa', expected_stage:'IMPLEMENTING',
                    expected_generation:1})
                });
                return {http:response.status, body:await response.json()};
              })()
            """
                % (run_id, project_id, change_name, run_id)
            )
            assert stale["http"] == 200 and stale["body"]["status"] != "COMPLETED", stale

            cancelled_viewports = (
                (1440, 900, False, "visual-review-cancelled-desktop-1440x900.png"),
                (1024, 768, False, "visual-review-cancelled-tablet-1024x768.png"),
                (768, 1024, True, "visual-review-cancelled-tablet-768x1024.png"),
                (390, 844, True, "visual-review-cancelled-mobile-390x844.png"),
                (360, 800, True, "visual-review-cancelled-mobile-360x800.png"),
            )
            for width, height, mobile, filename in cancelled_viewports:
                await client.set_viewport(width, height, mobile=mobile)
                await client.eval_js("window.scrollTo({top:0,behavior:'instant'})")
                await asyncio.sleep(0.15)
                capture = await client.send_cmd(
                    "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                )
                (preview_evidence_dir / filename).write_bytes(base64.b64decode(capture["data"]))
            candidate_source_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, timeout=10
            ).strip()
            preview_manifest = {
                "candidate_source_sha": candidate_source_sha,
                "base_sha": base_sha,
                "image_digest": image_digest,
                "database": f"{parsed.database} (disposable; loopback host + private Docker bridge)",
                "run_id": run_id,
                "job_id": job_id,
                "project_id": project_id,
                "change_name": change_name,
                "durable_states_observed": ["IMPLEMENTING/RUNNING", "CANCELLED"],
                "screenshots": [
                    "visual-review-active-desktop-1440x900-landing.png",
                    "visual-review-active-desktop-1440x900-drawer.png",
                    "visual-review-cancelled-mobile-390x844-toast.png",
                ]
                + [filename for _, _, _, filename in preview_viewports]
                + [filename for _, _, _, filename in cancelled_viewports],
                "classification": "QA-seeded disposable PostgreSQL preview; not production evidence",
            }
            (preview_evidence_dir / "preview-acceptance-manifest.json").write_text(
                json.dumps(preview_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        finally:
            await client.close()
    finally:
        if preview_session is not None:
            await preview_service.teardown_preview(preview_session)
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old_overrides)
        if db_manager._engine is not None:
            db_manager._engine.dispose()
        db_manager._engine = old_engine
        db_manager._sessionmaker = old_sessionmaker
        db_manager._database_url = old_url


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
            const validDetail = (change_name) => ({project_id:'project',change_name,status:'UNKNOWN',
              run_id:null,job_id:null,pipeline:[],candidate_history:[],checks:[],timeline:[],blocker_details:[],
              candidate_authority:null,review:{},audit:{},github:{},preview_validation:{}});
            let releaseOld;
            const controller = createExecutionViewController({
              fetchRequest: url => url.includes('/old-change')
                ? new Promise(resolve => { releaseOld = resolve; })
                : Promise.resolve({ok:true,status:200,json:async () => validDetail('new-change')}),
              elements:{detailContent:content,detailPlaceholder:placeholder},
              setOfflineBanner:()=>{},onUnauthorized:()=>{},getNavigationState:()=>null,
              renderDetail:detail=>rendered.push(detail.change_name),statusClass:()=>'',formatRelativeTime:()=>'',
            });
            controller.selectChange('project','old-change');
            await Promise.resolve();
            controller.selectChange('project','new-change');
            await new Promise(resolve => setTimeout(resolve,0));
            releaseOld({ok:true,status:200,json:async () => validDetail('old-change')});
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
        assert "Ejecutor asignado" in identity["run"]
        assert detail["current_executor"] in identity["run"]
        assert "Rama destino" in identity["run"]
        assert "Gate humano" in identity["run"]
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
