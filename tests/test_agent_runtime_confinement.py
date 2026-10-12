"""Focused tests for attempt-private agent state and failure classification."""

import asyncio
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from minime.domain.enums import (
    ContinuationDecision,
    ExecutionOutcome,
    ProviderResultClass,
)
from minime.services.agent_confinement import (
    AgentCredentialError,
    AgentProcessConfinement,
)
from minime.services.continuation_engine import ContinuationContext, ContinuationEngine
from minime.services.implementer_runner import CliImplementerRunner
from minime.services.outcome_governance import (
    CompletionVerificationResult,
    OutcomeGovernanceService,
)
from minime.services.provider_outcome_parser import ProviderOutcomeParser
from minime.services.reviewer_runner import CliReviewerRunner


def _confinement(tmp_path: Path) -> tuple[AgentProcessConfinement, Path, Path]:
    worktree = tmp_path / "execution-worktree"
    runtime = tmp_path / "runtime"
    worktree.mkdir()
    runtime.mkdir()
    return (
        AgentProcessConfinement(
            allowed_worktree_path=str(worktree),
            runtime_root=str(runtime),
            private_state_parent=str(tmp_path),
            require_kernel_confinement=False,
        ),
        worktree,
        runtime,
    )


def test_attempt_state_is_private_sanitized_and_removed(tmp_path: Path):
    confinement, _worktree, _runtime = _confinement(tmp_path)
    auth = tmp_path / "authorized-codex-auth.json"
    auth.write_text('{"access_token":"do-not-log"}', encoding="utf-8")
    auth.chmod(0o600)
    base_env = {
        "HOME": "/global/home",
        "CODEX_HOME": "/global/codex",
        "TMPDIR": "/host/tmp",
        "XDG_RUNTIME_DIR": "/host/run",
        "OPENAI_API_KEY": "must-not-inherit",
        "NORMAL_SETTING": "preserved",
    }

    with confinement.runtime_session(base_env, str(auth)) as runtime:
        root = runtime.host_root
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(runtime.auth_copy.stat().st_mode) == 0o600
        assert runtime.auth_copy.read_bytes() == auth.read_bytes()
        assert "do-not-log" in runtime.sensitive_values
        env_root = (
            runtime.sandbox_root if confinement.confinement_mechanism == "bubblewrap" else str(root)
        )
        assert runtime.environment["CODEX_HOME"] == f"{env_root}/codex"
        assert runtime.environment["HOME"] == f"{env_root}/home"
        assert runtime.environment["TMPDIR"] == f"{env_root}/tmp"
        assert runtime.environment["XDG_RUNTIME_DIR"] == f"{env_root}/runtime"
        assert "OPENAI_API_KEY" not in runtime.environment
        assert runtime.environment["NORMAL_SETTING"] == "preserved"

    assert not root.exists()
    assert auth.read_text(encoding="utf-8") == '{"access_token":"do-not-log"}'
    assert (
        AgentProcessConfinement._scrub_credential_values(b"CLI echoed do-not-log", ("do-not-log",))
        == b"CLI echoed [REDACTED_CODEX_CREDENTIAL]"
    )


def test_private_credential_rotation_is_detected_and_never_copied_back(tmp_path: Path):
    confinement, _worktree, _runtime = _confinement(tmp_path)
    auth = tmp_path / "auth.json"
    auth.write_text('{"token":"original"}', encoding="utf-8")
    auth.chmod(0o600)

    with confinement.runtime_session({}, str(auth)) as runtime:
        runtime.auth_copy.write_text('{"token":"rotated"}', encoding="utf-8")
        assert runtime.observe_credential_state() is True
        root = runtime.host_root

    assert not root.exists()
    assert auth.read_text(encoding="utf-8") == '{"token":"original"}'


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="confined credential-output suppression requires an OS confinement mechanism",
)
def test_rotated_codex_credentials_and_child_output_are_never_returned(tmp_path: Path):
    confinement, worktree, _runtime = _confinement(tmp_path)
    auth = tmp_path / "auth.json"
    auth.write_text('{"token":"old-secret-token"}', encoding="utf-8")
    auth.chmod(0o600)
    script = (
        "import json,os,pathlib; "
        "p=pathlib.Path(os.environ['CODEX_HOME'])/'auth.json'; "
        "p.write_text(json.dumps({'token':'new-rotated-secret'})); "
        "print('new-rotated-secret')"
    )
    result = asyncio.run(
        confinement.run_confined_async_subprocess(
            [sys.executable, "-c", script],
            cwd=str(worktree),
            input_bytes=None,
            timeout_seconds=10,
            env=os.environ.copy(),
            codex_auth_source=str(auth),
        )
    )
    assert result.credential_rotation_detected is True
    assert result.stdout == b""
    assert b"new-rotated-secret" not in result.stderr
    assert auth.read_text(encoding="utf-8") == '{"token":"old-secret-token"}'


