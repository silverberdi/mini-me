"""Primary implementer process runners."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from minime.config import AppConfig, CliInvocationProfile, resolve_cli_invocation
from minime.domain.enums import ExternalOutcome
from minime.logging import redact_secrets
from minime.services.agent_confinement import AgentConfinementError, AgentProcessConfinement
from minime.services.cli_preflight import preflight_cli_invocation
from minime.services.native_openspec_apply import parse_codex_apply_jsonl

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
    native_workflow_evidence: dict[str, object] | None = None


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
        effective_profile = self._profile_for_prompt()
        if effective_profile and effective_profile.prompt_transport == "argument":
            raw_cmd = [
                effective_profile.executable,
                *(arg.replace("{prompt}", prompt_context) for arg in effective_profile.args),
            ]
        elif effective_profile is not None:
            raw_cmd = [effective_profile.executable, *effective_profile.args]
        else:
            raw_cmd = list(self.command)
        if raw_cmd:
            search_path = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}"
            resolved = shutil.which(raw_cmd[0], path=search_path)
            if resolved:
                raw_cmd[0] = resolved
        return raw_cmd

    def _profile_for_prompt(self):
        if self.profile is None:
            return None
        if self.profile.provider.lower() != "codex" or self.profile.role != "implementer":
            return self.profile
        args = list(self.profile.args)
        if not args or args[0] != "exec":
            raise ValueError(
                "Codex implementer profile must use the observable `codex exec` interface."
            )
        if "--json" not in args:
            args.insert(1, "--json")
        return replace(self.profile, args=tuple(args))

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

        try:
            effective_profile = self._profile_for_prompt()
        except ValueError as exc:
            return ImplementerResult(
                exit_code=-2,
                timed_out=False,
                stdout=[],
                stderr=[redact_secrets(str(exc))],
                duration_ms=0,
                preflight_error="NATIVE_WORKFLOW_TRANSPORT_UNSUPPORTED",
            )

        if effective_profile is not None:
            preflight = await preflight_cli_invocation(effective_profile)
            if not preflight.ok:
                return ImplementerResult(
                    exit_code=-2,
                    timed_out=False,
                    stdout=[],
                    stderr=[redact_secrets(preflight.reason or "preflight failed")],
                    duration_ms=0,
                    preflight_error=preflight.reason,
                )

        try:
            raw_command = self._command_for_prompt(prompt_context)
        except ValueError as exc:
            return ImplementerResult(
                exit_code=-2,
                timed_out=False,
                stdout=[],
                stderr=[redact_secrets(str(exc))],
                duration_ms=0,
                preflight_error="NATIVE_WORKFLOW_TRANSPORT_UNSUPPORTED",
            )
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
        stdout_lines: list[str]
        workflow_evidence: dict[str, object] | None = None
        if (
            self.profile is not None
            and self.profile.provider.lower() == "codex"
            and self.profile.role == "implementer"
        ):
            from minime.services.native_openspec_apply import (
                CODEX_APPLY_SKILL_PATH,
                NATIVE_APPLY_CHANGE_RE,
                NATIVE_APPLY_SKILL_SHA_RE,
            )

            change_match = NATIVE_APPLY_CHANGE_RE.search(prompt_context)
            sha_match = NATIVE_APPLY_SKILL_SHA_RE.search(prompt_context)
            expected_change = change_match.group(1) if change_match else ""
            expected_sha = sha_match.group(1) if sha_match else ""
            raw_jsonl_lines = process_result.stdout.decode(errors="replace").splitlines()[
                : self.MAX_OUTPUT_LINES
            ]
            extracted_messages, workflow_evidence = parse_codex_apply_jsonl(
                raw_jsonl_lines,
                change_name=expected_change,
                workflow_path=CODEX_APPLY_SKILL_PATH,
                workflow_sha256=expected_sha,
            )
            stdout_lines = self._sanitize_output("\n".join(extracted_messages).encode())
            # Codex may report a failed turn only through JSONL stdout. The
            # workflow parser intentionally discards non-message events, so
            # retain only bounded/redacted error summaries in stderr on failure.
            if process_result.returncode != 0 or process_result.timed_out:
                stderr_errors = self._codex_failure_events(raw_jsonl_lines)
            else:
                stderr_errors = []
        elif (
            self.profile is not None
            and self.profile.provider.lower() in {"antigravity", "agy"}
            and self.profile.role == "implementer"
        ):
            from minime.services.native_openspec_apply import (
                AGY_APPLY_SKILL_PATH,
                NATIVE_APPLY_SKILL_SHA_RE,
                parse_antigravity_apply_output,
            )

            change_match = re.search(r"/opsx-apply\s+([a-z0-9][a-z0-9._-]{0,127})", prompt_context)
            sha_match = NATIVE_APPLY_SKILL_SHA_RE.search(prompt_context)
            expected_change = change_match.group(1) if change_match else ""
            expected_sha = sha_match.group(1) if sha_match else ""
            raw_lines = process_result.stdout.decode(errors="replace").splitlines()[
                : self.MAX_OUTPUT_LINES
            ]
            extracted_messages, workflow_evidence = parse_antigravity_apply_output(
                raw_lines,
                change_name=expected_change,
                workflow_path=AGY_APPLY_SKILL_PATH,
                workflow_sha256=expected_sha,
            )
            stdout_lines = self._sanitize_output("\n".join(extracted_messages).encode())
        else:
            stdout_lines = self._sanitize_output(process_result.stdout)
        stderr_lines = self._sanitize_output(process_result.stderr)
        if self.profile is not None and self.profile.provider.lower() == "codex":
            stderr_lines.extend(stderr_errors)
        return ImplementerResult(
            exit_code=process_result.returncode,
            timed_out=process_result.timed_out,
            stdout=stdout_lines,
            stderr=stderr_lines,
            duration_ms=duration_ms,
            preflight_error=(
                "PROVIDER_CREDENTIAL_ROTATION_NOT_PERSISTED" if rotation_error else None
            ),
            environment_error=rotation_error,
            native_workflow_evidence=workflow_evidence,
        )

    @staticmethod
    def _codex_failure_events(jsonl_lines: list[str]) -> list[str]:
        """Retain only bounded, redacted CLI error events; never tool/model text."""
        errors: list[str] = []
        for line in jsonl_lines:
            try:
                event = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict) or event.get("type") not in {
                "error", "turn.failed"
            }:
                continue
            item = event.get("error")
            if isinstance(item, dict):
                message = item.get("message")
            elif isinstance(item, str):
                message = item
            else:
                message = event.get("message")
            if isinstance(message, str) and message.strip():
                errors.append("codex error: " + redact_secrets(message.strip())[:512])
            if len(errors) == 3:
                break
        return errors

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
    implementer: str,
    config: AppConfig | None = None,
    *,
    model: str | None = None,
    effort: str | None = None,
) -> ImplementerRunnerInterface:
    return CliImplementerRunner(
        resolve_cli_invocation(implementer, "implementer", config, model=model, effort=effort)
    )
