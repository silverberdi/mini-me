"""Durable Greenfield onboarding coordinator.

This module only coordinates existing project, workspace, OpenSpec and GitHub
adapters.  It does not generate OpenSpec artifacts or replace an agent workflow.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from minime.adapters.openspec import OpenSpecAdapter
from minime.config import resolve_cli_invocation
from minime.domain.enums import ExternalOutcome, ProjectOnboardingStatus, ProjectType
from minime.domain.models import Project, ProjectConfigurationInput, utc_now
from minime.services.agent_confinement import AgentProcessConfinement
from minime.services.context_archive import ContextArchiveExtractor
from minime.services.implementer_runner import CliImplementerRunner, ImplementerResult
from minime.services.project_catalog_service import ProjectCatalogService
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

    THINKING_AGENT_INSTRUCTION = (
        "Organize only the supplied context files under the repository. Preserve source provenance, "
        "create context/INDEX.md as a concise navigation map, classify only evidenced product facts, "
        "requirements, decisions, restrictions, architecture, references, diagrams and assets, and "
        "record source paths in the index. Preserve prior decisions unless a source explicitly marks a "
        "replacement; record unresolved contradictions with both source paths. Link canonical context "
        "from AGENTS.md and openspec/config.yaml. Never invent requirements, decisions, OpenSpec "
        "artifacts or product claims. Use the installed official OpenSpec setup."
    )

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
        # Validate the complete ZIP before creating a row, credential, workspace or branch.
        package_sha = hashlib.sha256(archive).hexdigest() if archive else ""
        existing = self.uow.projects.get_by_id(configuration.project_id)
        if existing is not None:
            checkpoint = existing.onboarding_checkpoint or {}
            if (
                checkpoint.get("source_zip_sha256") == package_sha
                and checkpoint.get("pull_request_url")
                and existing.onboarding_status is ProjectOnboardingStatus.PR_PENDING
            ):
                return {
                    "project_id": existing.project_id,
                    "onboarding_status": existing.onboarding_status.value,
                    "checkpoint": ProjectService.public_onboarding_state(existing)["checkpoint"],
                    "reused": True,
                }
            raise GreenfieldBootstrapError(
                "Project already exists without a safely resumable bootstrap checkpoint"
            )
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
        package_sha = hashlib.sha256(archive).hexdigest() if archive else ""
        pending = project.onboarding_checkpoint.get("pending_context", {})
        if pending.get("source_zip_sha256") == package_sha and pending.get("pull_request_url"):
            return {"project_id": project_id, "pending_context": pending, "reused": True}
        if pending:
            raise GreenfieldBootstrapError("An unmerged incremental context PR is already pending")
        with tempfile.TemporaryDirectory(prefix="minime-context-incremental-", dir=tempfile.gettempdir()) as package_dir:
            extracted = self.extractor.extract(archive, package_dir)
            profile = self._thinking_profile(project)
            self._validate_thinking_profile(profile)
            binding = self.uow.project_managed_repository_bindings.get_by_project_id(project_id)
            workspace = self.projects.verified_managed_workspace_root(project_id)
            if binding is None or workspace is None:
                raise GreenfieldBootstrapError("Prepared project workspace identity is unavailable")
            adapter = self.connections.require_git_pr_write(project)
            self._git(str(workspace), "fetch", "origin", project.base_branch)
            base_sha = self._git(str(workspace), "rev-parse", f"origin/{project.base_branch}")
            branch = f"minime/context/{project_id}-{extracted.sha256[:12]}"
            self._assert_not_main(branch, project.base_branch)
            reconciled = self._reconcile_incremental_pr(
                project, adapter, branch, base_sha, extracted.sha256
            )
            if reconciled is not None:
                return reconciled
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
                context_delta = self._context_delta(worktree, extracted.files, package_dir)
                result = self._run_thinking_agent(project, worktree, profile, timeout_seconds)
                self._validate_candidate(worktree, incoming, extracted.files, Path(package_dir))
                self._validate_official_workspace(worktree)
                self._git(str(worktree), "add", "--all")
                self._git(str(worktree), "commit", "-m", "docs: add project context")
                head_sha = self._git(str(worktree), "rev-parse", "HEAD")
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
                    "context_branch": branch,
                    "bootstrap_branch": branch,
                    "base_sha": base_sha,
                    "head_sha": head_sha,
                    "pull_request_number": pr.data.get("number"),
                    "pull_request_url": pr.data.get("url"),
                    "agent_exit_code": result.exit_code,
                    "agent_duration_ms": result.duration_ms,
                    "agent_workflow_evidence": result.native_workflow_evidence or {},
                    "context_delta": context_delta,
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
        self._validate_official_capabilities(project)
        git_adapter = self.connections.require_git_pr_write(project)
        self._preflight_workspace_identity(project)
        # Prove the Git/PR grant and materialize a missing requested base branch
        # before the guarded local clone attempts to check it out.
        self._ensure_base_branch(project, git_adapter)
        # Reuse the existing guarded repository establishment and managed binding.
        self.onboarding.onboard_project(
            project,
            operator_email=operator_email,
            discover_context=False,
            managed_repository_root=self._configured_root(project),
        )
        project = self.uow.projects.get_by_id(project.project_id)
        if project is None:
            raise GreenfieldBootstrapError("Project disappeared during guarded workspace establishment")
        binding = self.uow.project_managed_repository_bindings.get_by_project_id(project.project_id)
        if binding is None:
            raise GreenfieldBootstrapError("Managed repository binding was not persisted")

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
            result = self._run_thinking_agent(project, worktree, profile, timeout_seconds)
            self._validate_candidate(worktree, incoming, source_files, package_root)
            self._validate_official_workspace(worktree)
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
                "agent_exit_code": result.exit_code,
                "agent_duration_ms": result.duration_ms,
                "agent_workflow_evidence": result.native_workflow_evidence or {},
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

    def _preflight_workspace_identity(self, project: Project) -> None:
        """Prove workspace topology before any branch or filesystem mutation."""
        if self.trusted_managed_root is None:
            raise GreenfieldBootstrapError("A trusted managed repository root is required for Greenfield bootstrap")
        managed_root = (self.trusted_managed_root / project.project_id).resolve()
        worktree_parent = managed_root / ".minime" / "worktrees"
        runtime_root = Path(AgentProcessConfinement.resolve_runtime_root()).resolve()

        def inside(path: Path, parent: Path) -> bool:
            try:
                path.relative_to(parent)
                return True
            except ValueError:
                return False

        if inside(managed_root, runtime_root) or inside(runtime_root, managed_root):
            raise GreenfieldBootstrapError("Managed workspace overlaps the runtime root")
        if not inside(managed_root, self.trusted_managed_root) or not inside(
            worktree_parent, self.trusted_managed_root
        ):
            raise GreenfieldBootstrapError("Managed workspace lies outside the trusted repository root")

    def _reconcile_incremental_pr(
        self, project: Project, adapter: Any, branch: str, base_sha: str, source_zip_sha256: str
    ) -> dict[str, Any] | None:
        """Reuse an already published PR before any repeated agent invocation."""
        lookup = getattr(adapter, "get_pull_request", None)
        if lookup is None:
            raise GreenfieldBootstrapError("Git/PR adapter cannot reconcile incremental PRs")
        result = lookup(project.provider_connections["git_pr"]["repository_url"], branch, project.base_branch)
        if result.outcome in {ExternalOutcome.UNKNOWN, ExternalOutcome.AMBIGUOUS}:
            raise GreenfieldBootstrapError("Incremental PR identity is unobservable; retry is blocked")
        if result.outcome != ExternalOutcome.SUCCESS or not isinstance(result.data, dict):
            return None
        data = result.data
        head_sha = data.get("head_sha")
        if not head_sha:
            raise GreenfieldBootstrapError("Existing incremental PR has no observable head SHA")
        pending = {
            "source_zip_sha256": source_zip_sha256,
            "context_branch": branch,
            "bootstrap_branch": branch,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "base_branch": project.base_branch,
            "pull_request_number": data.get("number"),
            "pull_request_url": data.get("url"),
            "reconciled": True,
        }
        if not pending["pull_request_number"] or not pending["pull_request_url"]:
            raise GreenfieldBootstrapError("Existing incremental PR identity is incomplete")
        project.onboarding_checkpoint = {
            **project.onboarding_checkpoint,
            "pending_context": pending,
        }
        project.updated_at = utc_now()
        self.uow.projects.save(project)
        self.uow.commit()
        return {"project_id": project.project_id, "pending_context": pending, "reused": True}

    def _run_thinking_agent(
        self, project: Project, worktree: Path, profile: Any, timeout_seconds: int
    ) -> ImplementerResult:
        if self.thinking_agent is not None:
            result = asyncio.run(
                self.thinking_agent.run(worktree, self.THINKING_AGENT_INSTRUCTION, timeout_seconds)
            )
        else:
            invocation = resolve_cli_invocation(profile.agent_id, "implementer", model=profile.model_id, effort=profile.effort)
            result = asyncio.run(
                CliImplementerRunner(invocation).run(
                    worktree, self.THINKING_AGENT_INSTRUCTION, timeout_seconds
                )
            )
        if result.exit_code != 0 or result.timed_out:
            raise GreenfieldBootstrapError("Thinking agent did not complete successfully")
        return result

    def _validate_official_capabilities(self, project: Project) -> None:
        try:
            asyncio.run(ProjectCatalogService().validate_project_profiles(project.agent_profiles))
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            raise GreenfieldBootstrapError(
                "Selected agent capabilities or official OpenSpec integration are unavailable"
            ) from exc

    def _validate_official_workspace(self, worktree: Path) -> None:
        evidence = self.openspec.validate_workspace(worktree)
        if evidence.get("status") != "PASS":
            raise GreenfieldBootstrapError(
                "Official OpenSpec workspace validation was not proven"
            )

    def _ensure_base_branch(self, project: Project, adapter: Any) -> None:
        repository = project.provider_connections["git_pr"]["repository_url"]
        current = adapter.get_repository_branch_head(repository, project.base_branch)
        if current.outcome is ExternalOutcome.SUCCESS and current.data:
            return
        default = adapter.get_repository_default_branch(repository)
        if default.outcome is not ExternalOutcome.SUCCESS or not default.data:
            raise GreenfieldBootstrapError("Configured base branch is absent and remote default is unobservable")
        default_head = adapter.get_repository_branch_head(repository, str(default.data))
        if default_head.outcome is not ExternalOutcome.SUCCESS or not default_head.data:
            raise GreenfieldBootstrapError("Remote default branch has no provable base commit")
        created = adapter.create_remote_branch(repository, project.base_branch, str(default_head.data))
        if created.outcome is not ExternalOutcome.SUCCESS or created.data != default_head.data:
            raise GreenfieldBootstrapError("Requested base branch could not be created from the remote default")

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
    def _validate_candidate(
        worktree: Path,
        incoming: Path,
        source_files: tuple[str, ...] = (),
        package_root: Path | None = None,
    ) -> None:
        if not incoming.is_dir() or not any(incoming.rglob("*")):
            raise GreenfieldBootstrapError("Validated context package produced no candidate source")
        if package_root is not None:
            for relative in source_files:
                source = package_root / relative
                copied = incoming / relative
                if not source.is_file() or not copied.is_file():
                    raise GreenfieldBootstrapError("Context provenance is incomplete")
                if GreenfieldBootstrapCoordinator._sha256(source) != GreenfieldBootstrapCoordinator._sha256(copied):
                    raise GreenfieldBootstrapError("Context source fidelity check failed")

        secret_names = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
        secret_suffixes = {".pem", ".key", ".p12", ".pfx"}
        canonical_agents = worktree / "AGENTS.md"
        canonical_config = worktree / "openspec" / "config.yaml"
        if not canonical_agents.is_file() or not canonical_config.is_file():
            raise GreenfieldBootstrapError("Official OpenSpec context anchors are missing")
        context_index = worktree / "context" / "INDEX.md"
        if package_root is not None and not context_index.is_file():
            raise GreenfieldBootstrapError("Thinking agent context index is missing")
        GreenfieldBootstrapCoordinator._validate_candidate_scope(worktree)
        for path in worktree.rglob("*"):
            if path.is_symlink():
                try:
                    path.resolve().relative_to(worktree.resolve())
                except ValueError as exc:
                    raise GreenfieldBootstrapError("Candidate contains an out-of-root link") from exc
            if not path.is_file():
                continue
            if path.name in secret_names or path.suffix.lower() in secret_suffixes:
                raise GreenfieldBootstrapError("Candidate contains a secret-bearing file")
            if path.name == "AGENTS.md" or path == canonical_config:
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if "context/" not in text and (path.name == "AGENTS.md" or path == canonical_config):
                    raise GreenfieldBootstrapError("Canonical context reference is missing")
            if path.suffix.lower() in {".md", ".yaml", ".yml"}:
                GreenfieldBootstrapCoordinator._validate_repository_links(path, worktree)

        if package_root is not None:
            index_text = context_index.read_text(encoding="utf-8")
            missing_sources = [relative for relative in source_files if relative not in index_text]
            if missing_sources:
                raise GreenfieldBootstrapError("Context index omits source provenance")

        for path in worktree.rglob("*"):
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_000_000:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(marker in text for marker in ("BEGIN PRIVATE KEY", "AWS_SECRET_ACCESS_KEY", "ghp_")):
                raise GreenfieldBootstrapError("Candidate contains a secret marker")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _validate_repository_links(path: Path, worktree: Path) -> None:
        for raw_target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = raw_target.strip().split("#", 1)[0].split("?", 1)[0].strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            candidate = (path.parent / target).resolve()
            try:
                candidate.relative_to(worktree.resolve())
            except ValueError as exc:
                raise GreenfieldBootstrapError("Context reference escapes the repository") from exc
            if not candidate.exists():
                raise GreenfieldBootstrapError("Context reference points to a missing file")

    @staticmethod
    def _validate_candidate_scope(worktree: Path) -> None:
        """Keep the organization agent inside the documentary/configuration surface."""
        changed = subprocess.run(
            ["git", "diff", "--name-only"], cwd=worktree, capture_output=True, text=True, check=False
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        if changed.returncode != 0 or untracked.returncode != 0:
            return
        paths = set(changed.stdout.splitlines()) | set(untracked.stdout.splitlines())
        def allowed(path: str) -> bool:
            return (
                path == "AGENTS.md"
                or path in {".agents/AGENTS.md", ".agent/AGENTS.md", "openspec/config.yaml"}
                or path.startswith(("context/", ".agents/skills/openspec-", ".agent/workflows/opsx-"))
            )
        unrelated = sorted(path for path in paths if path and not allowed(path))
        if unrelated:
            raise GreenfieldBootstrapError("Candidate contains unrelated or backlog-like changes")

    @staticmethod
    def _context_delta(worktree: Path, source_files: tuple[str, ...], package_root: Path) -> dict[str, list[str]]:
        """Classify incoming paths without overwriting approved context."""
        additions: list[str] = []
        replacements: list[str] = []
        for relative in source_files:
            incoming = package_root / relative
            approved = worktree / "context" / relative
            if approved.is_file() and GreenfieldBootstrapCoordinator._sha256(approved) != GreenfieldBootstrapCoordinator._sha256(incoming):
                replacements.append(relative)
            else:
                additions.append(relative)
        return {"additions": additions, "replacement_candidates": replacements}

    @staticmethod
    def _pr_body(project: Project, base_sha: str, head_sha: str) -> str:
        return f"Greenfield context bootstrap for `{project.project_id}`.\n\nBase SHA: `{base_sha}`\nHead SHA: `{head_sha}`\nHuman merge required; F3 ticket execution is not started."

    def _block(self, project: Project, reason: str) -> None:
        project.onboarding_status = ProjectOnboardingStatus.BLOCKED
        project.onboarding_reasons = [reason]
        project.updated_at = utc_now()
        self.uow.projects.save(project)
        self.uow.commit()