def test_unsafe_or_symlinked_credential_source_fails_closed(tmp_path: Path):
    confinement, _worktree, _runtime = _confinement(tmp_path)
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    auth.chmod(0o620)
    with pytest.raises(AgentCredentialError):
        with confinement.runtime_session({}, str(auth)):
            pytest.fail("unsafe auth source should not enter the runtime")

    auth.chmod(0o600)
    link = tmp_path / "auth-link.json"
    link.symlink_to(auth)
    with pytest.raises(AgentCredentialError):
        with confinement.runtime_session({}, str(link)):
            pytest.fail("symlink auth source should not enter the runtime")


def test_bubblewrap_command_binds_only_worktree_and_private_state(tmp_path: Path):
    confinement, worktree, runtime_root = _confinement(tmp_path)
    confinement.confinement_mechanism = "bubblewrap"
    with confinement.runtime_session({}) as runtime:
        command = confinement.wrap_command(["/usr/bin/true"], runtime)

    assert command[command.index("--bind") + 1 : command.index("--bind") + 3] == [
        str(worktree.resolve()),
        str(worktree.resolve()),
    ]
    assert ["--ro-bind", str(runtime_root.resolve()), str(runtime_root.resolve())] == [
        command[i : i + 3]
        for i in range(len(command) - 2)
        if command[i] == "--ro-bind" and command[i + 1] == str(runtime_root.resolve())
    ][0]
    assert ["--tmpfs", "/run"] == command[command.index("--tmpfs") : command.index("--tmpfs") + 2]
    assert "--unshare-pid" in command
    assert "/global" not in " ".join(command)


def test_environment_filesystem_failures_are_not_provider_failures():
    for message in (
        "Read-only file system (os error 30)",
        "failed to initialize sqlite state runtime: EROFS",
        "ENOENT: missing required path CODEX_HOME/tmp",
        "unable to create path aliases",
    ):
        parsed = ProviderOutcomeParser.parse_runner_output(
            provider="codex",
            role="implementer",
            model=None,
            exit_code=1,
            timed_out=False,
            stdout_lines=[],
            stderr_lines=[message],
        )
        assert parsed.result_class == ProviderResultClass.ENVIRONMENT_UNAVAILABLE
        outcome = OutcomeGovernanceService().classify_outcome(
            CompletionVerificationResult(is_complete=False), parsed
        )
        assert outcome == ExecutionOutcome.ENVIRONMENT_UNAVAILABLE
        decision = ContinuationEngine().decide(
            ContinuationContext(
                job_id="job",
                attempt_number=4,
                current_executor_role="codex",
                current_model_identity="codex",
                outcome=outcome,
                corrective_retries_for_current_executor=2,
                reassignment_count=2,
            )
        )
        assert decision.decision == ContinuationDecision.WAIT_EXTERNAL


def test_unknown_error_does_not_become_environment_failure():
    parsed = ProviderOutcomeParser.parse_runner_output(
        provider="codex",
        role="implementer",
        model=None,
        exit_code=1,
        timed_out=False,
        stdout_lines=[],
        stderr_lines=["UNKNOWN_ERROR: task could not be completed"],
    )
    assert parsed.result_class == ProviderResultClass.UNKNOWN_ERROR


@pytest.mark.parametrize("runner_type", [CliImplementerRunner, CliReviewerRunner])
def test_missing_kernel_confinement_is_environment_failure_before_cli_preflight(
    tmp_path: Path, monkeypatch, runner_type
):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(AgentProcessConfinement, "is_confinement_available", lambda _self: False)
    result = asyncio.run(runner_type(["codex", "exec", "-"]).run(worktree, "no inference", 1))
    assert result.environment_error is True
    assert result.preflight_error is None


