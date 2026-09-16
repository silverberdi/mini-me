# Focused Task Group 6 tests: CLI invocation preflight and compatibility proving.

import shutil
from unittest.mock import AsyncMock, patch

import pytest

from minime.config import CliInvocationProfile
from minime.services.cli_preflight import preflight_cli_invocation
from minime.services.implementer_runner import CliImplementerRunner

CODEX_IMPL = CliInvocationProfile(
    "codex", "implementer", "codex", ("exec", "-", "--approve-for-me", "--ephemeral"), "stdin"
)
CODEX_REV = CliInvocationProfile(
    "codex",
    "reviewer",
    "codex",
    ("review", "-"),
    "stdin",
)

OLD_CODEX_REV = CliInvocationProfile(
    "codex",
    "reviewer",
    "codex",
    ("exec", "-", "--sandbox", "read-only", "--ask-for-approval", "never", "--ephemeral"),
    "stdin",
)
AGY_IMPL = CliInvocationProfile(
    "antigravity",
    "implementer",
    "agy",
    ("--mode", "accept-edits", "--dangerously-skip-permissions", "--print-timeout", "1h", "--print={prompt}"),
    "argument",
)
AGY_REV = CliInvocationProfile(
    "antigravity",
    "reviewer",
    "agy",
    ("--mode", "plan", "--dangerously-skip-permissions", "--print-timeout", "1h", "--print={prompt}"),
    "argument",
)


async def test_preflight_missing_executable():
    profile = CliInvocationProfile(
        "codex", "implementer", "no-such-cli-xyz-123", ("exec", "-", "--approve-for-me"), "stdin"
    )
    result = await preflight_cli_invocation(profile)
    assert result.ok is False
    assert result.reason == "EXECUTABLE_MISSING"


async def test_preflight_unsupported_flag_detected(monkeypatch):
    monkeypatch.setattr(
        "minime.services.cli_preflight.shutil.which", lambda *a, **k: "/usr/local/bin/codex"
    )

    async def fake_help():
        return (0, "usage: codex exec --approve-for-me --ephemeral")

    profile = CliInvocationProfile(
        "codex", "implementer", "codex", ("exec", "-", "--approve-for-me", "--bogus-flag"), "stdin"
    )
    result = await preflight_cli_invocation(profile, help_runner=fake_help)
    assert result.ok is False
    assert result.reason == "UNSUPPORTED_FLAG"
    assert "--bogus-flag" in result.missing_flags


async def test_preflight_accepted_when_flags_present(monkeypatch):
    monkeypatch.setattr(
        "minime.services.cli_preflight.shutil.which", lambda *a, **k: "/usr/local/bin/codex"
    )

    async def fake_help():
        return (0, "usage: codex exec --approve-for-me --ephemeral")

    result = await preflight_cli_invocation(CODEX_IMPL, help_runner=fake_help)
    assert result.ok is True


async def test_implementer_runner_fails_fast_on_preflight(tmp_path):
    profile = CliInvocationProfile(
        "codex", "implementer", "no-such-cli-xyz-123", ("exec", "-", "--approve-for-me"), "stdin"
    )
    runner = CliImplementerRunner(profile)
    with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as exec_mock:
        result = await runner.run(tmp_path, "do nothing", 30)
    assert result.preflight_error == "EXECUTABLE_MISSING"
    assert result.exit_code == -2
    exec_mock.assert_not_awaited()


@pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not installed")
async def test_codex_implementer_profile_accepted():
    result = await preflight_cli_invocation(CODEX_IMPL)
    assert result.ok is True


@pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not installed")
async def test_codex_reviewer_profile_rejected_ask_for_approval_unsupported():
    result = await preflight_cli_invocation(OLD_CODEX_REV)
    assert result.ok is False
    assert "--ask-for-approval" in result.missing_flags


@pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not installed")
async def test_codex_reviewer_profile_accepted():
    result = await preflight_cli_invocation(CODEX_REV)
    assert result.ok is True


@pytest.mark.skipif(shutil.which("agy") is None, reason="agy CLI not installed")
async def test_agy_implementer_profile_accepted():
    result = await preflight_cli_invocation(AGY_IMPL)
    assert result.ok is True


@pytest.mark.skipif(shutil.which("agy") is None, reason="agy CLI not installed")
async def test_agy_reviewer_profile_accepted():
    result = await preflight_cli_invocation(AGY_REV)
    assert result.ok is True
