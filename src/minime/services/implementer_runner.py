"""Primary implementer process runners."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from minime.config import AppConfig, CliInvocationProfile, resolve_cli_invocation
from minime.logging import redact_secrets

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImplementerResult:
    exit_code: int
    timed_out: bool
    stdout: list[str]
    stderr: list[str]
    duration_ms: int


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
            return [
                self.profile.executable,
                *(arg.replace("{prompt}", prompt_context) for arg in self.profile.args),
            ]
        return self.command

    async def run(
        self, worktree_path: Path, prompt_context: str, timeout_seconds: int
    ) -> ImplementerResult:
        start = asyncio.get_running_loop().time()
        proc = await asyncio.create_subprocess_exec(
            *self._command_for_prompt(prompt_context),
            cwd=str(worktree_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        timed_out = False
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
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                os.killpg(proc.pid, signal.SIGKILL)
                stdout, stderr = await proc.communicate()
        duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
        return ImplementerResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            timed_out=timed_out,
            stdout=self._sanitize_output(stdout),
            stderr=self._sanitize_output(stderr),
            duration_ms=duration_ms,
        )

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
