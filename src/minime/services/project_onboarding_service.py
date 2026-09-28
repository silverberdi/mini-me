"""Project Onboarding Service for registration, binding validation, and auto-discovery."""

from __future__ import annotations

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

        # 2. Duplicate detection
        existing_project = self.uow.projects.get_by_id(project_id)
        if existing_project:
            raise ValueError(
                f"Project with ID '{project_id}' is already registered. Identifiers are immutable."
            )

        # Check for existing repository binding conflict
        all_projects = self.uow.projects.list_all()
        for p in all_projects:
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
                reasons.append(verify_res.error_message or "GitHub API was unobservable during repository verification.")
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

        # 5b. Establish and validate Stage C ProjectManagedRepositoryBinding
        import json
        import os
        import subprocess

        from minime.domain.models import ProjectManagedRepositoryBinding
        from minime.services.workspace_guard import ManagedWorkspaceGuard

        trusted_root = (
            os.path.realpath(self.trusted_managed_root)
            if self.trusted_managed_root
            else os.path.realpath(os.environ.get("MINIME_MANAGED_ROOT", "/opt/minime/repos"))
        )
        runtime_root = os.path.realpath(os.environ.get("MINIME_RUNTIME_ROOT", str(self.project_root)))

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

        guard = ManagedWorkspaceGuard(self.uow, runtime_root=runtime_root, trusted_managed_root=trusted_root)
        mismatch_reasons: list[str] = []

        # 1. Reject RUNTIME overlap BEFORE mutation
        if guard._paths_overlap(managed_root, runtime_root):
            mismatch_reasons.append(f"Managed repository root '{managed_root}' aliases or overlaps runtime root '{runtime_root}'.")

        if guard._paths_overlap(worktree_parent_dir, runtime_root):
            mismatch_reasons.append(f"Worktree parent dir '{worktree_parent_dir}' aliases or overlaps runtime root '{runtime_root}'.")

        # 2. Check trusted root bounds BEFORE mutation
        if trusted_root:
            if not (guard._is_path_inside(managed_root, trusted_root) or managed_root == trusted_root):
                mismatch_reasons.append(f"Managed repository root '{managed_root}' is outside trusted managed root '{trusted_root}'.")
            if not (guard._is_path_inside(worktree_parent_dir, trusted_root) or worktree_parent_dir == trusted_root):
                mismatch_reasons.append(f"Worktree parent directory '{worktree_parent_dir}' is outside trusted managed root '{trusted_root}'.")

        if mismatch_reasons:
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on pre-mutation topology checks: {'; '.join(reasons)}"
            )

        # 3. Establish filesystem layout
        try:
            os.makedirs(managed_root, exist_ok=True)
            os.makedirs(worktree_parent_dir, exist_ok=True)
        except Exception as exc:
            mismatch_reasons.append(f"Failed to create managed repository layout: {exc}")
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(f"Project onboarding failed closed on directory creation: {exc}") from exc

        # 4. Establish Git repository identity
        remote_url = f"https://{norm_repo}"
        base_br = input_data.base_branch or "main"

        try:
            if not os.path.exists(os.path.join(managed_root, ".git")):
                subprocess.run(["git", "init", "-b", base_br], cwd=managed_root, check=True, capture_output=True)
                subprocess.run(["git", "config", "user.name", "mini me"], cwd=managed_root, check=True)
                subprocess.run(["git", "config", "user.email", "minime@local"], cwd=managed_root, check=True)
                subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=managed_root, check=True)
                subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=managed_root, check=True, capture_output=True)

                if not any(f for f in os.listdir(managed_root) if f != ".git"):
                    readme_path = os.path.join(managed_root, "README.md")
                    with open(readme_path, "w", encoding="utf-8") as f:
                        f.write(f"# {display_name}\n\nManaged project repository for {norm_repo}\n")
                    subprocess.run(["git", "add", "."], cwd=managed_root, check=True)
                    subprocess.run(["git", "commit", "-m", "Initial managed repository base commit"], cwd=managed_root, check=True, capture_output=True)

                subprocess.run(["git", "update-ref", f"refs/remotes/origin/{base_br}", "HEAD"], cwd=managed_root, check=True)
            else:
                cp = subprocess.run(["git", "remote", "get-url", "origin"], cwd=managed_root, capture_output=True, text=True)
                if cp.returncode != 0:
                    subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=managed_root, check=True, capture_output=True)
        except Exception as exc:
            mismatch_reasons.append(f"Failed to establish Git repository: {exc}")
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(f"Project onboarding failed closed on Git repository establishment: {exc}") from exc

        # 5. Establish ownership marker file (.minime-managed-project.json)
        try:
            marker_file = os.path.join(managed_root, ".minime-managed-project.json")
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
            raise ValueError(f"Project onboarding failed closed on ownership marker creation: {exc}") from exc

        # 6. Post-establishment verification
        valid_git, git_reason = guard.verify_git_repository_identity(managed_root, norm_repo, remote_name="origin")
        if not valid_git:
            mismatch_reasons.append(f"Git repository identity verification failed post-establishment: {git_reason}")

        valid_marker, marker_msg, _, _ = guard.verify_managed_repository_ownership_marker(managed_root, project_id, norm_repo)
        if not valid_marker:
            mismatch_reasons.append(f"Ownership marker verification failed post-establishment: {marker_msg}")

        if not os.path.exists(managed_root) or not os.path.isdir(managed_root):
            mismatch_reasons.append(f"Managed root '{managed_root}' missing post-establishment.")

        if not os.path.exists(worktree_parent_dir) or not os.path.isdir(worktree_parent_dir):
            mismatch_reasons.append(f"Worktree parent directory '{worktree_parent_dir}' missing post-establishment.")

        if mismatch_reasons:
            reasons.extend(mismatch_reasons)
            onboarding_status = ProjectOnboardingStatus.BLOCKED
            raise ValueError(
                f"Project onboarding failed closed on post-establishment verification: {'; '.join(reasons)}"
            )

        managed_binding = ProjectManagedRepositoryBinding(
            project_id=project_id,
            canonical_repository_identity=norm_repo,
            remote_name="origin",
            managed_repository_root=managed_root,
            worktree_parent_dir=worktree_parent_dir,
            default_base_branch=input_data.base_branch,
            is_valid=True,
            mismatch_reasons=[],
            created_at=now,
            updated_at=now,
        )
        self.uow.project_managed_repository_bindings.save(managed_binding)

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
                "display_name": display_name,
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
