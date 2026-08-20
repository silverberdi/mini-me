"""Tests for implementation pipeline jobs, runners, checks, and observability."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from minime.domain.enums import ChangeStatus, EventType, JobStatus, ReadinessState
from minime.domain.models import Change, Project
from minime.services.deepseek_auditor_runner import MockAuditorRunner
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

        subprocess.run(
            ["git", "init"], cwd=str(path), check=True, capture_output=True
        )
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
        subprocess.run(
            ["git", "add", "."], cwd=str(path), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "initial"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "branch", "-M", "main"],
            cwd=str(path),
            check=True,
            capture_output=True,
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
        return WorktreeInfo(
            path=path, branch_name=f"minime/test-{job_id}", base_sha=head_sha
        )

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
) -> None:
    change_dir = tmp_path / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "tasks.md").write_text(tasks, encoding="utf-8")
    (change_dir / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
    (change_dir / "design.md").write_text("# Design\n", encoding="utf-8")
    (change_dir / "specs" / "feature").mkdir(parents=True, exist_ok=True)
    (change_dir / "specs" / "feature" / "spec.md").write_text(
        "# Spec\n", encoding="utf-8"
    )

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
        checks=checks
        or [{"name": "ok", "command": f"{sys.executable} -c 'print(123)'"}],
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
async def test_execution_pipeline_success_records_evidence_and_cleans_worktree(
    in_memory_uow, tmp_path
):
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n## 1. Things\n- [x] 1.1 Done\n",
    )
    worktrees = FakeWorktreeManager(tmp_path)
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(stdout=["token=supersecret"]),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                '```json\n{"verdict": "READY_TO_MERGE", "summary": "All good", "findings": []}\n```'
            ]
        ),
        auditor_runner=MockAuditorRunner(
            output=['{"risk": "low", "summary": "No material risk.", "findings": []}']
        ),
        worktree_manager=worktrees,
    )

    job = await service.run_job("mini-me", "synthetic-pipeline-change")

    assert job.status == JobStatus.READY_TO_MERGE
    assert job.base_sha is not None
    assert job.candidate_sha is not None
    assert worktrees.cleaned == [job.job_id]
    logs = in_memory_uow.job_logs.list_by_job(job.job_id)
    assert any("[REDACTED]" in log.message for log in logs)
    checks = in_memory_uow.check_results.list_by_job(job.job_id)
    assert len(checks) == 1
    metrics = in_memory_uow.metrics.list_facts(
        project_id="mini-me", change_id="synthetic-pipeline-change"
    )
    assert {m.metric_name for m in metrics} >= {
        "implementer_duration_ms",
        "checks_duration_ms",
        "review_duration_ms",
        "total_duration_ms",
    }


@pytest.mark.asyncio
async def test_execution_pipeline_check_failure_halts_and_records_result(
    in_memory_uow, tmp_path
):
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n- [x] 1.1 Done\n",
        checks=[
            {
                "name": "fail",
                "command": f"{sys.executable} -c 'import sys; print(\"bad\"); sys.exit(4)'",
            },
            {"name": "skip", "command": f"{sys.executable} -c 'print(\"skip\")'"},
        ],
    )
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("mini-me", "synthetic-pipeline-change")

    assert job.status == JobStatus.CHECKS_FAILED
    checks = in_memory_uow.check_results.list_by_job(job.job_id)
    assert [c.check_name for c in checks] == ["fail"]
    assert checks[0].exit_code == 4


@pytest.mark.asyncio
async def test_execution_pipeline_timeout_fails_and_records_event(
    in_memory_uow, tmp_path
):
    seed_ready_change(in_memory_uow, tmp_path, "# Tasks\n- [x] 1.1 Done\n")
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(timed_out=True),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("mini-me", "synthetic-pipeline-change")

    assert job.status == JobStatus.FAILED
    assert "timed out" in (job.error_message or "")
    events = in_memory_uow.events.list_events(
        project_id="mini-me", change_id="synthetic-pipeline-change"
    )
    assert any(event.event_type == EventType.JOB_TIMEOUT for event in events)


@pytest.mark.asyncio
async def test_execution_pipeline_incomplete_tasks_block_checks(
    in_memory_uow, tmp_path
):
    seed_ready_change(in_memory_uow, tmp_path, "# Tasks\n- [ ] 1.1 Not done\n")
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("mini-me", "synthetic-pipeline-change")

    assert job.status == JobStatus.FAILED
    assert in_memory_uow.check_results.list_by_job(job.job_id) == []
    events = in_memory_uow.events.list_events(
        project_id="mini-me", change_id="synthetic-pipeline-change"
    )
    assert any(event.event_type == EventType.INCOMPLETE_TASKS for event in events)
