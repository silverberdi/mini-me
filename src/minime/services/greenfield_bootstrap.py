"""Durable Greenfield onboarding coordinator.

This module only coordinates existing project, workspace, OpenSpec and GitHub
adapters.  It does not generate OpenSpec artifacts or replace an agent workflow.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from minime.adapters.openspec import OpenSpecAdapter
from minime.config import resolve_cli_invocation
from minime.domain.enums import ExternalOutcome, ProjectOnboardingStatus, ProjectType
from minime.domain.models import Project, ProjectConfigurationInput, ProjectOnboardingInput, utc_now
from minime.services.context_archive import ContextArchiveExtractor
from minime.services.implementer_runner import CliImplementerRunner, ImplementerResult
from minime.services.project_connection_service import ProjectConnectionService
from minime.services.project_onboarding_service import ProjectOnboardingService
from minime.services.project_service import ProjectService


class ThinkingAgent(Protocol):
    async def run(self, worktree: Path, instruction: str, timeout_seconds: int) -> ImplementerResult: ...


class GreenfieldBootstrapError(RuntimeError):
    """A Greenfield operation was refused or could not prove its postcondition."""


class GreenfieldBootstrapCoordinator:
    """Run ZIP -> isolated branch -> real thinking agent -> first PR.

    All effectful dependencies are injectable so the ordering and fail-closed
    behavior can be tested without pretending that a fake agent is production E2E.
    """

    def __init__(
        self,
        uow: Any,
        *,
        project_service: ProjectService | None = None,
        connection_service: ProjectConnectionService | None = None,
        onboarding_service: ProjectOnboardingService | None = None,
        archive_extractor: ContextArchiveExtractor | None = None,
        openspec: OpenSpecAdapter | None = None,
        thinking_agent: ThinkingAgent | None = None,
        project_root: str | Path = ".",
        trusted_managed_root: str | Path | None = None,
    ) -> None:
        self.uow = uow
        self.projects = project_service or ProjectService(uow)
        self.connections = connection_service or ProjectConnectionService(self.projects.credential_store)
        self.onboarding = onboarding_service or ProjectOnboardingService(
            uow, project_root=project_root, trusted_managed_root=trusted_managed_root
        )
        self.extractor = archive_extractor or ContextArchiveExtractor()
        self.openspec = openspec or OpenSpecAdapter()
        self.thinking_agent = thinking_agent
        self.project_root = Path(project_root).resolve()
        self.trusted_managed_root = (
            Path(trusted_managed_root).resolve() if trusted_managed_root else None
        )

    def bootstrap(
        self,
        configuration: ProjectConfigurationInput,
        archive: bytes,
        *,
        operator_email: str = "operator",
        timeout_seconds: int = 1_800,
    ) -> dict[str, Any]:
        """Perform a resumable Greenfield bootstrap and return sanitized evidence."""
        if configuration.project_type is not ProjectType.GREENFIELD:
            raise GreenfieldBootstrapError("Greenfield bootstrap requires project_type GREENFIELD")
        if self.uow.projects.get_by_id(configuration.project_id) is not None:
            raise GreenfieldBootstrapError("Project already exists; use its pending onboarding checkpoint")

        # Validate the complete ZIP before creating a row, credential, workspace or branch.
        package_sha = hashlib.sha256(archive).hexdigest() if archive else ""
        with tempfile.TemporaryDirectory(prefix="minime-context-", dir=tempfile.gettempdir()) as package_dir:
            package_root = Path(package_dir)
            extracted = self.extractor.extract(archive, package_root)
            checkpoint = {
                "operation_revision": package_sha,
                "source_zip_sha256": extracted.sha256,
                "provenance_reference": f"context/incoming/{extracted.sha256}/",
            }

            # Persist only after ZIP validation.  The existing project service owns
            # identity, credentials, profile validation and transaction boundaries.
            project = self.projects.create_configured_project(
                configuration,
                allow_greenfield=True,
                onboarding_checkpoint=checkpoint,
            )
            try:
                return self._run_after_project_creation(
                    project,
                    package_root,
                    extracted.files,
                    operator_email=operator_email,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                self._block(project, f"GREENFIELD_BOOTSTRAP_FAILED:{type(exc).__name__}")
                raise

    def add_context(
        self,
        project_id: str,
        archive: bytes,
        *,
        timeout_seconds: int = 1_800,
    ) -> dict[str, Any]:
        """Publish one incremental context PR without changing approved context."""
        project = self.uow.projects.get_by_id(project_id)
        if project is None:
            raise GreenfieldBootstrapError("Project not found")
        if project.onboarding_status is not ProjectOnboardingStatus.PREPARED:
            raise GreenfieldBootstrapError("Incremental context requires a prepared project")
        if project.onboarding_checkpoint.get("pending_context"):
            raise GreenfieldBootstrapError("An unmerged incremental context PR is already pending")
        package_sha = hashlib.sha256(archive).hexdigest() if archive else ""
        pending = project.onboarding_checkpoint.get("pending_context", {})
        if pending.get("source_zip_sha256") == package_sha and pending.get("pull_request_url"):
            return {"project_id": project_id, "pending_context": pending, "reused": True}
        with tempfile.TemporaryDirectory(prefix="minime-context-incremental-", dir=tempfile.gettempdir()) as package_dir:
            extracted = self.extractor.extract(archive, package_dir)
            profile = self._thinking_profile(project)
            self._validate_thinking_profile(profile)
            binding = self.uow.project_managed_repository_bindings.get_by_project_id(project_id)
            workspace = self.projects.verified_managed_workspace_root(project_id)
            if binding is None or workspace is None:
                raise GreenfieldBootstrapError("Prepared project workspace identity is unavailable")
            self._git(str(workspace), "fetch", "origin", project.base_branch)
            base_sha = self._git(str(workspace), "rev-parse", f"origin/{project.base_branch}")
            branch = f"minime/context/{project_id}-{extracted.sha256[:12]}"
            self._assert_not_main(branch, project.base_branch)
            worktree = Path(self._worktree_path(binding, branch))
            self._git(str(workspace), "worktree", "add", "--detach", str(worktree), base_sha)
            try:
                self._git(str(worktree), "checkout", "-b", branch)
                self.openspec.install_official_integrations(worktree, self._selected_agents(project))
                incoming = worktree / "context" / "incoming" / extracted.sha256
                incoming.mkdir(parents=True, mode=0o700)
                for relative in extracted.files:
                    source = Path(package_dir) / relative
                    target = incoming / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    target.chmod(0o600)
                self._run_thinking_agent(project, worktree, profile, timeout_seconds)
                self._validate_candidate(worktree, incoming)
                self._git(str(worktree), "add", "--all")
                self._git(str(worktree), "commit", "-m", "docs: add project context")
                head_sha = self._git(str(worktree), "rev-parse", "HEAD")
                adapter = self.connections.require_git_pr_write(project)
                pushed = adapter.push_branch(str(worktree), "origin", branch, head_sha)
                if pushed.outcome != ExternalOutcome.SUCCESS:
                    raise GreenfieldBootstrapError("Incremental context push was not proven successful")
                pr = self.connections.create_pull_request(
                    project,
                    branch,
                    "docs: add project context",
                    f"Incremental context for `{project_id}`.\n\nBase SHA: `{base_sha}`\nHead SHA: `{head_sha}`",
                    head_sha,
                )
                if pr.outcome != ExternalOutcome.SUCCESS or not isinstance(pr.data, dict):
                    raise GreenfieldBootstrapError("Incremental context PR was not proven successful")
                pending = {
                    "source_zip_sha256": extracted.sha256,
                    "bootstrap_branch": branch,
                    "base_sha": base_sha,
                    "head_sha": head_sha,
                    "pull_request_number": pr.data.get("number"),
                    "pull_request_url": pr.data.get("url"),
                }
                project.onboarding_checkpoint = {
                    **project.onboarding_checkpoint,
                    "pending_context": pending,
                }
                project.updated_at = utc_now()
                self.uow.projects.save(project)
                self.uow.commit()
                return {"project_id": project_id, "pending_context": pending, "reused": False}
            finally:
                self._git(str(workspace), "worktree", "remove", "--force", str(worktree), check=False)

    def _run_after_project_creation(
        self,
        project: Project,
        package_root: Path,
        source_files: tuple[str, ...],
        *,
        operator_email: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        profile = self._thinking_profile(project)
        self._validate_thinking_profile(profile)
        # Reuse the existing guarded repository establishment and managed binding.
        self.onboarding.onboard_project(
            ProjectOnboardingInput(
                project_id=project.project_id,
                display_name=project.display_name,
                repository=project.repository,
                base_branch=project.base_branch,
                openspec_path=project.openspec_path,
                implementer=project.implementer,
                reviewer=project.reviewer,
                managed_repository_root=self._configured_root(project),
            ),
            operator_email=operator_email,
        )
        project = self.uow.projects.get_by_id(project.project_id)
        if project is None:
            raise GreenfieldBootstrapError("Project disappeared during guarded workspace establishment")
        binding = self.uow.project_managed_repository_bindings.get_by_project_id(project.project_id)
        if binding is None:
            raise GreenfieldBootstrapError("Managed repository binding was not persisted")

        git_adapter = self.connections.require_git_pr_write(project)
        branch = f"minime/bootstrap/{project.project_id}-{project.onboarding_checkpoint['source_zip_sha256'][:12]}"
        self._assert_not_main(branch, project.base_branch)
        self._git(binding.managed_repository_root, "fetch", "origin", project.base_branch)
        base_sha = self._git(
            binding.managed_repository_root, "rev-parse", f"origin/{project.base_branch}"
        )
        self._git(binding.managed_repository_root, "worktree", "add", "--detach", self._worktree_path(binding, branch), base_sha)
        worktree = Path(self._worktree_path(binding, branch))
        try:
            self._git(str(worktree), "checkout", "-b", branch)
            self.openspec.install_official_integrations(worktree, self._selected_agents(project))
            incoming = worktree / "context" / "incoming" / project.onboarding_checkpoint["source_zip_sha256"]
            incoming.mkdir(parents=True, mode=0o700)
            for relative in source_files:
                source = package_root / relative
                target = incoming / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                target.chmod(0o600)
            self._run_thinking_agent(project, worktree, profile, timeout_seconds)
            self._validate_candidate(worktree, incoming)
            self._git(str(worktree), "add", "--all")
            self._git(str(worktree), "commit", "-m", "docs: bootstrap project context")
            head_sha = self._git(str(worktree), "rev-parse", "HEAD")
            pushed = git_adapter.push_branch(str(worktree), "origin", branch, head_sha)
            if pushed.outcome != ExternalOutcome.SUCCESS:
                raise GreenfieldBootstrapError("Bootstrap branch push was not proven successful")
            pr = self.connections.create_pull_request(
                project, branch, "docs: bootstrap project context",
                self._pr_body(project, base_sha, head_sha), head_sha,
            )
            if pr.outcome != ExternalOutcome.SUCCESS or not isinstance(pr.data, dict):
                raise GreenfieldBootstrapError("Bootstrap pull request was not proven successful")
            checkpoint = {
                **project.onboarding_checkpoint,
                "bootstrap_branch": branch,
                "base_branch": project.base_branch,
                "base_sha": base_sha,
                "expected_base_sha": base_sha,
                "head_sha": head_sha,
                "pull_request_number": pr.data.get("number"),
                "pull_request_url": pr.data.get("url"),
                "agent": profile.agent_id,
                "agent_model": profile.model_id,
            }
            project.onboarding_checkpoint = checkpoint
            project.onboarding_status = ProjectOnboardingStatus.PR_PENDING
            project.onboarding_reasons = ["Bootstrap PR awaits human review and merge."]
            project.updated_at = utc_now()
            self.uow.projects.save(project)
            self.uow.commit()
            return {"project_id": project.project_id, "onboarding_status": project.onboarding_status.value, "checkpoint": ProjectService.public_onboarding_state(project)["checkpoint"]}
        finally:
            self._git(binding.managed_repository_root, "worktree", "remove", "--force", str(worktree), check=False)

    def _run_thinking_agent(self, project: Project, worktree: Path, profile: Any, timeout_seconds: int) -> None:
        instruction = (
            "Organize only the supplied context files under the repository. Preserve source provenance, "
            "create navigable context documentation and links from AGENTS.md and openspec/config.yaml, "
            "record unresolved contradictions with both source paths, and never invent requirements, "
            "decisions, OpenSpec artifacts or product claims. Use the installed official OpenSpec setup."
        )
        if self.thinking_agent is not None:
            result = asyncio.run(self.thinking_agent.run(worktree, instruction, timeout_seconds))
        else:
            invocation = resolve_cli_invocation(profile.agent_id, "implementer", model=profile.model_id, effort=profile.effort)
            result = asyncio.run(CliImplementerRunner(invocation).run(worktree, instruction, timeout_seconds))
        if result.exit_code != 0 or result.timed_out:
            raise GreenfieldBootstrapError("Thinking agent did not complete successfully")

    @staticmethod
    def _thinking_profile(project: Project) -> Any:
        raw = project.agent_profiles.get("thinking")
        if not isinstance(raw, dict):
            raise GreenfieldBootstrapError("Thinking profile is not configured")
        from minime.domain.models import ProjectAgentProfile
        return ProjectAgentProfile.model_validate(raw)

    def _validate_thinking_profile(self, profile: Any) -> None:
        if not profile.agent_id or not profile.model_id or not profile.effort:
            raise GreenfieldBootstrapError("Thinking profile lacks executable capability metadata")
        if profile.agent_id.lower() not in {"codex", "antigravity", "agy"}:
            raise GreenfieldBootstrapError("Greenfield thinking requires a supported file-capable CLI agent")

    @staticmethod
    def _selected_agents(project: Project) -> list[str]:
        return sorted({str(value.get("agent_id", "")).lower() for value in project.agent_profiles.values() if isinstance(value, dict) and value.get("agent_id")})

    def _configured_root(self, project: Project) -> str | None:
        if self.trusted_managed_root is None:
            raise GreenfieldBootstrapError("A trusted managed repository root is required for Greenfield bootstrap")
        return str(self.trusted_managed_root / project.project_id)

    @staticmethod
    def _worktree_path(binding: Any, branch: str) -> str:
        safe = branch.replace("/", "-")
        return str(Path(binding.worktree_parent_dir) / safe)

    @staticmethod
    def _assert_not_main(branch: str, base_branch: str) -> None:
        if branch == base_branch or branch in {"main", "master"}:
            raise GreenfieldBootstrapError("Bootstrap writes to the configured base branch are forbidden")

    @staticmethod
    def _git(cwd: str, *args: str, check: bool = True) -> str:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
        if check and result.returncode:
            raise GreenfieldBootstrapError("Git bootstrap operation failed")
        return result.stdout.strip()

    @staticmethod
    def _validate_candidate(worktree: Path, incoming: Path) -> None:
        if not incoming.is_dir() or not any(incoming.rglob("*")):
            raise GreenfieldBootstrapError("Validated context package produced no candidate source")
        if (worktree / ".env").exists() or any(path.suffix in {".pem", ".key"} for path in worktree.rglob("*")):
            raise GreenfieldBootstrapError("Candidate contains a secret-bearing file")

    @staticmethod
    def _pr_body(project: Project, base_sha: str, head_sha: str) -> str:
        return f"Greenfield context bootstrap for `{project.project_id}`.\n\nBase SHA: `{base_sha}`\nHead SHA: `{head_sha}`\nHuman merge required; F3 ticket execution is not started."

    def _block(self, project: Project, reason: str) -> None:
        project.onboarding_status = ProjectOnboardingStatus.BLOCKED
        project.onboarding_reasons = [reason]
        project.updated_at = utc_now()
        self.uow.projects.save(project)
        self.uow.commit()
