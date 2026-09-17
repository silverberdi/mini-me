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
from minime.logging import redact_secrets
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
        if self.profile is not None:
            preflight = await preflight_cli_invocation(self.profile)
            if not preflight.ok:
                return ImplementerResult(
                    exit_code=-2,
                    timed_out=False,
                    stdout=[],
                    stderr=[redact_secrets(preflight.reason or 'preflight failed')],
                    duration_ms=0,
                    preflight_error=preflight.reason,
                )
        proc = await asyncio.create_subprocess_exec(
            *self._command_for_prompt(prompt_context),
            cwd=str(worktree_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        timed_out = False
        stdout = b""
        stderr = b""
        try:
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(
                        prompt_context.encode()
                        if not self.profile or self.profile.prompt_transport == "stdin"
                        else None
                    ),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except OSError:
                    pass
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
                except (asyncio.TimeoutError, Exception):
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    stdout, stderr = await proc.communicate()
        except BaseException as exc:
            # Bounded, cancellation-protected cleanup: SIGTERM -> grace -> SIGKILL,
            # awaiting process-group termination BEFORE the exception propagates.
            # Re-arm cancellation after cleanup so it is never silently swallowed.
            task = asyncio.current_task()
            was_cancelled = (
                isinstance(exc, asyncio.CancelledError)
                and task is not None
                and task.cancelling() > 0
            )
            if was_cancelled:
                task.uncancel()
            try:
                await self._terminate_process_group(proc)
            finally:
                if was_cancelled:
                    task.cancel()
            raise
        duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
        return ImplementerResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            timed_out=timed_out,
            stdout=self._sanitize_output(stdout),
            stderr=self._sanitize_output(stderr),
            duration_ms=duration_ms,
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
