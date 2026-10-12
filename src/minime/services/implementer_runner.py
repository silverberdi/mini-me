"""Primary implementer process runners."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from minime.config import AppConfig, CliInvocationProfile, resolve_cli_invocation
from minime.domain.enums import ExternalOutcome
from minime.logging import redact_secrets
from minime.services.agent_confinement import AgentConfinementError, AgentProcessConfinement
from minime.services.cli_preflight import preflight_cli_invocation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImplementerResult:
    exit_code: int
    timed_out: bool
    stdout: list[str]
    stderr: list[str]
    duration_ms: int
    preflight_error: str | None = None
    environment_error: bool = False


class ImplementerRunnerInterface:
    async def run(
        self, worktree_path: Path, prompt_context: str, timeout_seconds: int
    ) -> ImplementerResult:
        raise NotImplementedError


class CliImplementerRunner(ImplementerRunnerInterface):
    MAX_OUTPUT_LINES = 2000
    MAX_LINE_CHARS = 4000

    def __init__(self, invocation: CliInvocationProfile | list[str]):
        if isinstance(invocation, CliInvocationProfile):
            if invocation.prompt_transport not in {"stdin", "argument"}:
                raise ValueError(f"Unsupported prompt transport '{invocation.prompt_transport}'.")
            self.profile = invocation
            self.command = [invocation.executable, *invocation.args]
        else:
            self.profile = None
            self.command = invocation

    def _command_for_prompt(self, prompt_context: str) -> list[str]:
        if self.profile and self.profile.prompt_transport == "argument":
            raw_cmd = [
                self.profile.executable,
                *(arg.replace("{prompt}", prompt_context) for arg in self.profile.args),
            ]
        else:
            raw_cmd = list(self.command)
        if raw_cmd:
            search_path = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}"
            resolved = shutil.which(raw_cmd[0], path=search_path)
            if resolved:
                raw_cmd[0] = resolved
        return raw_cmd

    async def run(
        self, worktree_path: Path, prompt_context: str, timeout_seconds: int
    ) -> ImplementerResult:
        start = asyncio.get_running_loop().time()
        confinement = AgentProcessConfinement(allowed_worktree_path=str(worktree_path))
        preflight_check = confinement.validate_command_preflight(cwd=str(worktree_path))
        if preflight_check.outcome != ExternalOutcome.SUCCESS:
            environment_error = confinement.is_local_environment_preflight_error(
                preflight_check.error_message
            )
            return ImplementerResult(
                exit_code=-2,
                timed_out=False,
                stdout=[],
                stderr=[
                    redact_secrets(
                        preflight_check.error_message
                        or "Agent process confinement preflight failed"
                    )
                ],
                duration_ms=0,
                preflight_error=None if environment_error else preflight_check.error_message,
                environment_error=environment_error,
            )

        if self.profile is not None:
            preflight = await preflight_cli_invocation(self.profile)
            if not preflight.ok:
                return ImplementerResult(
                    exit_code=-2,
                    timed_out=False,
                    stdout=[],
                    stderr=[redact_secrets(preflight.reason or "preflight failed")],
                    duration_ms=0,
                    preflight_error=preflight.reason,
                )

        raw_command = self._command_for_prompt(prompt_context)
        input_bytes = (
            prompt_context.encode()
            if not self.profile or self.profile.prompt_transport == "stdin"
            else None
        )
        try:
            process_result = await confinement.run_confined_async_subprocess(
                raw_command,
                cwd=str(worktree_path),
                input_bytes=input_bytes,
                timeout_seconds=timeout_seconds,
                codex_auth_source=(
                    confinement.codex_auth_source()
                    if self.profile is not None and self.profile.provider.lower() == "codex"
                    else None
                ),
                antigravity_auth_source=(
                    confinement.antigravity_auth_source()
                    if self.profile is not None and self.profile.provider.lower() == "antigravity"
                    else None
                ),
            )
        except AgentConfinementError as err:
            return ImplementerResult(
                exit_code=-2,
                timed_out=False,
                stdout=[],
                stderr=[redact_secrets(str(err))],
                duration_ms=int((asyncio.get_running_loop().time() - start) * 1000),
                preflight_error=(
                    "PROVIDER_CREDENTIAL_UNAVAILABLE"
                    if not err.environment_unavailable
                    else "AGENT_RUNTIME_UNAVAILABLE"
                ),
                environment_error=err.environment_unavailable,
            )
        duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
        rotation_error = (
            process_result.credential_rotation_detected
            and not process_result.credential_access_refresh_only
        )
        return ImplementerResult(
            exit_code=process_result.returncode,
            timed_out=process_result.timed_out,
            stdout=self._sanitize_output(process_result.stdout),
            stderr=self._sanitize_output(process_result.stderr),
            duration_ms=duration_ms,
            preflight_error=(
                "PROVIDER_CREDENTIAL_ROTATION_NOT_PERSISTED" if rotation_error else None
            ),
            environment_error=rotation_error,
        )

    async def _terminate_process_group(self, proc: asyncio.subprocess.Process) -> None:
        """Bounded, cancellation-protected process-group teardown.

        Emits SIGTERM, awaits a bounded grace period, then SIGKILLs and awaits
        termination. Returns only once the process group is fully cleaned up.
        """
        if proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return
        except Exception:
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            await proc.communicate()
        except Exception:
            pass

    @classmethod
    def _sanitize_output(cls, output: bytes) -> list[str]:
        lines = output.decode(errors="replace").splitlines()[: cls.MAX_OUTPUT_LINES]
        return [redact_secrets(line[: cls.MAX_LINE_CHARS]) for line in lines]


class MockImplementerRunner(ImplementerRunnerInterface):
    def __init__(
        self,
        exit_code: int = 0,
        stdout: list[str] | None = None,
        stderr: list[str] | None = None,
        timed_out: bool = False,
    ):
        self.exit_code = exit_code
        self.stdout = stdout or []
        self.stderr = stderr or []
        self.timed_out = timed_out

    async def run(
        self, worktree_path: Path, prompt_context: str, timeout_seconds: int
    ) -> ImplementerResult:
        del prompt_context, timeout_seconds
        if self.exit_code == 0 and not self.timed_out:
            try:
                candidate_file = Path(worktree_path) / "candidate_impl.py"
                candidate_file.write_text("# Candidate implementation artifact\n")
                p1 = subprocess.run(
                    ["git", "add", "candidate_impl.py"],
                    cwd=str(worktree_path),
                    capture_output=True,
                    text=True,
                )
                p2 = subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.name=Test",
                        "-c",
                        "user.email=test@example.com",
                        "commit",
                        "-m",
                        "candidate changes",
                    ],
                    cwd=str(worktree_path),
                    capture_output=True,
                    text=True,
                )
                if p2.returncode != 0:
                    logger.warning(
                        f"Git commit failed in MockImplementerRunner: {p2.stderr} (add stdout: {p1.stdout}, add stderr: {p1.stderr})"
                    )
            except Exception as e:
                logger.warning(f"MockImplementerRunner exception: {e}")
        return ImplementerResult(
            exit_code=self.exit_code,
            timed_out=self.timed_out,
            stdout=[redact_secrets(line) for line in self.stdout],
            stderr=[redact_secrets(line) for line in self.stderr],
            duration_ms=1,
        )


def runner_for_implementer(
    implementer: str, config: AppConfig | None = None
) -> ImplementerRunnerInterface:
    return CliImplementerRunner(resolve_cli_invocation(implementer, "implementer", config))
