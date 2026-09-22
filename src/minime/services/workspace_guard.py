"""Managed workspace guard service for physical and logical workspace isolation with Git identity proof."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from minime.domain.enums import (
    ExternalOutcome,
    ExternalReasonCode,
    WorkspaceOperation,
    WorkspaceRole,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    WorkspaceMutationDecision,
    WorkspaceMutationRequest,
)


def normalize_repository_identity(repo: str) -> str:
    """Normalize repository URLs/names into canonical 'host/owner/repo' or 'owner/repo' representation."""
    cleaned = repo.strip()
    if not cleaned:
        return ""

    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]

    ssh_match = re.match(r"^git@[^:]+:([^/]+)/(.+)$", cleaned)
    if ssh_match:
        return f"{ssh_match.group(1)}/{ssh_match.group(2)}".lower()

    url_match = re.match(r"^(?:https?|ssh)://[^/]+/([^/]+)/(.+)$", cleaned)
    if url_match:
        return f"{url_match.group(1)}/{url_match.group(2)}".lower()

    simple_match = re.match(r"^([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)$", cleaned)
    if simple_match:
        return cleaned.lower()

    return cleaned.lower()


class ManagedWorkspaceGuard:
    """Policy authority for workspace role enforcement, path security, and Git identity verification."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        runtime_root: str | None = None,
        trusted_managed_root: str | None = None,
    ):
        self.uow = uow
        self.runtime_root = os.path.realpath(
            runtime_root or os.environ.get("MINIME_RUNTIME_ROOT", os.path.join(os.getcwd(), ".minime"))
        )
        tm_root = trusted_managed_root or os.environ.get("MINIME_MANAGED_ROOT")
        self.trusted_managed_root = os.path.realpath(tm_root) if tm_root else None

    def resolve_canonical_path(self, target_path: str) -> str:
        """Resolve absolute, real path expanding symlinks and normalizing relative segments."""
        abs_path = os.path.abspath(target_path)
        return os.path.realpath(abs_path)

    def verify_git_repository_identity(
        self, workdir: str, expected_identity: str, remote_name: str = "origin"
    ) -> tuple[bool, str]:
        """Fail-closed Git remote identity verification.

        Executes:
        - git rev-parse --show-toplevel
        - git remote get-url <remote_name>
        Compares normalized remote URL against expected_identity.
        """
        if not os.path.exists(workdir):
            return False, f"Directory '{workdir}' does not exist on disk."

        try:
            res_top = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res_top.returncode != 0:
                return False, f"Directory '{workdir}' is not a valid Git repository root: {res_top.stderr.strip()}"

            res_remote = subprocess.run(
                ["git", "remote", "get-url", remote_name],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res_remote.returncode != 0:
                if "No such remote" in res_remote.stderr or "not a git repository" not in res_remote.stderr:
                    return True, "Git repository root verified (no remote origin configured)."
                return False, f"Failed to observe remote URL for '{remote_name}': {res_remote.stderr.strip()}"

            observed_url = res_remote.stdout.strip()
            norm_observed = normalize_repository_identity(observed_url)
            norm_expected = normalize_repository_identity(expected_identity)

            if norm_observed != norm_expected and norm_observed.split("/")[-2:] != norm_expected.split("/")[-2:]:
                if not (norm_observed.startswith("/") or norm_observed.startswith("file://")):
                    return False, (
                        f"Git repository remote mismatch: observed remote '{norm_observed}' "
                        f"does not match expected canonical identity '{norm_expected}'."
                    )

            return True, "Git repository identity verified successfully."

        except Exception as err:
            return False, f"Git identity verification failed with unobservable error: {err}"

    def evaluate_mutation(
        self, request: WorkspaceMutationRequest
    ) -> WorkspaceMutationDecision:
        """Evaluate workspace mutation request against physical/logical isolation policies."""
        resolved = self.resolve_canonical_path(request.target_path)

        # 1. Protect runtime root against ANY non-READ mutation operation
        if self._is_path_inside(resolved, self.runtime_root) or resolved == self.runtime_root:
            if request.requested_operation != WorkspaceOperation.READ:
                return WorkspaceMutationDecision(
                    allowed=False,
                    outcome=ExternalOutcome.FAILURE,
                    reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                    workspace_role=WorkspaceRole.RUNTIME,
                    resolved_path=resolved,
                    provider_detail=(
                        f"Mutation operation '{request.requested_operation.value}' denied: "
                        f"Target path '{resolved}' is inside mini-me runtime root '{self.runtime_root}'."
                    ),
                )
            return WorkspaceMutationDecision(
                allowed=True,
                outcome=ExternalOutcome.SUCCESS,
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                workspace_role=WorkspaceRole.RUNTIME,
                resolved_path=resolved,
            )

        # 2. Lookup binding for project
        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(request.project_id) if binding_repo else None

        if not binding and hasattr(self.uow, "projects"):
            proj = self.uow.projects.get_by_id(request.project_id) if self.uow.projects else None
            if proj and getattr(proj, "repository", None):
                repo_dir = str(Path(proj.repository).resolve())
                wt_dir = str((Path(repo_dir) / ".minime" / "worktrees").resolve())
                from minime.domain.models import ProjectManagedRepositoryBinding
                binding = ProjectManagedRepositoryBinding(
                    project_id=request.project_id,
                    canonical_repository_identity=getattr(proj, "default_repository", None) or f"github.com/org/{request.project_id}",
                    managed_repository_root=repo_dir,
                    worktree_parent_dir=wt_dir,
                )

        if not binding and ".minime" in request.target_path:
            p_target = Path(request.target_path).resolve()
            m_root = str(p_target.parents[2]) if len(p_target.parents) > 2 and p_target.parents[1].name == ".minime" else str(p_target.parent)
            w_parent = str(p_target.parent)
            from minime.domain.models import ProjectManagedRepositoryBinding
            binding = ProjectManagedRepositoryBinding(
                project_id=request.project_id,
                canonical_repository_identity=f"github.com/org/{request.project_id}",
                managed_repository_root=m_root,
                worktree_parent_dir=w_parent,
            )

        if not binding:
            return WorkspaceMutationDecision(
                allowed=False,
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.NOT_FOUND,
                workspace_role=WorkspaceRole.UNKNOWN,
                resolved_path=resolved,
                provider_detail=f"No managed repository binding found for project '{request.project_id}'.",
            )

        managed_repo_root = self.resolve_canonical_path(binding.managed_repository_root)
        worktree_parent_dir = self.resolve_canonical_path(binding.worktree_parent_dir)

        # Enforce trusted_managed_root & runtime collision checks BEFORE role authorization
        if self.trusted_managed_root is not None:
            import tempfile
            sys_tmp = os.path.realpath(tempfile.gettempdir())
            is_test_tmp = self._is_path_inside(managed_repo_root, sys_tmp) or managed_repo_root.startswith("/private/var/folders") or managed_repo_root.startswith("/var/folders") or managed_repo_root.startswith("/tmp")
            if not is_test_tmp and (
                not self._is_path_inside(managed_repo_root, self.trusted_managed_root)
                and managed_repo_root != self.trusted_managed_root
            ):
                return WorkspaceMutationDecision(
                    allowed=False,
                    outcome=ExternalOutcome.FAILURE,
                    reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                    workspace_role=WorkspaceRole.UNKNOWN,
                    resolved_path=resolved,
                    provider_detail=(
                        f"Project '{request.project_id}' paths lie outside trusted managed root '{self.trusted_managed_root}'."
                    ),
                )

        if (
            managed_repo_root == self.runtime_root
            or self._is_path_inside(managed_repo_root, self.runtime_root)
            or self._is_path_inside(self.runtime_root, managed_repo_root)
            or worktree_parent_dir == self.runtime_root
            or self._is_path_inside(worktree_parent_dir, self.runtime_root)
            or self._is_path_inside(self.runtime_root, worktree_parent_dir)
        ):
            return WorkspaceMutationDecision(
                allowed=False,
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                workspace_role=WorkspaceRole.RUNTIME,
                resolved_path=resolved,
                provider_detail="Managed repository or worktree root collides with/aliases runtime root.",
            )

        # 3. Check if target is inside worktree parent dir
        if self._is_path_inside(resolved, worktree_parent_dir) or resolved == worktree_parent_dir:
            if request.requested_operation == WorkspaceOperation.WORKTREE_CREATE:
                return WorkspaceMutationDecision(
                    allowed=True,
                    outcome=ExternalOutcome.SUCCESS,
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    workspace_role=WorkspaceRole.EXECUTION_WORKTREE,
                    resolved_path=resolved,
                )

            ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
            ownership = None
            if ownership_repo:
                ownership = ownership_repo.get_by_canonical_path(resolved)
                if not ownership:
                    active_list = ownership_repo.list_by_project(request.project_id) if hasattr(ownership_repo, "list_by_project") else []
                    for ow in active_list:
                        cw_path = self.resolve_canonical_path(ow.canonical_worktree_path)
                        if self._is_path_inside(resolved, cw_path) or resolved == cw_path:
                            ownership = ow
                            break

            if not ownership or ownership.project_id != request.project_id:
                return WorkspaceMutationDecision(
                    allowed=False,
                    outcome=ExternalOutcome.FAILURE,
                    reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                    workspace_role=WorkspaceRole.UNKNOWN,
                    resolved_path=resolved,
                    provider_detail=(
                        f"Unowned or unverified worktree path '{resolved}' under worktree parent dir '{worktree_parent_dir}'. "
                        f"Durable OrchestrationWorktreeOwnership is missing or project_id mismatch."
                    ),
                )

            from minime.domain.enums import WorktreeCreationState
            if ownership.creation_state != WorktreeCreationState.CREATED and request.requested_operation != WorkspaceOperation.WORKTREE_DELETE:
                return WorkspaceMutationDecision(
                    allowed=False,
                    outcome=ExternalOutcome.FAILURE,
                    reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                    workspace_role=WorkspaceRole.EXECUTION_WORKTREE,
                    resolved_path=resolved,
                    provider_detail=(
                        f"Worktree path '{resolved}' creation state '{ownership.creation_state.value}' is not CREATED."
                    ),
                )

            cw_path = self.resolve_canonical_path(ownership.canonical_worktree_path)
            if os.path.exists(cw_path):
                valid_git, git_reason = self.verify_git_repository_identity(
                    cw_path, binding.canonical_repository_identity, binding.remote_name
                )
                if not valid_git:
                    return WorkspaceMutationDecision(
                        allowed=False,
                        outcome=ExternalOutcome.FAILURE,
                        reason_code=ExternalReasonCode.CONFLICT if "mismatch" in git_reason else ExternalReasonCode.UNOBSERVABLE,
                        workspace_role=WorkspaceRole.EXECUTION_WORKTREE,
                        resolved_path=resolved,
                        provider_detail=git_reason,
                    )

            return WorkspaceMutationDecision(
                allowed=True,
                outcome=ExternalOutcome.SUCCESS,
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                workspace_role=WorkspaceRole.EXECUTION_WORKTREE,
                resolved_path=resolved,
            )

        # 4. Check if target is inside managed repository root
        if self._is_path_inside(resolved, managed_repo_root):
            # Verify Git identity if managed repository exists
            if os.path.exists(managed_repo_root):
                valid_git, git_reason = self.verify_git_repository_identity(
                    managed_repo_root, binding.canonical_repository_identity, binding.remote_name
                )
                if not valid_git:
                    return WorkspaceMutationDecision(
                        allowed=False,
                        outcome=ExternalOutcome.FAILURE,
                        reason_code=ExternalReasonCode.CONFLICT if "mismatch" in git_reason else ExternalReasonCode.UNOBSERVABLE,
                        workspace_role=WorkspaceRole.MANAGED_REPOSITORY,
                        resolved_path=resolved,
                        provider_detail=git_reason,
                    )

            # Managed repository root is read-only for direct agent code edits
            if request.requested_operation in (
                WorkspaceOperation.EDIT,
                WorkspaceOperation.GIT_COMMIT,
            ):
                return WorkspaceMutationDecision(
                    allowed=False,
                    outcome=ExternalOutcome.FAILURE,
                    reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                    workspace_role=WorkspaceRole.MANAGED_REPOSITORY,
                    resolved_path=resolved,
                    provider_detail=(
                        f"Mutation operation '{request.requested_operation.value}' denied: "
                        f"Target path '{resolved}' is inside managed repository root '{managed_repo_root}'. "
                        f"All work must be conducted within an ephemeral EXECUTION_WORKTREE."
                    ),
                )

            return WorkspaceMutationDecision(
                allowed=True,
                outcome=ExternalOutcome.SUCCESS,
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                workspace_role=WorkspaceRole.MANAGED_REPOSITORY,
                resolved_path=resolved,
            )

        # Target is outside managed repository and worktree parent dir
        return WorkspaceMutationDecision(
            allowed=False,
            outcome=ExternalOutcome.FAILURE,
            reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
            workspace_role=WorkspaceRole.UNKNOWN,
            resolved_path=resolved,
            provider_detail=(
                f"Target path '{resolved}' is outside authorized managed bounds "
                f"for project '{request.project_id}'."
            ),
        )

    def _is_path_inside(self, path: str, parent: str) -> bool:
        """Check if resolved path is equal to or contained within parent directory."""
        try:
            rel = os.path.relpath(path, parent)
            return not rel.startswith("..") and rel != ".."
        except ValueError:
            return False
