"""Real browser regression for candidate resolution and confined evidence capture."""

from __future__ import annotations

import http.server
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from minime.config import PLAYWRIGHT_BROWSERS_PATH
from minime.services.agent_confinement import AgentProcessConfinement
from minime.services.candidate_test_resolver import CandidateTestResolver
from minime.services.checks_runner import ChecksRunner


def _has_chromium() -> bool:
    cache_root = Path(PLAYWRIGHT_BROWSERS_PATH)
    return any(cache_root.glob("chromium_headless_shell-*/**/chrome-headless-shell"))


def test_darwin_check_sandbox_allows_only_the_validated_private_cache(tmp_path: Path):
    cache = tmp_path / "private-cache"
    profile = AgentProcessConfinement._build_darwin_sandbox_profile(
        str(tmp_path / "worktree"), "/opt/minime/runtime", secure_cache_path=str(cache)
    )

    assert f'(allow file-write* (subpath "{cache}"))' in profile
    assert "(deny file-write*)" in profile
    assert '(allow file-write* (subpath "/Users")' not in profile


@pytest.mark.asyncio
@pytest.mark.skipif(not AgentProcessConfinement.is_host_confinement_available(), reason="confined checks require host confinement")
@pytest.mark.skipif(not _has_chromium(), reason="a Playwright Chromium runtime is required")
async def test_declared_playwright_runs_against_served_candidate_and_binds_sha(tmp_path: Path, monkeypatch):
    frontend_node_modules = Path(__file__).parents[1] / "frontend" / "node_modules"
    if not (frontend_node_modules / "@playwright" / "test").exists():
        pytest.skip("frontend Playwright dependency is not installed")

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Mini Me Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    (tmp_path / "package.json").write_text(
        '{"name":"candidate-e2e","scripts":{"test:e2e":"node e2e.mjs"}}', encoding="utf-8"
    )
    (tmp_path / "node_modules").symlink_to(frontend_node_modules, target_is_directory=True)
    (tmp_path / "index.html").write_text(
        """<!doctype html><html><body>
        <a href='/next.html'>Next</a><button id='load'>Load</button>
        <output id='result'></output><script>
        document.querySelector('#load').onclick=()=>setTimeout(()=>document.querySelector('#result').textContent='ready',25)
        </script></body></html>""",
        encoding="utf-8",
    )
    (tmp_path / "next.html").write_text("<h1>Candidate page</h1>", encoding="utf-8")
    (tmp_path / "e2e.mjs").write_text(
        """import { chromium } from '@playwright/test';
        const browser = await chromium.launch({headless:true});
        try {
          const first = await browser.newPage({viewport:{width:390,height:844}});
          const second = await browser.newPage({viewport:{width:1280,height:900}});
          await first.goto(process.env.CANDIDATE_URL);
          await first.getByRole('button',{name:'Load'}).click();
          await first.waitForFunction(()=>document.querySelector('#result').textContent==='ready');
          await first.getByRole('link',{name:'Next'}).click();
          if (!(await first.getByRole('heading',{name:'Candidate page'}).isVisible())) throw new Error('navigation failed');
          await second.goto(process.env.CANDIDATE_URL);
          if ((await second.locator('body').innerText()).includes('Candidate page')) throw new Error('sessions were not isolated');
          if (process.env.E2E_ASSERTION === 'fail') throw new Error('intentional assertion failure');
          console.log('navigation, async state, viewport, and isolated sessions passed');
        } finally { await browser.close(); }
        """,
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "package.json", "index.html", "next.html", "e2e.mjs"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "candidate fixture"], cwd=tmp_path, check=True, capture_output=True)
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=str(tmp_path), **kwargs))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        plan = CandidateTestResolver.resolve(tmp_path, {"index.html", "e2e.mjs"})
        assert plan.command == ["npm", "run", "test:e2e"]
        async def run_check(command: str, name: str):
            return await ChecksRunner().run(
                job_id="candidate-browser-e2e",
                checks=[{"name": name, "command": command}],
                worktree_path=tmp_path,
                candidate_sha=candidate_sha,
            )

        base_command = f"CANDIDATE_URL=http://127.0.0.1:{port}/"
        failed = await run_check(f"{base_command} E2E_ASSERTION=fail npm run test:e2e", "playwright-assertion-failure")
        assert not failed.passed
        assert failed.results[0].candidate_sha == candidate_sha
        assert failed.results[0].exit_code != 0
        assert failed.diagnostics[0].diagnostic_status.value == "FAIL"

        recovered = await run_check(f"{base_command} E2E_ASSERTION=pass npm run test:e2e", "playwright-recovery")
        assert recovered.passed, recovered.results[0].output_snippet if recovered.results else recovered.diagnostics
        check = recovered.results[0]
        assert check.command == f"{base_command} E2E_ASSERTION=pass npm run test:e2e"
        assert check.exit_code == 0
        assert check.duration_ms > 0
        assert check.candidate_sha == candidate_sha
        assert "navigation, async state, viewport, and isolated sessions passed" in check.output_snippet

        empty_browser_cache = tmp_path / "missing-runtime-browsers"
        empty_browser_cache.mkdir()
        monkeypatch.setattr("minime.config.PLAYWRIGHT_BROWSERS_PATH", str(empty_browser_cache))
        unavailable = await run_check(
            f"{base_command} npm run test:e2e",
            "playwright-missing-browser",
        )
        assert not unavailable.passed
        assert unavailable.diagnostics[0].diagnostic_status.value == "ENVIRONMENT_UNAVAILABLE"
        assert "Executable doesn't exist" in unavailable.diagnostics[0].reason
    finally:
        server.shutdown()
        thread.join(timeout=2)