@pytest.mark.skipif(
    not AgentProcessConfinement.is_host_confinement_available(),
    reason="process lifecycle cleanup requires an OS confinement mechanism",
)
def test_timeout_and_cancellation_reap_process_and_remove_private_runtime(tmp_path: Path):
    confinement, worktree, _runtime = _confinement(tmp_path)
    timed_out = asyncio.run(
        confinement.run_confined_async_subprocess(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=str(worktree),
            input_bytes=None,
            timeout_seconds=0.05,
            env=os.environ.copy(),
        )
    )
    assert timed_out.timed_out is True
    assert not list(tmp_path.glob("minime-agent-state-*"))

    async def cancel_attempt():
        task = asyncio.create_task(
            confinement.run_confined_async_subprocess(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                cwd=str(worktree),
                input_bytes=None,
                timeout_seconds=30,
                env=os.environ.copy(),
            )
        )
        for _ in range(100):
            if list(tmp_path.glob("minime-agent-state-*")):
                break
            await asyncio.sleep(0.01)
        assert list(tmp_path.glob("minime-agent-state-*"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not list(tmp_path.glob("minime-agent-state-*"))

    asyncio.run(cancel_attempt())


@pytest.mark.skipif(
    platform.system().lower() != "linux" or not shutil.which("bwrap"),
    reason="real write-denial proof requires Linux with Bubblewrap",
)
def test_real_bubblewrap_write_boundaries_and_ephemeral_cleanup(tmp_path: Path):
    confinement, worktree, runtime = _confinement(tmp_path)
    managed = tmp_path / "managed"
    other_worktree = tmp_path / "other-worktree"
    global_home = tmp_path / "global-home"
    arbitrary = tmp_path / "arbitrary-host-path"
    for directory in (managed, other_worktree, global_home):
        directory.mkdir()
    auth = tmp_path / "diagnostic-auth.json"
    auth.write_text("{}", encoding="utf-8")
    auth.chmod(0o600)
    ephemeral_root: Path | None = None
    with confinement.runtime_session({}, str(auth)) as state:
        ephemeral_root = state.host_root
        command = [
            sys.executable,
            "-c",
            "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); p.write_text('bad')",
            str(runtime / "escape"),
        ]
        wrapped = confinement.wrap_command(command, state)
        denied = subprocess.run(
            wrapped,
            cwd=worktree,
            env=state.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert denied.returncode != 0
        assert not (runtime / "escape").exists()
        positive = subprocess.run(
            confinement.wrap_command(
                [
                    sys.executable,
                    "-c",
                    "import os,pathlib; pathlib.Path('inside-worktree').write_text('ok'); "
                    "pathlib.Path(os.environ['CODEX_HOME'],'inside-state').write_text('ok')",
                ],
                state,
            ),
            cwd=worktree,
            env=state.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert positive.returncode == 0, positive.stderr
        assert (worktree / "inside-worktree").read_text(encoding="utf-8") == "ok"
        assert (state.host_root / "codex" / "inside-state").read_text(encoding="utf-8") == "ok"
        denied_paths = [
            runtime / "escape-2",
            managed / "escape",
            other_worktree / "escape",
            global_home / "escape",
            arbitrary / "escape",
            auth,
            tmp_path / "host-tmp-escape",
        ]
        for denied_path in denied_paths:
            wrapped = confinement.wrap_command(
                [
                    sys.executable,
                    "-c",
                    "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('bad')",
                    str(denied_path),
                ],
                state,
            )
            denied = subprocess.run(
                wrapped,
                cwd=worktree,
                env=state.environment,
                capture_output=True,
                text=True,
                check=False,
            )
            assert denied.returncode != 0, f"write unexpectedly succeeded: {denied_path}"
            if denied_path == auth:
                assert auth.read_text(encoding="utf-8") == "{}"
            else:
                assert not denied_path.exists()
        assert stat.S_IMODE(state.host_root.stat().st_mode) == 0o700
    assert ephemeral_root is not None and not ephemeral_root.exists()
    assert not (managed / "escape").exists()
    assert not (other_worktree / "escape").exists()
    assert not (global_home / "escape").exists()
    assert not (arbitrary / "escape").exists()
    assert auth.read_text(encoding="utf-8") == "{}"


@pytest.mark.skipif(
    platform.system().lower() != "linux" or not shutil.which("bwrap") or not shutil.which("codex"),
    reason="initialize-only Codex app-server smoke requires Linux, Bubblewrap, and Codex CLI",
)
def test_real_codex_app_server_initialize_only_under_bubblewrap(tmp_path: Path):
    worktree = tmp_path / "worktree"
    runtime = tmp_path / "runtime"
    worktree.mkdir()
    runtime.mkdir()
    confinement = AgentProcessConfinement(
        str(worktree), runtime_root=str(runtime), private_state_parent=str(tmp_path)
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": "mini-me-diagnostic", "version": "1"},
            "capabilities": {},
        },
    }

    async def initialize_only() -> tuple[bytes, bytes]:
        with confinement.runtime_session(os.environ.copy()) as runtime_state:
            process = await asyncio.create_subprocess_exec(
                *confinement.wrap_command(
                    ["codex", "app-server", "--listen", "stdio://"],
                    runtime_state,
                    unshare_network=True,
                ),
                cwd=str(worktree),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=runtime_state.environment,
                start_new_session=True,
            )
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write((json.dumps(request) + "\n").encode())
            await process.stdin.drain()
            try:
                response = await asyncio.wait_for(process.stdout.readline(), timeout=20)
                returncode = process.returncode
                if returncode is None:
                    await confinement._terminate_process_group(process)
                stderr = await process.stderr.read() if process.stderr is not None else b""
                return response + f"\nreturncode={returncode}".encode(), stderr
            finally:
                if process.returncode is None:
                    await confinement._terminate_process_group(process)

    response, stderr = asyncio.run(initialize_only())
    output = response.decode(errors="replace") + stderr.decode(errors="replace")
    assert "EROFS" not in output and "read-only file system" not in output.lower()
    assert response and b'"id":1' in response.replace(b" ", b"")
