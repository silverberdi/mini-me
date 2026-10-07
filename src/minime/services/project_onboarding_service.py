"""Project Onboarding Service for registration, binding validation, and auto-discovery."""

from __future__ import annotations

import os
from pathlib import Path

from minime.adapters.github import GitHubAdapter, GitHubAuthorizationError, GitHubRemoteError
from minime.domain.enums import EventType, ProjectOnboardingStatus, ProjectStatus
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    Project,
    ProjectOnboardingInput,
    ProjectOnboardingResult,
    utc_now,
)
from minime.logging import get_logger, set_correlation_context
from minime.services.context_discovery_service import ContextDiscoveryService
from minime.services.project_service import (
    normalize_repository_identity,
    validate_complementary_roles,
)

logger = get_logger("services.project_onboarding")


class ProjectOnboardingService:
    """Manages the onboarding flow for external projects."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        github_adapter: GitHubAdapter | None = None,
        context_discovery_service: ContextDiscoveryService | None = None,
        trusted_managed_root: str | Path | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.github_adapter = github_adapter or GitHubAdapter()
        self.context_discovery_service = context_discovery_service or ContextDiscoveryService(
            uow, project_root=self.project_root
        )
        self.trusted_managed_root = (
            str(Path(trusted_managed_root).resolve()) if trusted_managed_root else None
        )

    def _resolve_remote_source(self, raw_repo: str, norm_repo: str) -> str:
        cleaned = raw_repo.strip()
        if (
            cleaned.startswith("/")
            or cleaned.startswith("file://")
            or os.path.isabs(cleaned)
            or os.path.exists(cleaned)
        ):
            return cleaned
        if (
            cleaned.startswith("http://")
            or cleaned.startswith("https://")
            or cleaned.startswith("git@")
        ):
            return cleaned
        return f"https://github.com/{norm_repo}.git"

    def onboard_project(
        self,
        input_data: ProjectOnboardingInput,
        operator_email: str = "operator",
    ) -> ProjectOnboardingResult:
        """Onboard a new project with auto-discovery, conflict detection, and fail-closed validation."""
        set_correlation_context(
            project_id=input_data.project_id,
            operation_id="onboard_project",
        )

        project_id = input_data.project_id.strip()
        if not project_id:
            raise ValueError("project_id is required and cannot be empty.")

        display_name = input_data.display_name.strip() or project_id
        raw_repo = input_data.repository.strip()
        if not raw_repo:
            raise ValueError("repository identifier is required and cannot be empty.")

        # 1. Normalize repository identity
        try:
            norm_repo = normalize_repository_identity(raw_repo)
        except ValueError as exc:
            raise ValueError(f"Invalid repository identity '{raw_repo}': {exc}") from exc
        base_br = input_data.base_branch or "main"
        marker_filename = ".minime-managed-project.json"

        # 2. Existing-project recovery or duplicate detection.  A project id and
        # its durable identity are immutable, but an interrupted Stage C
        # workspace bootstrap may be resumed when that identity matches exactly.
        existing_project = self.uow.projects.get_by_id(project_id)
        resuming_existing_project = existing_project is not None
        if existing_project:
            identity_mismatches: list[str] = []
            existing_repo = normalize_repository_identity(existing_project.repository)
            if existing_repo != norm_repo:
                identity_mismatches.append(
                    f"repository is '{existing_repo}', not '{norm_repo}'"
                )
            if existing_project.base_branch != input_data.base_branch:
                identity_mismatches.append(
                    f"base_branch is '{existing_project.base_branch}', not '{input_data.base_branch}'"
                )
            if existing_project.openspec_path != input_data.openspec_path:
                identity_mismatches.append(
                    f"openspec_path is '{existing_project.openspec_path}', not '{input_data.openspec_path}'"
                )
            if existing_project.implementer != input_data.implementer:
                identity_mismatches.append(
                    f"implementer is '{existing_project.implementer}', not '{input_data.implementer}'"
                )
            if existing_project.reviewer != input_data.reviewer:
                identity_mismatches.append(
                    f"reviewer is '{existing_project.reviewer}', not '{input_data.reviewer}'"
                )
            if identity_mismatches:
                raise ValueError(
                    "Existing project immutable identity mismatch: "
                    + "; ".join(identity_mismatches)
                )

        # Check for existing repository binding conflict
        all_projects = self.uow.projects.list_all()
        for p in all_projects:
            if p.project_id == project_id:
                continue
            if p.repository.lower() == norm_repo.lower():
                raise ValueError(
                    f"Repository '{norm_repo}' is already bound to project '{p.project_id}'."
                )

        # 3. Validate complementary agent roles
        validate_complementary_roles(input_data.implementer, input_data.reviewer)

        # 4. Probe repository accessibility via GitHub App
        onboarding_status = ProjectOnboardingStatus.READY_FOR_WORK
        reasons: list[str] = []

        is_accessible = True
        try:
            verify_res = self.github_adapter.verify_repository(norm_repo)
            if verify_res.is_failure:
                is_accessible = False
                onboarding_status = ProjectOnboardingStatus.BLOCKED
                reasons.append(verify_res.error_message or "Repository access verification failed.")
            elif verify_res.is_unknown_or_ambiguous:
                reasons.append(
                    verify_res.error_message
                    or "GitHub API was unobservable during repository verification."
                )
        except GitHubAuthorizationError as exc:
            is_accessible = False
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            reasons.append(f"GitHub App authorization error: {exc}")
        except GitHubRemoteError as exc:
            reasons.append(f"GitHub API was unobservable during repository verification: {exc}")
        except Exception as exc:
            logger.debug(f"Local verification mode or unobservable: {exc}")

        # If repo is blocked due to hard access denial, fail closed
        if not is_accessible and onboarding_status == ProjectOnboardingStatus.BLOCKED:
            raise ValueError(
                f"Project onboarding failed closed on repository verification: {'; '.join(reasons)}"
            )

        # 5. Check local context directory presence
        root = self.project_root
        openspec_dir = root / input_data.openspec_path
        if not openspec_dir.exists():
            reasons.append(f"OpenSpec path '{input_data.openspec_path}' does not exist on disk.")
            if onboarding_status != ProjectOnboardingStatus.BLOCKED:
                onboarding_status = ProjectOnboardingStatus.CONTEXT_INCOMPLETE

        now = utc_now()

        # 6. Establish and validate Stage C ProjectManagedRepositoryBinding via Guard
        import json
        import os
        import subprocess

        from minime.domain.enums import WorkspaceOperation
        from minime.domain.models import ProjectManagedRepositoryBinding, WorkspaceMutationRequest
        from minime.services.workspace_guard import ManagedWorkspaceGuard

        trusted_root = (
            os.path.realpath(self.trusted_managed_root)
            if self.trusted_managed_root
            else os.path.realpath(os.environ.get("MINIME_MANAGED_ROOT", "/opt/minime/repos"))
        )
        runtime_root = os.path.realpath(
            os.environ.get("MINIME_RUNTIME_ROOT", str(self.project_root))
        )

        if getattr(input_data, "managed_repository_root", None):
            managed_root = os.path.realpath(input_data.managed_repository_root)
            if not self.trusted_managed_root and not os.environ.get("MINIME_MANAGED_ROOT"):
                trusted_root = os.path.dirname(managed_root)
        elif self.project_root != Path(runtime_root) and (self.project_root / ".git").exists():
            managed_root = str(self.project_root.resolve())
            if not self.trusted_managed_root and not os.environ.get("MINIME_MANAGED_ROOT"):
                trusted_root = os.path.dirname(managed_root)
        else:
            managed_root = os.path.realpath(f"{trusted_root}/{project_id}")

        if getattr(input_data, "worktree_parent_dir", None):
            worktree_parent_dir = os.path.realpath(input_data.worktree_parent_dir)
        else:
            worktree_parent_dir = os.path.realpath(f"{managed_root}/.minime/worktrees")

        guard = ManagedWorkspaceGuard(
            self.uow, runtime_root=runtime_root, trusted_managed_root=trusted_root
        )
        mismatch_reasons: list[str] = []

        provisional_binding = ProjectManagedRepositoryBinding(
            project_id=project_id,
            canonical_repository_identity=norm_repo,
            managed_repository_root=managed_root,
            worktree_parent_dir=worktree_parent_dir,
            default_base_branch=base_br,
            ownership_marker_filename=marker_filename,
            is_valid=True,
        )

        existing_managed_binding = self.uow.project_managed_repository_bindings.get_by_project_id(
            project_id
        )
        if existing_managed_binding:
            binding_mismatches: list[str] = []
            if (
                normalize_repository_identity(
                    existing_managed_binding.canonical_repository_identity
                )
                != norm_repo
            ):
                binding_mismatches.append("canonical repository identity differs")
            if os.path.realpath(existing_managed_binding.managed_repository_root) != managed_root:
                binding_mismatches.append("managed repository root differs")
            if os.path.realpath(existing_managed_binding.worktree_parent_dir) != worktree_parent_dir:
                binding_mismatches.append("worktree parent directory differs")
            if existing_managed_binding.remote_name != "origin":
                binding_mismatches.append("remote name is not 'origin'")
            if existing_managed_binding.default_base_branch != base_br:
                binding_mismatches.append("default base branch differs")
            if existing_managed_binding.ownership_marker_filename != marker_filename:
                binding_mismatches.append("ownership marker filename differs")
            if not existing_managed_binding.is_valid:
                binding_mismatches.append("existing managed repository binding is invalid")
            if existing_managed_binding.mismatch_reasons:
                binding_mismatches.append("existing managed repository binding has mismatch reasons")
            if binding_mismatches:
                raise ValueError(
                    "Existing managed repository binding mismatch: "
                    + "; ".join(binding_mismatches)
                )

        # 6a. Helper pre-checks (topology & trusted root containment)
        if guard._paths_overlap(managed_root, runtime_root):
            mismatch_reasons.append(
                f"Managed repository root '{managed_root}' aliases or overlaps runtime root '{runtime_root}'."
            )

        if guard._paths_overlap(worktree_parent_dir, runtime_root):
            mismatch_reasons.append(
                f"Worktree parent dir '{worktree_parent_dir}' aliases or overlaps runtime root '{runtime_root}'."
            )

        if trusted_root:
            if not (
                guard._is_path_inside(managed_root, trusted_root) or managed_root == trusted_root
            ):
                mismatch_reasons.append(
                    f"Managed repository root '{managed_root}' is outside trusted managed root '{trusted_root}'."
                )
            if not (
                guard._is_path_inside(worktree_parent_dir, trusted_root)
                or worktree_parent_dir == trusted_root
            ):
                mismatch_reasons.append(
                    f"Worktree parent directory '{worktree_parent_dir}' is outside trusted managed root '{trusted_root}'."
                )

        if mismatch_reasons:
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on pre-mutation topology checks: {'; '.join(reasons)}"
            )

        # 6b. MANDATORY Guard Authorization for target managed_root BEFORE filesystem or Git mutation
        req_managed_dir = WorkspaceMutationRequest(
            project_id=project_id,
            target_path=managed_root,
            requested_operation=WorkspaceOperation.EDIT,
        )
        dec_managed_dir = guard.evaluate_onboarding_bootstrap(
            req_managed_dir, provisional_binding=provisional_binding
        )
        if not dec_managed_dir.allowed:
            mismatch_reasons.append(
                f"ManagedWorkspaceGuard denied mutation authorization for repository root '{managed_root}': {dec_managed_dir.provider_detail}"
            )
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on Guard authorization denial for repository root: {dec_managed_dir.provider_detail}"
            )

        # 6c. Real Canonical Remote Repository Establishment (Clone / Fetch)
        remote_source = self._resolve_remote_source(raw_repo, norm_repo)

        try:
            if not os.path.exists(os.path.join(managed_root, ".git")):
                # Ensure parent dir exists under Guard authorization if needed
                parent_dir = os.path.dirname(managed_root)
                if parent_dir and not os.path.exists(parent_dir):
                    req_p = WorkspaceMutationRequest(
                        project_id=project_id,
                        target_path=parent_dir,
                        requested_operation=WorkspaceOperation.EDIT,
                    )
                    dec_p = guard.evaluate_onboarding_bootstrap(
                        req_p, provisional_binding=provisional_binding
                    )
                    if not dec_p.allowed:
                        raise ValueError(
                            f"Guard denied parent directory creation '{parent_dir}': {dec_p.provider_detail}"
                        )
                    os.makedirs(parent_dir, exist_ok=True)

                req_clone = WorkspaceMutationRequest(
                    project_id=project_id,
                    target_path=managed_root,
                    requested_operation=WorkspaceOperation.GIT_BRANCH,
                )
                dec_clone = guard.evaluate_onboarding_bootstrap(
                    req_clone, provisional_binding=provisional_binding
                )
                if not dec_clone.allowed:
                    raise ValueError(
                        f"Guard denied Git clone mutation for '{managed_root}': {dec_clone.provider_detail}"
                    )

                clone_cmd = ["git", "clone", "--branch", base_br, remote_source, managed_root]
                cp = subprocess.run(clone_cmd, capture_output=True, text=True)
                if cp.returncode != 0:
                    # Retry without --branch if branch checkout failed during clone
                    clone_fallback = ["git", "clone", remote_source, managed_root]
                    cp_fb = subprocess.run(clone_fallback, capture_output=True, text=True)
                    if cp_fb.returncode != 0:
                        raise ValueError(
                            f"Failed to clone remote repository from '{remote_source}' (branch '{base_br}'): "
                            f"{cp.stderr.strip() or cp_fb.stderr.strip() or cp.stdout.strip()}"
                        )
                    co_cp = subprocess.run(
                        ["git", "checkout", base_br],
                        cwd=managed_root,
                        capture_output=True,
                        text=True,
                    )
                    if co_cp.returncode != 0:
                        raise ValueError(
                            f"Remote repository does not contain requested base branch '{base_br}': {co_cp.stderr.strip()}"
                        )
            else:
                # 1. Verify remote identity BEFORE any fetch or mutation
                valid_git, git_reason = guard.verify_git_repository_identity(
                    managed_root, norm_repo, remote_name="origin"
                )
                if not valid_git:
                    raise ValueError(
                        f"Git repository identity verification failed pre-fetch: {git_reason}"
                    )

                # 2. Verify working tree safety BEFORE any fetch or mutation
                cp_status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=managed_root,
                    capture_output=True,
                    text=True,
                )
                if cp_status.returncode != 0:
                    raise ValueError(
                        f"Managed repository working tree status is unobservable: {cp_status.stderr.strip()}"
                    )
                dirty_lines = [
                    line
                    for line in cp_status.stdout.splitlines()
                    if line.strip() and line[3:] != marker_filename
                ]
                if dirty_lines:
                    raise ValueError(
                        f"Managed repository working tree is dirty: {'; '.join(dirty_lines)}"
                    )

                # 3. Fetch remote base branch under Guard authorization
                req_fetch = WorkspaceMutationRequest(
                    project_id=project_id,
                    target_path=managed_root,
                    requested_operation=WorkspaceOperation.GIT_BRANCH,
                )
                dec_fetch = guard.evaluate_onboarding_bootstrap(
                    req_fetch, provisional_binding=provisional_binding
                )
                if not dec_fetch.allowed:
                    raise ValueError(
                        f"Guard denied Git fetch mutation for '{managed_root}': {dec_fetch.provider_detail}"
                    )

                cp_fetch = subprocess.run(
                    ["git", "fetch", "origin", base_br],
                    cwd=managed_root,
                    capture_output=True,
                    text=True,
                )
                if cp_fetch.returncode != 0:
                    cp_fetch_fallback = subprocess.run(
                        ["git", "fetch", "origin"], cwd=managed_root, capture_output=True, text=True
                    )
                    if cp_fetch_fallback.returncode != 0:
                        fetch_err = (
                            cp_fetch.stderr.strip()
                            or cp_fetch_fallback.stderr.strip()
                            or "Remote fetch failed."
                        )
                        raise ValueError(
                            f"Remote repository '{remote_source}' is unobservable or unreachable during fetch: {fetch_err}"
                        )

                # 4. Analyze relationship between local HEAD and origin/<base_branch>
                cp_head = subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=managed_root, capture_output=True, text=True
                )
                cp_origin_head = subprocess.run(
                    ["git", "rev-parse", f"origin/{base_br}"],
                    cwd=managed_root,
                    capture_output=True,
                    text=True,
                )

                head_sha = cp_head.stdout.strip()
                origin_head_sha = cp_origin_head.stdout.strip()

                if cp_head.returncode != 0 or not head_sha:
                    raise ValueError(
                        f"Local HEAD commit in managed repository '{managed_root}' is unobservable: {cp_head.stderr.strip()}"
                    )
                if cp_origin_head.returncode != 0 or not origin_head_sha:
                    raise ValueError(
                        f"Remote base branch tracking ref 'origin/{base_br}' in managed repository is unobservable: {cp_origin_head.stderr.strip()}"
                    )

                # Allowed Outcomes:
                # A. HEAD == origin/base -> already converged; continue.
                if head_sha == origin_head_sha:
                    pass
                else:
                    # Check if local HEAD is an ancestor of origin/base
                    cp_ancestor = subprocess.run(
                        ["git", "merge-base", "--is-ancestor", "HEAD", f"origin/{base_br}"],
                        cwd=managed_root,
                        capture_output=True,
                        text=True,
                    )
                    if cp_ancestor.returncode == 0:
                        # B. local HEAD is an ancestor of origin/base -> safe fast-forward.
                        req_ff = WorkspaceMutationRequest(
                            project_id=project_id,
                            target_path=managed_root,
                            requested_operation=WorkspaceOperation.GIT_BRANCH,
                        )
                        dec_ff = guard.evaluate_onboarding_bootstrap(
                            req_ff, provisional_binding=provisional_binding
                        )
                        if not dec_ff.allowed:
                            raise ValueError(
                                f"Guard denied Git fast-forward mutation for '{managed_root}': {dec_ff.provider_detail}"
                            )

                        cp_branch = subprocess.run(
                            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=managed_root,
                            capture_output=True,
                            text=True,
                        )
                        current_branch = cp_branch.stdout.strip() if cp_branch.returncode == 0 else ""

                        if current_branch != base_br:
                            cp_co = subprocess.run(
                                ["git", "checkout", base_br],
                                cwd=managed_root,
                                capture_output=True,
                                text=True,
                            )
                            if cp_co.returncode != 0:
                                raise ValueError(
                                    f"Failed to checkout base branch '{base_br}' during fast-forward convergence: {cp_co.stderr.strip()}"
                                )

                        cp_ff = subprocess.run(
                            ["git", "merge", "--ff-only", f"origin/{base_br}"],
                            cwd=managed_root,
                            capture_output=True,
                            text=True,
                        )
                        if cp_ff.returncode != 0:
                            raise ValueError(
                                f"Fast-forward convergence failed for '{managed_root}': {cp_ff.stderr.strip()}"
                            )
                    else:
                        # Check if origin/base is an ancestor of local HEAD (local checkout is ahead)
                        cp_descendant = subprocess.run(
                            ["git", "merge-base", "--is-ancestor", f"origin/{base_br}", "HEAD"],
                            cwd=managed_root,
                            capture_output=True,
                            text=True,
                        )
                        if cp_descendant.returncode == 0:
                            # C. local checkout is ahead -> FAIL CLOSED
                            raise ValueError(
                                f"Local HEAD commit '{head_sha[:8]}' is ahead of remote base branch tracking ref 'origin/{base_br}' SHA '{origin_head_sha[:8]}'. Safe convergence cannot discard local commits."
                            )
                        else:
                            # D. histories diverged -> FAIL CLOSED
                            raise ValueError(
                                f"Local HEAD commit '{head_sha[:8]}' and remote base branch tracking ref 'origin/{base_br}' SHA '{origin_head_sha[:8]}' have diverged. Safe convergence cannot auto-merge or rebase."
                            )
        except Exception as exc:
            mismatch_reasons.append(f"Failed to establish canonical remote checkout: {exc}")
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on remote repository establishment: {exc}"
            ) from exc

        # 6d. Verify Remote Truth & Local HEAD Derivation (Require local HEAD SHA == origin/<base_branch> SHA!)
        cp_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=managed_root, capture_output=True, text=True
        )
        cp_origin_head = subprocess.run(
            ["git", "rev-parse", f"origin/{base_br}"],
            cwd=managed_root,
            capture_output=True,
            text=True,
        )

        head_sha = cp_head.stdout.strip()
        origin_head_sha = cp_origin_head.stdout.strip()

        if cp_head.returncode != 0 or not head_sha:
            mismatch_reasons.append(
                f"Local HEAD commit in managed repository '{managed_root}' is unobservable: {cp_head.stderr.strip()}"
            )
        if cp_origin_head.returncode != 0 or not origin_head_sha:
            mismatch_reasons.append(
                f"Remote base branch tracking ref 'origin/{base_br}' in managed repository is unobservable: {cp_origin_head.stderr.strip()}"
            )

        if head_sha and origin_head_sha and head_sha != origin_head_sha:
            mismatch_reasons.append(
                f"Local HEAD SHA '{head_sha}' does not match remote base branch tracking ref 'origin/{base_br}' SHA '{origin_head_sha}'."
            )

        if mismatch_reasons:
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on remote branch verification: {'; '.join(reasons)}"
            )

        # 6e. Post-checkout Remote Identity Verification
        valid_git, git_reason = guard.verify_git_repository_identity(
            managed_root, norm_repo, remote_name="origin"
        )
        if not valid_git:
            mismatch_reasons.append(
                f"Git repository identity verification failed post-checkout: {git_reason}"
            )
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on remote identity verification: {git_reason}"
            )

        # 6f. Establish Ownership Marker ONLY AFTER successful remote checkout verification
        marker_file = os.path.join(managed_root, marker_filename)
        req_marker = WorkspaceMutationRequest(
            project_id=project_id,
            target_path=marker_file,
            requested_operation=WorkspaceOperation.EDIT,
        )
        dec_marker = guard.evaluate_onboarding_bootstrap(
            req_marker, provisional_binding=provisional_binding
        )
        if not dec_marker.allowed:
            mismatch_reasons.append(
                f"ManagedWorkspaceGuard denied marker mutation: {dec_marker.provider_detail}"
            )
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on ownership marker authorization denial: {dec_marker.provider_detail}"
            )

        try:
            marker_data = {
                "project_id": project_id,
                "canonical_repository_identity": norm_repo,
            }
            with open(marker_file, "w", encoding="utf-8") as f:
                json.dump(marker_data, f, indent=2)
        except Exception as exc:
            mismatch_reasons.append(f"Failed to write ownership marker: {exc}")
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on ownership marker creation: {exc}"
            ) from exc

        valid_marker, marker_msg, _, _ = guard.verify_managed_repository_ownership_marker(
            managed_root, project_id, norm_repo, marker_filename
        )
        if not valid_marker:
            mismatch_reasons.append(
                f"Ownership marker verification failed post-establishment: {marker_msg}"
            )
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on ownership marker verification: {marker_msg}"
            )

        # 6g. Establish Worktree Parent Directory under Guard Authorization
        req_wt_parent = WorkspaceMutationRequest(
            project_id=project_id,
            target_path=worktree_parent_dir,
            requested_operation=WorkspaceOperation.WORKTREE_CREATE,
        )
        dec_wt_parent = guard.evaluate_onboarding_bootstrap(
            req_wt_parent, provisional_binding=provisional_binding
        )
        if not dec_wt_parent.allowed:
            mismatch_reasons.append(
                f"ManagedWorkspaceGuard denied worktree parent dir creation: {dec_wt_parent.provider_detail}"
            )
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on worktree parent directory authorization denial: {dec_wt_parent.provider_detail}"
            )

        try:
            os.makedirs(worktree_parent_dir, exist_ok=True)
        except Exception as exc:
            mismatch_reasons.append(f"Failed to create worktree parent directory: {exc}")
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on worktree parent directory creation: {exc}"
            ) from exc

        managed_binding_kwargs = {
            "project_id": project_id,
            "canonical_repository_identity": norm_repo,
            "remote_name": "origin",
            "managed_repository_root": managed_root,
            "worktree_parent_dir": worktree_parent_dir,
            "default_base_branch": base_br,
            "ownership_marker_filename": marker_filename,
            "is_valid": True,
            "mismatch_reasons": [],
            "validated_at": now,
            "created_at": now,
            "updated_at": now,
        }
        if existing_managed_binding:
            managed_binding_kwargs["binding_id"] = existing_managed_binding.binding_id
            managed_binding_kwargs["created_at"] = existing_managed_binding.created_at
        managed_binding = ProjectManagedRepositoryBinding(
            **managed_binding_kwargs
        )
        self.uow.project_managed_repository_bindings.save(managed_binding)

        if resuming_existing_project:
            assert existing_project is not None
            project = existing_project.model_copy(
                update={
                    "onboarding_status": onboarding_status,
                    "onboarding_reasons": reasons,
                    "updated_at": now,
                }
            )
        else:
            project = Project(
                project_id=project_id,
                display_name=display_name,
                repository=norm_repo,
                base_branch=input_data.base_branch,
                openspec_path=input_data.openspec_path,
                implementer=input_data.implementer,
                reviewer=input_data.reviewer,
                checks=input_data.checks,
                context_sources=input_data.context_sources,
                roadmap_path=input_data.roadmap_path,
                backlog_path=input_data.backlog_path,
                github_project_number=input_data.github_project_number,
                github_project_owner=input_data.github_project_owner,
                onboarding_status=onboarding_status,
                onboarding_reasons=reasons,
                status=ProjectStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )

        # 6. Save project entity and audit event
        self.uow.projects.save(project)

        event = Event(
            event_type=EventType.PROJECT_ONBOARDED,
            project_id=project_id,
            payload={
                "project_id": project_id,
                "display_name": project.display_name,
                "repository": norm_repo,
                "onboarding_status": onboarding_status.value,
                "operator_email": operator_email,
                "reasons": reasons,
            },
            timestamp=now,
        )
        self.uow.events.save(event)
        self.uow.commit()

        # 7. Trigger initial context and backlog discovery
        discovery_report = None
        try:
            discovery_report = self.context_discovery_service.discover_context(project_id)
        except Exception as exc:
            logger.warning(
                f"Initial context discovery encountered an error for '{project_id}': {exc}"
            )

        return ProjectOnboardingResult(
            project=project,
            status=onboarding_status,
            reasons=reasons,
            discovered_context=discovery_report,
        )
