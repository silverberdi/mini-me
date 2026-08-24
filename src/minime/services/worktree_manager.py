"""Git worktree lifecycle management for execution jobs with durable ownership tracking."""

from __future__ import annotations

import asyncio
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

    async def create_worktree(
        self, job_id: str, change_name: str, base_branch: str, project_id: str | None = None
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
        branch_name = f"minime/{change_name}-{job_id}"
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

    async def cleanup_worktree(self, job_id: str, project_id: str | None = None) -> None:
        path = self.worktree_path(job_id).resolve()
        if not path.exists():
            return
        try:
            await self._git(
                ["worktree", "remove", "--force", str(path)],
                cwd=self.project_root,
                job_id=job_id,
                project_id=project_id,
                operation_type="worktree_remove",
                managed_worktree_path=path,
            )
        finally:
            if path.exists():
                shutil.rmtree(path)
