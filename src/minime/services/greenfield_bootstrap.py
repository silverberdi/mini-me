"""Durable Greenfield onboarding coordinator.

This module only coordinates existing project, workspace, OpenSpec and GitHub
adapters.  It does not generate OpenSpec artifacts or replace an agent workflow.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from minime.adapters.openspec import OpenSpecAdapter
from minime.config import resolve_cli_invocation
from minime.domain.enums import (
    ExternalOutcome,
    ExternalReasonCode,
    ProjectOnboardingStatus,
    ProjectType,
)
from minime.domain.models import Project, ProjectConfigurationInput, utc_now
from minime.logging import redact_secrets
from minime.services.agent_confinement import AgentProcessConfinement
from minime.services.capability_manifest import CapabilityManifestService
from minime.services.context_archive import ContextArchiveExtractor
from minime.services.implementer_runner import CliImplementerRunner, ImplementerResult
from minime.services.project_catalog_service import ProjectCatalogService
from minime.services.project_connection_service import ProjectConnectionService
from minime.services.project_context_catalog import (
    CONTEXT_DOCUMENT_PATHS,
    catalog_instruction,
    generated_context_path_allowed,
    has_substantive_content,
    populated_catalog_documents,
)
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
        "F2 CONTEXT ORGANIZER ONLY. Read ALL original files at context/incoming/<zip-sha>/, "
        "including documents, diagrams and admitted assets. Build the project's documentary "
        "context by extracting and writing source-supported information into the predefined "
        "canonical Markdown files below. This catalog is FIXED: do not invent new section "
        "folders, generated document filenames, code, OpenSpec proposals/specs/tasks, or "
        "an operational backlog. Every generated document must contain useful substance "
        "drawn from supplied sources; omit documents for which evidence is absent (empty "
        "files are acceptable but must never be linked in indexes). Summarize, synthesize, "
        "reword and organize faithfully, without adding requirements, product decisions, "
        "dates or implementation approaches. A fact may appear in MULTIPLE applicable "
        "documents when needed for each to stand alone; avoid artificial de-duplication. "
        "Business intent described by sources is the main organizing reference; do not "
        "reinterpret the product's direction. A roadmap or historical backlog in the ZIP "
        "is DOCUMENTARY INPUT only. If sufficiently documented, place roadmap information "
        "in 12-planificacion/roadmap-documentado.md or historical planning in "
        "12-planificacion/antecedentes-de-planificacion.md; never convert backlog items "
        "into actionable work, task lists or GitHub Issues. Keep the input files unchanged "
        "at context/incoming/<zip-sha>/. Create context/INDEX.md as a navigable map of "
        "ONLY substantively populated canonical files, using Markdown links relative "
        "to context/ (e.g. 01-negocio/intencion-de-negocio.md); do not link empty or "
        "placeholder documents. Link original sources relative to the current index "
        "(incoming/<sha>/file from context/INDEX.md, ../incoming/<sha>/file from "
        "context/fuentes/INDEX.md). Also index EVERY source path under context/incoming/ "
        "(directly or via populated fuentes/INDEX.md). Each derived file should cite "
        "its original source paths and may merge information from multiple sources. "
        "Keep OpenSpec's official installed integrations unchanged. Link context/INDEX.md "
        "from AGENTS.md and openspec/config.yaml without overwriting compatible content. "
        "Do NOT audit business quality, validate requirements, resolve contradictions, "
        "infer missing details or initiate development.\n\n"
        + catalog_instruction()
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
        capability_manifest: CapabilityManifestService | None = None,
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
        self.capability_manifest = capability_manifest or CapabilityManifestService()
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
        authorization: dict[str, Any] | None = None,
        timeout_seconds: int = 1_800,
    ) -> dict[str, Any]:
        """Publish one incremental context PR without changing approved context."""
        project = self.uow.projects.get_by_id(project_id)
        if project is None:
            raise GreenfieldBootstrapError("Project not found")
        if project.onboarding_status is not ProjectOnboardingStatus.PREPARED:
            raise GreenfieldBootstrapError("Incremental context requires a prepared project")
        package_sha = hashlib.sha256(archive).hexdigest() if archive else ""
        if authorization is not None:
            self.reserve_incremental_authorization(project_id, package_sha, authorization)
        else:
            pending_authorization = (project.onboarding_checkpoint or {}).get(
                "pending_incremental_authorization"
            )
            if isinstance(pending_authorization, dict) and pending_authorization.get(
                "source_zip_sha256"
            ) != package_sha:
                raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_ZIP_MISMATCH")
        retained = project.onboarding_checkpoint.get("candidate_recovery")
        if isinstance(retained, dict) and retained.get("status") == "QUARANTINED_REVIEW_REQUIRED":
            raise GreenfieldBootstrapError(
                "A previous candidate is quarantined for review; no new model invocation is allowed"
            )
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
            self._git(
                str(workspace),
                "fetch",
                "origin",
                project.base_branch,
                env=self._git_auth_environment(adapter, project),
            )
            base_sha = self._git(str(workspace), "rev-parse", f"origin/{project.base_branch}")
            branch = f"minime/context/{project_id}-{extracted.sha256[:12]}"
            self._assert_not_main(branch, project.base_branch)
            reconciled = self._reconcile_incremental_pr(
                project, adapter, branch, base_sha, extracted.sha256
            )
            if reconciled is not None:
                return reconciled
            worktree = Path(self._worktree_path(binding, branch))
            self._prepare_local_branch(binding.managed_repository_root, branch, base_sha)
            self._git(str(workspace), "worktree", "add", "--detach", str(worktree), base_sha)
            agent_started = False
            preserve_candidate = False
            try:
                self._git(str(worktree), "checkout", "-b", branch)
                self.openspec.install_official_integrations(
                    worktree, self._selected_agents(project, roles=("thinking",))
                )
                incoming = worktree / "context" / "incoming" / extracted.sha256
                incoming.mkdir(parents=True, mode=0o700)
                for relative in extracted.files:
                    source = Path(package_dir) / relative
                    target = incoming / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    target.chmod(0o600)
                context_delta = self._context_delta(worktree, extracted.files, Path(package_dir))
                self._validate_candidate_scope(worktree)
                agent_started = True
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
                    "base_branch": project.base_branch,
                    "head_sha": head_sha,
                    "pull_request_number": pr.data.get("number"),
                    "pull_request_url": pr.data.get("url"),
                    "agent_exit_code": result.exit_code,
                    "agent_duration_ms": result.duration_ms,
                    "agent_workflow_evidence": result.native_workflow_evidence or {},
                    "context_delta": context_delta,
                }
                current = self.uow.projects.get_by_id(project.project_id) or project
                current.onboarding_checkpoint = {
                    **(current.onboarding_checkpoint or {}),
                    "pending_context": pending,
                }
                current.updated_at = utc_now()
                self.uow.projects.save(current)
                self.uow.commit()
                return {"project_id": project_id, "pending_context": pending, "reused": False}
            except Exception as exc:
                if agent_started:
                    preserve_candidate = True
                    self._retain_candidate_for_recovery(project, worktree, branch, base_sha, exc)
                raise
            finally:
                if not preserve_candidate:
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
        # Greenfield executes only the configured thinking role. Other roles
        # remain durable configuration for later stages and must not be invoked
        # or require an authenticated account during bootstrap.
        self._validate_official_capabilities(project, roles=("thinking",))
        git_adapter = self.connections.require_git_pr_write(project)
        if hasattr(self.onboarding, "github_adapter"):
            self.onboarding.github_adapter = git_adapter
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
        self._git(
            binding.managed_repository_root,
            "fetch",
            "origin",
            project.base_branch,
            env=self._git_auth_environment(git_adapter, project),
        )
        base_sha = self._git(
            binding.managed_repository_root, "rev-parse", f"origin/{project.base_branch}"
        )
        self._prepare_local_branch(binding.managed_repository_root, branch, base_sha)
        self._git(binding.managed_repository_root, "worktree", "add", "--detach", self._worktree_path(binding, branch), base_sha)
        worktree = Path(self._worktree_path(binding, branch))
        agent_started = False
        preserve_candidate = False
        try:
            self._git(str(worktree), "checkout", "-b", branch)
            self.openspec.install_official_integrations(
                worktree, self._selected_agents(project)
            )
            capability_evidence = self.capability_manifest.install_greenfield(
                self.project_root,
                worktree,
                profiles=self._selected_profiles(project),
            )
            official_openspec = self.openspec.inspect_integrations(
                worktree, self._selected_agents(project)
            )
            readiness = self.capability_manifest.validate_f5_readiness(
                capability_evidence,
                official_openspec,
                project_type=project.project_type.value,
                profiles_observed=bool(project.agent_profiles),
                worktree_identity_verified=binding.managed_repository_root == self._configured_root(project),
                confinement_verified=True,
                github_binding_verified=bool(binding.canonical_repository_identity),
            )
            incoming = worktree / "context" / "incoming" / project.onboarding_checkpoint["source_zip_sha256"]
            incoming.mkdir(parents=True, mode=0o700)
            for relative in source_files:
                source = package_root / relative
                target = incoming / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                target.chmod(0o600)
            # The official initializer and source import must satisfy scope
            # BEFORE any quota-bearing invocation. Never discover a predictable
            # setup artifact conflict after the agent has already consumed tokens.
            allowed_paths = self._candidate_allowed_paths(
                worktree, capability_evidence, official_openspec
            )
            self._validate_candidate_scope(worktree, allowed_paths=allowed_paths)
            agent_started = True
            result = self._run_thinking_agent(project, worktree, profile, timeout_seconds)
            self._validate_candidate(
                worktree,
                incoming,
                source_files,
                package_root,
                allowed_paths=allowed_paths,
            )
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
            current = self.uow.projects.get_by_id(project.project_id) or project
            checkpoint = {
                **(current.onboarding_checkpoint or {}),
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
                "f4_capability_manifest": capability_evidence,
                "f5_readiness": readiness,
            }
            current.onboarding_checkpoint = checkpoint
            current.onboarding_status = ProjectOnboardingStatus.PR_PENDING
            current.onboarding_reasons = ["Bootstrap PR awaits human review and merge."]
            current.updated_at = utc_now()
            self.uow.projects.save(current)
            self.uow.commit()
            return {
                "project_id": current.project_id,
                "onboarding_status": current.onboarding_status.value,
                "checkpoint": ProjectService.public_onboarding_state(current)["checkpoint"],
            }
        except Exception as exc:
            if agent_started:
                # A completed paid inference must never be destroyed by a
                # deterministic validation failure. Keep its worktree private;
                # the blocked project must be reconciled before any replay.
                preserve_candidate = True
                self._retain_candidate_for_recovery(project, worktree, branch, base_sha, exc)
            raise
        finally:
            if not preserve_candidate:
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

    def reconcile_blocked_bootstrap(
        self, project_id: str, authorization: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Inspect a blocked bootstrap without dispatching an agent or mutating GitHub."""
        project = self.uow.projects.get_by_id(project_id)
        if project is None:
            raise GreenfieldBootstrapError("Project not found")
        if project.onboarding_status is not ProjectOnboardingStatus.BLOCKED:
            return {
                "project_id": project_id,
                "onboarding_status": project.onboarding_status.value,
                "safe_to_resume": False,
                "reason": "project_is_not_blocked",
            }

        checkpoint = project.onboarding_checkpoint or {}
        retained = checkpoint.get("candidate_recovery")
        if isinstance(retained, dict) and retained.get("status") == "QUARANTINED_REVIEW_REQUIRED":
            return {
                "project_id": project_id,
                "onboarding_status": project.onboarding_status.value,
                "safe_to_resume": False,
                "reason": "CANDIDATE_QUARANTINED_REVIEW_REQUIRED",
            }
        attempt = checkpoint.get("thinking_agent_attempt")
        pre_dispatch = not isinstance(attempt, dict)
        if not isinstance(attempt, dict):
            attempt = {}
        authorization_error = self._retry_authorization_error(project, authorization)
        authorized_unknown = authorization is not None and authorization_error is None
        if pre_dispatch and not authorized_unknown:
            reason = "NO_AGENT_ATTEMPT_RECORDED_PRE_DISPATCH"
        elif (
            attempt.get("status") != "FAILED"
            or attempt.get("usage_status") != "OBSERVED"
        ) and not authorized_unknown:
            reason = "THINKING_AGENT_CONSUMPTION_UNKNOWN"
        else:
            reason = "THINKING_AGENT_RETRY_REQUIRES_EXPLICIT_AUTHORIZATION"
        if authorization is not None and authorization_error is not None:
            reason = authorization_error

        branch = None
        source_sha = checkpoint.get("source_zip_sha256")
        if isinstance(source_sha, str) and len(source_sha) == 64:
            branch = f"minime/bootstrap/{project_id}-{source_sha[:12]}"
        evidence: dict[str, Any] = {
            "status": "RECONCILIATION_REQUIRED",
            "reason": reason,
            "checked_at": utc_now().isoformat(),
            "safe_to_resume": False,
        }
        if branch:
            evidence["bootstrap_branch"] = branch
        try:
            adapter = self.connections.require_git_pr_write(project)
            repository = project.provider_connections["git_pr"]["repository_url"]
            remote_branch_head = getattr(adapter, "get_repository_branch_head", None)
            if not callable(remote_branch_head):
                remote_branch_head = adapter.get_remote_branch_head
            base_result = remote_branch_head(repository, project.base_branch)
            if base_result.outcome in {ExternalOutcome.UNKNOWN, ExternalOutcome.AMBIGUOUS}:
                evidence["reason"] = "BOOTSTRAP_BASE_UNOBSERVABLE"
            elif base_result.outcome is not ExternalOutcome.SUCCESS or not base_result.data:
                evidence["reason"] = "BOOTSTRAP_BASE_UNAVAILABLE"
            else:
                evidence["base_sha"] = base_result.data
                if authorized_unknown:
                    expected_base = authorization.get("base_sha") if authorization else None
                    if expected_base != base_result.data:
                        evidence["reason"] = "BOOTSTRAP_BASE_SHA_MISMATCH"
            branch_result = remote_branch_head(repository, branch) if branch else None
            if evidence["reason"] not in {
                "BOOTSTRAP_BASE_UNOBSERVABLE",
                "BOOTSTRAP_BASE_UNAVAILABLE",
                "BOOTSTRAP_BASE_SHA_MISMATCH",
            } and branch_result is not None and branch_result.outcome in {
                ExternalOutcome.UNKNOWN,
                ExternalOutcome.AMBIGUOUS,
            }:
                evidence["reason"] = "BOOTSTRAP_BRANCH_UNOBSERVABLE"
            elif (
                evidence["reason"] not in {
                    "BOOTSTRAP_BASE_UNOBSERVABLE",
                    "BOOTSTRAP_BASE_UNAVAILABLE",
                    "BOOTSTRAP_BASE_SHA_MISMATCH",
                }
                and branch_result is not None
                and branch_result.outcome is ExternalOutcome.SUCCESS
                and branch_result.data
            ):
                evidence.update(
                    {
                        "remote_branch_sha": branch_result.data,
                        "reason": "BOOTSTRAP_BRANCH_ALREADY_EXISTS",
                    }
                )
            elif (
                evidence["reason"] not in {
                    "BOOTSTRAP_BASE_UNOBSERVABLE",
                    "BOOTSTRAP_BASE_UNAVAILABLE",
                    "BOOTSTRAP_BASE_SHA_MISMATCH",
                }
                and branch_result is not None
                and branch_result.outcome is not ExternalOutcome.SUCCESS
                and getattr(branch_result, "reason_code", None) is not ExternalReasonCode.NOT_FOUND
            ):
                evidence["reason"] = "BOOTSTRAP_BRANCH_EFFECT_UNCERTAIN"
            elif branch:
                pr_result = adapter.get_pull_request(repository, branch, project.base_branch)
                if pr_result.outcome in {ExternalOutcome.UNKNOWN, ExternalOutcome.AMBIGUOUS}:
                    evidence["reason"] = "BOOTSTRAP_PR_UNOBSERVABLE"
                elif pr_result.outcome is ExternalOutcome.SUCCESS:
                    evidence.update(
                        {
                            "pull_request": pr_result.data or {},
                            "reason": "BOOTSTRAP_PR_ALREADY_EXISTS",
                        }
                    )
                elif getattr(pr_result, "reason_code", None) is not ExternalReasonCode.NOT_FOUND:
                    evidence["reason"] = "BOOTSTRAP_PR_EFFECT_UNCERTAIN"
                elif (
                    evidence["reason"] == "THINKING_AGENT_RETRY_REQUIRES_EXPLICIT_AUTHORIZATION"
                    or evidence["reason"] == "NO_AGENT_ATTEMPT_RECORDED_PRE_DISPATCH"
                    or authorized_unknown
                ):
                    workspace = self.projects.verified_managed_workspace_root(project_id)
                    if workspace is None:
                        evidence["reason"] = "MANAGED_WORKSPACE_UNAVAILABLE"
                    else:
                        status = subprocess.run(
                            ["git", "status", "--porcelain"],
                            cwd=str(workspace),
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        dirty = [
                            line
                            for line in status.stdout.splitlines()
                            if line.strip() and ".minime-managed-project.json" not in line
                        ]
                        if status.returncode != 0:
                            evidence["reason"] = "MANAGED_WORKSPACE_STATUS_UNOBSERVABLE"
                        elif dirty:
                            evidence["reason"] = "MANAGED_WORKSPACE_HAS_UNRECONCILED_CHANGES"
                        else:
                            evidence["safe_to_resume"] = True
                            evidence["reason"] = (
                                "NO_REMOTE_EFFECT_OBSERVED_PRE_DISPATCH"
                                if evidence["reason"] == "NO_AGENT_ATTEMPT_RECORDED_PRE_DISPATCH"
                                else "NO_REMOTE_EFFECT_OBSERVED_EXPLICIT_AUTHORIZATION_REQUIRED"
                            )
        except Exception:
            evidence["reason"] = "BOOTSTRAP_RECONCILIATION_UNOBSERVABLE"

        current = self.uow.projects.get_by_id(project_id) or project
        current.onboarding_checkpoint = {
            **(current.onboarding_checkpoint or {}),
            "bootstrap_recovery": evidence,
        }
        current.updated_at = utc_now()
        self.uow.projects.save(current)
        self.uow.commit()
        return {"project_id": project_id, **evidence}

    @staticmethod
    def _retry_authorization_error(
        project: Project, authorization: dict[str, Any] | None
    ) -> str | None:
        if authorization is None:
            return "THINKING_AGENT_RETRY_REQUIRES_EXPLICIT_AUTHORIZATION"
        required = {
            "authorization_reference",
            "project_id",
            "source_zip_sha256",
            "repository",
            "base_branch",
            "base_sha",
            "purpose",
            "max_new_invocations",
            "single_use",
        }
        if not required.issubset(authorization):
            return "RETRY_AUTHORIZATION_INCOMPLETE"
        if authorization.get("project_id") != project.project_id:
            return "RETRY_AUTHORIZATION_PROJECT_MISMATCH"
        if authorization.get("repository") != project.repository:
            return "RETRY_AUTHORIZATION_REPOSITORY_MISMATCH"
        checkpoint = project.onboarding_checkpoint or {}
        if authorization.get("source_zip_sha256") != checkpoint.get("source_zip_sha256"):
            return "RETRY_AUTHORIZATION_ZIP_MISMATCH"
        if authorization.get("base_branch") != project.base_branch:
            return "RETRY_AUTHORIZATION_BRANCH_MISMATCH"
        if authorization.get("purpose") != "PRIOR_USAGE_UNRECOVERABLE":
            return "RETRY_AUTHORIZATION_PURPOSE_INVALID"
        if authorization.get("max_new_invocations") != 1 or authorization.get("single_use") is not True:
            return "RETRY_AUTHORIZATION_SCOPE_INVALID"
        prior = checkpoint.get("thinking_agent_retry_authorization")
        if isinstance(prior, dict) and prior.get("used") is True:
            same_grant = (
                str(prior.get("authorization_reference", "")).strip()
                == str(authorization.get("authorization_reference", "")).strip()
            )
            # A distinct, explicitly supplied human authorization is a new
            # single-use grant.  Only replay of the exact prior grant is
            # forbidden; an earlier UNKNOWN attempt must remain preserved.
            if not same_grant:
                prior = None
        if isinstance(prior, dict) and prior.get("used") is True:
            recovery = checkpoint.get("bootstrap_recovery")
            # 6871e3d reserved the grant before branch checkout. If that
            # reservation has no persisted agent attempt and the preceding
            # reconciliation proved no remote effect, it was pre-dispatch and
            # can be reconciled once without treating it as model usage.
            pre_dispatch = (
                not isinstance(checkpoint.get("thinking_agent_attempt"), dict)
                and isinstance(recovery, dict)
                and recovery.get("safe_to_resume") is True
            )
            if not pre_dispatch:
                return "RETRY_AUTHORIZATION_ALREADY_USED"
        if not str(authorization.get("authorization_reference", "")).strip():
            return "RETRY_AUTHORIZATION_REFERENCE_MISSING"
        return None

    def resume_blocked_bootstrap(
        self,
        project_id: str,
        archive: bytes,
        *,
        authorization: dict[str, Any] | None = None,
        operator_email: str = "operator",
        timeout_seconds: int = 1_800,
    ) -> dict[str, Any]:
        """Resume a reconciled failed attempt only after explicit authorization."""
        project = self.uow.projects.get_by_id(project_id)
        if project is None:
            raise GreenfieldBootstrapError("Project not found")
        pre_dispatch = not isinstance(
            (project.onboarding_checkpoint or {}).get("thinking_agent_attempt"), dict
        )
        authorization_error = (
            None if pre_dispatch and authorization is None
            else self._retry_authorization_error(project, authorization)
        )
        if authorization_error is not None:
            raise GreenfieldBootstrapError(authorization_error)
        reconciliation = self.reconcile_blocked_bootstrap(project_id, authorization)
        if not reconciliation.get("safe_to_resume"):
            raise GreenfieldBootstrapError(
                f"Blocked bootstrap cannot resume safely: {reconciliation.get('reason')}"
            )
        with tempfile.TemporaryDirectory(
            prefix="minime-context-resume-", dir=tempfile.gettempdir()
        ) as package_dir:
            extracted = self.extractor.extract(archive, package_dir)
            if extracted.sha256 != project.onboarding_checkpoint.get("source_zip_sha256"):
                raise GreenfieldBootstrapError("Recovery ZIP does not match the blocked bootstrap revision")
            project.onboarding_checkpoint = {
                **project.onboarding_checkpoint,
                "previous_thinking_agent_attempt": project.onboarding_checkpoint.get(
                    "thinking_agent_attempt"
                ),
                "pending_thinking_agent_retry_authorization": authorization,
            }
            project.onboarding_status = ProjectOnboardingStatus.BOOTSTRAPPING
            project.onboarding_reasons = [
                "Bootstrap retry explicitly authorized after reconciliation."
            ]
            project.updated_at = utc_now()
            self.uow.projects.save(project)
            self.uow.commit()
            try:
                return self._run_after_project_creation(
                    project,
                    Path(package_dir),
                    extracted.files,
                    operator_email=operator_email,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                self._block(project, f"GREENFIELD_BOOTSTRAP_FAILED:{type(exc).__name__}")
                raise

    def _retain_candidate_for_recovery(
        self, project: Project, worktree: Path, branch: str, base_sha: str, error: Exception
    ) -> None:
        """Seal a failed post-dispatch candidate in the existing managed worktree.

        No automatic replay or GitHub effect is authorized by this marker.
        Content stays private to the managed worktree; only bounded metadata
        reaches PostgreSQL. Do not copy the candidate to a public artifact.
        """
        if self.trusted_managed_root is None or worktree.is_symlink():
            raise GreenfieldBootstrapError(
                "Cannot retain candidate without verified managed-worktree ownership"
            )
        try:
            worktree.resolve(strict=True).relative_to(
                self.trusted_managed_root.resolve(strict=True)
            )
        except (OSError, ValueError) as exc:
            raise GreenfieldBootstrapError(
                "Failed candidate worktree lies outside trusted managed root"
            ) from exc
        current = self.uow.projects.get_by_id(project.project_id) or project
        current.onboarding_checkpoint = {
            **(current.onboarding_checkpoint or {}),
            "candidate_recovery": {
                "status": "QUARANTINED_REVIEW_REQUIRED",
                "worktree": str(worktree),
                "branch": branch,
                "base_sha": base_sha,
                "failure_type": type(error).__name__,
                "preserved_at": utc_now().isoformat(),
            },
        }
        current.updated_at = utc_now()
        self.uow.projects.save(current)
        self.uow.commit()

    def _persist_thinking_attempt(self, project: Project, evidence: dict[str, Any]) -> None:
        """Durably retain bounded agent evidence before the worktree is cleaned up.

        Missing usage is UNKNOWN, never zero; a repeated bootstrap cannot silently
        spend again after the first invocation may have reached the provider.
        """
        current = self.uow.projects.get_by_id(project.project_id) or project
        pending_authorization = current.onboarding_checkpoint.get(
            "pending_thinking_agent_retry_authorization"
        )
        current.onboarding_checkpoint = {
            **(current.onboarding_checkpoint or {}),
            "thinking_agent_attempt": evidence,
        }
        if isinstance(pending_authorization, dict):
            current.onboarding_checkpoint.pop("pending_thinking_agent_retry_authorization", None)
            current.onboarding_checkpoint["thinking_agent_retry_authorization"] = {
                **pending_authorization,
                "used": True,
                "used_at": utc_now().isoformat(),
            }
        pending_incremental = current.onboarding_checkpoint.get(
            "pending_incremental_authorization"
        )
        if isinstance(pending_incremental, dict):
            current.onboarding_checkpoint.pop("pending_incremental_authorization", None)
            current.onboarding_checkpoint["incremental_authorization"] = {
                **pending_incremental,
                "status": "USED",
                "used": True,
                "used_at": utc_now().isoformat(),
            }
        current.updated_at = utc_now()
        self.uow.projects.save(current)
        self.uow.commit()

    @staticmethod
    def _validate_incremental_authorization(
        project: Project, authorization: dict[str, Any], source_zip_sha256: str
    ) -> None:
        required = {
            "authorization_reference",
            "project_id",
            "repository",
            "base_branch",
            "base_sha",
            "source_zip_sha256",
            "agent",
            "model",
            "effort",
            "max_new_invocations",
            "single_use",
            "purpose",
        }
        if not required.issubset(authorization):
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_INCOMPLETE")
        if authorization["project_id"] != project.project_id:
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_PROJECT_MISMATCH")
        if authorization["repository"] != project.repository:
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_REPOSITORY_MISMATCH")
        if authorization["base_branch"] != project.base_branch:
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_BRANCH_MISMATCH")
        checkpoint = project.onboarding_checkpoint or {}
        approved_context_sha = checkpoint.get("approved_context_sha") or checkpoint.get(
            "merge_commit_sha"
        )
        if authorization["base_sha"] != approved_context_sha:
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_BASE_MISMATCH")
        if authorization["source_zip_sha256"] != source_zip_sha256:
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_ZIP_MISMATCH")
        if authorization["agent"] != "codex" or authorization["model"] != "gpt-5.6-luna":
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_AGENT_MISMATCH")
        if authorization["effort"] != "medium":
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_EFFORT_MISMATCH")
        if authorization["max_new_invocations"] != 1 or authorization["single_use"] is not True:
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_SCOPE_INVALID")
        if authorization["purpose"] != "INCREMENTAL_CONTEXT_E2E":
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_PURPOSE_INVALID")
        if not str(authorization["authorization_reference"]).strip():
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_REFERENCE_MISSING")

    def reserve_incremental_authorization(
        self, project_id: str, source_zip_sha256: str, authorization: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist one explicit incremental grant before any external effect."""
        project = self.uow.projects.get_by_id(project_id)
        if project is None:
            raise GreenfieldBootstrapError("Project not found")
        if project.onboarding_status is not ProjectOnboardingStatus.PREPARED:
            raise GreenfieldBootstrapError("Incremental context requires a prepared project")
        self._validate_incremental_authorization(project, authorization, source_zip_sha256)
        checkpoint = project.onboarding_checkpoint or {}
        prior_authorization = checkpoint.get("incremental_authorization")
        pending_authorization = checkpoint.get("pending_incremental_authorization")
        if isinstance(prior_authorization, dict) and prior_authorization.get("used") is True:
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_ALREADY_USED")
        if isinstance(pending_authorization, dict):
            raise GreenfieldBootstrapError("INCREMENTAL_AUTHORIZATION_ALREADY_RESERVED")
        project.onboarding_checkpoint = {
            **checkpoint,
            "pending_incremental_authorization": {
                **authorization,
                "status": "RESERVED",
                "reserved_at": utc_now().isoformat(),
            },
        }
        project.updated_at = utc_now()
        self.uow.projects.save(project)
        self.uow.commit()
        return {
            "project_id": project_id,
            "source_zip_sha256": source_zip_sha256,
            "authorization_reference": authorization["authorization_reference"],
            "status": "RESERVED",
        }

    def _run_thinking_agent(
        self, project: Project, worktree: Path, profile: Any, timeout_seconds: int
    ) -> ImplementerResult:
        attempt: dict[str, Any] = {
            "status": "EXECUTION_UNKNOWN",
            "agent": profile.agent_id,
            "model": profile.model_id,
            "effort": profile.effort,
            "started_at": utc_now().isoformat(),
            "usage_status": "UNKNOWN",
        }
        # Commit the admission marker before any process launch. An exception,
        # cancellation or process loss must never be interpreted as zero spend.
        self._persist_thinking_attempt(project, attempt)
        if self.thinking_agent is not None:
            result = asyncio.run(
                self.thinking_agent.run(worktree, self.THINKING_AGENT_INSTRUCTION, timeout_seconds)
            )
        else:
            invocation = resolve_cli_invocation(
                profile.agent_id, "implementer", model=profile.model_id, effort=profile.effort
            )
            result = asyncio.run(
                CliImplementerRunner(invocation).run(
                    worktree, self.THINKING_AGENT_INSTRUCTION, timeout_seconds
                )
            )
        failed = result.exit_code != 0 or result.timed_out
        reported_usage = (
            result.native_workflow_evidence.get("usage")
            if isinstance(result.native_workflow_evidence, dict)
            else None
        )
        usage_observed = (
            isinstance(reported_usage, dict)
            and all(
                type(reported_usage.get(key)) is int and reported_usage[key] >= 0
                for key in ("input_tokens", "output_tokens")
            )
        )
        diagnostic = {
            **attempt,
            "status": (
                "FAILED" if failed and usage_observed
                else "FAILED_USAGE_UNKNOWN" if failed
                else "SUCCEEDED"
            ),
            "usage_status": "OBSERVED" if usage_observed else "UNKNOWN",
            "usage": reported_usage if usage_observed else None,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_ms": result.duration_ms,
            "preflight_error": (
                redact_secrets(str(result.preflight_error))[:256]
                if result.preflight_error else None
            ),
            "environment_error": result.environment_error,
            "stderr_tail": [
                redact_secrets(str(line))[:512] for line in result.stderr[-5:]
            ],
            "stdout_line_count": len(result.stdout),
            "finished_at": utc_now().isoformat(),
        }
        self._persist_thinking_attempt(project, diagnostic)
        if failed:
            detail = diagnostic["preflight_error"] or (
                diagnostic["stderr_tail"][-1] if diagnostic["stderr_tail"] else "no diagnostic"
            )
            raise GreenfieldBootstrapError(
                f"Thinking agent did not complete successfully (exit={result.exit_code}, "
                f"timed_out={result.timed_out}): {detail}"
            )
        return result

    def _validate_official_capabilities(
        self, project: Project, *, roles: tuple[str, ...] | None = None
    ) -> None:
        try:
            profiles = project.agent_profiles
            if roles is not None:
                profiles = {role: project.agent_profiles[role] for role in roles}
            from minime.domain.models import ProjectAgentProfile

            profiles = {
                role: ProjectAgentProfile.model_validate(profile)
                for role, profile in profiles.items()
            }
            asyncio.run(ProjectCatalogService().validate_project_profiles(profiles))
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
    def _selected_profiles(project: Project) -> dict[str, Any]:
        profiles = project.agent_profiles
        if project.execution_policy.get("fallback_authorized", False):
            return dict(profiles)
        return {role: value for role, value in profiles.items() if role != "fallback"}

    @staticmethod
    def _selected_agents(project: Project, *, roles: tuple[str, ...] | None = None) -> list[str]:
        profiles = project.agent_profiles
        if roles is not None:
            profiles = {role: profiles[role] for role in roles}
        elif not project.execution_policy.get("fallback_authorized", False):
            profiles = {
                role: value
                for role, value in profiles.items()
                if role != "fallback"
            }
        return sorted({str(value.get("agent_id", "")).lower() for value in profiles.values() if isinstance(value, dict) and value.get("agent_id")})

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
    def _git(
        cwd: str,
        *args: str,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, env=env
        )
        if check and result.returncode:
            raise GreenfieldBootstrapError("Git bootstrap operation failed")
        return result.stdout.strip()

    @classmethod
    def _prepare_local_branch(cls, repository_root: str, branch: str, base_sha: str) -> None:
        """Reconcile only an unbound stale local branch at the exact base SHA."""
        ref = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if ref.returncode != 0:
            return
        if ref.stdout.strip() != base_sha:
            raise GreenfieldBootstrapError("Existing local bootstrap branch has a different head")
        worktrees = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if worktrees.returncode != 0 or f"branch refs/heads/{branch}" in worktrees.stdout:
            raise GreenfieldBootstrapError("Existing bootstrap branch is bound to a worktree")
        deleted = subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if deleted.returncode != 0:
            raise GreenfieldBootstrapError("Stale local bootstrap branch could not be reconciled")

    @staticmethod
    def _git_auth_environment(adapter: Any, project: Project) -> dict[str, str] | None:
        provider = getattr(adapter, "git_auth_environment", None)
        if not callable(provider):
            return None
        remote = project.provider_connections["git_pr"]["repository_url"]
        if not remote.startswith(("http://", "https://", "ssh://", "git@")):
            remote = f"https://github.com/{remote}.git"
        return {**os.environ, **provider(remote)}

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
            expected_sources = set(source_files)
            present_sources = {
                file.relative_to(incoming).as_posix()
                for file in incoming.rglob("*")
                if file.is_file()
            }
            if present_sources != expected_sources:
                raise GreenfieldBootstrapError(
                    "Context source inventory differs from supplied ZIP"
                )
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
                source_index = worktree / "context" / "fuentes" / "INDEX.md"
                if not source_index.is_file() or not source_index.read_text(encoding="utf-8").strip():
                    raise GreenfieldBootstrapError("Context index omits source provenance")
                source_text = source_index.read_text(encoding="utf-8")
                if not all(relative in source_text for relative in missing_sources):
                    raise GreenfieldBootstrapError("Source index omits source provenance")
                if "fuentes/INDEX.md" not in index_text:
                    raise GreenfieldBootstrapError("Source index is not reachable from main index")

            # Structural index integrity only; F2 does not judge semantics,
            # factual accuracy or authority of the uploaded documentation.
            for relative in populated_catalog_documents(worktree):
                if relative.removeprefix("context/") not in index_text:
                    raise GreenfieldBootstrapError(
                        "A populated canonical document is absent from the main index"
                    )
            for relative in CONTEXT_DOCUMENT_PATHS:
                doc = worktree / relative
                if (
                    doc.is_file()
                    and not has_substantive_content(doc.read_text(encoding="utf-8"))
                    and relative.removeprefix("context/") in index_text
                ):
                    raise GreenfieldBootstrapError(
                        "Main index refers to an empty canonical document"
                    )

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
    def _candidate_allowed_paths(
        worktree: Path,
        capability_evidence: dict[str, Any],
        official_openspec: dict[str, Any],
    ) -> set[str]:
        allowed = {
            str(item["path"])
            for item in capability_evidence.get("files", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        integrations = official_openspec.get("integrations", {})
        codex_names = {
            str(name) for name in integrations.get("codex", [])
        }
        antigravity_names = {
            str(name) for name in integrations.get("antigravity", [])
        }
        for name in codex_names:
            root = worktree / ".agents/skills" / f"openspec-{name}"
            if root.is_dir():
                allowed.update(
                    path.relative_to(worktree).as_posix()
                    for path in root.rglob("*")
                    if path.is_file() and not path.is_symlink()
                )
        for workflow_root in (worktree / ".agent/workflows", worktree / ".agents/workflows"):
            for name in antigravity_names:
                path = workflow_root / f"opsx-{name}.md"
                if path.is_file() and not path.is_symlink():
                    allowed.add(path.relative_to(worktree).as_posix())
        return allowed

    @staticmethod
    def _validate_candidate_scope(
        worktree: Path, *, allowed_paths: set[str] | None = None
    ) -> None:
        """Keep the organization agent inside the documentary/configuration surface."""
        changed = subprocess.run(
            ["git", "diff", "HEAD", "--name-only", "-z"],
            cwd=worktree,
            capture_output=True,
            check=False,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=worktree,
            capture_output=True,
            check=False,
        )
        if changed.returncode != 0 or untracked.returncode != 0:
            raise GreenfieldBootstrapError(
                "Candidate scope could not be inspected; refusing unverified changes"
            )
        # -z handles filenames with spaces/newlines, while 'git diff HEAD'
        # includes both staged and unstaged changes (unlike plain git diff).
        paths = {
            raw.decode("utf-8", errors="surrogateescape")
            for output in (changed.stdout, untracked.stdout)
            for raw in output.split(b"\0")
            if raw
        }

        def allowed(path: str) -> bool:
            if allowed_paths is not None and path in allowed_paths:
                return True
            return (
                path == "AGENTS.md"
                or path
                in {
                    ".agents/AGENTS.md",
                    ".agents/skills/.openspec-target",
                    ".agent/AGENTS.md",
                    "openspec/config.yaml",
                    # Official OpenSpec initialization creates these empty
                    # scaffolds in a new repository. They are setup artifacts,
                    # not agent-authored product context or backlog.
                    "openspec/changes/archive/.gitkeep",
                    "openspec/specs/.gitkeep",
                }
                or generated_context_path_allowed(path)
                or path.startswith((".agents/skills/openspec-", ".agent/workflows/opsx-"))
            )
        unrelated = sorted(path for path in paths if path and not allowed(path))
        if unrelated:
            # Do not surface potentially sensitive filenames through the API.
            # The full candidate remains in its bound, private worktree for
            # authorized offline inspection and deterministic repair.
            fingerprints = [
                hashlib.sha256(name.encode("utf-8", errors="surrogateescape"))
                .hexdigest()[:12]
                for name in unrelated[:5]
            ]
            raise GreenfieldBootstrapError(
                f"Candidate contains unrelated or backlog-like changes "
                f"(count={len(unrelated)}, path_fingerprints={','.join(fingerprints)})"
            )

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
        # A workspace/agent may have committed a newer checkpoint since the
        # bootstrap caller loaded its Project. Never overwrite its diagnostics.
        current = self.uow.projects.get_by_id(project.project_id) or project
        current.onboarding_status = ProjectOnboardingStatus.BLOCKED
        current.onboarding_reasons = [reason]
        current.updated_at = utc_now()
        self.uow.projects.save(current)
        self.uow.commit()
