"""Executable regressions for the F3 runner/confinement boundary."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from minime.config import CliInvocationProfile
from minime.services.agent_confinement import AgentProcessConfinement
from minime.services.agent_runner import CliAgentRunner


@pytest.mark.asyncio
async def test_cli_runner_executes_only_through_confined_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    worktree = tmp_path / "worktree"
    runtime = tmp_path / "runtime"
    outside = tmp_path / "outside.txt"
    worktree.mkdir()
    runtime.mkdir(mode=0o700)
    (worktree / "authorized.txt").write_text("worktree-ok", encoding="utf-8")
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime))
    script = (
        "import os,pathlib; "
        "print((pathlib.Path.cwd()/'authorized.txt').read_text()); "
        f"p=pathlib.Path({str(outside)!r}); "
        "\ntry: p.write_text('forbidden')\nexcept OSError: print('outside-blocked')\n"
    )
    profile = CliInvocationProfile(
        provider="codex",
        role="implementer",
        executable=sys.executable,
        args=("-c", script),
        prompt_transport="stdin",
    )
    monkeypatch.setattr(AgentProcessConfinement, "codex_auth_source", lambda _self, _env=None: None)
    if not AgentProcessConfinement.is_host_confinement_available():
        pytest.skip("host kernel confinement is unavailable")

    result = await CliAgentRunner(invocation=profile).run(
        worktree_path=worktree,
        prompt_context="confinement-check",
        provider="codex",
        role="implementer",
    )

    assert result.exit_code == 0
    assert "worktree-ok" in result.stdout
    assert "outside-blocked" in result.stdout
    assert not outside.exists()


@pytest.mark.asyncio
async def test_cli_runner_fails_closed_when_confinement_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    worktree = tmp_path / "worktree"
    runtime = tmp_path / "runtime"
    worktree.mkdir()
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime))
    monkeypatch.setattr(AgentProcessConfinement, "is_confinement_available", lambda _self: False)
    profile = CliInvocationProfile(
        provider="codex",
        role="implementer",
        executable=sys.executable,
        args=("-c", "print('must-not-run')"),
        prompt_transport="stdin",
    )

    result = await CliAgentRunner(invocation=profile).run(
        worktree_path=worktree,
        prompt_context="must-fail-closed",
        provider="codex",
        role="implementer",
    )

    assert result.exit_code == -2
    assert result.preflight_error
    assert result.stdout == []


@pytest.mark.asyncio
async def test_cli_runner_uses_native_last_message_file_and_cleans_attempt_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    worktree = tmp_path / "worktree"
    runtime = tmp_path / "runtime"
    worktree.mkdir()
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime))
    script = (
        "import json,pathlib,sys; "
        "schema=pathlib.Path(sys.argv[sys.argv.index('--output-schema')+1]); "
        "out=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]); "
        "assert schema.is_file(); print('transport-noise'); "
        "print('diagnostic', file=sys.stderr); "
        "out.write_text(json.dumps({'complexity':'low','evidence':'native channel'}))"
    )
    profile = CliInvocationProfile(
        provider="codex",
        role="thinker",
        executable=sys.executable,
        args=("-c", script),
        prompt_transport="stdin",
    )
    monkeypatch.setattr(AgentProcessConfinement, "codex_auth_source", lambda _self, _env=None: None)
    if not AgentProcessConfinement.is_host_confinement_available():
        pytest.skip("host kernel confinement is unavailable")
    response_path = worktree / ".minime" / "classification-attempts" / "attempt-1" / "last-message.json"

    result = await CliAgentRunner(invocation=profile).run(
        worktree_path=worktree,
        prompt_context="classification-check",
        provider="codex",
        role="thinker",
        output_schema={"type": "object"},
        output_last_message_path=response_path,
    )

    assert result.exit_code == 0
    assert result.response_output == '{"complexity": "low", "evidence": "native channel"}'
    assert result.stderr == ["diagnostic"]
    assert not response_path.exists()
    assert not response_path.with_name("response.schema.json").exists()
