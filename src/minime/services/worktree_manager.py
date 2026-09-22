"""Git worktree lifecycle management for execution jobs with durable ownership tracking."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from minime.services.workspace_guard import ManagedWorkspaceGuard

from minime.domain.enums import GitOperationStatus, WorktreeCreationState
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import GitOperation, OrchestrationWorktreeOwnership, utc_now

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

    def _evaluate_guard_preflight(self, project_id: str | None, path: Path) -> None:
        if not project_id:
            raise ValueError("project_id is mandatory for managed worktree operations.")
        from minime.domain.enums import WorkspaceOperation
        from minime.domain.models import WorkspaceMutationRequest
        from minime.services.workspace_guard import ManagedWorkspaceGuard

        guard = self.workspace_guard
        if not guard and self.uow:
            guard = ManagedWorkspaceGuard(self.uow)

        if guard:
            req = WorkspaceMutationRequest(
                project_id=project_id,
                target_path=str(path.resolve()),
                requested_operation=WorkspaceOperation.WORKTREE_CREATE,
            )
            decision = guard.evaluate_mutation(req)
            if not decision.allowed:
                raise RuntimeError(
                    f"ManagedWorkspaceGuard denied WORKTREE_CREATE for path '{path}': {decision.provider_detail or decision.reason_code.value}"
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
            self.uow.commit()

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
            self.uow.commit()

        stdout, stderr = await proc.communicate()
        success = proc.returncode == 0

        if git_op and self.uow:
            new_status = GitOperationStatus.COMPLETED if success else GitOperationStatus.FAILED
            self.uow.git_operations.update_status(
                git_op.operation_id,
                new_status,
                completed_at=utc_now(),
            )
            self.uow.commit()

        if not success:
            raise RuntimeError(stderr.decode().strip() or stdout.decode().strip())
        return stdout.decode().strip()

    def _persist_pending_ownership(
        self, job_id: str, project_id: str | None, path: Path, branch_name: str
    ) -> OrchestrationWorktreeOwnership:
        if not project_id:
            raise ValueError("project_id is mandatory for managed worktree operations.")
        if not self.uow:
            raise RuntimeError("PersistenceUnitOfWork (uow) is required for durable worktree ownership.")
        repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        if not repo:
            raise RuntimeError("orchestration_worktree_ownerships repository missing in uow.")

        canonical_path = str(path.resolve())
        worktree_id = f"wt-{path.name}"
        ownership = OrchestrationWorktreeOwnership(
            worktree_id=worktree_id,
            project_id=project_id,
            job_id=job_id,
            canonical_worktree_path=canonical_path,
            branch_name=branch_name,
            creation_state=WorktreeCreationState.PENDING,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        repo.save(ownership)
        self.uow.commit()

        durable = repo.get_by_id(ownership.worktree_id) or repo.get_by_canonical_path(canonical_path)
        if not durable or durable.creation_state != WorktreeCreationState.PENDING:
            raise RuntimeError(f"Failed to verify durable PENDING ownership record for worktree path '{canonical_path}'.")
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
            raise RuntimeError(f"Worktree postcondition failed: path '{canonical_path}' does not exist.")

        if str(Path(ownership.canonical_worktree_path).resolve()) != canonical_path:
            raise RuntimeError(f"Worktree postcondition failed: path '{canonical_path}' does not match ownership '{ownership.canonical_worktree_path}'.")

        wt_list_out = await self._git(["worktree", "list", "--porcelain"], cwd=self.project_root)
        wt_paths = [
            str(Path(line[9:].strip()).resolve())
            for line in wt_list_out.splitlines()
            if line.startswith("worktree ")
        ]
        if canonical_path not in wt_paths:
            raise RuntimeError(f"Worktree postcondition failed: path '{canonical_path}' not present in git worktree list.")

        actual_branch = (await self._git(["branch", "--show-current"], cwd=resolved_path)).strip()
        if not actual_branch or actual_branch != expected_branch:
            raise RuntimeError(f"Worktree postcondition failed: actual branch '{actual_branch}' does not match expected '{expected_branch}'.")

        if expected_base_sha:
            head_sha = (await self._git(["rev-parse", "HEAD"], cwd=resolved_path)).strip()
            if not head_sha:
                raise RuntimeError("Worktree postcondition failed: unable to resolve HEAD SHA.")
            try:
                expected_sha = (await self._git(["rev-parse", expected_base_sha], cwd=self.project_root)).strip()
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
                        raise RuntimeError(f"Worktree postcondition failed: Git repository identity verification failed: {git_reason}")

        marker_file = resolved_path / ".minime_worktree_ownership.json"
        if not marker_file.exists():
            raise RuntimeError(f"Worktree postcondition failed: ownership marker file missing at '{marker_file}'.")
        try:
            m_data = json.loads(marker_file.read_text(encoding="utf-8"))
            if m_data.get("worktree_id") != ownership.worktree_id or str(Path(m_data.get("canonical_worktree_path", "")).resolve()) != canonical_path:
                raise RuntimeError("Worktree postcondition failed: ownership marker data mismatch.")
        except Exception as e:
            raise RuntimeError(f"Worktree postcondition failed: corrupt ownership marker: {e}")

    def _write_ownership_marker(self, path: Path, ownership: OrchestrationWorktreeOwnership) -> None:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        marker_file = path / ".minime_worktree_ownership.json"
        data = {
            "worktree_id": ownership.worktree_id,
            "project_id": ownership.project_id,
            "job_id": ownership.job_id,
            "canonical_worktree_path": ownership.canonical_worktree_path,
            "branch_name": ownership.branch_name,
            "created_at": ownership.created_at.isoformat() if hasattr(ownership.created_at, "isoformat") else str(ownership.created_at),
        }
        marker_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        try:
            git_ref = path / ".git"
            info_dir = None
            if git_ref.is_dir():
                info_dir = git_ref / "info"
            elif git_ref.is_file():
                text = git_ref.read_text(encoding="utf-8").strip()
                if text.startswith("gitdir:"):
                    gitdir = Path(text[7:].strip())
                    if not gitdir.is_absolute():
                        gitdir = (path / gitdir).resolve()
                    info_dir = gitdir / "info"
            if info_dir:
                info_dir.mkdir(parents=True, exist_ok=True)
                exclude_file = info_dir / "exclude"
                content = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
                if ".minime_worktree_ownership.json" not in content:
                    exclude_file.write_text(content.rstrip() + "\n.minime_worktree_ownership.json\n", encoding="utf-8")
        except Exception:
            pass

    def _finalize_created_ownership(self, ownership: OrchestrationWorktreeOwnership | None) -> None:
        if not ownership or not self.uow:
            return
        repo = getattr(self.uow, "orchestration_worktree_ownerships", None)
        if not repo:
            return
        ownership.creation_state = WorktreeCreationState.CREATED
        ownership.updated_at = utc_now()
        repo.save(ownership)
        self.uow.commit()

    def worktree_path(self, job_id: str) -> Path:
        return self.worktrees_root / job_id

    def remediation_worktree_path(self, job_id: str, generation: int) -> Path:
        return self.worktrees_root / f"{job_id}-remediation-gen{generation}"

    async def create_remediation_worktree(
        self,
        job_id: str,
        change_name: str,
        source_sha: str,
        generation: int,
        project_id: str | None = None,
    ) -> WorktreeInfo:
        """Create or reconcile a remediation workspace rooted at an immutable source SHA."""
        path = self.remediation_worktree_path(job_id, generation).resolve()
        root = self.worktrees_root.resolve()
        if root not in path.parents:
            raise ValueError(f"Worktree path escapes managed root: {path}")

        # 1. Guard preflight before any persistence or filesystem side effect
        self._evaluate_guard_preflight(project_id, path)

        branch = f"minime/{change_name}-{job_id}-remediation-gen{generation}"

        if path.exists():
            actual_branch = (await self._git(["branch", "--show-current"], cwd=path)).strip()
            actual_sha = await self.current_sha(path)
            if actual_branch != branch or actual_sha != source_sha:
                raise RuntimeError(
                    "Existing remediation workspace identity does not match durable source."
                )
            return WorktreeInfo(path, branch, source_sha)

        # 2. Mandatory durable PENDING ownership before git worktree add
        ownership = self._persist_pending_ownership(job_id, project_id, path, branch)

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
            project_id=project_id,
            operation_type="remediation_worktree_add",
            managed_worktree_path=path,
        )

        # 4. Write marker, prove postconditions, and transition to CREATED
        self._write_ownership_marker(path, ownership)
        await self._verify_creation_postconditions(path, ownership, expected_branch=branch, expected_base_sha=source_sha)
        self._finalize_created_ownership(ownership)

        return WorktreeInfo(path, branch, source_sha)

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
        found = {
            p
            for p in found
            if "minime_worktree_ownership.json" not in p
        }
        return tuple(sorted(found))

    async def create_worktree(
        self,
        job_id: str,
        change_name: str,
        base_branch: str,
        project_id: str | None = None,
        branch_name: str | None = None,
        reuse_existing: bool = False,
    ) -> WorktreeInfo:
        path = self.worktree_path(job_id).resolve()
        root = self.worktrees_root.resolve()
        if root not in path.parents:
            raise ValueError(f"Worktree path escapes managed root: {path}")
        if path.exists() and any(path.iterdir()) and not reuse_existing:
            raise ValueError(f"Worktree path already exists and is not empty: {path}")

        # 1. Guard preflight evaluation before any mutation side effect
        self._evaluate_guard_preflight(project_id, path)

        branch_name = branch_name or f"minime/{change_name}-{job_id}"
        base_sha = await self._git(["rev-parse", base_branch])

        if path.exists():
            try:
                await self._git(["rev-parse", "HEAD"], cwd=path)
                return WorktreeInfo(path=path, branch_name=branch_name, base_sha=base_sha)
            except Exception:
                await self.remove_clean_worktree_path(path, job_id, project_id)

        # 2. Mandatory durable PENDING ownership before git worktree add
        ownership = self._persist_pending_ownership(job_id, project_id, path, branch_name)

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
        await self._verify_creation_postconditions(path, ownership, expected_branch=branch_name, expected_base_sha=base_sha)
        self._finalize_created_ownership(ownership)

        # Copy active OpenSpec change directory into isolated worktree if present in project_root
        source_change_dir = self.project_root / "openspec" / "changes" / change_name
        dest_change_dir = path / "openspec" / "changes" / change_name
        if source_change_dir.exists() and not dest_change_dir.exists():
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
    ) -> WorktreeInfo:
        path = (self.worktrees_root / f"{job_id}-integration-gen{generation}").resolve()
        if self.worktrees_root.resolve() not in path.parents:
            raise ValueError(f"Integration worktree path escapes managed root: {path}")
        if path.exists():
            state = await self.inspect_worktree_state(path)
            if not state.dirty:
                return WorktreeInfo(path, branch_name, base_sha)
            raise RuntimeError(f"Existing integration worktree is dirty: {path}")

        # 1. Guard preflight evaluation before any mutation side effect
        self._evaluate_guard_preflight(project_id, path)

        # 2. Mandatory durable PENDING ownership before git worktree add
        ownership = self._persist_pending_ownership(job_id, project_id, path, branch_name)

        # 3. ONLY THEN execute git worktree add
        await self._git(
            ["worktree", "add", "-b", branch_name, str(path), base_sha],
            cwd=self.project_root,
            job_id=job_id,
            project_id=project_id,
            operation_type="candidate_base_integration_worktree_add",
            managed_worktree_path=path,
        )

        # 4. Write marker, prove postconditions, and transition to CREATED
        self._write_ownership_marker(path, ownership)
        await self._verify_creation_postconditions(path, ownership, expected_branch=branch_name, expected_base_sha=base_sha)
        self._finalize_created_ownership(ownership)

        return WorktreeInfo(path, branch_name, base_sha)

    async def cherry_pick(
        self,
        worktree_path: str | Path,
        commits: list[str],
        job_id: str,
        project_id: str | None = None,
    ) -> str:
        if commits:
            await self._git(
                ["cherry-pick", *commits],
                cwd=Path(worktree_path),
                job_id=job_id,
                project_id=project_id,
                operation_type="candidate_base_integration_replay",
                managed_worktree_path=Path(worktree_path),
            )
        return await self.current_sha(worktree_path)

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
        untracked_files = [p for p in untracked.split("\0") if p and "minime_worktree_ownership.json" not in p]
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
        path = self.worktree_path(job_id).resolve()
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
    ) -> WorktreeInfo | None:
        """Adopt only an exact post-commit remediation workspace after a crash."""
        path = self.remediation_worktree_path(job_id, generation).resolve()
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

    async def cleanup_worktree(self, job_id: str, project_id: str | None = None) -> str | None:
        """Compatibility alias that refuses dirty-worktree cleanup."""
        await self.remove_clean_worktree(job_id, project_id)
        return None

    async def remove_clean_worktree(self, job_id: str, project_id: str | None = None) -> None:
        """Remove a managed worktree only after independently proving it is clean."""
        await self.remove_clean_worktree_path(self.worktree_path(job_id), job_id, project_id)

    async def remove_clean_worktree_path(
        self,
        worktree_path: str | Path,
        job_id: str,
        project_id: str | None = None,
    ) -> None:
        if not project_id:
            raise ValueError("project_id is mandatory for managed worktree operations.")
        path = Path(worktree_path).resolve()
        if not path.exists():
            return

        canonical_path = str(path)

        # 4-Way Cleanup Reconciliation: Require durable OrchestrationWorktreeOwnership
        ownership_repo = getattr(self.uow, "orchestration_worktree_ownerships", None) if self.uow else None
        if not ownership_repo:
            logger.warning(
                f"Refusing deletion of directory at '{path}': missing ownership repository (EVIDENCE_INSUFFICIENT / NEEDS_HUMAN)"
            )
            return

        ownership = ownership_repo.get_by_canonical_path(canonical_path)
        if not ownership and hasattr(ownership_repo, "get_by_job_id"):
            cand = ownership_repo.get_by_job_id(job_id)
            if cand and str(Path(cand.canonical_worktree_path).resolve()) == canonical_path:
                ownership = cand

        # Durable DB ownership is MANDATORY. Marker alone, .git alone, or path-under-root alone can NEVER authorize deletion.
        if not ownership:
            logger.warning(
                f"Refusing deletion of directory at '{path}': no durable DB ownership record found (EVIDENCE_INSUFFICIENT / NEEDS_HUMAN)"
            )
            return

        if ownership.job_id != job_id or (project_id and ownership.project_id != project_id):
            logger.warning(
                f"Refusing deletion of worktree at '{path}': DB ownership job_id/project_id mismatch (CONFLICT / NEEDS_HUMAN)"
            )
            return

        if str(Path(ownership.canonical_worktree_path).resolve()) != canonical_path:
            logger.warning(
                f"Refusing deletion of worktree at '{path}': DB ownership canonical path mismatch (CONFLICT / NEEDS_HUMAN)"
            )
            return

        # git worktree list must confirm exact worktree
        wt_list_out = await self._git(["worktree", "list", "--porcelain"], cwd=self.project_root)
        wt_paths = [
            str(Path(line[9:].strip()).resolve())
            for line in wt_list_out.splitlines()
            if line.startswith("worktree ")
        ]
        if canonical_path not in wt_paths:
            logger.warning(
                f"Refusing deletion of worktree at '{path}': path not present in git worktree list (EVIDENCE_INSUFFICIENT / NEEDS_HUMAN)"
            )
            return

        # Marker corroboration IF present
        marker_file = path / ".minime_worktree_ownership.json"
        if marker_file.exists():
            try:
                marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
                if (
                    marker_data.get("worktree_id") != ownership.worktree_id
                    or str(Path(marker_data.get("canonical_worktree_path", "")).resolve()) != canonical_path
                    or marker_data.get("job_id") != ownership.job_id
                ):
                    logger.error(f"Marker corroboration failed for '{path}': CONFLICT. Refusing removal.")
                    return
            except Exception as e:
                logger.error(f"Corrupted ownership marker at '{path}': {e}. Refusing removal.")
                return

        state = await self.inspect_worktree_state(path)
        if state.dirty:
            raise RuntimeError(f"Refusing to remove dirty managed worktree: {path}")

        # Transition DELETING
        ownership.creation_state = WorktreeCreationState.DELETING
        ownership.updated_at = utc_now()
        ownership_repo.save(ownership)
        self.uow.commit()

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
            raise RuntimeError(f"Failed to verify physical removal of worktree path '{path}'.")

        # Transition DELETED
        ownership.creation_state = WorktreeCreationState.DELETED
        ownership.updated_at = utc_now()
        ownership_repo.save(ownership)
        self.uow.commit()
