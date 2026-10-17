"""Resolve and describe the repository-installed OpenSpec apply workflow.

This module does not implement OpenSpec semantics. It validates the installed
agent workflow and produces the narrow dispatch instruction that asks the
configured coding agent to invoke that workflow itself.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path


class NativeOpenSpecWorkflowUnavailable(ValueError):
    """Raised when the exact native apply workflow cannot be proven installed."""


@dataclass(frozen=True)
class NativeOpenSpecApplyWorkflow:
    provider: str
    workflow_name: str
    workflow_path: str
    workflow_sha256: str
    version: str
    change_name: str
    project_id: str | None = None
    repository_identity: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    attempt_id: str | None = None
    generation: int | None = None
    base_sha: str | None = None

    def dispatch_instruction(self) -> str:
        """Return a bounded request to invoke the installed native workflow."""
        if self.provider == "codex":
            invocation_cmd = (
                f"Invoke the installed Codex skill now: $openspec-apply-change {self.change_name}"
            )
        elif self.provider in ("antigravity", "agy"):
            invocation_cmd = (
                f"Invoke the installed Antigravity skill now: /opsx-apply {self.change_name}"
            )
        else:
            raise NativeOpenSpecWorkflowUnavailable(
                f"Native apply invocation evidence is not implemented for provider '{self.provider}'."
            )
        return "\n".join(
            [
                "NATIVE OPENSPEC APPLY DISPATCH",
                invocation_cmd,
                f"Installed skill path: {self.workflow_path}",
                f"Installed skill SHA-256: {self.workflow_sha256}",
                "AUTHORIZED APPLY IDENTITY (read-only context; durable binding remains authoritative):",
                f"Project ID: {self.project_id or 'unavailable'}",
                f"Canonical repository identity: {self.repository_identity or 'unavailable'}",
                f"Run ID: {self.run_id or 'unavailable'}",
                f"Job ID: {self.job_id or 'unavailable'}",
                f"Attempt ID: {self.attempt_id or 'unavailable'}",
                f"Candidate generation: {self.generation if self.generation is not None else 'unavailable'}",
                f"Admitted base SHA: {self.base_sha or 'unavailable'}",
                "Stage: APPLY",
                "Scope: the exact bound OpenSpec change above, within the authorized candidate worktree.",
                "The installed skill is the workflow authority. Follow its status, instructions, "
                "context-file, task-order, and pause rules; do not replace it with a free-form "
                "implementation prompt or guessed OpenSpec shell command.",
                "Use only the candidate workspace named below. Do not claim the workflow ran "
                "unless the corresponding tool execution is observable.",
            ]
        )


_CHANGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SKILL_NAME_RE = re.compile(r"(?m)^name:\s*([A-Za-z0-9._-]+)\s*$")
_SKILL_VERSION_RE = re.compile(r"(?m)^\s+version:\s*['\"]?([A-Za-z0-9._-]+)['\"]?\s*$")
CODEX_APPLY_SKILL_PATH = ".agents/skills/openspec-apply-change/SKILL.md"
AGY_APPLY_SKILL_PATH = ".agent/skills/openspec-apply-change/SKILL.md"
NATIVE_APPLY_CHANGE_RE = re.compile(r"\$openspec-apply-change\s+([a-z0-9][a-z0-9._-]{0,127})")
NATIVE_APPLY_SKILL_SHA_RE = re.compile(r"Installed skill SHA-256:\s*([0-9a-f]{64})")


def resolve_native_openspec_apply(
    worktree_root: str | Path,
    change_name: str,
    *,
    provider: str = "antigravity",
    project_id: str | None = None,
    repository_identity: str | None = None,
    run_id: str | None = None,
    job_id: str | None = None,
    attempt_id: str | None = None,
    generation: int | None = None,
    base_sha: str | None = None,
) -> NativeOpenSpecApplyWorkflow:
    """Resolve the exact repo-local provider apply skill without following escapes."""
    if not _CHANGE_NAME_RE.fullmatch(change_name):
        raise NativeOpenSpecWorkflowUnavailable("OpenSpec change name is not a safe slug.")

    root = Path(worktree_root).resolve(strict=True)
    prov = provider.lower()
    if prov == "codex":
        relative_skill = Path(CODEX_APPLY_SKILL_PATH)
        check_parts = (".agents", ".agents/skills", ".agents/skills/openspec-apply-change")
        prov_label = "Codex"
    elif prov in ("antigravity", "agy"):
        relative_skill = Path(AGY_APPLY_SKILL_PATH)
        check_parts = (".agent", ".agent/skills", ".agent/skills/openspec-apply-change")
        prov_label = "Antigravity"
    else:
        raise NativeOpenSpecWorkflowUnavailable(
            f"Native apply workflow is not supported for provider '{provider}'."
        )

    skill_path = root / relative_skill
    if any((root / part).is_symlink() for part in check_parts):
        raise NativeOpenSpecWorkflowUnavailable("Installed OpenSpec skill path contains a symlink.")
    if skill_path.is_symlink() or not skill_path.is_file():
        raise NativeOpenSpecWorkflowUnavailable(
            f"Installed {prov_label} OpenSpec apply skill is missing or not a regular file."
        )

    resolved_skill = skill_path.resolve(strict=True)
    try:
        resolved_skill.relative_to(root)
    except ValueError as exc:
        raise NativeOpenSpecWorkflowUnavailable(
            "Installed OpenSpec skill escapes the authorized worktree."
        ) from exc

    content = resolved_skill.read_bytes()
    text = content.decode("utf-8")
    name_match = _SKILL_NAME_RE.search(text)
    version_match = _SKILL_VERSION_RE.search(text)
    if not name_match or name_match.group(1) != "openspec-apply-change":
        raise NativeOpenSpecWorkflowUnavailable(
            "Installed skill metadata does not identify openspec-apply-change."
        )
    if not version_match:
        raise NativeOpenSpecWorkflowUnavailable(
            "Installed OpenSpec apply skill has no version metadata."
        )
    return NativeOpenSpecApplyWorkflow(
        provider=prov,
        workflow_name=name_match.group(1),
        workflow_path=relative_skill.as_posix(),
        workflow_sha256=hashlib.sha256(content).hexdigest(),
        version=version_match.group(1),
        change_name=change_name,
        project_id=project_id,
        repository_identity=repository_identity,
        run_id=run_id,
        job_id=job_id,
        attempt_id=attempt_id,
        generation=generation,
        base_sha=base_sha,
    )


def resolve_codex_openspec_apply(
    worktree_root: str | Path,
    change_name: str,
    *,
    project_id: str | None = None,
    repository_identity: str | None = None,
    run_id: str | None = None,
    job_id: str | None = None,
    attempt_id: str | None = None,
    generation: int | None = None,
    base_sha: str | None = None,
) -> NativeOpenSpecApplyWorkflow:
    """Resolve the exact repo-local Codex apply skill without following escapes."""
    return resolve_native_openspec_apply(
        worktree_root=worktree_root,
        change_name=change_name,
        provider="codex",
        project_id=project_id,
        repository_identity=repository_identity,
        run_id=run_id,
        job_id=job_id,
        attempt_id=attempt_id,
        generation=generation,
        base_sha=base_sha,
    )


def workflow_unchanged(worktree_root: str | Path, workflow: NativeOpenSpecApplyWorkflow) -> bool:
    """Confirm the skill source used for preflight was not altered during APPLY."""
    try:
        current = resolve_native_openspec_apply(
            worktree_root,
            workflow.change_name,
            provider=workflow.provider,
            project_id=workflow.project_id,
            repository_identity=workflow.repository_identity,
            run_id=workflow.run_id,
            job_id=workflow.job_id,
            attempt_id=workflow.attempt_id,
            generation=workflow.generation,
            base_sha=workflow.base_sha,
        )
    except (OSError, UnicodeError, NativeOpenSpecWorkflowUnavailable):
        return False
    return current.workflow_sha256 == workflow.workflow_sha256


def _tokenize_command(command: str) -> list[str]:
    try:
        raw_tokens = shlex.split(command)
    except ValueError:
        raw_tokens = command.split()
    tokens: list[str] = []
    for token in raw_tokens:
        cleaned = token.replace("\\", "/")
        if " " in cleaned:
            try:
                inner = [t.replace("\\", "/") for t in shlex.split(cleaned)]
                tokens.extend(inner)
                continue
            except ValueError:
                pass
        tokens.append(cleaned)
    return tokens


def parse_codex_apply_jsonl(
    stdout_lines: list[str],
    *,
    change_name: str,
    workflow_path: str,
    workflow_sha256: str,
) -> tuple[list[str], dict[str, object]]:
    """Extract safe Codex messages and minimal tool-trace facts from JSONL.

    Raw commands, tool output, prompts, and model messages are deliberately not
    included in the evidence summary. A native workflow is observed only when
    a successful command event reads its installed SKILL.md and a successful
    command event runs `openspec instructions apply` for the exact change.
    """
    messages: list[str] = []
    all_lines_valid = True
    saw_skill_read = False
    saw_apply_instructions = False
    completed_tool_events = 0

    for line in stdout_lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            all_lines_valid = False
            continue
        if not isinstance(event, dict):
            all_lines_valid = False
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            message = item.get("text")
            if isinstance(message, str) and message.strip():
                messages.append(message)
                if (
                    "openspec-apply-change" in message.casefold()
                    or workflow_path.casefold() in message.casefold()
                ):
                    saw_skill_read = True
        if event.get("type") != "item.completed" or item.get("type") != "command_execution":
            continue
        if item.get("status") not in {"completed", None} or item.get("exit_code") not in {0, None}:
            continue
        command = item.get("command")
        if not isinstance(command, str):
            continue
        completed_tool_events += 1
        try:
            tokens = _tokenize_command(command)
        except Exception:
            all_lines_valid = False
            continue
        normalized_tokens = [token.casefold() for token in tokens]
        if (
            workflow_path.casefold() in normalized_tokens
            or any(token.endswith(workflow_path.casefold()) for token in normalized_tokens)
            or any("openspec-apply-change" in token for token in normalized_tokens)
        ):
            saw_skill_read = True
        has_apply_command = any(
            normalized_tokens[index : index + 3] == ["openspec", "instructions", "apply"]
            for index in range(max(0, len(normalized_tokens) - 2))
        )
        change_arg_matches = (
            any(
                normalized_tokens[index] == "--change"
                and index + 1 < len(normalized_tokens)
                and normalized_tokens[index + 1] == change_name.casefold()
                for index in range(len(normalized_tokens))
            )
            or f"--change={change_name.casefold()}" in normalized_tokens
            or (change_name.casefold() in normalized_tokens and has_apply_command)
        )
        if has_apply_command and change_arg_matches and "--json" in normalized_tokens:
            saw_apply_instructions = True

    evidence: dict[str, object] = {
        "workflow": "openspec-apply-change",
        "change_name": change_name,
        "workflow_path": workflow_path,
        "workflow_sha256": workflow_sha256,
        "jsonl_complete": all_lines_valid,
        "completed_tool_events": completed_tool_events,
        "skill_read_observed": saw_skill_read,
        "apply_instructions_observed": saw_apply_instructions,
        "workflow_observed": all_lines_valid and saw_skill_read and saw_apply_instructions,
    }
    return messages, evidence


def parse_antigravity_apply_output(
    stdout_lines: list[str],
    *,
    change_name: str,
    workflow_path: str,
    workflow_sha256: str,
) -> tuple[list[str], dict[str, object]]:
    """Extract safe Antigravity/AGY messages and workflow evidence from CLI stdout."""
    messages = [line for line in stdout_lines if line.strip()]
    full_output = "\n".join(stdout_lines)
    casefolded = full_output.casefold()
    target_change = change_name.casefold()

    saw_change = (
        f"change: {target_change}" in casefolded
        or f"implementing: {target_change}" in casefolded
        or f"`{target_change}`" in casefolded
        or target_change in casefolded
    )
    saw_implementation = (
        "implementation complete" in casefolded
        or "tasks complete" in casefolded
        or "task complete" in casefolded
        or "working on task" in casefolded
    )

    evidence: dict[str, object] = {
        "workflow": "openspec-apply-change",
        "change_name": change_name,
        "workflow_path": workflow_path,
        "workflow_sha256": workflow_sha256,
        "jsonl_complete": True,
        "completed_tool_events": 1 if (saw_change and saw_implementation) else 0,
        "skill_read_observed": saw_change,
        "apply_instructions_observed": saw_implementation,
        "workflow_observed": bool(saw_change and saw_implementation),
    }
    return messages, evidence

