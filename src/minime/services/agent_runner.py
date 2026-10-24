"""Consolidated agent process runner with sandboxing, capacity preflight, and dynamic OpenSpec resolution."""

from __future__ import annotations

import asyncio
import hashlib
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

    @property
    def full_output(self) -> str:
        return "\n".join(self.stdout + self.stderr)

    def contains_token(self, token: str) -> bool:
        return token in self.full_output


class CliAgentRunner:
    """Unified runner for thinker, implementer, and reviewer agents under process confinement."""

    MAX_OUTPUT_LINES = 2500
    MAX_LINE_CHARS = 4000

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
                raise ValueError(f"Project profile '{profile_name}' has no verified agent identity.")
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
            skill_folder = op_to_skill.get(op, f"openspec-{op}")
            rel_path = Path(".agents/skills") / skill_folder / "SKILL.md"
            dispatch_cmd = f"${skill_folder} {change_name}"
            check_parts = (".agents", ".agents/skills", f".agents/skills/{skill_folder}")
        elif prov in ("antigravity", "agy"):
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
                (candidate for candidate in workflow_candidates if (root / candidate).is_file()),
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

        if self.budget_service is not None and project_id:
            if hasattr(self.budget_service, "get_headroom"):
                budget_result = self.budget_service.get_headroom(project_id)
                if isinstance(budget_result, tuple):
                    policy, headroom = budget_result
                else:
                    policy, headroom = True, budget_result
                # BudgetService governs the optional OpenRouter drain path. A
                # project that explicitly disables that fallback must not be
                # forced to create a meaningless positive OpenRouter allowance
                # before a direct primary-provider invocation can start.
                if (
                    str(provider_id).strip().lower() != "openrouter"
                    and getattr(policy, "enabled", True) is False
                ):
                    return
                if policy is None or headroom is None:
                    raise CapacityExhaustedError(
                        provider_id=provider_id,
                        message=f"Budget policy/headroom is unavailable for project '{project_id}'.",
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
        profile_name = {"thinker": "thinking", "implementer": "execution", "reviewer": "independent_review"}.get(role, role)
        providers = [provider for name, provider in self.profiles if name == profile_name]
        if len(providers) != 1:
            raise ValueError(f"No unique verified F2 provider is configured for role '{role}'.")
        return providers[0]

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
    ) -> AgentExecutionResult:
        """Execute agent under confinement with capacity preflight."""
        # 1. Capacity preflight
        self.check_capacity_preflight(project_id, provider, role)

        # 2. Confinement check
        confinement = AgentProcessConfinement(allowed_worktree_path=str(worktree_path))
        preflight_check = confinement.validate_command_preflight(cwd=str(worktree_path))
        if preflight_check.outcome != ExternalOutcome.SUCCESS:
            env_err = confinement.is_local_environment_preflight_error(preflight_check.error_message)
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
                stderr=[f"No verified executor configured for role '{role}' and provider '{provider}'."],
                duration_ms=0,
                preflight_error="missing_verified_executor",
                workflow=workflow,
            )

        cmd = self._command_for_prompt(prompt_context, profile)
        if not cmd:
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

        stdout_lines = [
            redact_secrets(line[: self.MAX_LINE_CHARS])
            for line in result.stdout.decode("utf-8", errors="replace").splitlines()
        ][: self.MAX_OUTPUT_LINES]
        stderr_lines = [
            redact_secrets(line[: self.MAX_LINE_CHARS])
            for line in result.stderr.decode("utf-8", errors="replace").splitlines()
        ][: self.MAX_OUTPUT_LINES]
        rotation_error = (
            "credential_rotation_not_persisted"
            if result.credential_rotation_detected and not result.credential_access_refresh_only
            else None
        )
        return AgentExecutionResult(
            exit_code=result.returncode,
            timed_out=result.timed_out,
            stdout=stdout_lines,
            stderr=stderr_lines,
            duration_ms=int((asyncio.get_running_loop().time() - start) * 1000),
            preflight_error=rotation_error,
            workflow=workflow,
        )
