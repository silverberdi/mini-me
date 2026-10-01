"""Git worktree lifecycle management for execution jobs with durable ownership tracking."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from minime.services.workspace_guard import ManagedWorkspaceGuard

from minime.domain.enums import (
    ExternalOutcome,
    ExternalReasonCode,
    GitOperationStatus,
    WorkspaceOperation,
    WorktreeCreationState,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    GitOperation,
    OrchestrationWorktreeOwnership,
    WorktreeCleanupResult,
    utc_now,
)

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
    ):
        if uow is None:
            raise ValueError("PersistenceUnitOfWork (uow) is required for WorktreeManager.")
        self.project_root = Path(project_root).resolve()
        self.worktrees_root = self.project_root / ".minime" / "worktrees"
        self.uow = uow
        self.workspace_guard = workspace_guard

    def _authorize_mutating_operation(
        self,
        project_id: str | None,
        target_path: Path,
        operation: WorkspaceOperation,
        require_created_ownership: bool = False,
        job_id: str | None = None,
    ) -> None:
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
            raise RuntimeError(stderr.decode().strip() or stdout.decode().strip())
        return stdout.decode().strip()

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
        worktree_id = f"wt-{job_id}" if job_id else f"wt-{path.name}"
        existing = (
            repo.get_by_canonical_path(canonical_path)
            if hasattr(repo, "get_by_canonical_path")
            else None
        ) or (repo.get_by_id(worktree_id) if hasattr(repo, "get_by_id") else None)
        if existing:
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
            if head_sha != expected_sha:
                raise RuntimeError(
                    f"Worktree postcondition failed: actual HEAD SHA '{head_sha}' does not match expected SHA '{expected_sha}'."
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
        branch_name = branch_name or f"minime/{eff_change_name}-{job_id}"

        if path.exists():
            if not reuse_existing:
                if any(path.iterdir()):
                    raise ValueError(f"Worktree path already exists and is not empty: {path}")
            else:
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
            source_base_sha=base_sha,
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
            path, ownership, expected_branch=branch_name, expected_base_sha=base_sha
        )
        self._finalize_created_ownership(ownership)

        # Copy active OpenSpec change directory into isolated worktree if present in project_root
        raw_source_change_dir = self.project_root / "openspec" / "changes" / change_name
        if raw_source_change_dir.exists():
            source_change_dir = raw_source_change_dir.resolve()
            openspec_changes_root = (self.project_root / "openspec" / "changes").resolve()
            if not (
                source_change_dir == openspec_changes_root
                or openspec_changes_root in source_change_dir.parents
            ):
                raise RuntimeError(
                    f"OpenSpec source change directory '{source_change_dir}' escapes '{openspec_changes_root}'."
                )

            dest_openspec_root = path.resolve() / "openspec"
            dest_change_dir = dest_openspec_root / "changes" / change_name
            if (
                os.path.islink(dest_openspec_root)
                or os.path.islink(dest_openspec_root / "changes")
                or os.path.islink(dest_change_dir)
            ):
                raise RuntimeError(
                    f"Symlink escape detected in OpenSpec destination path under '{path}'."
                )

            from minime.domain.models import WorkspaceMutationRequest
            from minime.services.workspace_guard import ManagedWorkspaceGuard

            guard = self.workspace_guard or ManagedWorkspaceGuard(self.uow)
            dest_req = WorkspaceMutationRequest(
                project_id=project_id or eff_project_id,
                target_path=str(dest_change_dir),
                requested_operation=WorkspaceOperation.EDIT,
            )
            dest_decision = guard.evaluate_mutation(dest_req)
            if not dest_decision.allowed:
                raise RuntimeError(
                    f"ManagedWorkspaceGuard denied OpenSpec propagation to '{dest_change_dir}': {dest_decision.provider_detail}"
                )

            if not dest_change_dir.exists():
                dest_change_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source_change_dir, dest_change_dir)

        return WorktreeInfo(path=path, branch_name=branch_name, base_sha=base_sha)

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
