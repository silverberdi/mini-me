"""Tests for 002 implementation pipeline jobs, runners, checks, and observability."""

import shutil
import sys
from pathlib import Path

import pytest

from minime.domain.enums import ChangeStatus, EventType, JobStatus, ReadinessState
from minime.domain.models import Change, Project
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.implementer_runner import MockImplementerRunner
from minime.services.worktree_manager import WorktreeInfo


class FakeWorktreeManager:
    def __init__(self, root: Path):
        self.root = root
        self.created_paths: dict[str, Path] = {}
        self.cleaned: list[str] = []

    async def create_worktree(self, job_id: str, change_name: str, base_branch: str) -> WorktreeInfo:
        del change_name, base_branch
        path = self.root / ".minime" / "worktrees" / job_id
        path.mkdir(parents=True)
        shutil.copytree(self.root / "openspec", path / "openspec")
        self.created_paths[job_id] = path
        return WorktreeInfo(path=path, branch_name=f"minime/test-{job_id}", base_sha="base-sha")

    async def current_sha(self, worktree_path: str | Path) -> str:
        del worktree_path
        return "candidate-sha"

    async def cleanup_worktree(self, job_id: str) -> None:
        self.cleaned.append(job_id)
        path = self.created_paths[job_id]
        shutil.rmtree(path)


def seed_ready_change(in_memory_uow, tmp_path: Path, tasks: str, checks: list[dict] | None = None) -> None:
    change_dir = tmp_path / "openspec" / "changes" / "002-implementation-pipeline"
    change_dir.mkdir(parents=True)
    (change_dir / "tasks.md").write_text(tasks, encoding="utf-8")
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
        checks=checks or [{"name": "ok", "command": f"{sys.executable} -c 'print(123)'"}],
    )
    change = Change(
        project_id="mini-me",
        name="002-implementation-pipeline",
        status=ChangeStatus.READY,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.projects.save(project)
    in_memory_uow.changes.save(change)


@pytest.mark.asyncio
async def test_execution_pipeline_success_records_evidence_and_cleans_worktree(in_memory_uow, tmp_path):
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
        worktree_manager=worktrees,
    )

    job = await service.run_job("mini-me", "002-implementation-pipeline")

    assert job.status == JobStatus.CHECKS_PASSED
    assert job.base_sha == "base-sha"
    assert job.candidate_sha == "candidate-sha"
    assert worktrees.cleaned == [job.job_id]
    logs = in_memory_uow.job_logs.list_by_job(job.job_id)
    assert any("[REDACTED]" in log.message for log in logs)
    checks = in_memory_uow.check_results.list_by_job(job.job_id)
    assert len(checks) == 1
    metrics = in_memory_uow.metrics.list_facts(project_id="mini-me", change_id="002-implementation-pipeline")
    assert {m.metric_name for m in metrics} >= {
        "implementer_duration_ms",
        "checks_duration_ms",
        "total_duration_ms",
    }


@pytest.mark.asyncio
async def test_execution_pipeline_check_failure_halts_and_records_result(in_memory_uow, tmp_path):
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n- [x] 1.1 Done\n",
        checks=[
            {"name": "fail", "command": f"{sys.executable} -c 'import sys; print(\"bad\"); sys.exit(4)'"},
            {"name": "skip", "command": f"{sys.executable} -c 'print(\"skip\")'"},
        ],
    )
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("mini-me", "002-implementation-pipeline")

    assert job.status == JobStatus.CHECKS_FAILED
    checks = in_memory_uow.check_results.list_by_job(job.job_id)
    assert [c.check_name for c in checks] == ["fail"]
    assert checks[0].exit_code == 4


@pytest.mark.asyncio
async def test_execution_pipeline_timeout_fails_and_records_event(in_memory_uow, tmp_path):
    seed_ready_change(in_memory_uow, tmp_path, "# Tasks\n- [x] 1.1 Done\n")
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(timed_out=True),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("mini-me", "002-implementation-pipeline")

    assert job.status == JobStatus.FAILED
    assert "timed out" in (job.error_message or "")
    events = in_memory_uow.events.list_events(project_id="mini-me", change_id="002-implementation-pipeline")
    assert any(event.event_type == EventType.JOB_TIMEOUT for event in events)


@pytest.mark.asyncio
async def test_execution_pipeline_incomplete_tasks_block_checks(in_memory_uow, tmp_path):
    seed_ready_change(in_memory_uow, tmp_path, "# Tasks\n- [ ] 1.1 Not done\n")
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("mini-me", "002-implementation-pipeline")

    assert job.status == JobStatus.FAILED
    assert in_memory_uow.check_results.list_by_job(job.job_id) == []
    events = in_memory_uow.events.list_events(project_id="mini-me", change_id="002-implementation-pipeline")
    assert any(event.event_type == EventType.INCOMPLETE_TASKS for event in events)
