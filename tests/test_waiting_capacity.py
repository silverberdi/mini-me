"""Unit tests for WAITING_CAPACITY transitions, checkpoint preservation, and pairing invariant enforcement."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from minime.domain.enums import (
    ChangeStatus,
    EventType,
    JobStatus,
    ProviderHealthStatus,
    ReadinessState,
)
from minime.domain.models import Change, Project
from minime.services.checks_runner import ChecksRunner, ChecksRunResult
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.implementer_runner import MockImplementerRunner
from minime.services.reviewer_runner import MockReviewerRunner
from minime.services.worktree_manager import WorktreeInfo


class FakeWorktreeManager:
    def __init__(self, root: Path):
        self.root = root
        self.created_paths: dict[str, Path] = {}
        self.cleaned: list[str] = []

    async def create_worktree(
        self, job_id: str, change_name: str, base_branch: str
    ) -> WorktreeInfo:
        del change_name, base_branch
        path = self.root / ".minime" / "worktrees" / job_id
        path.mkdir(parents=True, exist_ok=True)
        if (self.root / "openspec").exists():
            shutil.copytree(self.root / "openspec", path / "openspec")
        else:
            (path / "openspec").mkdir(parents=True, exist_ok=True)

        subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "initial"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "branch", "-M", "main"], cwd=str(path), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            check=True,
            capture_output=True,
            text=True,
        )
        head_sha = proc.stdout.strip()
        self.created_paths[job_id] = path
        return WorktreeInfo(path=path, branch_name=f"minime/test-{job_id}", base_sha=head_sha)

    async def current_sha(self, worktree_path: str | Path) -> str:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree_path),
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    async def cleanup_worktree(self, job_id: str) -> None:
        self.cleaned.append(job_id)
        path = self.created_paths[job_id]
        if path.exists():
            shutil.rmtree(path)


def seed_ready_change(
    in_memory_uow,
    tmp_path: Path,
    tasks: str,
    checks: list[dict] | None = None,
    change_name: str = "synthetic-pipeline-change",
    implementer: str = "codex",
    reviewer: str = "antigravity",
) -> None:
    change_dir = tmp_path / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "tasks.md").write_text(tasks, encoding="utf-8")
    (change_dir / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
    (change_dir / "design.md").write_text("# Design\n", encoding="utf-8")
    (change_dir / "specs" / "feature").mkdir(parents=True, exist_ok=True)
    (change_dir / "specs" / "feature" / "spec.md").write_text("# Spec\n", encoding="utf-8")

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer=implementer,
        reviewer=reviewer,
        checks=checks or [{"name": "ok", "command": f"{sys.executable} -c 'print(123)'"}],
    )
    change = Change(
        project_id="mini-me",
        name=change_name,
        status=ChangeStatus.READY,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.projects.save(project)
    in_memory_uow.changes.save(change)


@pytest.mark.asyncio
async def test_implementer_quota_exhaustion_transitions_to_waiting_capacity(
    in_memory_uow, tmp_path
):
    """Verify that an implementer quota exhaustion transitions job to WAITING_CAPACITY without failing."""
    change_name = "005-feature"
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n- [x] 1.1 Done\n",
        change_name=change_name,
    )

    # Implementer fails with quota limit
    mock_imp = MockImplementerRunner(
        exit_code=1,
        stderr=["Error: insufficient_quota. Try again in 3600 seconds."],
    )
    mock_rev = MockReviewerRunner()

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        implementer_runner=mock_imp,
        reviewer_runner=mock_rev,
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await pipeline.run_job("mini-me", change_name)
    assert job.status == JobStatus.WAITING_CAPACITY
    assert job.waiting_provider == "codex"
    assert job.expected_reset_at is not None

    # Verify provider health updated to EXHAUSTED
    health = in_memory_uow.provider_health.get_by_provider("codex")
    assert health.status == ProviderHealthStatus.EXHAUSTED

    # Verify event emitted
    events = in_memory_uow.events.list_events()
    wait_events = [e for e in events if e.event_type == EventType.JOB_WAITING_CAPACITY]
    assert len(wait_events) >= 1


@pytest.mark.asyncio
async def test_reviewer_rate_limit_transitions_to_waiting_capacity(in_memory_uow, tmp_path):
    """Verify that a reviewer rate limit transitions job to WAITING_CAPACITY and preserves completed checks."""
    change_name = "005-feature-2"
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n- [x] 1.1 Done\n",
        checks=[{"name": "unit_tests", "command": "echo ok", "timeout_seconds": 10}],
        change_name=change_name,
    )

    # Implementer succeeds
    mock_imp = MockImplementerRunner(
        exit_code=0,
        stdout=["Implementation completed successfully."],
    )
    # Reviewer hits rate limit
    mock_rev = MockReviewerRunner(
        exit_code=1,
        stderr=["HTTP 429 Too Many Requests. Rate limit exceeded."],
    )

    class MockChecksRunner(ChecksRunner):
        async def run(
            self, job_id: str, checks: list[dict], worktree_path: Path
        ) -> ChecksRunResult:
            from minime.domain.models import CheckResult

            res = CheckResult(
                job_id=job_id,
                check_name="unit_tests",
                command="echo ok",
                exit_code=0,
                duration_ms=5,
                output_snippet="ok",
            )
            return ChecksRunResult(passed=True, results=[res])

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        implementer_runner=mock_imp,
        reviewer_runner=mock_rev,
        checks_runner=MockChecksRunner(),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await pipeline.run_job("mini-me", change_name)
    assert job.status == JobStatus.WAITING_CAPACITY
    assert job.waiting_provider == "antigravity"

    # Checkpoint preservation: check results were recorded and preserved
    check_results = in_memory_uow.check_results.list_by_job(job.job_id)
    assert len(check_results) == 1
    assert check_results[0].check_name == "unit_tests"
    assert check_results[0].exit_code == 0


@pytest.mark.asyncio
async def test_pairing_invariants_prevent_self_review_and_reviewer_replacement(
    in_memory_uow, tmp_path
):
    """Verify that self-review policy violations reject job immediately."""
    change_name = "005-feature-3"
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n- [x] 1.1 Done\n",
        change_name=change_name,
        implementer="codex",
        reviewer="codex",
    )

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=MockReviewerRunner(),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await pipeline.run_job("mini-me", change_name)
    assert job.status == JobStatus.FAILED

    events = in_memory_uow.events.list_events()
    viol_events = [e for e in events if e.event_type == EventType.REVIEW_POLICY_VIOLATION]
    assert len(viol_events) == 1
