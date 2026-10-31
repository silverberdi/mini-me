"""Thin, fail-closed OpenCode CLI boundary.

OpenCode remains an external CLI. This module only validates project authorization,
candidate/worktree identity, native workflow presence, and records observable process
outcomes. It does not implement a shell, OpenSpec, provider fallback, or lifecycle.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from minime.config import OpenCodeCapabilityConfig
from minime.logging import redact_secrets
from minime.services.agent_confinement import AgentConfinementError, AgentProcessConfinement
from minime.services.cli_preflight import PreflightResult

SUPPORTED_OPERATIONS = frozenset({"explore", "propose", "apply", "verify"})
SUPPORTED_ROLES = frozenset({"execution", "independent_review"})


class OpenCodeDispatchError(RuntimeError):
    """A request was refused before it could become authoritative work."""


class OpenCodePreflight(Protocol):
    async def __call__(self, executable: str, args: tuple[str, ...]) -> PreflightResult: ...


class CandidateEvidenceRecorder(Protocol):
    def record(self, evidence: "OpenCodeEvidence") -> None: ...


@dataclass(frozen=True)
class OpenCodeRequest:
    project_id: str
    role: str
    operation: str
    worktree_path: Path
    candidate_sha: str
    candidate_author: str | None = None
    reviewer_identity: str | None = None
    prompt: str = ""


@dataclass(frozen=True)
class OpenCodeEvidence:
    provider: str
    executable: str
    executable_sha256: str | None
    role: str
    operation: str
    project_id: str
    worktree_path: str
    candidate_sha: str | None
    workflow_path: str | None
    workflow_sha256: str | None
    exit_code: int | None
    timed_out: bool
    stdout: tuple[str, ...] = ()
    stderr: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    failure_reason: str | None = None
    authoritative: bool = False
    lifecycle_authority: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, **json.loads(json.dumps(self.__dict__))}


@dataclass(frozen=True)
class OpenCodeOutcome:
    accepted: bool
    evidence: OpenCodeEvidence


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _git_head(worktree: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else None


def _native_workflow(worktree: Path, operation: str) -> tuple[str, str] | None:
    """Locate the installed agent workflow, without executing or reimplementing it."""
    skill_name = {
        "explore": "openspec-explore",
        "propose": "openspec-propose",
        "apply": "openspec-apply-change",
        "verify": "openspec-verify-change",
    }[operation]
    candidates = (
        worktree / ".agents" / "skills" / skill_name / "SKILL.md",
        worktree / ".agent" / "workflows" / f"opsx-{operation}.md",
    )
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(worktree)
        except (OSError, ValueError):
            continue
        digest = _sha256_file(resolved)
        if digest:
            return candidate.relative_to(worktree).as_posix(), digest
    return None


def _forbidden_external_action(prompt: str) -> bool:
    normalized = prompt.lower()
    return any(
        marker in normalized
        for marker in (
            "deploy production",
            "production deploy",
            "restart scheduler",
            "close remote request",
            "close the ticket",
            "close ticket",
            "merge pull request",
            "merge pr",
        )
    )


def _has_explicit_result(stdout: tuple[str, ...]) -> bool:
    """Require an explicit terminal result before accepting CLI output."""
    for line in reversed(stdout):
        stripped = line.strip().strip('`')
        if stripped in {"COMPLETE", "INCOMPLETE", "HUMAN_REQUIRED"}:
            return True
        try:
            payload = json.loads(stripped)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("status") in {
            "COMPLETE", "INCOMPLETE", "HUMAN_REQUIRED"
        }:
            return True
    return False


def _provider_failure_reason(
    *, returncode: int, timed_out: bool, stdout: tuple[str, ...], stderr: tuple[str, ...]
) -> str:
    """Classify an observed provider/CLI failure without retrying or choosing fallback.

    Recovery and fallback remain the provider-policy authority.  This adapter only
    preserves a stable, redacted classification in candidate evidence.
    """
    if timed_out:
        return "PROVIDER_TIMEOUT"
    combined = "\n".join((*stderr, *stdout)).lower()
    if any(marker in combined for marker in ("quota", "insufficient balance", "rate limit", "429", "402")):
        return "PROVIDER_QUOTA_OR_RATE_LIMIT"
    if any(marker in combined for marker in ("authentication", "unauthorized", "invalid api key", "401", "403")):
        return "PROVIDER_AUTHENTICATION_FAILURE"
    if returncode != 0:
        return "PROVIDER_PROCESS_FAILURE"
    return "NON_AUTHORITATIVE_PROCESS_RESULT"


def _git_artifacts(worktree: Path) -> tuple[str, ...]:
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=worktree, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    return tuple(line[3:].strip() for line in output.splitlines() if len(line) > 3)


async def _default_preflight(executable: str, args: tuple[str, ...]) -> PreflightResult:
    """Prove the installed CLI responds before any worktree dispatch."""
    del args
    try:
        process = await asyncio.create_subprocess_exec(
            executable, "--version", stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=tempfile.gettempdir(),
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
    except (OSError, asyncio.TimeoutError):
        return PreflightResult(ok=False, reason="CLI_VERSION_UNAVAILABLE")
    if process.returncode != 0 or not (stdout + stderr).strip():
        return PreflightResult(ok=False, reason="CLI_VERSION_UNAVAILABLE")
    return PreflightResult(ok=True)


class OpenCodeAdapter:
    """Project-scoped adapter that delegates execution to existing confinement."""

    def __init__(
        self,
        config: OpenCodeCapabilityConfig,
        *,
        project_id: str,
        confinement_factory=AgentProcessConfinement,
        preflight: OpenCodePreflight | None = None,
        recorder: CandidateEvidenceRecorder | None = None,
    ) -> None:
        self.config = config
        self.project_id = project_id
        self._confinement_factory = confinement_factory
        self._preflight = preflight
        self._recorder = recorder

    def _evidence(self, request: OpenCodeRequest, **kwargs: Any) -> OpenCodeEvidence:
        evidence = OpenCodeEvidence(
            provider=self.config.provider or "opencode",
            executable=self.config.executable,
            executable_sha256=kwargs.pop("executable_sha256", None),
            role=request.role,
            operation=request.operation,
            project_id=request.project_id,
            worktree_path=str(request.worktree_path),
            candidate_sha=kwargs.pop("candidate_sha", request.candidate_sha),
            workflow_path=kwargs.pop("workflow_path", None),
            workflow_sha256=kwargs.pop("workflow_sha256", None),
            exit_code=kwargs.pop("exit_code", None),
            timed_out=kwargs.pop("timed_out", False),
            stdout=tuple(kwargs.pop("stdout", ())),
            stderr=tuple(kwargs.pop("stderr", ())),
            artifacts=tuple(kwargs.pop("artifacts", ())),
            failure_reason=kwargs.pop("failure_reason", None),
            authoritative=kwargs.pop("authoritative", False),
            lifecycle_authority=False,
        )
        if kwargs:
            raise TypeError(f"Unexpected evidence fields: {sorted(kwargs)}")
        if self._recorder:
            self._recorder.record(evidence)
        return evidence

    def _refuse(self, request: OpenCodeRequest, reason: str) -> OpenCodeOutcome:
        return OpenCodeOutcome(False, self._evidence(request, failure_reason=reason, candidate_sha=None))

    async def dispatch(self, request: OpenCodeRequest) -> OpenCodeOutcome:
        role = request.role.strip()
        operation = request.operation.strip().lower()
        request = OpenCodeRequest(**{**request.__dict__, "role": role, "operation": operation})
        if request.project_id != self.project_id:
            return self._refuse(request, "PROJECT_BINDING_MISMATCH")
        if not self.config.enabled or role not in self.config.roles:
            return self._refuse(request, "OPENCODE_NOT_AUTHORIZED")
        if role not in SUPPORTED_ROLES:
            return self._refuse(request, "ROLE_NOT_SUPPORTED")
        if operation not in SUPPORTED_OPERATIONS:
            return self._refuse(request, "OPERATION_NOT_NATIVE_OPENSPEC")
        if bool(self.config.provider) != bool(self.config.model):
            return self._refuse(request, "MODEL_PROVIDER_CONFIGURATION_INCOMPLETE")
        if self.config.api_key_env and not os.environ.get(self.config.api_key_env):
            return self._refuse(request, "PROVIDER_CREDENTIAL_MISSING")
        if role == "independent_review" and (
            not request.reviewer_identity or request.reviewer_identity == request.candidate_author
        ):
            return self._refuse(request, "REVIEWER_NOT_INDEPENDENT")
        if _forbidden_external_action(request.prompt):
            return self._refuse(request, "EXTERNAL_ACTION_NOT_AUTHORIZED")

        try:
            worktree = request.worktree_path.resolve(strict=True)
        except OSError:
            return self._refuse(request, "WORKTREE_UNAVAILABLE")
        if not worktree.is_dir():
            return self._refuse(request, "WORKTREE_UNAVAILABLE")
        actual_sha = _git_head(worktree)
        if not actual_sha or actual_sha != request.candidate_sha:
            return self._refuse(request, "CANDIDATE_SHA_MISMATCH")
        workflow = _native_workflow(worktree, operation)
        if workflow is None:
            return self._refuse(request, "NATIVE_OPENSPEC_WORKFLOW_MISSING")
        executable = shutil.which(self.config.executable)
        if not executable:
            return self._refuse(request, "EXECUTABLE_MISSING")
        executable_sha = _sha256_file(Path(executable))
        args = list(self.config.args)
        if not args:
            args = ["run"]
            if self.config.provider and self.config.model:
                args.extend(["--model", f"{self.config.provider}/{self.config.model}"])
        extra_env = {"SHELL": "/bin/bash"}
        if self.config.api_key_env and self.config.api_key_env in os.environ:
            extra_env[self.config.api_key_env] = os.environ[self.config.api_key_env]
        preflight = self._preflight or _default_preflight
        result = await preflight(executable, tuple(args))
        if not result.ok:
            return self._refuse(request, result.reason or "PREFLIGHT_FAILED")
        confinement = self._confinement_factory(allowed_worktree_path=str(worktree))
        try:
            call_kwargs = {
                "cwd": str(worktree),
                "input_bytes": request.prompt.encode(),
                "timeout_seconds": self.config.timeout_seconds,
                "read_only_worktree": role == "independent_review",
            }
            try:
                process = await confinement.run_confined_async_subprocess(
                    [executable, *args], **call_kwargs, extra_env=extra_env
                )
            except TypeError:
                process = await confinement.run_confined_async_subprocess(
                    [executable, *args], **call_kwargs
                )
        except (AgentConfinementError, OSError) as exc:
            return self._refuse(request, f"DISPATCH_FAILED:{type(exc).__name__}")
        stdout = tuple(redact_secrets(line) for line in process.stdout.decode(errors="replace").splitlines())
        stderr = tuple(redact_secrets(line) for line in process.stderr.decode(errors="replace").splitlines())
        artifacts = _git_artifacts(worktree)
        success = (
            process.returncode == 0
            and not process.timed_out
            and _has_explicit_result(stdout)
        )
        evidence = self._evidence(
            request, executable_sha256=executable_sha, workflow_path=workflow[0],
            workflow_sha256=workflow[1], exit_code=process.returncode, timed_out=process.timed_out,
            stdout=stdout, stderr=stderr, artifacts=artifacts, authoritative=success,
            failure_reason=None if success else _provider_failure_reason(
                returncode=process.returncode,
                timed_out=process.timed_out,
                stdout=stdout,
                stderr=stderr,
            ),
        )
        return OpenCodeOutcome(success, evidence)
