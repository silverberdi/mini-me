"""Consolidated agent process runner with sandboxing, capacity preflight, and dynamic OpenSpec resolution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minime.config import AppConfig, CliInvocationProfile, load_config, resolve_cli_invocation
from minime.domain.enums import ExternalOutcome
from minime.logging import get_logger, redact_secrets
from minime.services.agent_confinement import AgentConfinementError, AgentProcessConfinement

logger = get_logger("services.agent_runner")

_SKILL_NAME_RE = re.compile(r"(?m)^name:\s*([A-Za-z0-9._-]+)\s*$")
_SKILL_VERSION_RE = re.compile(r"(?m)^\s+version:\s*['\"]?([A-Za-z0-9._-]+)['\"]?\s*$")


class CapacityExhaustedError(RuntimeError):
    """Raised when provider capacity, rate-limit, or budget headroom is exhausted."""

    def __init__(self, provider_id: str, message: str) -> None:
        super().__init__(message)
        self.provider_id = provider_id


class NativeOpenSpecWorkflowUnavailable(ValueError):
    """Raised when an official OpenSpec workflow is missing or incompatible."""


@dataclass(frozen=True)
class ResolvedWorkflow:
    provider: str
    operation: str
    workflow_name: str
    workflow_path: str
    workflow_sha256: str
    change_name: str
    dispatch_command: str


@dataclass(frozen=True)
class AgentExecutionResult:
    exit_code: int
    timed_out: bool
    stdout: list[str]
    stderr: list[str]
    duration_ms: int
    preflight_error: str | None = None
    environment_error: bool = False
    workflow: ResolvedWorkflow | None = None
    structured_output: list[str] | None = None
    diagnostic_output: list[str] | None = None
    output_truncated: bool = False
    structured_output_missing: bool = False
    structured_output_too_large: bool = False
    final_response: str | None = None
    final_response_status: str | None = None
    final_response_source: str | None = None

    @property
    def full_output(self) -> str:
        return "\n".join(self.stdout + self.stderr)

    @property
    def response_output(self) -> str:
        """Return only the authoritative provider response channel, excluding diagnostics.

        If final_response_status is specified:
        - Only 'COMPLETE' allows access to final_response.
        - If final_response is missing, empty, or whitespace, it returns ""
          (never falls back to diagnostic stdout or incidental output).
        If final_response_status is not specified (e.g. legacy test fixtures without status):
        - Returns explicit final_response if present, then structured_output, then stdout.
        """
        if self.final_response_status is not None:
            if self.final_response_status != "COMPLETE":
                return ""
            if self.final_response is not None and self.final_response.strip():
                return self.final_response.strip()
            return ""
        if self.final_response is not None and self.final_response.strip():
            return self.final_response.strip()
        if self.structured_output is not None:
            return "\n".join(self.structured_output).strip()
        return "\n".join(self.stdout).strip()

    def contains_token(self, token: str) -> bool:
        return token in self.full_output


class CliAgentRunner:
    """Unified runner for thinker, implementer, and reviewer agents under process confinement."""

    MAX_OUTPUT_LINES = 2500
    MAX_LINE_CHARS = 4000
    MAX_STRUCTURED_OUTPUT_BYTES = 1_048_576
    MAX_FINAL_RESPONSE_BYTES = MAX_STRUCTURED_OUTPUT_BYTES

    @classmethod
    def _extract_final_response(
        cls, stdout: bytes, provider: str, *, captured_incompletely: bool = False
    ) -> tuple[str | None, str, str]:
        """Extract a complete provider answer BEFORE diagnostic log abbreviations.

        This method has no authority over OpenSpec stages: it verifies transport
        completeness only. An incomplete Codex event stream cannot degrade to
        plain text and accidentally authorize a stage from tool logs.
        """
        if captured_incompletely or len(stdout) > 8 * 1024 * 1024:
            return None, "TRUNCATED", "stdout"
        try:
            raw_text = stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None, "TRUNCATED", "stdout"
        raw_lines = raw_text.splitlines()
        events: list[dict[str, Any]] = []
        recognized = {
            "thread.started",
            "turn.started",
            "turn.completed",
            "turn.failed",
            "item.started",
            "item.updated",
            "item.completed",
        }
        has_native_events = False
        malformed = False
        for line in raw_lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                malformed = True
                continue
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                malformed = True
                continue
            if event["type"] in recognized:
                has_native_events = True
            events.append(event)
        if has_native_events:
            if provider.lower() != "codex" or malformed:
                return None, "AMBIGUOUS", "codex_ndjson"
            completed = 0
            failed = False
            final_messages: list[str] = []
            for event in events:
                event_type = event.get("type")
                if event_type == "turn.failed":
                    failed = True
                elif event_type == "turn.completed":
                    completed += 1
                elif event_type == "item.completed":
                    item = event.get("item")
                    if not isinstance(item, dict):
                        return None, "AMBIGUOUS", "codex_ndjson"
                    if item.get("type") == "agent_message":
                        if completed or not isinstance(item.get("text"), str):
                            return None, "AMBIGUOUS", "codex_ndjson"
                        if item["text"].strip():
                            final_messages.append(item["text"])
            if failed or completed != 1 or not final_messages:
                return None, "AMBIGUOUS", "codex_ndjson"
            answer = final_messages[-1]
            source = "codex_ndjson"
        else:
            answer = raw_text
            source = "stdout_text"
        if not answer.strip():
            return None, "MISSING", source
        if len(answer.encode("utf-8")) > cls.MAX_FINAL_RESPONSE_BYTES:
            return None, "TRUNCATED", source
        return redact_secrets(answer), "COMPLETE", source

    def __init__(
        self,
        invocation: CliInvocationProfile | list[str] | None = None,
        capacity_service: Any | None = None,
        budget_service: Any | None = None,
        profiles: dict[tuple[str, str], CliInvocationProfile] | None = None,
    ) -> None:
        if isinstance(invocation, CliInvocationProfile):
            if invocation.prompt_transport not in {"stdin", "argument"}:
                raise ValueError(f"Unsupported prompt transport '{invocation.prompt_transport}'.")
            self.profile = invocation
            self.command = [invocation.executable, *invocation.args]
        elif isinstance(invocation, list):
            self.profile = None
            self.command = list(invocation)
        else:
            self.profile = None
            self.command = []
        self.capacity_service = capacity_service
        self.budget_service = budget_service
        self.profiles = profiles or {}

    @classmethod
    def for_project_profiles(
        cls,
        project_profiles: dict[str, Any],
        *,
        config: AppConfig | None = None,
        capacity_service: Any | None = None,
        budget_service: Any | None = None,
    ) -> "CliAgentRunner":
        """Build verified CLI invocations from the persisted F2 profile selection."""
        if not isinstance(project_profiles, dict):
            raise ValueError("Project agent profiles are missing or invalid.")
        role_map = {
            "thinking": "implementer",
            "execution": "implementer",
            "independent_review": "reviewer",
            "fallback": "implementer",
        }
        resolved: dict[tuple[str, str], CliInvocationProfile] = {}
        for profile_name, role in role_map.items():
            raw = project_profiles.get(profile_name)
            if hasattr(raw, "model_dump"):
                raw = raw.model_dump()
            if not isinstance(raw, dict):
                raise ValueError(f"Project profile '{profile_name}' is missing or invalid.")
            provider = str(raw.get("agent_id") or "").strip().lower()
            if not provider:
                raise ValueError(
                    f"Project profile '{profile_name}' has no verified agent identity."
                )
            provider = "antigravity" if provider == "agy" else provider
            profile = resolve_cli_invocation(
                provider,
                role,
                config or load_config(),
                model=str(raw.get("model_id") or "").strip() or None,
                effort=str(raw.get("effort") or "").strip() or None,
            )
            resolved[(profile_name, provider)] = profile
        return cls(
            capacity_service=capacity_service,
            budget_service=budget_service,
            profiles=resolved,
        )

    def resolve_workflow(
        self,
        worktree_path: str | Path,
        provider: str,
        operation: str,
        change_name: str,
    ) -> ResolvedWorkflow:
        """Dynamically resolve and verify official OpenSpec workflow in the worktree."""
        root = Path(worktree_path).resolve(strict=True)
        prov = provider.lower()
        prov = "antigravity" if prov == "agy" else prov
        op = operation.lower()

        if prov == "codex":
            op_to_skill = {
                "explore": "openspec-explore",
                "propose": "openspec-propose",
                "apply": "openspec-apply-change",
                "verify": "openspec-verify-change",
                "sync": "openspec-sync-specs",
                "archive": "openspec-archive-change",
            }
            if op in {"normalize", "pr_prepare"}:
                skill_name = (
                    "minime-request-normalizer" if op == "normalize" else "minime-pr-preparer"
                )
                rel_path = Path(".agents/skills") / skill_name / "SKILL.md"
                dispatch_cmd = f"${skill_name} {change_name}"
                check_parts = (".agents", ".agents/skills", f".agents/skills/{skill_name}")
            else:
                skill_folder = op_to_skill.get(op, f"openspec-{op}")
                rel_path = Path(".agents/skills") / skill_folder / "SKILL.md"
                dispatch_cmd = f"${skill_folder} {change_name}"
                check_parts = (".agents", ".agents/skills", f".agents/skills/{skill_folder}")
        elif prov in ("antigravity", "agy"):
            if op in {"normalize", "pr_prepare"}:
                skill_name = (
                    "minime-request-normalizer" if op == "normalize" else "minime-pr-preparer"
                )
                skill_candidates = (
                    Path(".agent/skills") / skill_name / "SKILL.md",
                    Path(".agents/skills") / skill_name / "SKILL.md",
                )
                rel_path = next(
                    (candidate for candidate in skill_candidates if (root / candidate).is_file()),
                    None,
                )
                dispatch_cmd = f"/{skill_name} {change_name}"
                check_parts = (".agent", ".agent/skills", ".agents", ".agents/skills")
                if rel_path is None:
                    raise NativeOpenSpecWorkflowUnavailable(
                        "Installed minime-request-normalizer skill is missing for Antigravity."
                    )
            else:
                op_to_file = {
                    "explore": "opsx-explore.md",
                    "propose": "opsx-propose.md",
                    "apply": "opsx-apply.md",
                    "verify": "opsx-verify.md",
                    "sync": "opsx-sync.md",
                    "archive": "opsx-archive.md",
                }
                workflow_file = op_to_file.get(op, f"opsx-{op}.md")
                dispatch_cmd = f"/opsx-{op} {change_name}"
                workflow_candidates = (
                    Path(".agent/workflows") / workflow_file,
                    Path(".agents/workflows") / workflow_file,
                )
                for candidate in workflow_candidates:
                    if candidate.is_symlink():
                        raise NativeOpenSpecWorkflowUnavailable(
                            f"Installed OpenSpec workflow path contains a symlink: {candidate}"
                        )
                rel_path = next(
                    (
                        candidate
                        for candidate in workflow_candidates
                        if (root / candidate).is_file()
                    ),
                    None,
                )
                check_parts = (".agent", ".agent/workflows", ".agents", ".agents/workflows")
        else:
            raise NativeOpenSpecWorkflowUnavailable(
                f"Dynamic OpenSpec resolution is not supported for provider '{provider}'."
            )

        if rel_path is None:
            raise NativeOpenSpecWorkflowUnavailable(
                f"Installed {prov} OpenSpec workflow '{op}' is missing or not a regular file."
            )
        full_path = root / rel_path
        # Verify no symlinks in check_parts
        for part in check_parts:
            p = root / part
            if p.is_symlink():
                raise NativeOpenSpecWorkflowUnavailable(
                    f"Installed OpenSpec workflow path contains a symlink: {part}"
                )

        if full_path.is_symlink() or not full_path.is_file():
            if op == "verify":
                raise NativeOpenSpecWorkflowUnavailable(
                    f"Native OpenSpec Verify workflow is not installed for '{prov}' at {rel_path}."
                )
            raise NativeOpenSpecWorkflowUnavailable(
                f"Installed {prov} OpenSpec workflow '{op}' is missing or not a regular file at {rel_path}."
            )

        resolved_file = full_path.resolve(strict=True)
        try:
            resolved_file.relative_to(root)
        except ValueError as exc:
            raise NativeOpenSpecWorkflowUnavailable(
                "Installed OpenSpec workflow escapes the authorized worktree."
            ) from exc

        content = resolved_file.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()

        return ResolvedWorkflow(
            provider=prov,
            operation=op,
            workflow_name=rel_path.stem,
            workflow_path=rel_path.as_posix(),
            workflow_sha256=sha256,
            change_name=change_name,
            dispatch_command=dispatch_cmd,
        )

    def check_capacity_preflight(
        self,
        project_id: str | None,
        provider_id: str,
        role: str,
    ) -> None:
        """Preflight provider capacity, quota, and budget limits before agent dispatch."""
        if self.capacity_service is not None and project_id:
            # Check capacity if method available
            if hasattr(self.capacity_service, "can_admit_change"):
                decision = self.capacity_service.can_admit_change(project_id)
                allowed = decision[0] if isinstance(decision, tuple) else decision
                if not allowed:
                    raise CapacityExhaustedError(
                        provider_id=provider_id,
                        message=f"Capacity service rejected admission for project '{project_id}'.",
                    )

        # BudgetService is exclusively an OpenRouter fallback authority.
        # Subscription-based Codex/Antigravity dispatch must not depend on
        # an OpenRouter policy row, even when the row is absent or enabled.
        # Provider capacity and per-role authorization are enforced separately.
        if (
            self.budget_service is not None
            and project_id
            and str(provider_id).strip().lower() == "openrouter"
        ):
            budget_result = self.budget_service.get_headroom(project_id)
            if isinstance(budget_result, tuple):
                policy, headroom = budget_result
            else:
                policy, headroom = None, budget_result
            if policy is None or not getattr(policy, "enabled", False) or headroom is None:
                raise CapacityExhaustedError(
                    provider_id=provider_id,
                    message=f"OpenRouter budget policy/headroom is unavailable or disabled for project '{project_id}'.",
                )
            daily = getattr(headroom, "daily_headroom_usd", headroom)
            monthly = getattr(headroom, "monthly_headroom_usd", daily)
            if daily <= 0 or monthly <= 0:
                raise CapacityExhaustedError(
                    provider_id=provider_id,
                    message=f"Budget headroom exhausted for provider '{provider_id}' on project '{project_id}'.",
                )

    def _profile_for(self, role: str, provider: str) -> CliInvocationProfile | None:
        normalized_provider = "antigravity" if provider.lower() == "agy" else provider.lower()
        profile_name = {
            "thinker": "thinking",
            "implementer": "execution",
            "reviewer": "independent_review",
        }.get(role, role)
        return self.profiles.get((profile_name, normalized_provider)) or self.profile

    def provider_for_role(self, role: str) -> str:
        """Return the provider selected by the verified persisted F2 profile."""
        profile_name = {
            "thinker": "thinking",
            "implementer": "execution",
            "reviewer": "independent_review",
        }.get(role, role)
        providers = [provider for name, provider in self.profiles if name == profile_name]
        if len(providers) != 1:
            raise ValueError(f"No unique verified F2 provider is configured for role '{role}'.")
        return providers[0]

    @staticmethod
    def observed_usage(result: AgentExecutionResult) -> dict[str, int] | None:
        """Extract only an explicit Codex turn.completed usage event; never infer counters."""
        for line in reversed(getattr(result, "diagnostic_output", None) or []):
            try:
                event = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict) or event.get("type") != "turn.completed":
                continue
            usage = event.get("usage")
            if not isinstance(usage, dict):
                continue
            if not all(
                type(usage.get(key)) is int and usage[key] >= 0
                for key in ("input_tokens", "output_tokens")
            ):
                continue
            return {
                key: usage[key]
                for key in ("input_tokens", "cached_input_tokens", "output_tokens")
                if type(usage.get(key)) is int and usage[key] >= 0
            }
        return None

    def _command_for_prompt(
        self, prompt_context: str, profile: CliInvocationProfile | None
    ) -> list[str]:
        if profile and profile.prompt_transport == "argument":
            raw_cmd = [
                profile.executable,
                *(arg.replace("{prompt}", prompt_context) for arg in profile.args),
            ]
        elif profile:
            raw_cmd = [profile.executable, *profile.args]
        else:
            raw_cmd = list(self.command)

        if raw_cmd:
            search_path = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}"
            resolved = shutil.which(raw_cmd[0], path=search_path)
            if resolved:
                raw_cmd[0] = resolved
        return raw_cmd

    async def run(
        self,
        worktree_path: Path,
        prompt_context: str,
        timeout_seconds: int = 300,
        project_id: str | None = None,
        role: str = "implementer",
        provider: str = "antigravity",
        workflow: ResolvedWorkflow | None = None,
        output_schema: dict[str, Any] | None = None,
        output_last_message_path: Path | None = None,
    ) -> AgentExecutionResult:
        """Execute agent under confinement with capacity preflight."""
        # 1. Capacity preflight
        self.check_capacity_preflight(project_id, provider, role)

        # 2. Confinement check
        confinement = AgentProcessConfinement(allowed_worktree_path=str(worktree_path))
        preflight_check = confinement.validate_command_preflight(cwd=str(worktree_path))
        if preflight_check.outcome != ExternalOutcome.SUCCESS:
            env_err = confinement.is_local_environment_preflight_error(
                preflight_check.error_message
            )
            return AgentExecutionResult(
                exit_code=-2,
                timed_out=False,
                stdout=[],
                stderr=[f"Preflight validation failed: {preflight_check.error_message}"],
                duration_ms=0,
                preflight_error=preflight_check.error_message,
                environment_error=env_err,
                workflow=workflow,
            )

        profile = self._profile_for(role, provider)
        if profile is None:
            return AgentExecutionResult(
                exit_code=-1,
                timed_out=False,
                stdout=[],
                stderr=[
                    f"No verified executor configured for role '{role}' and provider '{provider}'."
                ],
                duration_ms=0,
                preflight_error="missing_verified_executor",
                workflow=workflow,
            )

        response_path = (
            Path(output_last_message_path).resolve() if output_last_message_path else None
        )
        schema_path = response_path.with_name("response.schema.json") if response_path else None
        if response_path:
            root = Path(worktree_path).resolve(strict=True)
            try:
                response_path.relative_to(root)
            except ValueError as exc:
                raise ValueError(
                    "Structured response path must remain inside the authorized worktree."
                ) from exc
            relative_parts = response_path.relative_to(root).parts
            cursor = root
            for part in relative_parts[:-1]:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ValueError("Structured response path cannot traverse a symlink.")
            if response_path.exists() or (schema_path and schema_path.exists()):
                raise ValueError("Structured response paths must be fresh for the current attempt.")
            response_path.parent.mkdir(parents=True, exist_ok=True)
            if output_schema is None:
                raise ValueError("An output schema is required with --output-last-message.")
            schema_path.write_text(json.dumps(output_schema, sort_keys=True), encoding="utf-8")

        def cleanup_structured_output() -> None:
            if response_path:
                response_path.unlink(missing_ok=True)
            if schema_path:
                schema_path.unlink(missing_ok=True)

        cmd = self._command_for_prompt(prompt_context, profile)
        if not cmd:
            cleanup_structured_output()
            return AgentExecutionResult(
                exit_code=-1,
                timed_out=False,
                stdout=[],
                stderr=["No executable command configured for agent."],
                duration_ms=0,
                workflow=workflow,
            )

        start = asyncio.get_running_loop().time()
        is_stdin = profile.prompt_transport == "stdin"
        stdin_data = prompt_context.encode("utf-8") if is_stdin else None
        env = os.environ.copy()
        env["TERM"] = "dumb"

        try:
            if response_path and schema_path:
                cmd.extend(
                    [
                        "--output-schema",
                        str(schema_path),
                        "--output-last-message",
                        str(response_path),
                    ]
                )
            auth_kwargs: dict[str, str] = {}
            normalized_provider = provider.lower()
            if normalized_provider == "agy":
                normalized_provider = "antigravity"
            if normalized_provider == "codex":
                auth_kwargs["codex_auth_source"] = confinement.codex_auth_source(env)
            elif normalized_provider == "antigravity":
                auth_kwargs["antigravity_auth_source"] = confinement.antigravity_auth_source(env)
            result = await confinement.run_confined_async_subprocess(
                cmd,
                cwd=str(worktree_path),
                input_bytes=stdin_data,
                timeout_seconds=timeout_seconds,
                env=env,
                **auth_kwargs,
            )
        except AgentConfinementError as exc:
            cleanup_structured_output()
            duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
            return AgentExecutionResult(
                exit_code=-2,
                timed_out=False,
                stdout=[],
                stderr=[redact_secrets(str(exc))],
                duration_ms=duration_ms,
                preflight_error=str(exc),
                environment_error=exc.environment_unavailable,
                workflow=workflow,
            )
        except OSError as exc:
            cleanup_structured_output()
            duration_ms = int((asyncio.get_running_loop().time() - start) * 1000)
            return AgentExecutionResult(
                exit_code=-1,
                timed_out=False,
                stdout=[],
                stderr=[redact_secrets(f"Confined subprocess start failed: {exc}")],
                duration_ms=duration_ms,
                environment_error=True,
                workflow=workflow,
            )

        raw_stdout_lines = result.stdout.decode("utf-8", errors="replace").splitlines()
        raw_stderr_lines = result.stderr.decode("utf-8", errors="replace").splitlines()
        output_truncated = (
            len(raw_stdout_lines) > self.MAX_OUTPUT_LINES
            or len(raw_stderr_lines) > self.MAX_OUTPUT_LINES
            or any(len(line) > self.MAX_LINE_CHARS for line in raw_stdout_lines + raw_stderr_lines)
            or getattr(result, "stdout_capture_truncated", False)
            or getattr(result, "stderr_capture_truncated", False)
        )
        stdout_lines = [redact_secrets(line[: self.MAX_LINE_CHARS]) for line in raw_stdout_lines][
            : self.MAX_OUTPUT_LINES
        ]
        stderr_lines = [redact_secrets(line[: self.MAX_LINE_CHARS]) for line in raw_stderr_lines][
            : self.MAX_OUTPUT_LINES
        ]
        structured_output_missing = bool(response_path and not response_path.is_file())
        structured_output_too_large = False
        structured_output: list[str] | None = [] if response_path else None
        final_response: str | None = None
        final_response_status = "MISSING"
        final_response_source = "structured_file" if response_path else "stdout"
        if response_path and response_path.is_file():
            if response_path.stat().st_size > self.MAX_STRUCTURED_OUTPUT_BYTES:
                structured_output_too_large = True
                final_response_status = "TRUNCATED"
            else:
                try:
                    # Structured final responses are bounded and read without
                    # UTF-8 replacement, independently from diagnostic output.
                    original_response = response_path.read_text(encoding="utf-8")
                except UnicodeError:
                    final_response_status = "TRUNCATED"
                else:
                    final_response = redact_secrets(original_response)
                    structured_output = [final_response]
                    final_response_status = "COMPLETE" if final_response.strip() else "MISSING"
                    if final_response_status != "COMPLETE":
                        final_response = None
        if not response_path:
            final_response, final_response_status, final_response_source = (
                self._extract_final_response(
                    result.stdout,
                    provider,
                    captured_incompletely=getattr(result, "stdout_capture_truncated", False),
                )
            )
        if structured_output_missing:
            stdout_lines = []
        rotation_error = (
            "credential_rotation_not_persisted"
            if result.credential_rotation_detected and not result.credential_access_refresh_only
            else None
        )
        try:
            return AgentExecutionResult(
                exit_code=result.returncode,
                timed_out=result.timed_out,
                stdout=stdout_lines,
                stderr=stderr_lines,
                duration_ms=int((asyncio.get_running_loop().time() - start) * 1000),
                preflight_error=rotation_error,
                workflow=workflow,
                structured_output=structured_output,
                diagnostic_output=[
                    *[redact_secrets(line[: self.MAX_LINE_CHARS]) for line in raw_stdout_lines][
                        : self.MAX_OUTPUT_LINES
                    ],
                    *stderr_lines,
                ],
                output_truncated=output_truncated,
                structured_output_missing=structured_output_missing,
                structured_output_too_large=structured_output_too_large,
                final_response=final_response,
                final_response_status=final_response_status,
                final_response_source=final_response_source,
            )
        finally:
            cleanup_structured_output()
