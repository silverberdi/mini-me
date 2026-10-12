"""Git worktree lifecycle management for execution jobs with durable ownership tracking."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from minime.adapters.github import GitHubAdapter

if TYPE_CHECKING:
    from minime.services.workspace_guard import ManagedWorkspaceGuard

from minime.domain.enums import (
    EventType,
    ExecutionOutcome,
    ExternalOutcome,
    ExternalReasonCode,
    GitOperationStatus,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    WorkspaceOperation,
    WorktreeCreationState,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    GitOperation,
    OrchestrationWorktreeOwnership,
    WorktreeCleanupResult,
    utc_now,
)
from minime.logging import redact_secrets

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorktreeInfo:
    path: Path
    branch_name: str
    base_sha: str


@dataclass(frozen=True)
class WorktreeState:
    dirty: bool
    fingerprint: str
    files: tuple[str, ...]


class WorktreeManager:
    """Creates isolated candidate worktrees under `.minime/worktrees/<job_id>` with Git operation tracking."""

    def __init__(
        self,
        project_root: str | Path,
        uow: PersistenceUnitOfWork,
        workspace_guard: ManagedWorkspaceGuard | None = None,
        github_adapter: GitHubAdapter | None = None,
    ):
        if uow is None:
            raise ValueError("PersistenceUnitOfWork (uow) is required for WorktreeManager.")
        self.project_root = Path(project_root).resolve()
        self.worktrees_root = self.project_root / ".minime" / "worktrees"
        self.uow = uow
        self.workspace_guard = workspace_guard
        self.github_adapter = github_adapter or GitHubAdapter()

    def _authorize_mutating_operation(
        self,
        project_id: str | None,
        target_path: Path,
        operation: WorkspaceOperation,
        require_created_ownership: bool = False,
        job_id: str | None = None,
    ) -> bool:
        if not project_id:
            raise ValueError(
                f"project_id is mandatory for managed workspace mutation '{operation.value}'."
            )

        canonical_path = target_path.resolve()

        if not self.uow:
            raise RuntimeError(
                f"PersistenceUnitOfWork (uow) is required for workspace mutation '{operation.value}'."
            )

        from minime.services.workspace_guard import ManagedWorkspaceGuard, is_binding_fully_valid

        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project_id) if binding_repo else None

        if not is_binding_fully_valid(binding):
            raise RuntimeError(
                f"Mutating operation '{operation.value}' denied: binding for project '{project_id}' is missing, invalid, or unverified."
            )

        canonical_source = str(self.project_root.resolve())
        canonical_binding_root = str(Path(binding.managed_repository_root).resolve())
        if canonical_source != canonical_binding_root:
            raise RuntimeError(
                f"Mutating operation '{operation.value}' denied: WorktreeManager project_root '{canonical_source}' "
                f"does not match binding managed_repository_root '{canonical_binding_root}'."
            )

        guard = self.workspace_guard or ManagedWorkspaceGuard(self.uow)

        from minime.domain.enums import ExternalOutcome, WorkspaceRole
        from minime.domain.models import WorkspaceMutationRequest

        source_req = WorkspaceMutationRequest(
            project_id=project_id,
            target_path=canonical_source,
            requested_operation=WorkspaceOperation.READ,
        )
        source_decision = guard.evaluate_mutation(source_req)
        if (
            not source_decision.allowed
            or source_decision.workspace_role != WorkspaceRole.MANAGED_REPOSITORY
            or source_decision.outcome != ExternalOutcome.SUCCESS
        ):
            raise RuntimeError(
                f"Mutating operation '{operation.value}' denied: source managed repository '{canonical_source}' "
                f"fails workspace guard authorization: {source_decision.provider_detail}"
            )

        if require_created_ownership:
            ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
            if ownership_repo:
                ownership = ownership_repo.get_by_canonical_path(str(canonical_path))
                if not ownership and job_id and hasattr(ownership_repo, "get_by_job_id"):
                    cand = ownership_repo.get_by_job_id(job_id)
                    if cand and str(Path(cand.canonical_worktree_path).resolve()) == str(
                        canonical_path
                    ):
                        ownership = cand

                if not ownership or ownership.creation_state not in (
                    WorktreeCreationState.CREATED,
                    WorktreeCreationState.PENDING,
                ):
                    raise RuntimeError(
                        f"Mutating operation '{operation.value}' denied: no valid worktree ownership found for '{canonical_path}'."
                    )

        req = WorkspaceMutationRequest(
            project_id=project_id,
            target_path=str(canonical_path),
            requested_operation=operation,
        )
        decision = guard.evaluate_mutation(req)
        if not decision.allowed:
            raise RuntimeError(
                f"ManagedWorkspaceGuard denied {operation.value} for path '{canonical_path}': {decision.provider_detail or decision.reason_code.value}"
            )

    def _resolve_project_id(self, project_id: str | None, job_id: str | None = None) -> str | None:
        if project_id:
            return project_id
        if not self.uow or not job_id:
            return None
        if hasattr(self.uow, "jobs") and self.uow.jobs:
            try:
                job = (
                    self.uow.jobs.get_by_id(job_id) if hasattr(self.uow.jobs, "get_by_id") else None
                )
                if job and getattr(job, "project_id", None):
                    return job.project_id
            except Exception:
                pass
        if hasattr(self.uow, "orchestration_runs") and self.uow.orchestration_runs:
            runs_repo = self.uow.orchestration_runs
            if hasattr(runs_repo, "get_by_active_job_id"):
                try:
                    r = runs_repo.get_by_active_job_id(job_id)
                    if r and getattr(r, "project_id", None):
                        return r.project_id
                except Exception:
                    pass
            runs = []
            if hasattr(runs_repo, "list_runs"):
                try:
                    runs = runs_repo.list_runs()
                except Exception:
                    pass
            elif hasattr(runs_repo, "list_all"):
                try:
                    runs = runs_repo.list_all()
                except Exception:
                    pass
            if not runs and hasattr(runs_repo, "_store"):
                store = getattr(runs_repo, "_store", {})
                runs = list(store.values()) if isinstance(store, dict) else []
            for r in runs:
                if (
                    getattr(r, "active_job_id", None) == job_id
                    or getattr(r, "run_id", None) == job_id
                ) and getattr(r, "project_id", None):
                    return r.project_id
        if (
            hasattr(self.uow, "orchestration_worktree_ownerships")
            and self.uow.orchestration_worktree_ownerships
        ):
            ow_repo = self.uow.orchestration_worktree_ownerships
            if hasattr(ow_repo, "get_by_job_id"):
                try:
                    ow = ow_repo.get_by_job_id(job_id)
                    if ow and getattr(ow, "project_id", None):
                        return ow.project_id
                except Exception:
                    pass
        return None

    def _flush_uow(self) -> None:
        if not self.uow:
            return
        flush_fn = getattr(self.uow, "flush", None)
        if callable(flush_fn):
            flush_fn()
        elif hasattr(self.uow, "commit") and callable(getattr(self.uow, "commit", None)):
            self.uow.commit()

    def resolve_worktree_parent_dir(self, project_id: str | None) -> Path:
        if not project_id:
            raise ValueError("project_id is mandatory to resolve worktree parent directory.")
        if not self.uow:
            raise RuntimeError(
                "PersistenceUnitOfWork (uow) is required to resolve worktree parent directory."
            )
        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        if not binding_repo:
            raise RuntimeError("project_managed_repository_bindings repository is missing in uow.")
        binding = binding_repo.get_by_project_id(project_id)
        from minime.services.workspace_guard import is_binding_fully_valid

        if not is_binding_fully_valid(binding):
            raise RuntimeError(
                f"Failing closed: no valid durable binding or worktree_parent_dir found for project_id '{project_id}'."
            )
        return Path(binding.worktree_parent_dir).resolve()

    def worktree_path(self, job_id: str, project_id: str | None = None) -> Path:
        eff_project_id = self._resolve_project_id(project_id, job_id)
        return self.resolve_worktree_parent_dir(eff_project_id) / job_id

    def remediation_worktree_path(
        self, job_id: str, generation: int, project_id: str | None = None
    ) -> Path:
        eff_project_id = self._resolve_project_id(project_id, job_id)
        return (
            self.resolve_worktree_parent_dir(eff_project_id)
            / f"{job_id}-remediation-gen{generation}"
        )

    def review_worktree_path(
        self,
        job_id: str,
        reviewer_role: str,
        project_id: str | None = None,
        candidate_sha: str | None = None,
    ) -> Path:
        eff_project_id = self._resolve_project_id(project_id, job_id)
        sanitized_role = reviewer_role.replace("/", "_").replace("\\", "_").replace(":", "_")
        short_sha = candidate_sha[:8] if candidate_sha else ""
        suffix = f"-{short_sha}" if short_sha else ""
        return (
            self.resolve_worktree_parent_dir(eff_project_id)
            / f"{job_id}-review-{sanitized_role}{suffix}"
        )

    async def _git(
        self,
        args: list[str],
        cwd: Path | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        operation_type: str | None = None,
        managed_worktree_path: Path | str | None = None,
    ) -> str:
        command_cwd = cwd or self.project_root
        git_op = None
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        auth_secrets: tuple[str, ...] = ()

        # Remote reads during published-intake handoff must use the same non-
        # interactive GitHub App authority as intake publication. Credentials are
        # installed only through child-process config env and never enter argv/logs.
        if args and args[0] in {"fetch", "ls-remote", "push"}:
            eff_project_id = project_id or self._resolve_project_id(project_id, job_id)
            binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
            binding = (
                binding_repo.get_by_project_id(eff_project_id)
                if binding_repo and eff_project_id
                else None
            )
            remote_name = getattr(binding, "remote_name", None) or "origin"
            remote_url_proc = await asyncio.create_subprocess_exec(
                "git",
                "remote",
                "get-url",
                remote_name,
                cwd=str(command_cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            remote_url_out, _ = await remote_url_proc.communicate()
            if remote_url_proc.returncode != 0:
                raise RuntimeError(
                    f"Git remote '{remote_name}' cannot be resolved for published intake handoff."
                )
            try:
                auth_bundle = self.github_adapter._git_auth_bundle(remote_url_out.decode().strip())
            except Exception as exc:
                raise RuntimeError(
                    f"GitHub App authorization for remote '{remote_name}' is unavailable: "
                    f"{redact_secrets(str(exc))}"
                ) from None
            env.update(dict(auth_bundle.env))
            auth_secrets = tuple(auth_bundle.secrets)

        if self.uow and job_id and operation_type:
            target_wt = Path(managed_worktree_path or command_cwd).resolve()
            git_op = GitOperation(
                job_id=job_id,
                project_id=project_id or "unknown",
                worktree_path=str(target_wt),
                operation_type=operation_type,
                status=GitOperationStatus.RUNNING,
                started_at=utc_now(),
            )
            self.uow.git_operations.save(git_op)
            self._flush_uow()

        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(command_cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        if git_op and self.uow and proc.pid:
            git_op.pid = proc.pid
            self.uow.git_operations.save(git_op)
            self._flush_uow()

        stdout, stderr = await proc.communicate()
        success = proc.returncode == 0

        if git_op and self.uow:
            new_status = GitOperationStatus.COMPLETED if success else GitOperationStatus.FAILED
            self.uow.git_operations.update_status(
                git_op.operation_id,
                new_status,
                completed_at=utc_now(),
            )
            self._flush_uow()

        if not success:
            error = (
                stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
            )
            raise RuntimeError(redact_secrets(error, list(auth_secrets)))
        decoded_stdout = stdout.decode()
        # Porcelain status encodes index/worktree state in leading spaces. A
        # generic strip() destroys that security-relevant distinction (" M"
        # becomes "M ") and can misclassify a permitted unstaged artifact
        # repair as staged content. Preserve the exact NUL-delimited records.
        if (
            args
            and args[0] == "status"
            and any(argument.startswith("--porcelain") for argument in args[1:])
        ):
            return decoded_stdout
        return decoded_stdout.strip()

    async def _git_show_bytes(self, object_path: str) -> bytes:
        """Read an exact published blob without text trimming or newline rewriting."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            "show",
            object_path,
            cwd=str(self.project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        stdout, _stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError("Published artifact content is unobservable.")
        return stdout

    async def _materialize_verified_published_intake_artifacts(
        self,
        *,
        destination_worktree: Path,
        project_id: str,
        change_name: str,
        job_id: str,
        recovery_snapshot_sha: str | None = None,
    ) -> None:
        """Materialize only the verified remote intake tree into an execution worktree."""
        intake_repo = getattr(self.uow, "intake_workspace_ownerships", None)
        from minime.services.intake_workspace_ownership_selection import (
            resolve_published_intake_ownership,
        )

        backlog_repo = getattr(self.uow, "backlog_items", None)
        linked_item = (
            backlog_repo.get_by_openspec_change_name(project_id, change_name)
            if backlog_repo
            else None
        )
        ownership = (
            resolve_published_intake_ownership(
                intake_repo,
                project_id=project_id,
                change_name=change_name,
                item_key=linked_item.item_key if linked_item else None,
                allow_released=True,
            )
            if intake_repo
            else None
        )
        if not ownership:
            # This manager also serves historical/non-intake worktree callers.
            # They receive no OpenSpec materialization; scheduler admission is
            # the authority that requires a published intake identity.
            return False
        if not ownership.published_ref or not ownership.published_sha:
            raise RuntimeError(
                "Execution handoff denied: no published intake artifact identity exists."
            )

        from minime.domain.enums import IntakeWorkspacePublicationState
        from minime.services.workspace_guard import is_binding_fully_valid

        if ownership.publication_state != IntakeWorkspacePublicationState.PUBLISHED:
            raise RuntimeError(
                "Execution handoff denied: intake artifacts are not durably published."
            )
        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project_id) if binding_repo else None
        if not is_binding_fully_valid(binding):
            raise RuntimeError("Execution handoff denied: managed repository binding is invalid.")
        if ownership.canonical_repository_identity != binding.canonical_repository_identity:
            raise RuntimeError(
                "Execution handoff denied: intake ownership repository identity conflicts with the managed binding."
            )
        expected_ref = f"refs/minime/intake/{change_name}"
        if ownership.published_ref != expected_ref:
            raise RuntimeError(
                "Execution handoff denied: published ref does not match change identity."
            )

        observed = await self._git(
            ["ls-remote", binding.remote_name, ownership.published_ref],
            cwd=self.project_root,
            job_id=job_id,
            project_id=project_id,
            operation_type="published_intake_ref_observe",
            managed_worktree_path=destination_worktree,
        )
        observed_parts = observed.split()
        if (
            len(observed_parts) != 2
            or observed_parts[0] != ownership.published_sha
            or observed_parts[1] != ownership.published_ref
        ):
            raise RuntimeError(
                "Execution handoff denied: published intake ref drifted or is unobservable."
            )

        await self._git(
            ["fetch", "--no-tags", binding.remote_name, ownership.published_ref],
            cwd=self.project_root,
            job_id=job_id,
            project_id=project_id,
            operation_type="published_intake_ref_fetch",
            managed_worktree_path=destination_worktree,
        )
        fetched_sha = await self._git(["rev-parse", "FETCH_HEAD"], cwd=self.project_root)
        if fetched_sha != ownership.published_sha:
            raise RuntimeError(
                "Execution handoff denied: fetched intake commit differs from persisted SHA."
            )

        prefix = f"openspec/changes/{change_name}/"
        tree = await self._git(
            ["ls-tree", "-r", "-z", ownership.published_sha, "--", prefix],
            cwd=self.project_root,
        )
        tree_entries = [entry for entry in tree.split("\0") if entry]
        relative_paths: list[str] = []
        for entry in tree_entries:
            metadata, separator, path_text = entry.partition("\t")
            fields = metadata.split()
            if (
                not separator
                or len(fields) != 3
                or fields[0] != "100644"
                or fields[1] != "blob"
                or not path_text.startswith(prefix)
            ):
                raise RuntimeError(
                    "Execution handoff denied: published intake tree contains a non-regular or malformed entry."
                )
            relative_paths.append(path_text[len(prefix) :])
        required = {"proposal.md", "tasks.md", "design.md"}
        actual = set(relative_paths)
        if (
            len(actual) != len(relative_paths)
            or not required.issubset(actual)
            or not any(path.startswith("specs/") and path.endswith(".md") for path in actual)
            or any(
                not path
                or PurePosixPath(path).is_absolute()
                or ".." in PurePosixPath(path).parts
                or "\\" in path
                or (
                    path not in required
                    and not (path.startswith("specs/") and path.endswith(".md"))
                )
                for path in actual
            )
        ):
            raise RuntimeError(
                "Execution handoff denied: published intake artifact manifest is invalid."
            )

        destination = destination_worktree / "openspec" / "changes" / change_name
        worktree_root = destination_worktree.resolve()
        path_component = worktree_root
        for component in ("openspec", "changes", change_name):
            path_component = path_component / component
            if path_component.is_symlink():
                raise RuntimeError(
                    "Execution handoff denied: OpenSpec materialization path contains a symlink."
                )
        if not path_component.resolve().is_relative_to(worktree_root):
            raise RuntimeError(
                "Execution handoff denied: OpenSpec materialization path escapes its worktree."
            )
        if destination.is_symlink():
            raise RuntimeError(
                "Execution handoff denied: OpenSpec materialization path is a symlink."
            )
        if recovery_snapshot_sha and not destination.is_dir():
            raise RuntimeError(
                "Execution handoff denied: verified recovery snapshot artifacts are absent from the worktree."
            )
        if destination.exists():
            expected_dirs = {
                str(parent)
                for relative_path in relative_paths
                for parent in PurePosixPath(relative_path).parents
                if str(parent) != "."
            }
            actual_paths: set[str] = set()
            actual_dirs: set[str] = set()
            for candidate in destination.rglob("*"):
                if candidate.is_symlink():
                    raise RuntimeError(
                        "Execution handoff denied: existing OpenSpec materialization contains a symlink."
                    )
                if candidate.is_file():
                    actual_paths.add(candidate.relative_to(destination).as_posix())
                elif candidate.is_dir():
                    actual_dirs.add(candidate.relative_to(destination).as_posix())
            if actual_paths != set(relative_paths) or actual_dirs != expected_dirs:
                raise RuntimeError(
                    "Execution handoff denied: existing OpenSpec materialization differs from the published manifest."
                )
            published_contents: dict[str, bytes] = {}
            snapshot_contents: dict[str, bytes] = {}
            for relative_path in relative_paths:
                expected_content = await self._git_show_bytes(
                    f"{ownership.published_sha}:{prefix}{relative_path}"
                )
                published_contents[relative_path] = expected_content
                if recovery_snapshot_sha:
                    snapshot_contents[relative_path] = await self._git_show_bytes(
                        f"{recovery_snapshot_sha}:{prefix}{relative_path}"
                    )
            current_contents = {
                relative_path: (destination / relative_path).read_bytes()
                for relative_path in relative_paths
            }
            repair_paths: list[str] = []
            for relative_path, expected_content in published_contents.items():
                current_content = current_contents[relative_path]
                if not recovery_snapshot_sha:
                    if current_content != expected_content:
                        raise RuntimeError(
                            "Execution handoff denied: existing OpenSpec materialization content differs from the published tree."
                        )
                    continue
                snapshot_content = snapshot_contents[relative_path]
                missing_final_lf = expected_content.endswith(b"\n") and (
                    snapshot_content == expected_content[:-1]
                )
                if snapshot_content != expected_content and not missing_final_lf:
                    raise RuntimeError(
                        "Execution handoff denied: recovery snapshot differs from published artifacts beyond one omitted final LF."
                    )
                if current_content not in {
                    expected_content,
                    expected_content[:-1] if missing_final_lf else expected_content,
                }:
                    raise RuntimeError(
                        "Execution handoff denied: existing OpenSpec materialization contains unauthorized content."
                    )
                if missing_final_lf:
                    repair_paths.append(relative_path)

            if repair_paths:
                ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
                recovery_ownership = (
                    ownership_repo.get_by_job_id(job_id) if ownership_repo else None
                )
                if (
                    not recovery_ownership
                    or recovery_ownership.creation_state != WorktreeCreationState.CREATED
                    or recovery_ownership.project_id != project_id
                    or recovery_ownership.job_id != job_id
                    or recovery_ownership.change_name != change_name
                    or not recovery_ownership.source_base_sha
                ):
                    raise RuntimeError(
                        "Execution handoff denied: legacy LF repair lacks canonical CREATED recovery ownership."
                    )
                run_repo = getattr(self.uow, "orchestration_runs", None)
                linked_job = (
                    self.uow.jobs.get_by_id(job_id) if getattr(self.uow, "jobs", None) else None
                )
                linked_run = run_repo.get_by_id(recovery_ownership.run_id) if run_repo else None
                if (
                    not linked_job
                    or not linked_run
                    or linked_job.project_id != project_id
                    or linked_job.change_name != change_name
                    or linked_job.base_sha != recovery_ownership.source_base_sha
                    or linked_job.candidate_sha
                    or linked_run.project_id != project_id
                    or linked_run.change_name != change_name
                    or linked_run.active_job_id != job_id
                    or linked_run.base_sha != recovery_ownership.source_base_sha
                    or linked_run.current_candidate_sha
                ):
                    raise RuntimeError(
                        "Execution handoff denied: legacy LF repair conflicts with durable Run/Job identity or candidate evidence."
                    )
                events_repo = getattr(self.uow, "events", None)
                if not events_repo or not callable(getattr(events_repo, "save", None)):
                    raise RuntimeError(
                        "Execution handoff denied: durable repair evidence authority is unavailable."
                    )
                for relative_path in repair_paths:
                    artifact_path = destination / relative_path
                    if artifact_path.is_symlink() or not artifact_path.is_file():
                        raise RuntimeError(
                            "Execution handoff denied: a repair target is not a regular file."
                        )
                identity = {
                    "worktree_id": recovery_ownership.worktree_id,
                    "run_id": recovery_ownership.run_id,
                    "job_id": job_id,
                    "source_base_sha": recovery_ownership.source_base_sha,
                    "recovery_snapshot_sha": recovery_snapshot_sha,
                    "published_ref": ownership.published_ref,
                    "published_sha": ownership.published_sha,
                }
                recovery_events = events_repo.list_events(
                    project_id=project_id, change_id=change_name, limit=10000
                )
                matching_events = [
                    event
                    for event in recovery_events
                    if event.event_type == EventType.INTAKE_ARTIFACT_HANDOFF_RECONCILED
                    and event.operation_id == job_id
                ]
                if any(
                    any(event.payload.get(key) != value for key, value in identity.items())
                    for event in matching_events
                ):
                    raise RuntimeError(
                        "Execution handoff denied: prior repair evidence conflicts with current durable identity."
                    )
                try:
                    final_observation = await self._git(
                        ["ls-remote", binding.remote_name, ownership.published_ref],
                        cwd=self.project_root,
                        job_id=job_id,
                        project_id=project_id,
                        operation_type="published_intake_ref_reobserve",
                        managed_worktree_path=destination_worktree,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "Execution handoff denied: published ref could not be re-observed before repair."
                    ) from exc
                final_parts = final_observation.split()
                if (
                    len(final_parts) != 2
                    or final_parts[0] != ownership.published_sha
                    or final_parts[1] != ownership.published_ref
                ):
                    raise RuntimeError(
                        "Execution handoff denied: published ref changed during artifact verification."
                    )
                before_digests = {
                    relative_path: hashlib.sha256(snapshot_contents[relative_path]).hexdigest()
                    for relative_path in repair_paths
                }
                published_digests = {
                    relative_path: hashlib.sha256(published_contents[relative_path]).hexdigest()
                    for relative_path in repair_paths
                }
                if any(
                    event.payload.get("reconciled_paths") != repair_paths
                    or event.payload.get("prior_sha256") != before_digests
                    or event.payload.get("published_blob_sha256") != published_digests
                    for event in matching_events
                ):
                    raise RuntimeError(
                        "Execution handoff denied: prior repair evidence conflicts with the verified artifact manifest."
                    )
                # All files and snapshot differences are preflighted above. Each
                # authorized mutation is a single-byte append, so interruption
                # leaves either the historical bytes or the exact published blob.
                for relative_path in repair_paths:
                    artifact_path = destination / relative_path
                    current_content = artifact_path.read_bytes()
                    published_content = published_contents[relative_path]
                    if current_content == published_content:
                        continue
                    if current_content != published_content[:-1] or not published_content.endswith(
                        b"\n"
                    ):
                        raise RuntimeError(
                            "Execution handoff denied: repair target changed after validation."
                        )
                    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
                    descriptor = os.open(artifact_path, flags)
                    try:
                        if (
                            not stat.S_ISREG(os.fstat(descriptor).st_mode)
                            or os.write(descriptor, b"\n") != 1
                        ):
                            raise RuntimeError(
                                "Execution handoff denied: unable to append the single verified LF byte."
                            )
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                if any(
                    (destination / relative_path).read_bytes() != expected
                    for relative_path, expected in published_contents.items()
                ):
                    raise RuntimeError(
                        "Execution handoff denied: post-repair artifact verification failed."
                    )
                if not matching_events:
                    events_repo.save(
                        Event(
                            event_type=EventType.INTAKE_ARTIFACT_HANDOFF_RECONCILED,
                            project_id=project_id,
                            change_id=change_name,
                            operation_id=job_id,
                            payload={
                                **identity,
                                "reconciled_paths": repair_paths,
                                "prior_sha256": before_digests,
                                "published_blob_sha256": published_digests,
                            },
                        )
                    )
                    self._flush_uow()
            return True
        for relative_path in relative_paths:
            content = await self._git_show_bytes(
                f"{ownership.published_sha}:{prefix}{relative_path}"
            )
            artifact_path = destination / relative_path
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(content)
        return True

    def _resolve_real_run_id(
        self,
        job_id: str,
        run_id: str | None = None,
        project_id: str | None = None,
        change_name: str | None = None,
    ) -> str:
        durable_run_id = None
        if self.uow:
            # 1. Check uow.orchestration_runs
            if hasattr(self.uow, "orchestration_runs") and self.uow.orchestration_runs:
                runs_repo = self.uow.orchestration_runs
                if hasattr(runs_repo, "get_by_active_job_id"):
                    try:
                        r = runs_repo.get_by_active_job_id(job_id)
                        if r and getattr(r, "run_id", None):
                            durable_run_id = r.run_id
                    except Exception:
                        pass
                if not durable_run_id and hasattr(runs_repo, "get_by_id"):
                    try:
                        r = runs_repo.get_by_id(job_id)
                        if r and getattr(r, "run_id", None):
                            durable_run_id = r.run_id
                    except Exception:
                        pass
                if (
                    not durable_run_id
                    and project_id
                    and change_name
                    and hasattr(runs_repo, "get_active_run")
                ):
                    try:
                        r = runs_repo.get_active_run(project_id, change_name)
                        if r and getattr(r, "run_id", None):
                            durable_run_id = r.run_id
                    except Exception:
                        pass

                if not durable_run_id:
                    runs = []
                    if hasattr(runs_repo, "list_runs"):
                        try:
                            runs = runs_repo.list_runs()
                        except Exception:
                            pass
                    elif hasattr(runs_repo, "list_all"):
                        try:
                            runs = runs_repo.list_all()
                        except Exception:
                            pass
                    if not runs and hasattr(runs_repo, "_store"):
                        store = getattr(runs_repo, "_store", {})
                        runs = list(store.values()) if isinstance(store, dict) else []
                    if not runs and hasattr(runs_repo, "store"):
                        store = getattr(runs_repo, "store", {})
                        runs = list(store.values()) if isinstance(store, dict) else []

                    for r in runs:
                        if (
                            getattr(r, "active_job_id", None) == job_id
                            or getattr(r, "run_id", None) == job_id
                        ) and getattr(r, "run_id", None):
                            durable_run_id = r.run_id
                            break

            # 2. Check uow.candidate_remediations
            if (
                not durable_run_id
                and hasattr(self.uow, "candidate_remediations")
                and self.uow.candidate_remediations
            ):
                rem_repo = self.uow.candidate_remediations
                if hasattr(rem_repo, "list_by_job"):
                    try:
                        rems = rem_repo.list_by_job(job_id)
                        if rems and getattr(rems[0], "run_id", None):
                            durable_run_id = rems[0].run_id
                    except Exception:
                        pass

            # 3. Check uow.orchestration_worktree_ownerships
            if (
                not durable_run_id
                and hasattr(self.uow, "orchestration_worktree_ownerships")
                and self.uow.orchestration_worktree_ownerships
            ):
                ow_repo = self.uow.orchestration_worktree_ownerships
                if hasattr(ow_repo, "get_by_job_id"):
                    try:
                        ow = ow_repo.get_by_job_id(job_id)
                        if ow and getattr(ow, "run_id", None):
                            durable_run_id = ow.run_id
                    except Exception:
                        pass

            # 4. Check uow.jobs
            if not durable_run_id and hasattr(self.uow, "jobs") and self.uow.jobs:
                try:
                    job = (
                        self.uow.jobs.get_by_id(job_id)
                        if hasattr(self.uow.jobs, "get_by_id")
                        else None
                    )
                    if job and getattr(job, "run_id", None):
                        durable_run_id = job.run_id
                except Exception:
                    pass

        if durable_run_id:
            if run_id and run_id != durable_run_id:
                raise ValueError(
                    f"CONFLICT: Caller-supplied run_id '{run_id}' conflicts with durable run_id '{durable_run_id}' for job_id '{job_id}'."
                )
            return durable_run_id

        raise ValueError(
            f"EVIDENCE_INSUFFICIENT: Durable run_id for job_id '{job_id}' is unobservable in persistence."
        )

    def _resolve_real_change_name(
        self,
        job_id: str,
        change_name: str | None = None,
        project_id: str | None = None,
        run_id: str | None = None,
    ) -> str:
        durable_change_name = None
        if self.uow:
            # 1. Check uow.jobs
            if hasattr(self.uow, "jobs") and self.uow.jobs:
                try:
                    job = (
                        self.uow.jobs.get_by_id(job_id)
                        if hasattr(self.uow.jobs, "get_by_id")
                        else None
                    )
                    if job and getattr(job, "change_name", None):
                        durable_change_name = job.change_name
                except Exception:
                    pass

            # 2. Check uow.orchestration_runs
            if (
                not durable_change_name
                and hasattr(self.uow, "orchestration_runs")
                and self.uow.orchestration_runs
            ):
                runs_repo = self.uow.orchestration_runs
                eff_run = run_id
                if eff_run and hasattr(runs_repo, "get_by_id"):
                    try:
                        r = runs_repo.get_by_id(eff_run)
                        if r and getattr(r, "change_name", None):
                            durable_change_name = r.change_name
                    except Exception:
                        pass
                if not durable_change_name and hasattr(runs_repo, "get_by_active_job_id"):
                    try:
                        r = runs_repo.get_by_active_job_id(job_id)
                        if r and getattr(r, "change_name", None):
                            durable_change_name = r.change_name
                    except Exception:
                        pass
                if not durable_change_name:
                    runs = []
                    if hasattr(runs_repo, "list_runs"):
                        try:
                            runs = runs_repo.list_runs()
                        except Exception:
                            pass
                    elif hasattr(runs_repo, "list_all"):
                        try:
                            runs = runs_repo.list_all()
                        except Exception:
                            pass
                    if not runs and hasattr(runs_repo, "_store"):
                        store = getattr(runs_repo, "_store", {})
                        runs = list(store.values()) if isinstance(store, dict) else []
                    if not runs and hasattr(runs_repo, "store"):
                        store = getattr(runs_repo, "store", {})
                        runs = list(store.values()) if isinstance(store, dict) else []

                    for r in runs:
                        if (
                            getattr(r, "active_job_id", None) == job_id
                            or getattr(r, "run_id", None) == job_id
                            or getattr(r, "run_id", None) == eff_run
                        ) and getattr(r, "change_name", None):
                            durable_change_name = r.change_name
                            break

            # 3. Check uow.candidate_remediations
            if (
                not durable_change_name
                and hasattr(self.uow, "candidate_remediations")
                and self.uow.candidate_remediations
            ):
                rem_repo = self.uow.candidate_remediations
                if hasattr(rem_repo, "list_by_job"):
                    try:
                        rems = rem_repo.list_by_job(job_id)
                        if rems and getattr(rems[0], "change_name", None):
                            durable_change_name = rems[0].change_name
                    except Exception:
                        pass

            # 4. Check uow.orchestration_worktree_ownerships
            if (
                not durable_change_name
                and hasattr(self.uow, "orchestration_worktree_ownerships")
                and self.uow.orchestration_worktree_ownerships
            ):
                ow_repo = self.uow.orchestration_worktree_ownerships
                if hasattr(ow_repo, "get_by_job_id"):
                    try:
                        ow = ow_repo.get_by_job_id(job_id)
                        if ow and getattr(ow, "change_name", None):
                            durable_change_name = ow.change_name
                    except Exception:
                        pass

        if durable_change_name:
            if change_name and change_name != durable_change_name:
                raise ValueError(
                    f"CONFLICT: Caller-supplied change_name '{change_name}' conflicts with durable change_name '{durable_change_name}' for job_id '{job_id}'."
                )
            return durable_change_name

        raise ValueError(
            f"EVIDENCE_INSUFFICIENT: Durable change_name for job_id '{job_id}' is unobservable in persistence."
        )

    def _persist_pending_ownership(
        self,
        job_id: str,
        project_id: str | None,
        path: Path,
        branch: str,
        run_id: str | None = None,
        change_name: str | None = None,
        source_repository_identity: str | None = None,
        source_base_sha: str | None = None,
    ) -> OrchestrationWorktreeOwnership:
        if not project_id:
            raise ValueError("project_id is mandatory for managed worktree operations.")
        if not self.uow:
            raise RuntimeError(
                "PersistenceUnitOfWork (uow) is required for durable worktree ownership."
            )
        repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        if not repo:
            raise RuntimeError("orchestration_worktree_ownerships repository missing in uow.")

        eff_repo_identity = source_repository_identity
        if not eff_repo_identity or eff_repo_identity in ("origin", "unknown-repo"):
            binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
            if binding_repo:
                binding = binding_repo.get_by_project_id(project_id)
                if binding:
                    eff_repo_identity = binding.canonical_repository_identity

        eff_run_id = self._resolve_real_run_id(
            job_id, run_id, project_id=project_id, change_name=change_name
        )
        eff_change_name = self._resolve_real_change_name(
            job_id, change_name, project_id=project_id, run_id=eff_run_id
        )
        eff_base_sha = source_base_sha

        if not eff_run_id:
            raise ValueError(
                f"Failing closed: run_id for job_id '{job_id}' is unobservable or empty."
            )
        if not eff_change_name:
            raise ValueError(
                f"Failing closed: change_name for job_id '{job_id}' is unobservable or empty."
            )
        if not branch:
            raise ValueError(
                f"Failing closed: branch for job_id '{job_id}' is unobservable or empty."
            )
        if not eff_repo_identity:
            raise RuntimeError(
                f"Failing closed: source_repository_identity for project_id '{project_id}' is unobservable."
            )
        if not eff_base_sha:
            raise RuntimeError(
                f"Failing closed: source_base_sha for job_id '{job_id}' is unobservable."
            )

        canonical_path = str(path.resolve())
        default_worktree_id = f"wt-{job_id}" if job_id else f"wt-{path.name}"
        existing_by_id = repo.get_by_id(default_worktree_id) if hasattr(repo, "get_by_id") else None
        if existing_by_id and existing_by_id.canonical_worktree_path != canonical_path:
            worktree_id = f"wt-{job_id}-{path.name}" if job_id else f"wt-{path.name}"
        else:
            worktree_id = default_worktree_id

        existing = (
            repo.get_by_canonical_path(canonical_path)
            if hasattr(repo, "get_by_canonical_path")
            else None
        ) or (repo.get_by_id(worktree_id) if hasattr(repo, "get_by_id") else None)
        if existing:
            existing.canonical_worktree_path = canonical_path
            existing.project_id = project_id
            existing.job_id = job_id
            existing.run_id = eff_run_id
            existing.change_name = eff_change_name
            existing.source_repository_identity = eff_repo_identity
            existing.source_base_sha = eff_base_sha
            existing.branch = branch
            existing.creation_state = WorktreeCreationState.PENDING
            existing.updated_at = utc_now()
            repo.save(existing)
            self._flush_uow()
            return existing

        hook = getattr(self, "_test_pre_ownership_insert_hook", None)
        if hook is not None:
            hook()

        ownership = OrchestrationWorktreeOwnership(
            worktree_id=worktree_id,
            project_id=project_id,
            job_id=job_id,
            run_id=eff_run_id,
            change_name=eff_change_name,
            canonical_worktree_path=canonical_path,
            source_repository_identity=eff_repo_identity,
            source_base_sha=eff_base_sha,
            branch=branch,
            creation_state=WorktreeCreationState.PENDING,
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        from minime.db.savepoint import execute_with_savepoint_recovery

        def _recovery_on_ownership_conflict() -> OrchestrationWorktreeOwnership | None:
            return repo.get_by_canonical_path(canonical_path)

        session = getattr(self.uow, "session", None)
        if session is not None and hasattr(session, "begin_nested"):
            saved, recovery_res = execute_with_savepoint_recovery(
                session=session,
                save_fn=lambda: repo.save(ownership),
                constraint_name="uq_orchestration_worktree_ownership_path",
                recovery_fn=_recovery_on_ownership_conflict,
            )
            if not saved and recovery_res is not None:
                return recovery_res
        else:
            repo.save(ownership)

        self._flush_uow()

        durable = repo.get_by_id(ownership.worktree_id) or repo.get_by_canonical_path(
            canonical_path
        )
        if not durable or durable.creation_state != WorktreeCreationState.PENDING:
            raise RuntimeError(
                f"Failed to verify durable PENDING ownership record for worktree path '{canonical_path}'."
            )
        return durable

    async def _verify_creation_postconditions(
        self,
        path: Path,
        ownership: OrchestrationWorktreeOwnership,
        expected_branch: str,
        expected_base_sha: str | None = None,
        expected_head_sha: str | None = None,
    ) -> None:
        resolved_path = path.resolve()
        canonical_path = str(resolved_path)

        if not resolved_path.exists():
            raise RuntimeError(
                f"Worktree postcondition failed: path '{canonical_path}' does not exist."
            )

        if str(Path(ownership.canonical_worktree_path).resolve()) != canonical_path:
            raise RuntimeError(
                f"Worktree postcondition failed: path '{canonical_path}' does not match ownership '{ownership.canonical_worktree_path}'."
            )

        wt_list_out = await self._git(["worktree", "list", "--porcelain"], cwd=self.project_root)
        wt_paths = [
            str(Path(line[9:].strip()).resolve())
            for line in wt_list_out.splitlines()
            if line.startswith("worktree ")
        ]
        if canonical_path not in wt_paths:
            raise RuntimeError(
                f"Worktree postcondition failed: path '{canonical_path}' not present in git worktree list."
            )

        actual_branch = (await self._git(["branch", "--show-current"], cwd=resolved_path)).strip()
        if not actual_branch or actual_branch != expected_branch:
            raise RuntimeError(
                f"Worktree postcondition failed: actual branch '{actual_branch}' does not match expected '{expected_branch}'."
            )

        if expected_base_sha:
            head_sha = (await self._git(["rev-parse", "HEAD"], cwd=resolved_path)).strip()
            if not head_sha:
                raise RuntimeError("Worktree postcondition failed: unable to resolve HEAD SHA.")
            try:
                expected_sha = (
                    await self._git(["rev-parse", expected_base_sha], cwd=self.project_root)
                ).strip()
            except Exception:
                expected_sha = expected_base_sha.strip()
            expected_head = expected_head_sha or expected_sha
            if head_sha != expected_head:
                raise RuntimeError(
                    f"Worktree postcondition failed: actual HEAD SHA '{head_sha}' does not match expected SHA '{expected_head}'."
                )

        if self.uow:
            binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
            if binding_repo:
                binding = binding_repo.get_by_project_id(ownership.project_id)
                if binding:
                    from minime.services.workspace_guard import ManagedWorkspaceGuard

                    guard = self.workspace_guard or ManagedWorkspaceGuard(self.uow)
                    valid_git, git_reason = guard.verify_git_repository_identity(
                        canonical_path, binding.canonical_repository_identity, binding.remote_name
                    )
                    if not valid_git:
                        raise RuntimeError(
                            f"Worktree postcondition failed: Git repository identity verification failed: {git_reason}"
                        )

        marker_file = resolved_path / ".minime_worktree_ownership.json"
        if not marker_file.exists():
            raise RuntimeError(
                f"Worktree postcondition failed: ownership marker file missing at '{marker_file}'."
            )
        try:
            m_data = json.loads(marker_file.read_text(encoding="utf-8"))
            if (
                m_data.get("worktree_id") != ownership.worktree_id
                or str(Path(m_data.get("canonical_worktree_path", "")).resolve()) != canonical_path
            ):
                raise RuntimeError("Worktree postcondition failed: ownership marker data mismatch.")
        except Exception as e:
            raise RuntimeError(f"Worktree postcondition failed: corrupt ownership marker: {e}")

    def _write_ownership_marker(
        self, path: Path, ownership: OrchestrationWorktreeOwnership
    ) -> None:
        resolved_path = path.resolve()
        if not resolved_path.exists():
            resolved_path.mkdir(parents=True, exist_ok=True)
        marker_file = resolved_path / ".minime_worktree_ownership.json"

        # Reject symlinks at marker file target
        if marker_file.is_symlink() or os.path.islink(marker_file):
            raise RuntimeError(
                f"Symlink escape detected at ownership marker target '{marker_file}'. Refusing write."
            )

        resolved_marker = marker_file.resolve()
        if not (resolved_marker == marker_file or resolved_path in resolved_marker.parents):
            raise RuntimeError(
                f"Ownership marker target '{resolved_marker}' escapes worktree root '{resolved_path}'."
            )

        # Authorize marker write with ManagedWorkspaceGuard
        from minime.domain.enums import WorktreeCreationState
        from minime.domain.models import WorkspaceMutationRequest
        from minime.services.workspace_guard import ManagedWorkspaceGuard

        guard = self.workspace_guard or ManagedWorkspaceGuard(self.uow)
        requested_op = (
            WorkspaceOperation.WORKTREE_CREATE
            if getattr(ownership, "creation_state", None) == WorktreeCreationState.PENDING
            else WorkspaceOperation.EDIT
        )
        req = WorkspaceMutationRequest(
            project_id=ownership.project_id,
            target_path=str(resolved_marker),
            requested_operation=requested_op,
        )
        decision = guard.evaluate_mutation(req)
        if not decision.allowed:
            raise RuntimeError(
                f"ManagedWorkspaceGuard denied write to ownership marker '{resolved_marker}': {decision.provider_detail or decision.reason_code.value}"
            )

        data = {
            "worktree_id": ownership.worktree_id,
            "project_id": ownership.project_id,
            "job_id": ownership.job_id,
            "run_id": ownership.run_id,
            "change_name": ownership.change_name,
            "canonical_worktree_path": ownership.canonical_worktree_path,
            "branch": ownership.branch,
            "branch_name": ownership.branch_name,
            "source_repository_identity": ownership.source_repository_identity,
            "source_base_sha": ownership.source_base_sha,
            "created_at": ownership.created_at.isoformat()
            if hasattr(ownership.created_at, "isoformat")
            else str(ownership.created_at),
        }
        marker_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Git exclude bookkeeping: Authorize exact Git metadata destination under managed bounds
        try:
            git_ref = resolved_path / ".git"
            info_dir = None
            if git_ref.is_dir():
                info_dir = git_ref / "info"
            elif git_ref.is_file():
                text = git_ref.read_text(encoding="utf-8").strip()
                if text.startswith("gitdir:"):
                    gitdir = Path(text[7:].strip())
                    if not gitdir.is_absolute():
                        gitdir = (resolved_path / gitdir).resolve()
                    info_dir = gitdir / "info"
            if info_dir:
                target_dirs = [info_dir]
                if info_dir.parent and info_dir.parent.parent and info_dir.parent.parent.parent:
                    target_dirs.append(info_dir.parent.parent.parent / "info")
                for target_dir in target_dirs:
                    exclude_file = target_dir / "exclude"
                    if exclude_file.is_symlink() or os.path.islink(exclude_file):
                        raise RuntimeError(
                            f"Symlink escape detected at Git exclude file '{exclude_file}'."
                        )
                    resolved_exclude = exclude_file.resolve()
                    ex_req = WorkspaceMutationRequest(
                        project_id=ownership.project_id,
                        target_path=str(resolved_exclude),
                        requested_operation=WorkspaceOperation.WORKTREE_CREATE,
                    )
                    ex_decision = guard.evaluate_mutation(ex_req)
                    if not ex_decision.allowed:
                        raise RuntimeError(
                            f"ManagedWorkspaceGuard denied write to Git exclude file '{resolved_exclude}': {ex_decision.provider_detail}"
                        )
                    target_dir.mkdir(parents=True, exist_ok=True)
                    content = (
                        exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
                    )
                    if ".minime_worktree_ownership.json" not in content:
                        exclude_file.write_text(
                            content.rstrip() + "\n.minime_worktree_ownership.json\n",
                            encoding="utf-8",
                        )
        except RuntimeError:
            raise
        except Exception:
            pass

    def _verify_ownership_marker(
        self,
        path: Path,
        ownership: OrchestrationWorktreeOwnership,
        worktree_kind: str = "worktree",
    ) -> None:
        marker_file = path.resolve() / ".minime_worktree_ownership.json"
        if not marker_file.exists():
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Ownership marker file missing at '{marker_file}'."
            )
        try:
            m_data = json.loads(marker_file.read_text(encoding="utf-8"))
        except Exception as e:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Corrupt ownership marker: {e}"
            )

        mandatory_fields = [
            "worktree_id",
            "project_id",
            "job_id",
            "run_id",
            "change_name",
            "canonical_worktree_path",
            "source_repository_identity",
            "source_base_sha",
        ]
        for field in mandatory_fields:
            val = m_data.get(field)
            if val is None or str(val).strip() == "":
                raise RuntimeError(
                    f"Refusing to adopt existing {worktree_kind} at '{path}': "
                    f"Ownership marker missing mandatory field '{field}'."
                )

        marker_branch = m_data.get("branch") or m_data.get("branch_name")
        if not marker_branch or str(marker_branch).strip() == "":
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': "
                f"Ownership marker missing mandatory field 'branch'."
            )

        if m_data.get("worktree_id") != ownership.worktree_id:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': "
                f"Ownership marker worktree_id '{m_data.get('worktree_id')}' does not match durable '{ownership.worktree_id}'."
            )
        if m_data.get("project_id") != ownership.project_id:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': "
                f"Ownership marker project_id '{m_data.get('project_id')}' does not match durable '{ownership.project_id}'."
            )
        if m_data.get("job_id") != ownership.job_id:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': "
                f"Ownership marker job_id '{m_data.get('job_id')}' does not match durable '{ownership.job_id}'."
            )
        if m_data.get("run_id") != ownership.run_id:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': "
                f"Ownership marker run_id '{m_data.get('run_id')}' does not match durable '{ownership.run_id}'."
            )
        if m_data.get("change_name") != ownership.change_name:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': "
                f"Ownership marker change_name '{m_data.get('change_name')}' does not match durable '{ownership.change_name}'."
            )
        if str(Path(m_data.get("canonical_worktree_path", "")).resolve()) != str(path.resolve()):
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': "
                f"Ownership marker canonical_worktree_path '{m_data.get('canonical_worktree_path')}' does not match '{path.resolve()}'."
            )
        if marker_branch != ownership.branch:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': "
                f"Ownership marker branch '{marker_branch}' does not match durable '{ownership.branch}'."
            )
        if m_data.get("source_repository_identity") != ownership.source_repository_identity:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': "
                f"Ownership marker source_repository_identity '{m_data.get('source_repository_identity')}' does not match durable '{ownership.source_repository_identity}'."
            )
        if m_data.get("source_base_sha") != ownership.source_base_sha:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': "
                f"Ownership marker source_base_sha '{m_data.get('source_base_sha')}' does not match durable '{ownership.source_base_sha}'."
            )

    def _finalize_created_ownership(self, ownership: OrchestrationWorktreeOwnership | None) -> None:
        if not ownership or not self.uow:
            return
        repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        if not repo:
            return
        ownership.creation_state = WorktreeCreationState.CREATED
        ownership.updated_at = utc_now()
        repo.save(ownership)
        self._flush_uow()

    async def create_remediation_worktree(
        self,
        job_id: str,
        change_name: str,
        source_sha: str,
        generation: int,
        project_id: str | None = None,
        run_id: str | None = None,
    ) -> WorktreeInfo:
        """Create or reconcile a remediation workspace rooted at an immutable source SHA."""
        eff_project_id = self._resolve_project_id(project_id, job_id)
        eff_run_id = self._resolve_real_run_id(
            job_id, run_id, project_id=eff_project_id, change_name=change_name
        )
        eff_change_name = self._resolve_real_change_name(
            job_id, change_name, project_id=eff_project_id, run_id=eff_run_id
        )

        branch = f"minime/{eff_change_name}-{job_id}-remediation-gen{generation}"
        path = self.remediation_worktree_path(job_id, generation, eff_project_id).resolve()
        parent = self.resolve_worktree_parent_dir(eff_project_id).resolve()
        if parent not in path.parents:
            raise ValueError(f"Worktree path escapes managed root: {path}")

        # 1. Guard preflight before any persistence or filesystem side effect
        self._authorize_mutating_operation(eff_project_id, path, WorkspaceOperation.WORKTREE_CREATE)

        if path.exists():
            await self._verify_worktree_adoption_proof(
                path=path,
                job_id=job_id,
                eff_project_id=eff_project_id,
                eff_run_id=eff_run_id,
                eff_change_name=eff_change_name,
                expected_branch=branch,
                expected_base_sha=source_sha,
                require_clean=False,
                worktree_kind="remediation worktree",
            )
            return WorktreeInfo(path, branch, source_sha)

        # 2. Mandatory durable PENDING ownership before git worktree add
        ownership = self._persist_pending_ownership(
            job_id,
            eff_project_id,
            path,
            branch=branch,
            run_id=eff_run_id,
            change_name=eff_change_name,
            source_base_sha=source_sha,
        )

        try:
            await self._git(["rev-parse", "--verify", f"refs/heads/{branch}"])
            raise RuntimeError(
                f"Remediation branch already exists without its managed worktree: {branch}"
            )
        except RuntimeError as exc:
            if "already exists without" in str(exc):
                raise

        # 3. ONLY THEN execute git worktree add
        await self._git(
            ["worktree", "add", "-b", branch, str(path), source_sha],
            cwd=self.project_root,
            job_id=job_id,
            project_id=eff_project_id,
            operation_type="remediation_worktree_add",
            managed_worktree_path=path,
        )

        # 4. Write marker, prove postconditions, and transition to CREATED
        self._write_ownership_marker(path, ownership)
        await self._verify_creation_postconditions(
            path, ownership, expected_branch=branch, expected_base_sha=source_sha
        )
        self._finalize_created_ownership(ownership)

        return WorktreeInfo(path, branch, source_sha)

    async def create_review_worktree(
        self,
        job_id: str,
        change_name: str,
        candidate_sha: str,
        reviewer_role: str,
        project_id: str | None = None,
        run_id: str | None = None,
    ) -> WorktreeInfo:
        """Create or reconcile an isolated reviewer/auditor execution workspace derived from candidate_sha."""
        eff_project_id = self._resolve_project_id(project_id, job_id)
        eff_run_id = self._resolve_real_run_id(
            job_id, run_id, project_id=eff_project_id, change_name=change_name
        )
        eff_change_name = self._resolve_real_change_name(
            job_id, change_name, project_id=eff_project_id, run_id=eff_run_id
        )

        sanitized_role = reviewer_role.replace("/", "_").replace("\\", "_").replace(":", "_")
        short_sha = candidate_sha[:8] if candidate_sha else ""
        suffix = f"-{short_sha}" if short_sha else ""
        branch = f"minime/{eff_change_name}-{job_id}-review-{sanitized_role}{suffix}"
        path = self.review_worktree_path(
            job_id, reviewer_role, eff_project_id, candidate_sha=candidate_sha
        ).resolve()
        parent = self.resolve_worktree_parent_dir(eff_project_id).resolve()
        if parent not in path.parents:
            raise ValueError(f"Worktree path escapes managed root: {path}")

        # 1. Guard preflight evaluation before any persistence or filesystem side effect
        self._authorize_mutating_operation(eff_project_id, path, WorkspaceOperation.WORKTREE_CREATE)

        if path.exists():
            await self._verify_worktree_adoption_proof(
                path=path,
                job_id=job_id,
                eff_project_id=eff_project_id,
                eff_run_id=eff_run_id,
                eff_change_name=eff_change_name,
                expected_branch=branch,
                expected_base_sha=candidate_sha,
                require_clean=False,
                worktree_kind="review worktree",
            )
            return WorktreeInfo(path, branch, candidate_sha)

        # 2. Mandatory durable PENDING ownership before git worktree add
        ownership = self._persist_pending_ownership(
            job_id,
            eff_project_id,
            path,
            branch=branch,
            run_id=eff_run_id,
            change_name=eff_change_name,
            source_base_sha=candidate_sha,
        )

        branch_exists = False
        try:
            await self._git(["rev-parse", "--verify", f"refs/heads/{branch}"])
            branch_exists = True
        except Exception:
            branch_exists = False

        cmd = (
            ["worktree", "add", str(path), branch]
            if branch_exists
            else ["worktree", "add", "-b", branch, str(path), candidate_sha]
        )

        # 3. ONLY THEN execute git worktree add
        await self._git(
            cmd,
            cwd=self.project_root,
            job_id=job_id,
            project_id=eff_project_id,
            operation_type="review_worktree_add",
            managed_worktree_path=path,
        )

        # 4. Write marker, prove postconditions, and transition to CREATED
        self._write_ownership_marker(path, ownership)
        await self._verify_creation_postconditions(
            path, ownership, expected_branch=branch, expected_base_sha=candidate_sha
        )
        self._finalize_created_ownership(ownership)

        return WorktreeInfo(path, branch, candidate_sha)

    async def changed_paths_since(
        self, worktree_path: str | Path, source_sha: str
    ) -> tuple[str, ...]:
        """Return committed, staged, unstaged and untracked paths relative to source."""
        path = Path(worktree_path).resolve()
        diff = await self._git(["diff", "--name-only", source_sha], cwd=path)
        committed = await self._git(["diff", "--name-only", f"{source_sha}..HEAD"], cwd=path)
        status = await self._git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=path)
        found = {line.strip() for line in (diff + "\n" + committed).splitlines() if line.strip()}
        found.update(
            line[3:].strip() for line in status.splitlines() if len(line) >= 4 and line[3:].strip()
        )
        found = {p for p in found if "minime_worktree_ownership.json" not in p}
        return tuple(sorted(found))

    async def _verify_worktree_adoption_proof(
        self,
        *,
        path: Path,
        job_id: str,
        eff_project_id: str,
        eff_run_id: str,
        eff_change_name: str,
        expected_branch: str,
        expected_base_sha: str | None = None,
        require_clean: bool = True,
        worktree_kind: str = "worktree",
    ) -> None:
        ownership_repo = (
            getattr(self.uow, "orchestration_worktree_ownerships", None) if self.uow else None
        )
        ownership = (
            ownership_repo.get_by_canonical_path(str(path.resolve())) if ownership_repo else None
        )
        if not ownership and ownership_repo and hasattr(ownership_repo, "get_by_job_id"):
            cand = ownership_repo.get_by_job_id(job_id)
            if cand and str(Path(cand.canonical_worktree_path).resolve()) == str(path.resolve()):
                ownership = cand

        binding_repo = (
            getattr(self.uow, "project_managed_repository_bindings", None) if self.uow else None
        )
        binding = binding_repo.get_by_project_id(eff_project_id) if binding_repo else None

        if not ownership:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': No durable OrchestrationWorktreeOwnership record found."
            )
        if ownership.creation_state != WorktreeCreationState.CREATED:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Worktree creation state is '{ownership.creation_state.value}', not CREATED."
            )
        if getattr(ownership, "has_synthetic_placeholder", False):
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Durable ownership record contains synthetic placeholders."
            )
        if ownership.project_id != eff_project_id:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Project ID '{ownership.project_id}' does not match expected '{eff_project_id}'."
            )
        if ownership.job_id != job_id:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Job ID '{ownership.job_id}' does not match expected '{job_id}'."
            )
        if ownership.run_id != eff_run_id:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Run ID '{ownership.run_id}' does not match durable '{eff_run_id}'."
            )
        if ownership.change_name != eff_change_name:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Change name '{ownership.change_name}' does not match durable '{eff_change_name}'."
            )
        if str(Path(ownership.canonical_worktree_path).resolve()) != str(path.resolve()):
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Canonical path '{ownership.canonical_worktree_path}' does not match '{path.resolve()}'."
            )
        if ownership.branch != expected_branch:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Branch '{ownership.branch}' does not match expected '{expected_branch}'."
            )
        if not binding:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': No valid ProjectManagedRepositoryBinding found for project '{eff_project_id}'."
            )
        if ownership.source_repository_identity != binding.canonical_repository_identity:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Source repository identity '{ownership.source_repository_identity}' does not match binding '{binding.canonical_repository_identity}'."
            )
        if not ownership.source_base_sha or not str(ownership.source_base_sha).strip():
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Durable ownership record has empty source_base_sha."
            )

        if expected_base_sha:
            try:
                resolved_expected = (
                    await self._git(["rev-parse", expected_base_sha], cwd=self.project_root)
                ).strip()
            except Exception:
                resolved_expected = expected_base_sha.strip()

            try:
                resolved_ownership_base = (
                    await self._git(["rev-parse", ownership.source_base_sha], cwd=self.project_root)
                ).strip()
            except Exception:
                resolved_ownership_base = ownership.source_base_sha.strip()

            if (
                ownership.source_base_sha != expected_base_sha
                and resolved_ownership_base != resolved_expected
            ):
                raise RuntimeError(
                    f"Refusing to adopt existing {worktree_kind} at '{path}': Source base SHA '{ownership.source_base_sha}' does not match expected '{expected_base_sha}'."
                )

        try:
            wt_list_out = await self._git(
                ["worktree", "list", "--porcelain"], cwd=self.project_root
            )
            wt_paths = [
                str(Path(line[9:].strip()).resolve())
                for line in wt_list_out.splitlines()
                if line.startswith("worktree ")
            ]
            if str(path.resolve()) not in wt_paths:
                raise RuntimeError(
                    f"Refusing to adopt existing {worktree_kind} at '{path}': Path '{path}' is not present in git worktree list."
                )

            from minime.services.workspace_guard import ManagedWorkspaceGuard

            guard = self.workspace_guard or ManagedWorkspaceGuard(self.uow)
            git_ok, git_reason = guard.verify_git_repository_identity(
                str(path.resolve()), binding.canonical_repository_identity, binding.remote_name
            )
            if not git_ok:
                raise RuntimeError(
                    f"Refusing to adopt existing {worktree_kind} at '{path}': Git identity verification failed: {git_reason}"
                )

            self._verify_ownership_marker(path, ownership, worktree_kind=worktree_kind)

            actual_branch = (await self._git(["branch", "--show-current"], cwd=path)).strip()
            if actual_branch != expected_branch:
                raise RuntimeError(
                    f"Refusing to adopt existing {worktree_kind} at '{path}': Actual branch '{actual_branch}' does not match expected '{expected_branch}'."
                )

            actual_sha = await self.current_sha(path)
            if not actual_sha or not actual_sha.strip():
                raise RuntimeError(
                    f"Refusing to adopt existing {worktree_kind} at '{path}': Observable worktree HEAD SHA is unobservable or empty."
                )
            actual_sha = actual_sha.strip()

            eff_expected_base = expected_base_sha or ownership.source_base_sha
            try:
                resolved_expected_sha = (
                    await self._git(["rev-parse", eff_expected_base], cwd=self.project_root)
                ).strip()
            except Exception:
                resolved_expected_sha = eff_expected_base.strip()

            if actual_sha != resolved_expected_sha and actual_sha != eff_expected_base.strip():
                has_candidate_proof = False
                if self.uow:
                    if hasattr(self.uow, "jobs") and self.uow.jobs:
                        j = self.uow.jobs.get_by_id(job_id)
                        if j and getattr(j, "candidate_sha", None) == actual_sha:
                            has_candidate_proof = True
                    if (
                        not has_candidate_proof
                        and hasattr(self.uow, "orchestration_runs")
                        and self.uow.orchestration_runs
                    ):
                        r = self.uow.orchestration_runs.get_by_id(job_id) or (
                            self.uow.orchestration_runs.get_by_job_id(job_id)
                            if hasattr(self.uow.orchestration_runs, "get_by_job_id")
                            else None
                        )
                        if r:
                            cand_sha = getattr(r, "candidate_sha", None) or getattr(
                                r, "current_candidate_sha", None
                            )
                            if cand_sha == actual_sha:
                                has_candidate_proof = True
                if not has_candidate_proof:
                    raise RuntimeError(
                        f"Refusing to adopt existing {worktree_kind} at '{path}': "
                        f"Actual HEAD SHA '{actual_sha}' does not match expected base SHA '{eff_expected_base}' "
                        f"and is not backed by durable candidate evidence."
                    )

            if require_clean:
                state = await self.inspect_worktree_state(path)
                if state.dirty:
                    raise RuntimeError(
                        f"Refusing to adopt existing {worktree_kind} at '{path}': Existing integration worktree is dirty: {path}"
                    )
        except RuntimeError:
            raise
        except Exception as err:
            raise RuntimeError(
                f"Refusing to adopt existing {worktree_kind} at '{path}': Adoption check failed: {err}"
            )

    async def _verify_deleted_worktree_recreation(
        self,
        *,
        job_id: str,
        project_id: str,
        run_id: str,
        change_name: str,
        path: Path,
        branch: str,
        base_branch: str,
        current_base_sha: str,
    ) -> str | None:
        """Prove a DELETED worktree's exact recovery branch before reactivation."""
        ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        ownership = ownership_repo.get_by_job_id(job_id) if ownership_repo else None
        if not ownership or ownership.creation_state not in {
            WorktreeCreationState.DELETED,
            WorktreeCreationState.CREATED,
        }:
            return None
        is_created_recovery = ownership.creation_state == WorktreeCreationState.CREATED

        def refuse(reason: str) -> None:
            raise RuntimeError(f"Deleted worktree recreation denied: {reason}")

        if is_created_recovery:
            if not path.is_dir() or path.is_symlink():
                refuse("the durably CREATED recovery worktree path is missing or unsafe.")
        elif path.exists() or path.is_symlink():
            refuse("the durably DELETED worktree path is not absent.")
        if str(Path(ownership.canonical_worktree_path).resolve()) != str(path.resolve()):
            refuse("durable canonical path does not match the derived job path.")
        if (
            ownership.project_id != project_id
            or ownership.job_id != job_id
            or ownership.run_id != run_id
            or ownership.change_name != change_name
            or ownership.branch != branch
        ):
            refuse("project, job, run, change, or persisted branch identity conflicts.")

        binding_repo = getattr(self.uow, "project_managed_repository_bindings", None)
        binding = binding_repo.get_by_project_id(project_id) if binding_repo else None
        from minime.services.workspace_guard import ManagedWorkspaceGuard, is_binding_fully_valid

        if not is_binding_fully_valid(binding):
            refuse("the project-managed repository binding is not valid.")
        if binding.canonical_repository_identity != ownership.source_repository_identity:
            refuse("the durable source repository identity conflicts with the project binding.")
        guard = self.workspace_guard or ManagedWorkspaceGuard(self.uow)
        git_ok, git_reason = guard.verify_git_repository_identity(
            str(self.project_root), binding.canonical_repository_identity, binding.remote_name
        )
        if not git_ok:
            refuse(f"managed repository identity could not be verified: {git_reason}")

        canonical_base_branch = base_branch
        remote_name = binding.remote_name or "origin"
        remote_prefix = f"{remote_name}/"
        if canonical_base_branch.startswith(remote_prefix):
            canonical_base_branch = canonical_base_branch[len(remote_prefix) :]
        elif canonical_base_branch.startswith("origin/"):
            canonical_base_branch = canonical_base_branch.removeprefix("origin/")
        project_repo = getattr(self.uow, "projects", None)
        project = project_repo.get_by_id(project_id) if project_repo else None
        if not project or not project.base_branch:
            refuse("the project's canonical base branch is unavailable.")
        declared_base_branch = project.base_branch.removeprefix("refs/heads/")
        for prefix in (remote_prefix, "origin/"):
            if declared_base_branch.startswith(prefix):
                declared_base_branch = declared_base_branch.removeprefix(prefix)
        if declared_base_branch != canonical_base_branch:
            refuse("requested base branch conflicts with the project's canonical base branch.")
        remote_ref = f"refs/heads/{canonical_base_branch}"
        try:
            remote_observation = await self._git(
                ["ls-remote", remote_name, remote_ref], project_id=project_id
            )
        except Exception as exc:
            refuse(f"canonical remote base ref could not be verified: {exc}")
        remote_lines = [line.split() for line in remote_observation.splitlines() if line.strip()]
        if len(remote_lines) != 1 or len(remote_lines[0]) != 2 or remote_lines[0][1] != remote_ref:
            refuse("canonical remote base ref observation was missing or ambiguous.")
        remote_base_sha = remote_lines[0][0]
        observation_ref = f"refs/minime/observed-base/{uuid.uuid4().hex}"
        try:
            if remote_base_sha != current_base_sha:
                # Resolve a stale-but-not-divergent managed ref using the
                # existing authenticated Git authority. Fetch only the exact
                # observed base into a disposable private ref; never move the
                # managed base branch or its working tree.
                await self._git(
                    [
                        "fetch",
                        "--no-tags",
                        "--no-write-fetch-head",
                        remote_name,
                        f"{remote_ref}:{observation_ref}",
                    ],
                    project_id=project_id,
                )
                fetched_sha = (
                    await self._git(
                        ["rev-parse", "--verify", f"{observation_ref}^{{commit}}"],
                        cwd=self.project_root,
                    )
                ).strip()
                if fetched_sha != remote_base_sha:
                    refuse(
                        "canonical remote base changed between observation and authenticated fetch."
                    )
            else:
                fetched_sha = remote_base_sha
        except Exception:
            refuse("authoritative remote base could not be resolved consistently.")
        finally:
            try:
                await self._git(["update-ref", "-d", observation_ref], cwd=self.project_root)
            except Exception:
                # The observation ref is disposable and is never used as
                # authority by a later invocation.
                pass

        # The recovery branch remains rooted in its original, durable base B.
        # A later main tip C is acceptable only as an observed descendant; it
        # must never replace B in ownership, Run/Job, or WorktreeInfo lineage.
        source_base = ownership.source_base_sha
        if not source_base:
            refuse("durable original base is missing.")
        try:
            resolved_source_base = (
                await self._git(
                    ["rev-parse", "--verify", f"{source_base}^{{commit}}"],
                    cwd=self.project_root,
                )
            ).strip()
            if resolved_source_base != source_base:
                refuse("durable original base is not an exact local commit identity.")
            await self._git(
                ["merge-base", "--is-ancestor", source_base, fetched_sha],
                cwd=self.project_root,
            )
        except Exception:
            refuse("authoritative current base is not provably a descendant of the original base.")
        try:
            await self._git(
                ["merge-base", "--is-ancestor", current_base_sha, fetched_sha],
                cwd=self.project_root,
            )
        except Exception:
            refuse("local managed base branch diverges from the authoritative remote base.")

        job = self.uow.jobs.get_by_id(job_id)
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if (
            not job
            or job.project_id != project_id
            or job.change_name != change_name
            # RecoveryConvergenceService first converts an interrupted RUNNING
            # execution to QUEUED, or a prior environment stop to
            # WAITING_CAPACITY, before OrchestrationService resumes the same
            # run. That canonical checkpoint is valid only with all the run,
            # attempt, ownership, and snapshot proofs enforced below.
            or job.status
            not in {
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                JobStatus.NEEDS_HUMAN,
                JobStatus.WAITING_CAPACITY,
                JobStatus.FAILED,
            }
        ):
            refuse("the linked job identity or resumable status is inconsistent.")
        if (
            not run
            or run.project_id != project_id
            or run.change_name != change_name
            or run.active_job_id != job_id
            or run.current_stage != OrchestrationStage.IMPLEMENTING
        ):
            refuse("the linked orchestration run identity or stage is inconsistent.")
        if run.stop_outcome in {
            OrchestrationStopOutcome.COMPLETED,
            OrchestrationStopOutcome.CANCELLED,
        }:
            refuse("the linked orchestration run is terminal and cannot be reconstructed.")
        if job.candidate_sha or run.current_candidate_sha:
            refuse("candidate evidence exists; this no-candidate recovery path cannot be used.")

        if run.base_sha != source_base or (job.base_sha and job.base_sha != source_base):
            refuse("base SHA conflicts with durable run/job/worktree lineage.")

        attempts_repo = getattr(self.uow, "job_attempts", None)
        attempts = attempts_repo.list_by_job(job_id) if attempts_repo else []
        if not attempts:
            refuse(
                "the latest durable attempt does not prove a recoverable initialization failure."
            )
        # Preserve the pre-existing ordering/acceptance behavior for ordinary
        # environment/provider initialization failures. The new exceptional
        # PREMATURE_STOP route requires a unique latest attempt identity.
        latest_attempt = attempts[-1]
        ordinary_recovery_outcome = latest_attempt.normalized_outcome in {
            ExecutionOutcome.ENVIRONMENT_UNAVAILABLE,
            ExecutionOutcome.PROVIDER_FAILURE,
        }
        latest_attempt_number = max(attempt.attempt_number for attempt in attempts)
        latest_attempts = [
            attempt for attempt in attempts if attempt.attempt_number == latest_attempt_number
        ]
        crash_interrupted_recovery = (
            is_created_recovery
            and len(latest_attempts) == 1
            and latest_attempt.attempt_number == latest_attempt_number
            and self._has_durable_crash_interruption_recovery(
                latest_attempt=latest_attempt,
                job=job,
                run=run,
                source_base=source_base,
                project_id=project_id,
                change_name=change_name,
            )
        )
        if not ordinary_recovery_outcome and not crash_interrupted_recovery:
            refuse(
                "the latest durable attempt does not prove an environment/provider initialization failure or an evidenced crash-interrupted CREATED recovery."
            )

        if (
            await self._git(["check-ref-format", "--branch", branch], cwd=self.project_root)
        ).strip() != branch:
            refuse("persisted recovery branch is not a valid local branch name.")
        ref = f"refs/heads/{branch}"
        try:
            branch_sha = (
                await self._git(["rev-parse", "--verify", ref], cwd=self.project_root)
            ).strip()
        except Exception as exc:
            refuse(f"persisted recovery branch is not observable: {exc}")
        if not branch_sha:
            refuse("persisted recovery branch has no observable commit.")
        if is_created_recovery:
            try:
                worktrees = await self._git(
                    ["worktree", "list", "--porcelain"], cwd=self.project_root
                )
                registered_paths = {
                    str(Path(line.removeprefix("worktree ").strip()).resolve())
                    for line in worktrees.splitlines()
                    if line.startswith("worktree ")
                }
                if str(path.resolve()) not in registered_paths:
                    refuse("the CREATED path is not registered by the canonical Git worktree.")
                self._verify_ownership_marker(path, ownership, worktree_kind="recovery worktree")
                actual_branch = (await self._git(["branch", "--show-current"], cwd=path)).strip()
                actual_head = (await self.current_sha(path)).strip()
                if actual_branch != branch or actual_head != branch_sha:
                    refuse(
                        "the CREATED worktree branch or snapshot HEAD conflicts with durable Git evidence."
                    )
                git_ok, git_reason = guard.verify_git_repository_identity(
                    str(path.resolve()), binding.canonical_repository_identity, binding.remote_name
                )
                if not git_ok:
                    refuse(f"CREATED worktree Git identity could not be verified: {git_reason}")
                status_output = await self._git(
                    ["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=path
                )
                artifact_prefix = f"openspec/changes/{change_name}/"
                for record in (entry for entry in status_output.split("\0") if entry):
                    if len(record) < 4:
                        refuse("CREATED recovery worktree status is malformed.")
                    index_status, worktree_status = record[0], record[1]
                    changed_path = record[3:]
                    if (
                        index_status != " "
                        or worktree_status not in {" ", "M"}
                        or not changed_path.startswith(artifact_prefix)
                    ):
                        refuse(
                            "CREATED recovery worktree contains changes outside the historical artifact tree."
                        )
            except RuntimeError:
                raise
            except Exception:
                refuse("CREATED recovery worktree registration or marker is unobservable.")
        if branch_sha == source_base:
            refuse("recovery branch has no distinct durable snapshot commit.")

        try:
            parent_sha = (
                await self._git(["rev-parse", f"{branch_sha}^"], cwd=self.project_root)
            ).strip()
            commit_count = (
                await self._git(
                    ["rev-list", "--count", f"{source_base}..{branch_sha}"], cwd=self.project_root
                )
            ).strip()
            subject = (
                await self._git(["show", "-s", "--format=%s", branch_sha], cwd=self.project_root)
            ).strip()
            author = (
                await self._git(
                    ["show", "-s", "--format=%an%x00%ae", branch_sha], cwd=self.project_root
                )
            ).strip()
            changed = {
                line.strip()
                for line in (
                    await self._git(
                        ["diff", "--name-only", f"{source_base}..{branch_sha}"],
                        cwd=self.project_root,
                    )
                ).splitlines()
                if line.strip()
            }
            tree_lines = (
                await self._git(
                    ["ls-tree", "-r", branch_sha, "--", f"openspec/changes/{change_name}/"],
                    cwd=self.project_root,
                )
            ).splitlines()
        except Exception as exc:
            refuse(f"recovery commit evidence is not observable: {exc}")

        authorized_prefix = f"openspec/changes/{change_name}/"
        if (
            parent_sha != source_base
            or commit_count != "1"
            or subject != f"mini me recovery snapshot for {job_id}"
            or author != "mini me recovery\x00mini-me-recovery@localhost"
            or not changed
            or any(not item.startswith(authorized_prefix) for item in changed)
            or any(not line.startswith("100644 blob ") for line in tree_lines)
        ):
            refuse(
                "branch tip is not one exact artifact-only recovery snapshot rooted at the original base."
            )

        events_repo = getattr(self.uow, "events", None)
        events = (
            events_repo.list_events(project_id=project_id, change_id=change_name, limit=1000)
            if events_repo
            else []
        )
        recovery_events = [
            event
            for event in events
            if event.event_type == EventType.WORKTREE_RECOVERY_SNAPSHOT
            and event.payload.get("job_id") == job_id
            and event.payload.get("branch") == branch
            and event.payload.get("recovery_sha") == branch_sha
            and str(Path(event.payload.get("worktree_path", "")).resolve()) == str(path.resolve())
        ]
        if len(recovery_events) != 1:
            refuse(
                "no unique durable recovery-snapshot event binds this exact branch SHA and path."
            )
        try:
            final_remote_observation = await self._git(
                ["ls-remote", remote_name, remote_ref], project_id=project_id
            )
        except Exception:
            refuse("canonical remote base could not be re-observed before recreation.")
        final_remote_lines = [
            line.split() for line in final_remote_observation.splitlines() if line.strip()
        ]
        if (
            len(final_remote_lines) != 1
            or len(final_remote_lines[0]) != 2
            or final_remote_lines[0][1] != remote_ref
            or final_remote_lines[0][0] != remote_base_sha
        ):
            refuse("canonical remote base changed during recreation validation.")
        return branch_sha

    def _has_durable_crash_interruption_recovery(
        self,
        *,
        latest_attempt: Any,
        job: Any,
        run: Any,
        source_base: str,
        project_id: str,
        change_name: str,
    ) -> bool:
        """Recognize an unfinished attempt followed by canonical on-demand Run recovery.

        JOB_RECOVERED is emitted by RecoveryConvergenceService after Control Plane
        CONTINUE obtains the Run claim. It is not, by itself, proof of a host crash:
        the incomplete PREMATURE_STOP, attempt/counter relation, exact Run/Job
        linkage, CREATED snapshot, publication, and Git checks in the caller are
        all required as corroborating evidence.
        """
        if (
            latest_attempt.normalized_outcome != ExecutionOutcome.PREMATURE_STOP
            or latest_attempt.completed_at is not None
            or latest_attempt.duration_ms is not None
            or latest_attempt.attempt_number != job.attempt_count + 1
            or job.project_id != project_id
            or job.change_name != change_name
            or job.candidate_sha is not None
            or run.project_id != project_id
            or run.change_name != change_name
            or run.active_job_id != job.job_id
            or run.current_stage != OrchestrationStage.IMPLEMENTING
            or run.current_generation < 1
            or run.current_candidate_sha is not None
            or run.base_sha != source_base
            or (job.base_sha and job.base_sha != source_base)
        ):
            return False

        events_repo = getattr(self.uow, "events", None)
        if not events_repo:
            return False
        events = events_repo.list_events(project_id=project_id, change_id=change_name, limit=10000)
        recovery_events = [event for event in events if event.timestamp > latest_attempt.started_at]
        recovered_jobs = [
            event
            for event in recovery_events
            if event.event_type == EventType.JOB_RECOVERED and event.operation_id == job.job_id
        ]
        if not recovered_jobs:
            return False

        # This payload is produced only by the canonical run-continuation
        # recovery branch. Require its source, linked Run and generation, rather
        # than treating an arbitrary/old JOB_RECOVERED as authorization.
        latest_recovery = max(recovered_jobs, key=lambda event: event.timestamp)
        valid_latest_recovery = (
            latest_recovery.project_id == project_id
            and latest_recovery.change_id == change_name
            and latest_recovery.payload.get("job_id") == job.job_id
            and latest_recovery.payload.get("run_id") == run.run_id
            and latest_recovery.payload.get("run_generation") == run.current_generation
            and latest_recovery.payload.get("recovery_source") == "CONTROL_PLANE"
            and latest_recovery.payload.get("interrupted_stage") == "implementer"
            and latest_recovery.payload.get("recovered_status") == JobStatus.QUEUED.value
            and latest_recovery.payload.get("recovery_cycle_id")
        )
        if not valid_latest_recovery:
            return False

        decisions_repo = getattr(self.uow, "recovery_decisions", None)
        if not decisions_repo or not callable(getattr(decisions_repo, "list_by_cycle", None)):
            return False
        canonical_decisions = decisions_repo.list_by_cycle(
            latest_recovery.payload["recovery_cycle_id"]
        )
        if len(canonical_decisions) != 1:
            return False
        decision = canonical_decisions[0]
        if (
            decision.claim_key != f"run:{run.run_id}"
            or decision.identity_type != "RUN"
            or decision.identity_id != run.run_id
            or decision.project_id != project_id
            or decision.change_name != change_name
            or getattr(decision.source, "value", decision.source) != "CONTROL_PLANE"
            or decision.planned_action != "DRIVE_CONTINUATION"
            or getattr(decision.status, "value", decision.status) != "EXECUTING"
            or not decision.fence_token
        ):
            return False

        claims_repo = getattr(self.uow, "claims", None)
        if (
            not claims_repo
            or not callable(getattr(claims_repo, "get_by_key", None))
            or not callable(getattr(claims_repo, "validate_cas", None))
        ):
            return False
        claim = claims_repo.get_by_key(decision.claim_key)
        if (
            not claim
            or not claim.is_active
            or claim.fence_token != decision.fence_token
            or not claims_repo.validate_cas(
                claim_key=decision.claim_key,
                owner_instance_id=claim.owner_instance_id,
                fence_token=decision.fence_token,
            )
        ):
            return False

        # Unresolved or candidate-bearing actions contradict the no-candidate
        # recovery case; completed non-candidate history is retained.
        actions_repo = getattr(self.uow, "orchestration_external_actions", None)
        if not actions_repo or not callable(getattr(actions_repo, "list_by_run", None)):
            return False
        for action in actions_repo.list_by_run(run.run_id):
            action_status = getattr(action.status, "value", action.status)
            if action.candidate_sha or action_status in {
                "RESERVED",
                "EXECUTING",
                "UNKNOWN",
                "AMBIGUOUS",
            }:
                return False
        return True

    async def create_worktree(
        self,
        job_id: str,
        change_name: str,
        base_branch: str,
        project_id: str | None = None,
        branch_name: str | None = None,
        reuse_existing: bool = False,
        run_id: str | None = None,
    ) -> WorktreeInfo:
        path = self.worktree_path(job_id, project_id).resolve()
        parent = self.resolve_worktree_parent_dir(project_id).resolve()
        if parent not in path.parents:
            raise ValueError(f"Worktree path escapes managed root: {path}")
        if path.exists() and any(path.iterdir()) and not reuse_existing:
            raise ValueError(f"Worktree path already exists and is not empty: {path}")

        # 1. Guard preflight evaluation before any mutation side effect
        self._authorize_mutating_operation(project_id, path, WorkspaceOperation.WORKTREE_CREATE)

        base_sha_raw = await self._git(["rev-parse", base_branch])
        if inspect.isawaitable(base_sha_raw):
            base_sha_raw = await base_sha_raw
        base_sha = (
            str(base_sha_raw).strip()
            if isinstance(base_sha_raw, str)
            else (
                base_sha_raw.strip()
                if hasattr(base_sha_raw, "strip")
                else str(base_sha_raw or "").strip()
            )
        )
        if not base_sha:
            raise RuntimeError(
                f"Failing closed: base_sha for base_branch '{base_branch}' is unobservable or empty."
            )

        eff_project_id = self._resolve_project_id(project_id, job_id)
        eff_run_id = self._resolve_real_run_id(
            job_id, run_id, project_id=eff_project_id, change_name=change_name
        )
        eff_change_name = self._resolve_real_change_name(
            job_id, change_name, project_id=eff_project_id, run_id=eff_run_id
        )
        requested_branch_name = branch_name
        recovered_head_sha = None
        worktree_ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        historical_ownership = (
            worktree_ownership_repo.get_by_job_id(job_id) if worktree_ownership_repo else None
        )
        recreation_source_base = None
        recovery_snapshot_sha = None
        recovery_event_candidate = False
        if historical_ownership and historical_ownership.creation_state in {
            WorktreeCreationState.DELETED,
            WorktreeCreationState.CREATED,
        }:
            if historical_ownership.creation_state == WorktreeCreationState.CREATED:
                events_repo = getattr(self.uow, "events", None)
                prior_events = (
                    events_repo.list_events(
                        project_id=eff_project_id, change_id=eff_change_name, limit=1000
                    )
                    if events_repo
                    else []
                )
                recovery_event_candidate = any(
                    event.event_type == EventType.WORKTREE_RECOVERY_SNAPSHOT
                    and event.payload.get("job_id") == job_id
                    for event in prior_events
                )
            should_verify_recovery = (
                historical_ownership.creation_state == WorktreeCreationState.DELETED
                or recovery_event_candidate
            )
        else:
            should_verify_recovery = False

        if should_verify_recovery:
            if requested_branch_name and requested_branch_name != historical_ownership.branch:
                raise RuntimeError(
                    "Recovery worktree adoption denied: caller branch differs from persisted branch identity."
                )
            branch_name = historical_ownership.branch
            if not eff_project_id or not eff_run_id:
                raise RuntimeError(
                    "Recovery worktree adoption denied: durable project/run identity is unavailable."
                )
            recovery_snapshot_sha = await self._verify_deleted_worktree_recreation(
                job_id=job_id,
                project_id=eff_project_id,
                run_id=eff_run_id,
                change_name=eff_change_name,
                path=path,
                branch=branch_name,
                base_branch=base_branch,
                current_base_sha=base_sha,
            )
            recovered_head_sha = recovery_snapshot_sha
            recreation_source_base = historical_ownership.source_base_sha
        else:
            branch_name = requested_branch_name or f"minime/{eff_change_name}-{job_id}"

        if path.exists():
            if not reuse_existing:
                if any(path.iterdir()):
                    raise ValueError(f"Worktree path already exists and is not empty: {path}")
            else:
                if recovery_snapshot_sha:
                    if not recovery_event_candidate:
                        raise RuntimeError(
                            "Recovery worktree adoption denied: existing CREATED path lacks a durable recovery snapshot event."
                        )
                    await self._materialize_verified_published_intake_artifacts(
                        destination_worktree=path,
                        project_id=eff_project_id,
                        change_name=eff_change_name,
                        job_id=job_id,
                        recovery_snapshot_sha=recovery_snapshot_sha,
                    )
                    return WorktreeInfo(
                        path=path,
                        branch_name=branch_name,
                        base_sha=recreation_source_base or base_sha,
                    )
                await self._verify_worktree_adoption_proof(
                    path=path,
                    job_id=job_id,
                    eff_project_id=eff_project_id,
                    eff_run_id=eff_run_id,
                    eff_change_name=eff_change_name,
                    expected_branch=branch_name,
                    expected_base_sha=base_sha,
                    require_clean=False,
                    worktree_kind="worktree",
                )
                return WorktreeInfo(path=path, branch_name=branch_name, base_sha=base_sha)

        if not run_id and self.uow and hasattr(self.uow, "jobs"):
            job = self.uow.jobs.get_by_id(job_id)
            if job and hasattr(job, "run_id") and job.run_id:
                run_id = job.run_id

        # 2. Mandatory durable PENDING ownership before git worktree add
        ownership = self._persist_pending_ownership(
            job_id,
            project_id,
            path,
            branch=branch_name,
            run_id=run_id,
            change_name=change_name,
            source_base_sha=recreation_source_base or base_sha,
        )

        branch_exists = False
        try:
            await self._git(["rev-parse", "--verify", f"refs/heads/{branch_name}"])
            branch_exists = True
        except Exception:
            branch_exists = False

        if branch_exists:
            cmd = ["worktree", "add", str(path), branch_name]
        else:
            cmd = ["worktree", "add", "-b", branch_name, str(path), base_branch]

        # 3. ONLY THEN execute git worktree add
        await self._git(
            cmd,
            cwd=self.project_root,
            job_id=job_id,
            project_id=project_id,
            operation_type="worktree_add",
            managed_worktree_path=path,
        )

        # 4. Write marker, prove postconditions, and transition to CREATED
        self._write_ownership_marker(path, ownership)
        await self._verify_creation_postconditions(
            path,
            ownership,
            expected_branch=branch_name,
            expected_base_sha=recreation_source_base or base_sha,
            expected_head_sha=recovered_head_sha,
        )
        self._finalize_created_ownership(ownership)

        await self._materialize_verified_published_intake_artifacts(
            destination_worktree=path,
            project_id=eff_project_id,
            change_name=change_name,
            job_id=job_id,
            recovery_snapshot_sha=recovery_snapshot_sha,
        )

        return WorktreeInfo(
            path=path,
            branch_name=branch_name,
            base_sha=recreation_source_base or base_sha,
        )

    async def current_sha(self, worktree_path: str | Path) -> str:
        return await self._git(["rev-parse", "HEAD"], cwd=Path(worktree_path))

    async def create_integration_worktree(
        self,
        job_id: str,
        branch_name: str,
        base_sha: str,
        generation: int,
        project_id: str | None = None,
        run_id: str | None = None,
        change_name: str | None = None,
        target_short_sha: str | None = None,
    ) -> WorktreeInfo:
        eff_project_id = self._resolve_project_id(project_id, job_id)
        if not eff_project_id:
            raise ValueError(
                f"Failing closed: project_id for job_id '{job_id}' cannot be observed."
            )

        suffix = f"-{target_short_sha}" if target_short_sha else ""
        path = (
            self.resolve_worktree_parent_dir(eff_project_id)
            / f"{job_id}-integration-gen{generation}{suffix}"
        ).resolve()
        parent = self.resolve_worktree_parent_dir(eff_project_id).resolve()
        if parent not in path.parents:
            raise ValueError(f"Integration worktree path escapes managed root: {path}")

        # 1. Guard preflight evaluation before any mutation side effect or directory checks
        self._authorize_mutating_operation(eff_project_id, path, WorkspaceOperation.WORKTREE_CREATE)

        eff_run_id = self._resolve_real_run_id(
            job_id, run_id, project_id=eff_project_id, change_name=change_name
        )
        eff_change_name = self._resolve_real_change_name(
            job_id, change_name, project_id=eff_project_id, run_id=eff_run_id
        )

        if path.exists():
            await self._verify_worktree_adoption_proof(
                path=path,
                job_id=job_id,
                eff_project_id=eff_project_id,
                eff_run_id=eff_run_id,
                eff_change_name=eff_change_name,
                expected_branch=branch_name,
                expected_base_sha=base_sha,
                require_clean=True,
                worktree_kind="integration worktree",
            )
            return WorktreeInfo(path, branch_name, base_sha)

        # 2. Mandatory durable PENDING ownership before git worktree add
        ownership = self._persist_pending_ownership(
            job_id,
            eff_project_id,
            path,
            branch=branch_name,
            run_id=eff_run_id,
            change_name=eff_change_name,
            source_base_sha=base_sha,
        )

        # 3. ONLY THEN execute git worktree add
        await self._git(
            ["worktree", "add", "-b", branch_name, str(path), base_sha],
            cwd=self.project_root,
            job_id=job_id,
            project_id=eff_project_id,
            operation_type="candidate_base_integration_worktree_add",
            managed_worktree_path=path,
        )

        # 4. Write marker, prove postconditions, and transition to CREATED
        self._write_ownership_marker(path, ownership)
        await self._verify_creation_postconditions(
            path, ownership, expected_branch=branch_name, expected_base_sha=base_sha
        )
        self._finalize_created_ownership(ownership)

        return WorktreeInfo(path, branch_name, base_sha)

    async def cherry_pick(
        self,
        worktree_path: str | Path,
        commits: list[str],
        job_id: str,
        project_id: str | None = None,
    ) -> str:
        path = Path(worktree_path).resolve()
        self._authorize_mutating_operation(
            project_id,
            path,
            WorkspaceOperation.GIT_COMMIT,
            require_created_ownership=True,
            job_id=job_id,
        )
        if commits:
            await self._git(
                ["cherry-pick", *commits],
                cwd=path,
                job_id=job_id,
                project_id=project_id,
                operation_type="candidate_base_integration_replay",
                managed_worktree_path=path,
            )
        return await self.current_sha(path)

    async def inspect_worktree_state(self, worktree_path: str | Path) -> WorktreeState:
        path = Path(worktree_path).resolve()
        status = await self._git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=path)
        status_lines = [
            line
            for line in status.splitlines()
            if len(line) >= 4 and line[3:].strip() and "minime_worktree_ownership.json" not in line
        ]
        files = tuple(sorted(line[3:] for line in status_lines))
        cached = await self._git(["diff", "--cached", "--binary"], cwd=path)
        unstaged = await self._git(["diff", "--binary"], cwd=path)
        untracked = await self._git(["ls-files", "--others", "--exclude-standard", "-z"], cwd=path)
        untracked_files = [
            p for p in untracked.split("\0") if p and "minime_worktree_ownership.json" not in p
        ]
        digest = hashlib.sha256()
        digest.update(cached.encode())
        digest.update(unstaged.encode())
        for relative in sorted(untracked_files):
            candidate = path / relative
            digest.update(relative.encode())
            if candidate.is_file():
                digest.update(candidate.read_bytes())
        return WorktreeState(dirty=bool(status_lines), fingerprint=digest.hexdigest(), files=files)

    async def working_state_fingerprint(self, worktree_path: str | Path) -> str:
        return (await self.inspect_worktree_state(worktree_path)).fingerprint

    async def create_recovery_snapshot(
        self, job_id: str, project_id: str | None = None
    ) -> str | None:
        path = self.worktree_path(job_id, project_id).resolve()
        self._authorize_mutating_operation(
            project_id,
            path,
            WorkspaceOperation.GIT_COMMIT,
            require_created_ownership=True,
            job_id=job_id,
        )
        state = await self.inspect_worktree_state(path)
        if not state.dirty:
            return None
        if await self._only_published_intake_repair_is_pending(path, job_id, project_id):
            # The exact published artifacts are an authoritative handoff view,
            # not implementation progress. Keep the original recovery commit
            # and branch untouched; the dirty CREATED worktree remains available
            # for a later authorized continuation.
            return None
        await self._git(
            ["add", "-A"],
            cwd=path,
            job_id=job_id,
            project_id=project_id,
            operation_type="recovery_snapshot_stage",
            managed_worktree_path=path,
        )
        await self._git(
            [
                "-c",
                "user.name=mini me recovery",
                "-c",
                "user.email=mini-me-recovery@localhost",
                "commit",
                "-m",
                f"mini me recovery snapshot for {job_id}",
            ],
            cwd=path,
            job_id=job_id,
            project_id=project_id,
            operation_type="recovery_snapshot_commit",
            managed_worktree_path=path,
        )
        return await self.current_sha(path)

    async def _only_published_intake_repair_is_pending(
        self, path: Path, job_id: str, project_id: str | None
    ) -> bool:
        """Recognize only a cleanly isolated, event-proven OpenSpec byte repair."""
        if not project_id or not self.uow:
            return False
        ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        events_repo = getattr(self.uow, "events", None)
        jobs_repo = getattr(self.uow, "jobs", None)
        runs_repo = getattr(self.uow, "orchestration_runs", None)
        if not all((ownership_repo, events_repo, jobs_repo, runs_repo)):
            return False
        ownership = ownership_repo.get_by_job_id(job_id)
        job = jobs_repo.get_by_id(job_id)
        run = runs_repo.get_by_id(ownership.run_id) if ownership else None
        if (
            not ownership
            or ownership.creation_state != WorktreeCreationState.CREATED
            or ownership.project_id != project_id
            or ownership.job_id != job_id
            or str(Path(ownership.canonical_worktree_path).resolve()) != str(path.resolve())
            or not job
            or job.candidate_sha
            or not run
            or run.active_job_id != job_id
            or run.current_candidate_sha
        ):
            return False
        try:
            if (
                await self._git(["branch", "--show-current"], cwd=path)
            ).strip() != ownership.branch:
                return False
            head_sha = (await self.current_sha(path)).strip()
            artifact_prefix = f"openspec/changes/{ownership.change_name}/"
            status = await self._git(
                ["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=path
            )
            changed_paths: set[str] = set()
            for record in (entry for entry in status.split("\0") if entry):
                if len(record) < 4 or record[:2] != " M":
                    return False
                changed_path = record[3:]
                if not changed_path.startswith(artifact_prefix):
                    return False
                changed_paths.add(changed_path[len(artifact_prefix) :])
        except Exception:
            return False
        if not changed_paths:
            return False
        events = events_repo.list_events(
            project_id=project_id, change_id=ownership.change_name, limit=10000
        )
        for event in events:
            if (
                event.event_type != EventType.INTAKE_ARTIFACT_HANDOFF_RECONCILED
                or event.operation_id != job_id
                or event.payload.get("worktree_id") != ownership.worktree_id
                or event.payload.get("recovery_snapshot_sha") != head_sha
                or event.payload.get("source_base_sha") != ownership.source_base_sha
            ):
                continue
            reconciled_paths = set(event.payload.get("reconciled_paths", []))
            published_digests = event.payload.get("published_blob_sha256", {})
            if not reconciled_paths or changed_paths != reconciled_paths:
                continue
            if set(published_digests) != reconciled_paths:
                continue
            try:
                if all(
                    hashlib.sha256((path / artifact_prefix / relative).read_bytes()).hexdigest()
                    == published_digests[relative]
                    for relative in reconciled_paths
                ):
                    return True
            except OSError:
                return False
        return False

    async def finalize_candidate_commit(
        self,
        worktree_path: str | Path,
        job_id: str,
        project_id: str | None = None,
        remediation_id: str | None = None,
        contract_hash: str | None = None,
    ) -> str:
        path = Path(worktree_path).resolve()
        self._authorize_mutating_operation(
            project_id,
            path,
            WorkspaceOperation.GIT_COMMIT,
            require_created_ownership=True,
            job_id=job_id,
        )
        state = await self.inspect_worktree_state(path)
        if state.dirty:
            await self._git(
                ["add", "-A"],
                cwd=path,
                job_id=job_id,
                project_id=project_id,
                operation_type="candidate_stage",
                managed_worktree_path=path,
            )
            commit_args = [
                "-c",
                "user.name=mini me",
                "-c",
                "user.email=mini-me@localhost",
                "commit",
                "-m",
                f"mini me authoritative candidate for {job_id}",
            ]
            if remediation_id and contract_hash:
                commit_args.extend(
                    [
                        "-m",
                        f"Mini-Me-Remediation: {remediation_id}\nMini-Me-Contract: {contract_hash}",
                    ]
                )
            await self._git(
                commit_args,
                cwd=path,
                job_id=job_id,
                project_id=project_id,
                operation_type="candidate_commit",
                managed_worktree_path=path,
            )
        return await self.current_sha(path)

    async def verify_remediation_commit(
        self,
        worktree_path: str | Path,
        source_sha: str,
        branch_name: str,
        remediation_id: str,
        contract_hash: str,
        authorized_paths: list[str],
    ) -> tuple[bool, str | None]:
        """Reconcile a post-commit crash only when Git proves exact remediation identity."""
        path = Path(worktree_path).resolve()
        actual_branch = (await self._git(["branch", "--show-current"], cwd=path)).strip()
        head = await self.current_sha(path)
        if actual_branch != branch_name or head == source_sha:
            return False, "Remediation branch or advanced HEAD is not present."
        parent = (await self._git(["rev-parse", "HEAD^"], cwd=path)).strip()
        if parent != source_sha:
            return False, "Remediation commit parent does not match source candidate."
        message = await self._git(["show", "-s", "--format=%B", "HEAD"], cwd=path)
        if (
            f"Mini-Me-Remediation: {remediation_id}" not in message
            or f"Mini-Me-Contract: {contract_hash}" not in message
        ):
            return False, "Remediation commit trailers do not match durable identity."
        changed = set(await self.changed_paths_since(path, source_sha))
        allowed = set(authorized_paths)
        if not changed or not changed.issubset(allowed):
            return (
                False,
                "Reconciled remediation commit changed paths outside its authorized scope.",
            )
        return True, head

    async def reconcile_remediation_worktree(
        self,
        job_id: str,
        change_name: str,
        source_sha: str,
        generation: int,
        remediation_id: str,
        contract_hash: str,
        authorized_paths: list[str],
        project_id: str | None = None,
    ) -> WorktreeInfo | None:
        """Adopt only an exact post-commit remediation workspace after a crash."""
        path = self.remediation_worktree_path(job_id, generation, project_id).resolve()
        if not path.exists():
            return None
        branch = f"minime/{change_name}-{job_id}-remediation-gen{generation}"
        head = await self.current_sha(path)
        if head == source_sha:
            return None
        valid, error = await self.verify_remediation_commit(
            path,
            source_sha,
            branch,
            remediation_id,
            contract_hash,
            authorized_paths,
        )
        if not valid:
            raise RuntimeError(error or "Remediation commit reconciliation failed.")
        return WorktreeInfo(path, branch, source_sha)

    async def cleanup_worktree(
        self, job_id: str, project_id: str | None = None
    ) -> WorktreeCleanupResult:
        """Compatibility alias that removes clean worktree path."""
        return await self.remove_clean_worktree(job_id, project_id)

    async def remove_clean_worktree(
        self, job_id: str, project_id: str | None = None
    ) -> WorktreeCleanupResult:
        """Remove a managed worktree only after independently proving it is clean."""
        return await self.remove_clean_worktree_path(
            self.worktree_path(job_id, project_id), job_id, project_id
        )

    async def remove_clean_worktree_path(
        self,
        worktree_path: str | Path,
        job_id: str,
        project_id: str | None = None,
    ) -> WorktreeCleanupResult:
        if not project_id:
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.POLICY_DENIED,
                provider_detail="project_id is mandatory for managed worktree operations.",
            )

        path = Path(worktree_path).resolve()
        if not path.exists():
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.SUCCESS,
                reason_code=ExternalReasonCode.ALREADY_ABSENT,
                provider_detail=f"Worktree path '{path}' is already absent.",
            )

        # Guard authorization before deleting
        try:
            self._authorize_mutating_operation(
                project_id,
                path,
                WorkspaceOperation.WORKTREE_DELETE,
                require_created_ownership=True,
                job_id=job_id,
            )
        except (RuntimeError, ValueError) as exc:
            logger.warning(f"Refusing deletion of directory at '{path}': {exc}")
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.POLICY_DENIED,
                provider_detail=f"Guard denied deletion: {exc}",
            )

        canonical_path = str(path)

        # 4-Way Cleanup Reconciliation: Require durable OrchestrationWorktreeOwnership
        ownership_repo = (
            getattr(self.uow, "orchestration_worktree_ownerships", None) if self.uow else None
        )
        if not ownership_repo:
            logger.warning(
                f"Refusing deletion of directory at '{path}': missing ownership repository (EVIDENCE_INSUFFICIENT)"
            )
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.UNKNOWN,
                reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                provider_detail=f"Missing ownership repository for '{path}'.",
            )

        ownership = ownership_repo.get_by_canonical_path(canonical_path)
        if not ownership and hasattr(ownership_repo, "get_by_job_id"):
            cand = ownership_repo.get_by_job_id(job_id)
            if cand and str(Path(cand.canonical_worktree_path).resolve()) == canonical_path:
                ownership = cand

        # Durable DB ownership is MANDATORY. Marker alone, .git alone, or path-under-root alone can NEVER authorize deletion.
        if not ownership:
            logger.warning(
                f"Refusing deletion of directory at '{path}': no durable DB ownership record found (EVIDENCE_INSUFFICIENT)"
            )
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.UNKNOWN,
                reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                provider_detail=f"No durable DB ownership record found for '{path}'.",
            )

        if getattr(ownership, "has_synthetic_placeholder", False):
            logger.warning(
                f"Refusing deletion at '{path}': DB ownership contains synthetic placeholders (POLICY_DENIED)"
            )
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.POLICY_DENIED,
                provider_detail=f"Durable DB ownership contains synthetic placeholders for '{path}'.",
            )

        if ownership.job_id != job_id or (project_id and ownership.project_id != project_id):
            logger.warning(
                f"Refusing deletion of worktree at '{path}': DB ownership job_id/project_id mismatch (CONFLICT)"
            )
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.CONFLICT,
                provider_detail=f"DB ownership job_id/project_id mismatch for '{path}'.",
            )

        if str(Path(ownership.canonical_worktree_path).resolve()) != canonical_path:
            logger.warning(
                f"Refusing deletion of worktree at '{path}': DB ownership canonical path mismatch (CONFLICT)"
            )
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.CONFLICT,
                provider_detail=f"DB ownership canonical path mismatch for '{path}'.",
            )

        # git worktree list must confirm exact worktree
        try:
            wt_list_out = await self._git(
                ["worktree", "list", "--porcelain"], cwd=self.project_root
            )
            wt_paths = [
                str(Path(line[9:].strip()).resolve())
                for line in wt_list_out.splitlines()
                if line.startswith("worktree ")
            ]
            if canonical_path not in wt_paths:
                logger.warning(
                    f"Refusing deletion of worktree at '{path}': path not present in git worktree list (EVIDENCE_INSUFFICIENT)"
                )
                return WorktreeCleanupResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                    provider_detail=f"Path '{path}' not present in git worktree list.",
                )
        except Exception as exc:
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.UNKNOWN,
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                provider_detail=f"Git worktree list query failed: {exc}",
            )

        # Marker corroboration IF present
        marker_file = path / ".minime_worktree_ownership.json"
        if marker_file.exists():
            try:
                self._verify_ownership_marker(path, ownership, worktree_kind="worktree")
            except Exception as e:
                logger.error(f"Marker corroboration failed for '{path}': {e}. Refusing removal.")
                err_str = str(e)
                is_conflict = (
                    "does not match" in err_str
                    or "mismatch" in err_str
                    or "worktree_id" in err_str
                    or "project_id" in err_str
                    or "job_id" in err_str
                    or "run_id" in err_str
                    or "change_name" in err_str
                    or "branch" in err_str
                    or "source_repository_identity" in err_str
                    or "source_base_sha" in err_str
                )
                return WorktreeCleanupResult(
                    outcome=ExternalOutcome.FAILURE if is_conflict else ExternalOutcome.UNKNOWN,
                    reason_code=ExternalReasonCode.CONFLICT
                    if is_conflict
                    else ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                    provider_detail=f"Marker corroboration failed for '{path}': {e}.",
                )

        state = await self.inspect_worktree_state(path)
        if state.dirty:
            logger.warning(f"Refusing to remove dirty managed worktree at '{path}': POLICY_DENIED.")
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.POLICY_DENIED,
                provider_detail=f"Managed worktree at '{path}' is dirty.",
            )

        # Transition DELETING
        ownership.creation_state = WorktreeCreationState.DELETING
        ownership.updated_at = utc_now()
        ownership_repo.save(ownership)
        self._flush_uow()

        # Remove git worktree
        await self._git(
            ["worktree", "remove", "--force", str(path)],
            cwd=self.project_root,
            job_id=job_id,
            project_id=project_id,
            operation_type="worktree_remove",
            managed_worktree_path=path,
        )

        # Verify physical removal
        if path.exists():
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                provider_detail=f"Failed to verify physical removal of worktree path '{path}'.",
            )

        # Transition DELETED
        ownership.creation_state = WorktreeCreationState.DELETED
        ownership.updated_at = utc_now()
        ownership_repo.save(ownership)
        self._flush_uow()

        return WorktreeCleanupResult(
            outcome=ExternalOutcome.SUCCESS,
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            provider_detail=f"Successfully removed clean worktree at '{path}'.",
        )

    async def remove_review_worktree(
        self,
        worktree_path: str | Path,
        job_id: str,
        project_id: str | None = None,
    ) -> WorktreeCleanupResult:
        """Remove a disposable reviewer/auditor execution worktree with 4-way cleanup authority."""
        eff_project_id = self._resolve_project_id(project_id, job_id)
        if not eff_project_id:
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.POLICY_DENIED,
                provider_detail="project_id is mandatory for managed worktree operations.",
            )

        path = Path(worktree_path).resolve()
        canonical_path = str(path)

        # 1. 4-Way Authority Step 1: Durable DB ownership check FIRST
        ownership_repo = (
            getattr(self.uow, "orchestration_worktree_ownerships", None) if self.uow else None
        )
        if not ownership_repo:
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.UNKNOWN,
                reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                provider_detail=f"Missing ownership repository for '{path}'.",
            )

        ownership = ownership_repo.get_by_canonical_path(canonical_path)
        if not ownership and hasattr(ownership_repo, "get_by_job_id"):
            cand = ownership_repo.get_by_job_id(job_id)
            if cand and str(Path(cand.canonical_worktree_path).resolve()) == canonical_path:
                ownership = cand

        # Absent review path + no durable ownership => UNKNOWN / EVIDENCE_INSUFFICIENT, not success
        if not ownership:
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.UNKNOWN,
                reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
                provider_detail=f"No durable DB ownership record found for '{path}'.",
            )

        if getattr(ownership, "has_synthetic_placeholder", False):
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.POLICY_DENIED,
                provider_detail=f"Durable DB ownership contains synthetic placeholders for '{path}'.",
            )

        if ownership.job_id != job_id or ownership.project_id != eff_project_id:
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.CONFLICT,
                provider_detail=f"DB ownership job_id/project_id mismatch for '{path}'.",
            )

        if str(Path(ownership.canonical_worktree_path).resolve()) != canonical_path:
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.CONFLICT,
                provider_detail=f"DB ownership canonical path mismatch for '{path}'.",
            )

        # Guard preflight authorization
        try:
            self._authorize_mutating_operation(
                eff_project_id,
                path,
                WorkspaceOperation.WORKTREE_DELETE,
                require_created_ownership=False,
                job_id=job_id,
            )
        except (RuntimeError, ValueError) as exc:
            logger.warning(f"Refusing deletion of review worktree at '{path}': {exc}")
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.POLICY_DENIED,
                provider_detail=f"Guard denied deletion: {exc}",
            )

        # 2. 4-Way Authority Step 3: git worktree list observation
        wt_in_git = False
        try:
            wt_list_out = await self._git(
                ["worktree", "list", "--porcelain"], cwd=self.project_root
            )
            wt_paths = [
                str(Path(line[9:].strip()).resolve())
                for line in wt_list_out.splitlines()
                if line.startswith("worktree ")
            ]
            wt_in_git = canonical_path in wt_paths
        except Exception as exc:
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.UNKNOWN,
                reason_code=ExternalReasonCode.UNOBSERVABLE,
                provider_detail=f"Git worktree list query failed: {exc}",
            )

        # 3. 4-Way Authority Step 4: Marker corroboration if present on disk
        marker_file = path / ".minime_worktree_ownership.json"
        if marker_file.exists():
            try:
                self._verify_ownership_marker(path, ownership, worktree_kind="review worktree")
            except Exception as e:
                return WorktreeCleanupResult(
                    outcome=ExternalOutcome.FAILURE,
                    reason_code=ExternalReasonCode.CONFLICT,
                    provider_detail=f"Marker corroboration failed for '{path}': {e}.",
                )

        dir_exists = path.exists()

        # Reconcile DB state vs Git state vs physical presence:
        if ownership.creation_state == WorktreeCreationState.DELETED:
            if not dir_exists and not wt_in_git:
                return WorktreeCleanupResult(
                    outcome=ExternalOutcome.SUCCESS,
                    reason_code=ExternalReasonCode.ALREADY_ABSENT,
                    provider_detail=f"Review worktree at '{path}' is already absent and state is DELETED.",
                )
            if dir_exists or wt_in_git:
                return WorktreeCleanupResult(
                    outcome=ExternalOutcome.FAILURE,
                    reason_code=ExternalReasonCode.CONFLICT,
                    provider_detail=f"Inconsistent observation: DB state is DELETED but path exists ({dir_exists}) or git lists it ({wt_in_git}).",
                )

        # Active ownership (CREATED, PENDING, DELETING)
        if wt_in_git:
            ownership.creation_state = WorktreeCreationState.DELETING
            ownership.updated_at = utc_now()
            ownership_repo.save(ownership)
            self._flush_uow()

            try:
                await self._git(
                    ["worktree", "remove", "--force", str(path)],
                    cwd=self.project_root,
                    job_id=job_id,
                    project_id=eff_project_id,
                    operation_type="review_worktree_remove",
                    managed_worktree_path=path,
                )
            except Exception as e:
                logger.warning(f"git worktree remove failed: {e}")

            try:
                wt_list_out = await self._git(
                    ["worktree", "list", "--porcelain"], cwd=self.project_root
                )
                wt_paths = [
                    str(Path(line[9:].strip()).resolve())
                    for line in wt_list_out.splitlines()
                    if line.startswith("worktree ")
                ]
                if canonical_path in wt_paths:
                    return WorktreeCleanupResult(
                        outcome=ExternalOutcome.FAILURE,
                        reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                        provider_detail=f"Failed to remove worktree path '{path}' from git worktree list.",
                    )
            except Exception as exc:
                return WorktreeCleanupResult(
                    outcome=ExternalOutcome.UNKNOWN,
                    reason_code=ExternalReasonCode.UNOBSERVABLE,
                    provider_detail=f"Git worktree list query failed after removal: {exc}",
                )

        if path.exists():
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.FAILURE,
                reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
                provider_detail=f"Failed to verify physical removal of review worktree path '{path}'.",
            )

        # Transition DELETED
        ownership.creation_state = WorktreeCreationState.DELETED
        ownership.updated_at = utc_now()
        ownership_repo.save(ownership)
        self._flush_uow()

        if not dir_exists and not wt_in_git:
            return WorktreeCleanupResult(
                outcome=ExternalOutcome.SUCCESS,
                reason_code=ExternalReasonCode.ALREADY_ABSENT,
                provider_detail=f"Successfully reconciled absent review worktree state to DELETED for '{path}'.",
            )

        return WorktreeCleanupResult(
            outcome=ExternalOutcome.SUCCESS,
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            provider_detail=f"Successfully removed review worktree at '{path}'.",
        )
