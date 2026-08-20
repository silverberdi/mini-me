"""Git worktree lifecycle management for execution jobs."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorktreeInfo:
    path: Path
    branch_name: str
    base_sha: str


class WorktreeManager:
    """Creates isolated candidate worktrees under `.minime/worktrees/<job_id>`."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.worktrees_root = self.project_root / ".minime" / "worktrees"

    async def _git(self, args: list[str], cwd: Path | None = None) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd or self.project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode().strip() or stdout.decode().strip())
        return stdout.decode().strip()

    def worktree_path(self, job_id: str) -> Path:
        return self.worktrees_root / job_id

    async def create_worktree(self, job_id: str, change_name: str, base_branch: str) -> WorktreeInfo:
        path = self.worktree_path(job_id).resolve()
        root = self.worktrees_root.resolve()
        if root not in path.parents:
            raise ValueError(f"Worktree path escapes managed root: {path}")
        if path.exists() and any(path.iterdir()):
            raise ValueError(f"Worktree path already exists and is not empty: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        branch_name = f"minime/{change_name}-{job_id}"
        base_sha = await self._git(["rev-parse", base_branch])
        await self._git(["worktree", "add", "-b", branch_name, str(path), base_branch])
        return WorktreeInfo(path=path, branch_name=branch_name, base_sha=base_sha)

    async def current_sha(self, worktree_path: str | Path) -> str:
        return await self._git(["rev-parse", "HEAD"], cwd=Path(worktree_path))

    async def cleanup_worktree(self, job_id: str) -> None:
        path = self.worktree_path(job_id).resolve()
        if not path.exists():
            return
        try:
            await self._git(["worktree", "remove", "--force", str(path)])
        finally:
            if path.exists():
                shutil.rmtree(path)
