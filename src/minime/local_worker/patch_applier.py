"""Deterministic patch policy validation and authorized patch application for the local worker.

Patch application is authorized ONLY inside an ephemeral EXECUTION_WORKTREE and is strictly
prohibited from targeting runtime checkout (/opt/minime/app) or managed repository directly.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minime.domain.enums import WorkspaceOperation, WorkspaceRole
from minime.domain.models import WorkspaceMutationRequest
from minime.local_worker.models import LocalResultKind, LocalTaskEnvelope

logger = logging.getLogger(__name__)

_HEADER_LINE_RE = re.compile(r"^(?:---|\+\+\+)\s+(.+)")


@dataclass(frozen=True)
class PatchPolicyDecision:
    valid: bool
    touched_files: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""


@dataclass(frozen=True)
class PatchApplicationResult:
    success: bool
    applied: bool = False
    authoritative_changed_files: tuple[str, ...] = field(default_factory=tuple)
    error: str = ""


def parse_patch_touched_files(patch: str) -> tuple[bool, set[str], str]:
    """Parse unified diff to derive authoritative touched file paths (relative).

    Returns (valid: bool, files: set[str], error_reason: str).
    """
    if not patch or not patch.strip():
        return True, set(), ""

    lines = patch.splitlines()
    touched_files: set[str] = set()

    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            match = _HEADER_LINE_RE.match(line)
            if not match:
                continue
            path_part = match.group(1).strip()
            if path_part == "/dev/null":
                continue
            # Strip timestamp if tab-separated
            path_part = path_part.split("\t")[0].strip()

            # Strip leading a/ or b/ if present
            if path_part.startswith("a/") or path_part.startswith("b/"):
                clean_path = path_part[2:]
            else:
                clean_path = path_part

            if not clean_path:
                continue
            if clean_path.startswith("/") or clean_path.startswith("\\"):
                return False, set(), f"Absolute path detected in patch: {clean_path}"
            norm_parts = clean_path.replace("\\", "/").split("/")
            if ".." in norm_parts:
                return False, set(), f"Path traversal (..) detected in patch: {clean_path}"

            touched_files.add(clean_path)

    if not touched_files and ("--- " in patch or "+++ " in patch or "diff --git" in patch):
        return False, set(), "Malformed patch diff headers"

    return True, touched_files, ""


def _build_git_env() -> dict[str, str]:
    """Sanitize environment variables for Git subprocess operations."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    for variable in (
        "GIT_TRACE",
        "GIT_TRACE_PACKET",
        "GIT_TRACE_CURL",
        "GIT_CURL_VERBOSE",
        "GIT_TRANSPORT_TRACE",
    ):
        env.pop(variable, None)
    return env


def validate_patch_policy(
    patch: str | None,
    envelope: LocalTaskEnvelope,
    kind: LocalResultKind = LocalResultKind.CHANGES_PROPOSED,
) -> PatchPolicyDecision:
    """Validate patch against envelope security bounds before filesystem mutation."""
    if kind is LocalResultKind.NO_CHANGE_JUSTIFIED:
        if patch and patch.strip():
            return PatchPolicyDecision(
                valid=False,
                touched_files=(),
                reason="NO_CHANGE_JUSTIFIED result must not supply a patch",
            )
        return PatchPolicyDecision(
            valid=True, touched_files=(), reason="NO_CHANGE_JUSTIFIED with null patch"
        )

    if kind is LocalResultKind.CHANGES_PROPOSED:
        if not patch or not patch.strip():
            return PatchPolicyDecision(
                valid=False,
                touched_files=(),
                reason="CHANGES_PROPOSED result requires a non-empty patch",
            )

    if not patch or not patch.strip():
        return PatchPolicyDecision(
            valid=False, touched_files=(), reason="Patch is missing or empty"
        )

    valid_diff, touched_files_set, parse_err = parse_patch_touched_files(patch)
    if not valid_diff:
        return PatchPolicyDecision(valid=False, touched_files=(), reason=parse_err)

    if not touched_files_set:
        return PatchPolicyDecision(
            valid=False, touched_files=(), reason="Patch contained no valid touched files"
        )

    allowed_set = set(envelope.allowed_files)
    forbidden_set = set(envelope.forbidden_files)

    for touched in touched_files_set:
        if touched in forbidden_set:
            return PatchPolicyDecision(
                valid=False,
                touched_files=tuple(sorted(touched_files_set)),
                reason=f"Touched file '{touched}' is in forbidden_files",
            )
        if allowed_set and touched not in allowed_set:
            return PatchPolicyDecision(
                valid=False,
                touched_files=tuple(sorted(touched_files_set)),
                reason=f"Touched file '{touched}' is not in allowed_files",
            )

    return PatchPolicyDecision(
        valid=True,
        touched_files=tuple(sorted(touched_files_set)),
        reason="Patch policy validation passed",
    )


