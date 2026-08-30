"""Git worktree lifecycle management for execution jobs with durable ownership tracking."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from minime.domain.enums import GitOperationStatus
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import GitOperation, utc_now

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

    def __init__(self, project_root: str | Path, uow: PersistenceUnitOfWork | None = None):
        self.project_root = Path(project_root).resolve()
        self.worktrees_root = self.project_root / ".minime" / "worktrees"
        self.uow = uow

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
            # Explicit managed worktree path must identify the target managed worktree for the mini me job
            target_wt = Path(managed_worktree_path or command_cwd).resolve()
            git_op = GitOperation(
                job_id=job_id,
                project_id=project_id or "unknown",
                worktree_path=str(target_wt),
                operation_type=operation_type,
                status=GitOperationStatus.RUNNING,
                started_at=utc_now(),
            )
            # 1. Persist durable GitOperation RUNNING record before launching subprocess
            self.uow.git_operations.save(git_op)
            self.uow.commit()

        # 2. Only launch subprocess after persistence succeeds
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(command_cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # 3. Persist PID immediately after process launch when available
        if git_op and self.uow and proc.pid:
            git_op.pid = proc.pid
            self.uow.git_operations.save(git_op)
            self.uow.commit()

        stdout, stderr = await proc.communicate()
        success = proc.returncode == 0

        # 4. Persist final COMPLETED / FAILED state
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
        branch = f"minime/{change_name}-{job_id}-remediation-gen{generation}"
        if path.exists():
            actual_branch = (await self._git(["branch", "--show-current"], cwd=path)).strip()
            actual_sha = await self.current_sha(path)
            if actual_branch != branch or actual_sha != source_sha:
                raise RuntimeError(
                    "Existing remediation workspace identity does not match durable source."
                )
            return WorktreeInfo(path, branch, source_sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self._git(["rev-parse", "--verify", f"refs/heads/{branch}"])
            raise RuntimeError(
                f"Remediation branch already exists without its managed worktree: {branch}"
            )
        except RuntimeError as exc:
            if "already exists without" in str(exc):
                raise
        await self._git(
            ["worktree", "add", "-b", branch, str(path), source_sha],
            cwd=self.project_root,
            job_id=job_id,
            project_id=project_id,
            operation_type="remediation_worktree_add",
            managed_worktree_path=path,
        )
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
        return tuple(sorted(found))

    async def create_worktree(
        self,
        job_id: str,
        change_name: str,
        base_branch: str,
        project_id: str | None = None,
        branch_name: str | None = None,
    ) -> WorktreeInfo:
        path = self.worktree_path(job_id).resolve()
        root = self.worktrees_root.resolve()
        if root not in path.parents:
            raise ValueError(f"Worktree path escapes managed root: {path}")
        if path.exists() and any(path.iterdir()):
            raise ValueError(f"Worktree path already exists and is not empty: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self._git(["worktree", "prune"], cwd=self.project_root)
        except Exception:
            pass
        branch_name = branch_name or f"minime/{change_name}-{job_id}"
        base_sha = await self._git(["rev-parse", base_branch])
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

        await self._git(
            cmd,
            cwd=self.project_root,
            job_id=job_id,
            project_id=project_id,
            operation_type="worktree_add",
            managed_worktree_path=path,
        )
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
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._git(
            ["worktree", "add", "-b", branch_name, str(path), base_sha],
            cwd=self.project_root,
            job_id=job_id,
            project_id=project_id,
            operation_type="candidate_base_integration_worktree_add",
            managed_worktree_path=path,
        )
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
        files = tuple(
            sorted(line[3:] for line in status.splitlines() if len(line) >= 4 and line[3:].strip())
        )
        cached = await self._git(["diff", "--cached", "--binary"], cwd=path)
        unstaged = await self._git(["diff", "--binary"], cwd=path)
        untracked = await self._git(["ls-files", "--others", "--exclude-standard", "-z"], cwd=path)
        digest = hashlib.sha256()
        digest.update(cached.encode())
        digest.update(unstaged.encode())
        for relative in sorted(filter(None, untracked.split("\0"))):
            candidate = path / relative
            digest.update(relative.encode())
            if candidate.is_file():
                digest.update(candidate.read_bytes())
        return WorktreeState(dirty=bool(status), fingerprint=digest.hexdigest(), files=files)

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
        path = Path(worktree_path).resolve()
        if not path.exists():
            return
        state = await self.inspect_worktree_state(path)
        if state.dirty:
            raise RuntimeError(f"Refusing to remove dirty managed worktree: {path}")
        await self._git(
            ["worktree", "remove", str(path)],
            cwd=self.project_root,
            job_id=job_id,
            project_id=project_id,
            operation_type="worktree_remove",
            managed_worktree_path=path,
        )
        if path.exists():
            shutil.rmtree(path)
