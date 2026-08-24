"""Tests for Git worktree lifecycle and implementer subprocess runner."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from minime.adapters.github import GitHubAdapter
from minime.services.implementer_runner import CliImplementerRunner
from minime.services.worktree_manager import WorktreeManager


async def run(cmd: list[str], cwd: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, (stdout.decode(), stderr.decode())


@pytest.mark.asyncio
async def test_worktree_manager_create_collision_and_cleanup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    await run(["git", "init", "-b", "main"], repo)
    await run(["git", "config", "user.email", "test@example.com"], repo)
    await run(["git", "config", "user.name", "Test User"], repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    await run(["git", "add", "README.md"], repo)
    await run(["git", "commit", "-m", "initial"], repo)

    manager = WorktreeManager(repo)
    info = await manager.create_worktree("job-1", "002-implementation-pipeline", "main")

    assert info.path.exists()
    assert info.branch_name.startswith("minime/002-implementation-pipeline-job-1")
    assert await manager.current_sha(info.path) == info.base_sha

    with pytest.raises(ValueError, match="not empty"):
        await manager.create_worktree("job-1", "002-implementation-pipeline", "main")

    await manager.cleanup_worktree("job-1")
    assert not info.path.exists()


@pytest.mark.asyncio
async def test_production_push_uses_repository_root_after_worktree_cleanup(tmp_path):
    """A finalized candidate remains pushable after its managed worktree is removed."""
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    await run(["git", "init", "-b", "main"], repo)
    await run(["git", "config", "user.email", "test@example.com"], repo)
    await run(["git", "config", "user.name", "Test User"], repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    await run(["git", "add", "README.md"], repo)
    await run(["git", "commit", "-m", "initial"], repo)
    await run(["git", "init", "--bare", str(remote)], repo)
    await run(["git", "remote", "add", "origin", str(remote)], repo)

    manager = WorktreeManager(repo)
    info = await manager.create_worktree("job-push", "008-autonomous-change-orchestration", "main")
    (info.path / "candidate.py").write_text("candidate = True\n", encoding="utf-8")
    await run(["git", "add", "candidate.py"], info.path)
    await run(["git", "commit", "-m", "candidate"], info.path)
    candidate_sha = (await _git_output(["git", "rev-parse", "HEAD"], info.path)).strip()
    await manager.cleanup_worktree("job-push")
    assert not info.path.exists()

    assert GitHubAdapter().push_branch(
        worktree_path=str(repo),
        remote="origin",
        branch="minime/008-autonomous-change-orchestration",
        candidate_sha=candidate_sha,
    )
    remote_sha = (
        await _git_output(
            [
                "git",
                "ls-remote",
                "--heads",
                str(remote),
                "refs/heads/minime/008-autonomous-change-orchestration",
            ],
            repo,
        )
    ).split()[0]
    assert remote_sha == candidate_sha


async def _git_output(cmd: list[str], cwd: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, (stdout.decode(), stderr.decode())
    return stdout.decode()


@pytest.mark.asyncio
async def test_cli_implementer_runner_redacts_output_and_times_out(tmp_path):
    output_runner = CliImplementerRunner(
        [
            sys.executable,
            "-c",
            "print('token=secret123'); import sys; print('api_key=hidden', file=sys.stderr)",
        ]
    )
    result = await output_runner.run(tmp_path, "prompt", timeout_seconds=5)

    assert result.exit_code == 0
    assert any("[REDACTED]" in line for line in result.stdout)
    assert any("[REDACTED]" in line for line in result.stderr)

    timeout_runner = CliImplementerRunner([sys.executable, "-c", "import time; time.sleep(10)"])
    timeout_result = await timeout_runner.run(tmp_path, "prompt", timeout_seconds=1)

    assert timeout_result.timed_out is True
    assert timeout_result.exit_code != 0
