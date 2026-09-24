"""Tests for Git worktree lifecycle and implementer subprocess runner."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.adapters.github import GitHubAdapter
from minime.config import AppConfig, CliInvocationConfig, ProviderConfig, load_config
from minime.domain.models import ProjectManagedRepositoryBinding
from minime.services.implementer_runner import CliImplementerRunner, runner_for_implementer
from minime.services.reviewer_runner import CliReviewerRunner, runner_for_reviewer
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


async def setup_test_repo(repo_path: Path, uow: InMemoryPersistenceUnitOfWork, project_id: str = "test-project") -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    await run(["git", "init", "-b", "main"], repo_path)
    await run(["git", "config", "user.email", "test@example.com"], repo_path)
    await run(["git", "config", "user.name", "Test User"], repo_path)
    await run(["git", "remote", "add", "origin", f"https://github.com/org/{project_id}"], repo_path)
    (repo_path / "README.md").write_text("hello\n", encoding="utf-8")
    await run(["git", "add", "README.md"], repo_path)
    await run(["git", "commit", "-m", "initial"], repo_path)

    binding = ProjectManagedRepositoryBinding(
        project_id=project_id,
        canonical_repository_identity=f"github.com/org/{project_id}",
        managed_repository_root=str(repo_path.resolve()),
        worktree_parent_dir=str((repo_path / ".minime" / "worktrees").resolve()),
    )
    uow.project_managed_repository_bindings.save(binding)


@pytest.mark.asyncio
async def test_worktree_manager_create_collision_and_cleanup(tmp_path):
    repo = tmp_path / "repo"
    uow = InMemoryPersistenceUnitOfWork()
    await setup_test_repo(repo, uow, "job-1-proj")

    manager = WorktreeManager(repo, uow=uow)
    info = await manager.create_worktree("job-1", "002-implementation-pipeline", "main", project_id="job-1-proj", run_id="run-1")

    assert info.path.exists()
    assert info.branch_name.startswith("minime/002-implementation-pipeline-job-1")
    assert await manager.current_sha(info.path) == info.base_sha

    with pytest.raises(ValueError, match="not empty"):
        await manager.create_worktree("job-1", "002-implementation-pipeline", "main", project_id="job-1-proj", run_id="run-1")

    await manager.cleanup_worktree("job-1", project_id="job-1-proj")
    assert not info.path.exists()


@pytest.mark.asyncio
async def test_cleanup_worktree_refuses_dirty_worktree_without_deleting_it(tmp_path):
    repo = tmp_path / "repo"
    uow = InMemoryPersistenceUnitOfWork()
    await setup_test_repo(repo, uow, "job-rec-proj")

    manager = WorktreeManager(repo, uow=uow)
    info = await manager.create_worktree("job-recovery", "010-change", "main", project_id="job-rec-proj", run_id="run-rec")
    (info.path / "README.md").write_text("recovered\n", encoding="utf-8")
    (info.path / "new.py").write_text("candidate = True\n", encoding="utf-8")
    git_commands: list[list[str]] = []
    original_git = manager._git

    async def recording_git(args, **kwargs):
        git_commands.append(args)
        return await original_git(args, **kwargs)

    manager._git = recording_git

    with pytest.raises(RuntimeError, match="Refusing to remove dirty"):
        await manager.cleanup_worktree("job-recovery", project_id="job-rec-proj")

    assert info.path.exists()
    assert (info.path / "README.md").read_text(encoding="utf-8") == "recovered\n"
    assert (info.path / "new.py").read_text(encoding="utf-8") == "candidate = True\n"
    assert (
        (await _git_output(["git", "branch", "--show-current"], info.path))
        .strip()
        .startswith("minime/010-change-job-recovery")
    )
    assert all("--force" not in args for args in git_commands)


@pytest.mark.asyncio
async def test_remove_clean_worktree_removes_clean_managed_worktree(tmp_path):
    repo = tmp_path / "repo"
    uow = InMemoryPersistenceUnitOfWork()
    await setup_test_repo(repo, uow, "job-clean-proj")

    manager = WorktreeManager(repo, uow=uow)
    info = await manager.create_worktree("job-clean", "010-change", "main", project_id="job-clean-proj", run_id="run-clean")

    await manager.remove_clean_worktree("job-clean", project_id="job-clean-proj")

    assert not info.path.exists()


@pytest.mark.asyncio
async def test_production_push_uses_repository_root_after_worktree_cleanup(tmp_path):
    """A finalized candidate remains pushable after its managed worktree is removed."""
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    uow = InMemoryPersistenceUnitOfWork()
    await setup_test_repo(repo, uow, "job-push-proj")
    await run(["git", "init", "--bare", str(remote)], repo)
    await run(["git", "remote", "set-url", "origin", str(remote)], repo)
    binding = uow.project_managed_repository_bindings.get_by_project_id("job-push-proj")
    binding.canonical_repository_identity = str(remote.resolve())
    uow.project_managed_repository_bindings.save(binding)

    manager = WorktreeManager(repo, uow=uow)
    info = await manager.create_worktree("job-push", "008-autonomous-change-orchestration", "main", project_id="job-push-proj", run_id="run-push")
    (info.path / "candidate.py").write_text("candidate = True\n", encoding="utf-8")
    await run(["git", "add", "candidate.py"], info.path)
    await run(["git", "commit", "-m", "candidate"], info.path)
    candidate_sha = (await _git_output(["git", "rev-parse", "HEAD"], info.path)).strip()
    await manager.cleanup_worktree("job-push", project_id="job-push-proj")
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


@pytest.mark.asyncio
async def test_remote_branch_head_uses_registered_repo_not_process_cwd(tmp_path, monkeypatch):
    """Remote reconciliation must resolve origin from the registered repo root."""
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    remote_a = tmp_path / "remote-a.git"
    remote_b = tmp_path / "remote-b.git"

    for repo, remote, marker in (
        (repo_a, remote_a, "A"),
        (repo_b, remote_b, "B"),
    ):
        repo.mkdir()
        await run(["git", "init", "-b", "main"], repo)
        await run(["git", "config", "user.email", "test@example.com"], repo)
        await run(["git", "config", "user.name", "Test User"], repo)
        (repo / "marker.txt").write_text(f"{marker}\n", encoding="utf-8")
        await run(["git", "add", "marker.txt"], repo)
        await run(["git", "commit", "-m", f"initial {marker}"], repo)
        await run(["git", "init", "--bare", str(remote)], repo)
        await run(["git", "remote", "add", "origin", str(remote)], repo)
        await run(["git", "push", "origin", "main"], repo)

    sha_a = (await _git_output(["git", "rev-parse", "HEAD"], repo_a)).strip()
    sha_b = (await _git_output(["git", "rev-parse", "HEAD"], repo_b)).strip()
    assert sha_a != sha_b

    monkeypatch.chdir(repo_b)
    observed = GitHubAdapter().get_remote_branch_head(
        repository=str(repo_a), branch="main", remote="origin"
    )
    observed_sha = observed.data if hasattr(observed, "data") else observed
    assert observed_sha == sha_a
    assert observed_sha != sha_b


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


def test_configured_cli_profiles_build_generic_implementer_and_reviewer_vectors():
    config = AppConfig(
        providers={
            "codex": ProviderConfig(
                command="codex",
                roles=["implementer", "reviewer"],
                invocation={
                    "implementer": CliInvocationConfig(
                        args=["exec", "-", "--sandbox", "workspace-write"]
                    ),
                    "reviewer": CliInvocationConfig(args=["exec", "-", "--sandbox", "read-only"]),
                },
            ),
            "future-cli": ProviderConfig(
                command="future",
                roles=["implementer"],
                invocation={"implementer": CliInvocationConfig(args=["run", "--headless"])},
            ),
        }
    )

    implementer = runner_for_implementer("codex", config)
    reviewer = runner_for_reviewer("codex", config)
    future = runner_for_implementer("future-cli", config)

    assert isinstance(implementer, CliImplementerRunner)
    assert implementer.command == ["codex", "exec", "-", "--sandbox", "workspace-write"]
    assert isinstance(reviewer, CliReviewerRunner)
    assert reviewer.command == ["codex", "exec", "-", "--sandbox", "read-only"]
    assert future.command == ["future", "run", "--headless"]


def test_known_headless_cli_contracts_are_configured():
    config = load_config("config/minime.yaml")

    assert runner_for_implementer("codex", config).command == [
        "codex",
        "exec",
        "-",
        "--approve-for-me",
        "--ephemeral",
    ]
    assert runner_for_implementer("antigravity", config).command == [
        "agy",
        "--mode",
        "accept-edits",
        "--dangerously-skip-permissions",
        "--print-timeout",
        "1h",
        "--print={prompt}",
    ]
    assert runner_for_reviewer("antigravity", config).command == [
        "agy",
        "--mode",
        "plan",
        "--dangerously-skip-permissions",
        "--print-timeout",
        "1h",
        "--print={prompt}",
    ]


@pytest.mark.asyncio
async def test_cli_runner_bounds_sanitized_output(tmp_path):
    output_runner = CliImplementerRunner(
        [sys.executable, "-c", "print('token=secret123'); print('x' * 5000)"]
    )
    result = await output_runner.run(tmp_path, "prompt", timeout_seconds=5)

    assert len(result.stdout) == 2
    assert "secret123" not in result.stdout[0]
    assert len(result.stdout[1]) == output_runner.MAX_LINE_CHARS