class LocalPatchApplier:
    """Applies validated patches ONLY inside authorized EXECUTION_WORKTREE targets."""

    def __init__(self, uow: Any, worktree_manager: Any | None = None):
        if uow is None:
            raise ValueError("PersistenceUnitOfWork (uow) is mandatory for LocalPatchApplier.")
        self.uow = uow
        self.worktree_manager = worktree_manager

    def apply_patch(
        self,
        *,
        worktree_path: str | Path,
        envelope: LocalTaskEnvelope,
        patch: str,
        project_id: str,
        job_id: str,
    ) -> PatchApplicationResult:
        """Apply patch programmatically inside authorized EXECUTION_WORKTREE only."""
        if not project_id or not str(project_id).strip():
            return PatchApplicationResult(
                success=False, error="project_id is mandatory for authorized patch application."
            )
        if not job_id or not str(job_id).strip():
            return PatchApplicationResult(
                success=False, error="job_id is mandatory for authorized patch application."
            )

        if not patch or not patch.strip():
            return PatchApplicationResult(
                success=True, applied=False, authoritative_changed_files=()
            )

        target_dir = Path(worktree_path).resolve()
        if not target_dir.exists() or not target_dir.is_dir():
            return PatchApplicationResult(
                success=False, error=f"Target worktree path '{target_dir}' does not exist on disk."
            )

        # 0. Path identity / symlink resolution check
        abs_target = Path(os.path.abspath(str(worktree_path)))
        if abs_target != target_dir or os.path.islink(str(worktree_path)):
            return PatchApplicationResult(
                success=False,
                error=f"Path identity mismatch / symlink detected: abspath '{abs_target}' != realpath '{target_dir}'.",
            )

        # 1. SDLC Isolation Check via ManagedWorkspaceGuard (FAIL CLOSED)
        from minime.services.workspace_guard import ManagedWorkspaceGuard

        guard = ManagedWorkspaceGuard(self.uow)
        req = WorkspaceMutationRequest(
            project_id=project_id,
            target_path=str(target_dir),
            requested_operation=WorkspaceOperation.EDIT,
            actor="local_worker",
        )
        decision = guard.evaluate_mutation(req)
        if not decision.allowed or decision.workspace_role != WorkspaceRole.EXECUTION_WORKTREE:
            return PatchApplicationResult(
                success=False,
                error=f"Workspace mutation denied: {decision.provider_detail or 'Not an EXECUTION_WORKTREE'}",
            )

        # 2. Durable OrchestrationWorktreeOwnership verification in UoW
        ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        if not ownership_repo:
            return PatchApplicationResult(
                success=False, error="orchestration_worktree_ownerships repository missing in uow."
            )

        ownership = ownership_repo.get_by_canonical_path(str(target_dir))
        if not ownership and hasattr(ownership_repo, "get_by_job_id"):
            cand = ownership_repo.get_by_job_id(job_id)
            if cand and str(Path(cand.canonical_worktree_path).resolve()) == str(target_dir):
                ownership = cand

        if not ownership:
            return PatchApplicationResult(
                success=False,
                error=f"Durable OrchestrationWorktreeOwnership missing for '{target_dir}'.",
            )

        if ownership.project_id != project_id:
            return PatchApplicationResult(
                success=False,
                error=f"Ownership project_id mismatch: observed '{ownership.project_id}', expected '{project_id}'.",
            )

        if ownership.job_id != job_id:
            return PatchApplicationResult(
                success=False,
                error=f"Ownership job_id mismatch: observed '{ownership.job_id}', expected '{job_id}'.",
            )

        if getattr(ownership, "has_synthetic_placeholder", False):
            return PatchApplicationResult(
                success=False, error=f"Ownership at '{target_dir}' has synthetic placeholder."
            )

        # 3. On-disk .minime_worktree_ownership.json verification via WorktreeManager
        from minime.services.worktree_manager import WorktreeManager

        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project_id) if binding_repo else None
        if not binding or not getattr(binding, "managed_repository_root", None):
            return PatchApplicationResult(
                success=False,
                error=f"Valid ProjectManagedRepositoryBinding missing for project_id '{project_id}'.",
            )

        worktree_mgr = self.worktree_manager or WorktreeManager(
            project_root=binding.managed_repository_root, uow=self.uow, workspace_guard=guard
        )
        try:
            worktree_mgr._verify_ownership_marker(
                target_dir, ownership, worktree_kind="execution worktree"
            )
        except Exception as exc:
            return PatchApplicationResult(
                success=False, error=f"Worktree ownership marker verification failed: {exc}"
            )

        # 4. Re-verify runtime checkout & managed repo immutability
        runtime_root = guard.runtime_root
        managed_root = os.path.realpath(binding.managed_repository_root)
        resolved_target = str(target_dir)

        if resolved_target == runtime_root or resolved_target.startswith(runtime_root + "/"):
            return PatchApplicationResult(
                success=False, error="Refusing to mutate runtime checkout directly."
            )

        if resolved_target == managed_root or resolved_target.startswith(managed_root + "/"):
            return PatchApplicationResult(
                success=False, error="Refusing to mutate managed repository directly."
            )

        # 5. Check worktree is clean before application
        git_env = _build_git_env()
        status_res = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=10,
            env=git_env,
        )
        if status_res.returncode != 0:
            return PatchApplicationResult(
                success=False, error=f"Git status failed in worktree: {status_res.stderr}"
            )

        status_lines = [
            line
            for line in status_res.stdout.splitlines()
            if line.strip() and ".minime_worktree_ownership.json" not in line
        ]
        if status_lines:
            return PatchApplicationResult(
                success=False,
                error=f"Worktree '{target_dir}' is dirty before patch application.",
            )

        # 6. Programmatic git apply with sanitized env
        apply_res = subprocess.run(
            ["git", "apply", "-"],
            input=patch,
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=30,
            env=git_env,
        )
        if apply_res.returncode != 0:
            return PatchApplicationResult(
                success=False,
                error=f"git apply failed (code {apply_res.returncode}): {apply_res.stderr.strip() or apply_res.stdout.strip()}",
            )

        # 7. Postcondition verification: git diff --name-only / status
        post_diff = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=10,
            env=git_env,
        )
        post_untracked = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=10,
            env=git_env,
        )

        changed_set: set[str] = set()
        if post_diff.returncode == 0:
            for line in post_diff.stdout.splitlines():
                if line.strip():
                    changed_set.add(line.strip())

        if post_untracked.returncode == 0:
            for line in post_untracked.stdout.splitlines():
                if len(line) >= 4:
                    fname = line[3:].strip()
                    if fname and ".minime_worktree_ownership.json" not in fname:
                        changed_set.add(fname)

        actual_changed = tuple(sorted(changed_set))
        allowed_set = set(envelope.allowed_files)

        # Postcondition check: actual_changed <= allowed_files
        for ch in actual_changed:
            if allowed_set and ch not in allowed_set:
                return PatchApplicationResult(
                    success=False,
                    error=f"Postcondition failed: Actual changed file '{ch}' is not in allowed_files.",
                )

        return PatchApplicationResult(
            success=True,
            applied=True,
            authoritative_changed_files=actual_changed,
            error="",
        )
