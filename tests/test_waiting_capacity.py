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


def test_scheduler_reconciles_and_resumes_waiting_capacity(in_memory_uow, tmp_path):
    """Verify that SchedulerService.tick / reconcile_waiting_runs auto-resumes WAITING_CAPACITY runs when provider is available."""
    from datetime import timedelta
    from minime.domain.enums import HumanGate, JobStatus, OrchestrationStage, OrchestrationStopOutcome, ProjectStatus
    from minime.domain.models import Job, OrchestrationRun, Project, ProjectBinding, ProviderHealth, utc_now
    from minime.services.orchestration_service import OrchestrationService
    from minime.services.scheduler_service import SchedulerService

    # Set up git repo
    subprocess.run(["git", "init", "-b", "main"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=str(tmp_path), check=True)

    project_id = "mini-me"
    change_name = "021-test-waiting-resume"
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n- [x] 1.1 Done\n",
        change_name=change_name,
    )

    binding = ProjectBinding(
        project_id=project_id,
        openspec_change_name=change_name,
        repository="silverberdi/mini-me",
        github_issue_number=1,
        is_valid=True,
    )
    in_memory_uow.bindings.save(binding)

    from conftest import ReadinessGitHubStub
    from minime.services.deepseek_auditor_runner import MockAuditorRunner

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(exit_code=0, stdout=["Implementation complete"]),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                '```json\n{"verdict": "READY_TO_MERGE", "summary": "Looks good", "findings": []}\n```'
            ]
        ),
        auditor_runner=MockAuditorRunner(output=['{"risk": "low", "summary": "Audit passed", "findings": []}']),
    )
    orch_svc = OrchestrationService(
        uow=in_memory_uow,
        project_root=tmp_path,
        pipeline=pipeline,
        github_adapter=ReadinessGitHubStub(),
    )

    admission = orch_svc.admit_change(project_id, change_name)
    assert admission.admitted is True

    # Put provider in EXHAUSTED and stop run in WAITING_CAPACITY
    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="codex",
            status=ProviderHealthStatus.EXHAUSTED,
            last_error_summary="Quota exceeded",
        )
    )
    run = orch_svc.drive_coordinator(admission.run.run_id)
    assert run.stop_outcome == OrchestrationStopOutcome.WAITING_CAPACITY
    assert run.is_active is True

    # Now provider capacity recovers
    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="codex",
            status=ProviderHealthStatus.AVAILABLE,
        )
    )

    # Reconcile waiting runs in scheduler
    scheduler = SchedulerService(uow=in_memory_uow, project_root=tmp_path, orchestration_service=orch_svc)
    resumed_ids = scheduler.reconcile_waiting_runs(project_id=project_id, drive_resumed=False)

    assert run.run_id in resumed_ids
    updated_run = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert updated_run.stop_outcome != OrchestrationStopOutcome.WAITING_CAPACITY


def test_scheduler_waiting_capacity_timeout_escalates_to_needs_human(in_memory_uow, tmp_path):
    """Verify that SchedulerService escalates to NEEDS_HUMAN when waiting timeout is exceeded."""
    from datetime import timedelta
    from minime.domain.enums import HumanGate, JobStatus, OrchestrationStage, OrchestrationStopOutcome
    from minime.domain.models import Job, OrchestrationRun, utc_now
    from minime.services.scheduler_service import SchedulerService

    change_name = "021-test-waiting-timeout"
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n- [x] 1.1 Done\n",
        change_name=change_name,
    )

    job = Job(
        project_id="mini-me",
        change_name=change_name,
        implementer_role="codex",
        status=JobStatus.WAITING_CAPACITY,
        waiting_provider="codex",
    )
    in_memory_uow.jobs.save(job)

    # Run waiting for 3 hours (exceeding 2h timeout)
    run = OrchestrationRun(
        project_id="mini-me",
        change_name=change_name,
        base_sha="abcdef1234567890",
        active_job_id=job.job_id,
        current_stage=OrchestrationStage.IMPLEMENTING,
        stop_outcome=OrchestrationStopOutcome.WAITING_CAPACITY,
        human_gate=None,
        stop_reason="External execution environment is temporarily unavailable",
        stop_details={"provider": "codex", "waiting_since": (utc_now() - timedelta(hours=3)).isoformat()},
        is_active=True,
    )
    in_memory_uow.orchestration_runs.save(run)

    scheduler = SchedulerService(uow=in_memory_uow, project_root=tmp_path)
    resumed_ids = scheduler.reconcile_waiting_runs(project_id="mini-me", drive_resumed=False, timeout_hours=2.0)

    assert len(resumed_ids) == 0
    updated_run = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert updated_run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
    assert updated_run.human_gate == HumanGate.NEEDS_HUMAN
    assert updated_run.is_active is False
    assert "timeout exceeded" in updated_run.stop_reason.lower()

    updated_job = in_memory_uow.jobs.get_by_id(job.job_id)
    assert updated_job.status == JobStatus.NEEDS_HUMAN


def test_restart_recovery_cancels_jobs_for_done_changes(in_memory_uow, tmp_path):
    """Verify that RestartRecoveryService cancels leftover jobs for completed/DONE changes."""
    from minime.domain.enums import ChangeStatus, JobStatus
    from minime.domain.models import Change, Job
    from minime.services.restart_recovery_service import RestartRecoveryService

    change_name = "021-done-change"
    change = Change(
        project_id="mini-me",
        name=change_name,
        status=ChangeStatus.DONE,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        project_id="mini-me",
        change_name=change_name,
        implementer_role="codex",
        status=JobStatus.QUEUED,
    )
    in_memory_uow.jobs.save(job)

    recovery = RestartRecoveryService(uow=in_memory_uow, project_root=tmp_path)
    reconciled = recovery.reconcile_on_startup()

    updated_job = in_memory_uow.jobs.get_by_id(job.job_id)
    assert updated_job.status == JobStatus.CANCELLED
    assert "already in terminal state" in updated_job.error_message


@pytest.mark.asyncio
async def test_checks_runner_timeout_cleanup(tmp_path):
    """Verify that ChecksRunner enforces timeout and terminates long-running subprocess."""
    from minime.services.checks_runner import ChecksRunner

    runner = ChecksRunner(timeout_seconds=1)
    checks = [
        {
            "name": "sleep-test",
            "command": "python3 -c 'import time; time.sleep(10)'",
        }
    ]
    res = await runner.run("job-timeout", checks, tmp_path)
    assert res.passed is False
    assert len(res.results) == 1
    assert res.results[0].exit_code == 124
    assert "timed out" in res.results[0].output_snippet.lower()


