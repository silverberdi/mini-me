"""Tests for implementation pipeline jobs, runners, checks, and observability."""

import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from minime.domain.enums import ChangeStatus, EventType, JobStatus, ReadinessState
from minime.domain.models import Change, JobHandoff, Project, RecoveryClaimContext, utc_now
from minime.services.deepseek_auditor_runner import MockAuditorRunner
from minime.services.execution_pipeline import (
    ExecutionPipelineService,
    format_candidate_workspace_context,
)
from minime.services.handoff_manager import HandoffManager
from minime.services.implementer_runner import MockImplementerRunner
from minime.services.openspec_tasks import OpenSpecTaskTracker
from minime.services.reviewer_runner import MockReviewerRunner
from minime.services.worktree_manager import WorktreeInfo


def _dummy_claim_context(uow: Any, claim_key: str = "run:test-pipe") -> RecoveryClaimContext:
    if hasattr(uow, "claims") and uow.claims is not None:
        ctx = uow.claims.acquire_or_reacquire(claim_key, "test-instance", 3600)
        if ctx:
            if isinstance(ctx, RecoveryClaimContext):
                return ctx
            return RecoveryClaimContext(
                claim_key=getattr(ctx, "claim_key", claim_key),
                owner_instance_id=getattr(ctx, "owner_instance_id", "test-instance"),
                fence_token=getattr(ctx, "fence_token", 1),
                lease_expires_at=getattr(ctx, "lease_expires_at", utc_now() + timedelta(hours=1)),
            )
    return RecoveryClaimContext(
        claim_key=claim_key,
        owner_instance_id="test-instance",
        fence_token=1,
        lease_expires_at=utc_now() + timedelta(hours=1),
    )


def test_workspace_context_is_absolute_and_openspec_tracker_stays_task_focused(tmp_path):
    relative_path = Path("relative-candidate-workspace")
    context = format_candidate_workspace_context(relative_path)

    assert f"Absolute path: {relative_path.resolve()}" in context
    assert "all repository reads, writes, edits" in context
    assert "provider scratch directories" in context

    tracker = OpenSpecTaskTracker(tmp_path)
    task_context = tracker.format_prompt_context("openspec", "missing-change")
    assert "CANDIDATE WORKSPACE" not in task_context


def test_handoff_prompt_normalizes_to_authoritative_workspace(tmp_path):
    handoff = JobHandoff(
        job_id="job-1",
        from_attempt_id="attempt-1",
        from_executor="one",
        to_executor="two",
        worktree_path="relative/stale-worktree",
        base_sha="base",
        candidate_sha="candidate",
    )
    prompt = HandoffManager().format_handoff_prompt(
        handoff, authoritative_worktree_path=tmp_path / "candidate"
    )

    assert f"Worktree Path: {(tmp_path / 'candidate').resolve()}" in prompt
    assert "relative/stale-worktree" not in prompt


class FakeWorktreeManager:
    def __init__(self, root: Path):
        self.root = root
        self.created_paths: dict[str, Path] = {}
        self.cleaned: list[str] = []

    async def create_worktree(
        self, job_id: str, change_name: str, base_branch: str, *args, **kwargs
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

    async def create_review_worktree(
        self,
        job_id: str,
        change_name: str,
        candidate_sha: str,
        reviewer_role: str,
        project_id: str | None = None,
        run_id: str | None = None,
    ) -> WorktreeInfo:
        del project_id, run_id
        sanitized_role = reviewer_role.replace("/", "_").replace("\\", "_").replace(":", "_")
        short_sha = candidate_sha[:8] if candidate_sha else ""
        suffix = f"-{short_sha}" if short_sha else ""
        path = self.root / ".minime" / "worktrees" / f"{job_id}-review-{sanitized_role}{suffix}"
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        source_wt = self.created_paths.get(job_id)
        if source_wt and source_wt.exists():
            for item in source_wt.iterdir():
                if item.name == ".git":
                    continue
                if item.is_dir():
                    shutil.copytree(item, path / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, path / item.name)
        elif (self.root / "openspec").exists():
            shutil.copytree(self.root / "openspec", path / "openspec", dirs_exist_ok=True)
        else:
            (path / "openspec").mkdir(parents=True, exist_ok=True)

        subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test"], cwd=str(path), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init review wt"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.created_paths[f"{job_id}-review-{sanitized_role}"] = path
        branch = f"minime/{change_name}-{job_id}-review-{sanitized_role}{suffix}"
        return WorktreeInfo(path=path, branch_name=branch, base_sha=candidate_sha or head_sha)

    async def remove_review_worktree(
        self,
        worktree_path: str | Path,
        job_id: str,
        project_id: str | None = None,
    ) -> None:
        del project_id
        if not hasattr(self, "cleaned_review_worktrees"):
            self.cleaned_review_worktrees = []
        self.cleaned_review_worktrees.append(f"{job_id}-review")
        path = Path(worktree_path)
        if path.exists():
            shutil.rmtree(path)


class RecoveryOrderingWorktreeManager(FakeWorktreeManager):
    def __init__(self, root: Path, ordering: list[str]):
        super().__init__(root)
        self.ordering = ordering

    async def create_recovery_snapshot(self, job_id: str, project_id: str | None = None):
        del project_id
        self.ordering.append("snapshot")
        return f"recovery-{job_id}"

    async def remove_clean_worktree(self, job_id: str, project_id: str | None = None) -> None:
        del project_id
        self.ordering.append("remove")


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
    (change_dir / "specs" / "feature" / "spec.md").write_text("# Spec\n", encoding="utf-8")

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

    job = await service.run_job("mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow))

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
async def test_recovery_evidence_is_committed_before_worktree_removal(in_memory_uow, tmp_path):
    seed_ready_change(in_memory_uow, tmp_path, "# Tasks\n\n## 1. Things\n- [x] 1.1 Done\n")
    ordering: list[str] = []
    worktrees = RecoveryOrderingWorktreeManager(tmp_path, ordering)
    original_commit = in_memory_uow.commit

    def commit_with_ordering() -> None:
        if (
            any(
                event.event_type == EventType.WORKTREE_RECOVERY_SNAPSHOT
                for event in in_memory_uow.events.list_events()
            )
            and "evidence" not in ordering
        ):
            ordering.append("evidence")
        original_commit()

    in_memory_uow.commit = commit_with_ordering
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=MockReviewerRunner(
            stdout=['```json\n{"verdict": "READY_TO_MERGE", "summary": "ok", "findings": []}\n```']
        ),
        auditor_runner=MockAuditorRunner(
            output=['{"risk": "low", "summary": "ok", "findings": []}']
        ),
        worktree_manager=worktrees,
    )

    job = await service.run_job("mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow))

    assert job.status == JobStatus.READY_TO_MERGE
    assert ordering == ["snapshot", "evidence", "remove"]
    recovery_event = next(
        event
        for event in in_memory_uow.events.list_events()
        if event.event_type == EventType.WORKTREE_RECOVERY_SNAPSHOT
    )
    assert recovery_event.payload["recovery_sha"] == f"recovery-{job.job_id}"
    assert recovery_event.payload["authoritative_candidate"] is False


@pytest.mark.asyncio
async def test_recovery_evidence_failure_blocks_without_removal(in_memory_uow, tmp_path):
    seed_ready_change(in_memory_uow, tmp_path, "# Tasks\n\n## 1. Things\n- [x] 1.1 Done\n")
    ordering: list[str] = []
    worktrees = RecoveryOrderingWorktreeManager(tmp_path, ordering)
    original_commit = in_memory_uow.commit
    failed = False

    def failing_recovery_commit() -> None:
        nonlocal failed
        has_recovery_event = any(
            event.event_type == EventType.WORKTREE_RECOVERY_SNAPSHOT
            for event in in_memory_uow.events.list_events()
        )
        if has_recovery_event and not failed:
            failed = True
            raise RuntimeError("token=secret-recovery-value")
        original_commit()

    in_memory_uow.commit = failing_recovery_commit
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=MockReviewerRunner(
            stdout=['```json\n{"verdict": "READY_TO_MERGE", "summary": "ok", "findings": []}\n```']
        ),
        auditor_runner=MockAuditorRunner(
            output=['{"risk": "low", "summary": "ok", "findings": []}']
        ),
        worktree_manager=worktrees,
    )

    job = await service.run_job("mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow))

    assert job.status == JobStatus.RECOVERY_BLOCKED
    assert ordering == ["snapshot"]
    assert "[REDACTED]" in (job.error_message or "")
    assert "secret-recovery-value" not in (job.error_message or "")


@pytest.mark.asyncio
async def test_execution_pipeline_check_failure_halts_and_records_result(in_memory_uow, tmp_path):
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

    job = await service.run_job("mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow))

    assert job.status == JobStatus.CHECKS_FAILED
    checks = in_memory_uow.check_results.list_by_job(job.job_id)
    assert [c.check_name for c in checks] == ["fail", "skip"]
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

    job = await service.run_job("mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow))

    assert job.status in (JobStatus.NEEDS_HUMAN, JobStatus.FAILED)
    events = in_memory_uow.events.list_events(
        project_id="mini-me", change_id="synthetic-pipeline-change"
    )
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

    job = await service.run_job("mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow))

    assert job.status in (JobStatus.NEEDS_HUMAN, JobStatus.FAILED)
    assert in_memory_uow.check_results.list_by_job(job.job_id) == []
    events = in_memory_uow.events.list_events(
        project_id="mini-me", change_id="synthetic-pipeline-change"
    )
    assert any(event.event_type == EventType.INCOMPLETE_TASKS for event in events)
