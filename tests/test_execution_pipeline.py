"""Tests for implementation pipeline jobs, runners, checks, and observability."""

import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from minime.config import CliInvocationProfile
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ExecutionOutcome,
    HumanGate,
    JobStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProgressClassification,
    ProviderHealthStatus,
    ProviderResultClass,
    ReadinessState,
    ReviewStatus,
)
from minime.domain.models import (
    Change,
    Job,
    JobAttempt,
    JobHandoff,
    OperatorActionRequest,
    OrchestrationRun,
    Project,
    RecoveryClaimContext,
    Review,
    utc_now,
)
from minime.services.control_plane_service import ControlPlaneService
from minime.services.deepseek_auditor_runner import MockAuditorRunner
from minime.services.execution_pipeline import (
    ExecutionPipelineService,
    format_candidate_workspace_context,
)
from minime.services.handoff_manager import HandoffManager
from minime.services.implementer_runner import (
    CliImplementerRunner,
    ImplementerResult,
    MockImplementerRunner,
)
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
    tasks = tracker.parse_tasks("openspec", "missing-change")
    assert tasks == []


@pytest.mark.asyncio
async def test_missing_native_apply_skill_blocks_before_cli_invocation(
    in_memory_uow, tmp_path, monkeypatch, test_capacity_strategy
):
    """A production-shaped CLI selection cannot run when the native skill is absent."""
    change_name = "native-skill-missing"
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n## 1. Work\n- [ ] 1.1 Implement the authorized task\n",
        checks=[],
        change_name=change_name,
    )
    invoked: list[str] = []
    test_capacity_strategy(("codex", "antigravity"))

    class InvocationMustNotRun(CliImplementerRunner):
        async def run(self, worktree_path: Path, prompt_context: str, timeout_seconds: int):
            del worktree_path, prompt_context, timeout_seconds
            invoked.append("runner")
            raise AssertionError("CLI must not be invoked without the installed native skill")

    profile = CliInvocationProfile(
        provider="codex",
        role="implementer",
        executable="codex",
        args=("exec", "-", "--approve-for-me", "--ephemeral"),
        prompt_transport="stdin",
    )
    monkeypatch.setattr(
        "minime.services.execution_pipeline.runner_for_implementer",
        lambda executor, **kwargs: InvocationMustNotRun(profile),
    )
    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path),
    )
    job = pipeline.queue_job("mini-me", change_name)
    in_memory_uow.orchestration_runs.save(
        OrchestrationRun(
            project_id=job.project_id,
            change_name=job.change_name,
            base_sha="base-sha",
            active_job_id=job.job_id,
        )
    )

    class AcceptedContractReview:
        async def review_before_apply(self, *args):
            from minime.services.contract_review_service import ContractReviewResult

            return ContractReviewResult(True, "test-review", "test-contract-hash")

    pipeline.contract_review_service = AcceptedContractReview()

    result = await pipeline.execute_queued_job(
        job.job_id, claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert result.status == JobStatus.NEEDS_HUMAN
    assert "native openspec apply preflight blocked" in (result.error_message or "").lower()
    assert invoked == []
    assert in_memory_uow.job_attempts.list_by_job(job.job_id) == []


@pytest.mark.asyncio
async def test_auth_required_preflight_waits_without_worktree_or_runner_invocation(
    in_memory_uow, tmp_path, monkeypatch
):
    change_name = "auth-required-preflight"
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n## 1. Work\n- [ ] 1.1 Implement the authorized task\n",
        checks=[],
        change_name=change_name,
    )
    invoked: list[str] = []
    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path),
    )
    refresh_calls = []

    async def no_capacity_refresh(provider):
        refresh_calls.append(provider)
        return False

    monkeypatch.setattr(
        pipeline.health_service, "refresh_capacity_from_read_only_source", no_capacity_refresh
    )
    monkeypatch.setattr(
        "minime.services.execution_pipeline.runner_for_implementer",
        lambda executor: invoked.append(executor),
    )
    job = pipeline.queue_job("mini-me", change_name)
    for provider in ("codex", "antigravity"):
        health = pipeline.health_service.get_health(provider)
        health.status = ProviderHealthStatus.AUTH_REQUIRED
        pipeline.uow.provider_health.save(health)

    result = await pipeline.execute_queued_job(
        job.job_id, claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert result.status == JobStatus.WAITING_CAPACITY
    assert invoked == []
    assert pipeline.worktree_manager.created_paths == {}
    assert in_memory_uow.job_attempts.list_by_job(job.job_id) == []
    assert "codex" in refresh_calls


@pytest.mark.asyncio
async def test_runner_factory_profile_error_fails_closed_without_unprofiled_retry(
    in_memory_uow, tmp_path, monkeypatch, test_capacity_strategy
):
    change_name = "profile-construction-fails-closed"
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n## 1. Work\n- [ ] 1.1 Implement the authorized task\n",
        checks=[],
        change_name=change_name,
    )
    test_capacity_strategy(("codex", "antigravity"))
    factory_calls: list[tuple[tuple, dict]] = []
    runner_calls: list[str] = []

    def incompatible_factory(*args, **kwargs):
        factory_calls.append((args, kwargs))
        raise TypeError("profile arguments unsupported")

    monkeypatch.setattr(
        "minime.services.execution_pipeline.runner_for_implementer", incompatible_factory
    )

    async def preflight_ok(profile):
        del profile
        from minime.services.cli_preflight import PreflightResult

        return PreflightResult(ok=True)

    monkeypatch.setattr("minime.services.execution_pipeline.preflight_cli_invocation", preflight_ok)
    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path),
        implementer_runner=None,
    )
    pipeline.implementer_runner = None
    job = pipeline.queue_job("mini-me", change_name)
    in_memory_uow.orchestration_runs.save(
        OrchestrationRun(
            project_id=job.project_id,
            change_name=job.change_name,
            base_sha="base-sha",
            active_job_id=job.job_id,
        )
    )

    class AcceptedContractReview:
        async def review_before_apply(self, *args):
            from minime.services.contract_review_service import ContractReviewResult

            return ContractReviewResult(True, "test-review", "test-contract-hash")

    pipeline.contract_review_service = AcceptedContractReview()
    result = await pipeline.execute_queued_job(
        job.job_id, claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert result.status == JobStatus.NEEDS_HUMAN
    assert "refusing unprofiled dispatch" in (result.error_message or "").lower()
    assert factory_calls
    assert factory_calls[0][1].get("model")
    assert factory_calls[0][1].get("effort")
    assert runner_calls == []


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


def test_control_plane_reassign_then_continue_reaches_codex_runner_over_old_handoff(
    in_memory_uow, tmp_path, monkeypatch, test_capacity_strategy
):
    from minime.domain.enums import ProviderHealthStatus
    from minime.domain.models import ProviderHealth

    change_name = "n01-provider-reassignment"
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n## 1. Work\n- [ ] 1.1 Implement the authorized task\n",
        checks=[],
        change_name=change_name,
    )
    project = in_memory_uow.projects.get_by_id("mini-me")
    project.external_providers_allowed = ["codex", "antigravity"]
    in_memory_uow.projects.save(project)
    test_capacity_strategy(("codex", "antigravity"))
    run = OrchestrationRun(
        run_id="run-n01-reassign-integration",
        project_id=project.project_id,
        change_name=change_name,
        base_sha="baseline-sha",
        current_stage=OrchestrationStage.IMPLEMENTING,
        resumable_stage=OrchestrationStage.IMPLEMENTING,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_reason="SAME_SHA_RETRY_SUPPRESSED",
        is_active=False,
        active_job_id="job-n01-reassign-integration",
    )
    job = Job(
        job_id=run.active_job_id,
        project_id=project.project_id,
        change_name=change_name,
        implementer_role="antigravity",
        current_executor="antigravity",
        status=JobStatus.NEEDS_HUMAN,
        attempt_count=3,
        reassignment_count=1,
    )
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.jobs.save(job)
    for number in range(1, 4):
        in_memory_uow.job_attempts.save(
            JobAttempt(
                attempt_id=f"n01-historical-{number}",
                job_id=job.job_id,
                attempt_number=number,
                executor_role="antigravity",
                model_identity="antigravity:model",
                normalized_outcome=ExecutionOutcome.PREMATURE_STOP.value,
                progress_classification=ProgressClassification.NO_PROGRESS,
                start_sha="same-candidate-sha",
                end_sha="same-candidate-sha",
                is_same_sha_duplicate=number == 3,
                error_details={
                    "reason": "SAME_SHA_RETRY_SUPPRESSED" if number == 3 else "no progress"
                },
            )
        )
    old_handoff = JobHandoff(
        job_id=job.job_id,
        from_attempt_id="n01-historical-2",
        from_executor="codex",
        to_executor="antigravity",
        worktree_path=str(tmp_path / "historical-worktree"),
        base_sha="baseline-sha",
        candidate_sha="same-candidate-sha",
    )
    in_memory_uow.job_handoffs.save(old_handoff)
    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="codex",
            status=ProviderHealthStatus.AVAILABLE,
            last_result_class=ProviderResultClass.SUCCESS,
            last_success_at=utc_now(),
        )
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="antigravity",
            status=ProviderHealthStatus.AVAILABLE,
            last_result_class=ProviderResultClass.SUCCESS,
            last_success_at=utc_now(),
        )
    )
    in_memory_uow.commit()

    selected_runners: list[str] = []

    class DiagnosticRunner:
        async def run(self, worktree_path: Path, prompt_context: str, timeout_seconds: int):
            del worktree_path, prompt_context, timeout_seconds
            return ImplementerResult(
                exit_code=-2,
                timed_out=False,
                stdout=[],
                stderr=["diagnostic runner reached; no provider invoked"],
                duration_ms=0,
                preflight_error="TEST_ENVIRONMENT_UNAVAILABLE",
                environment_error=True,
            )

    def runner_for_selected_executor(executor: str, **kwargs):
        selected_runners.append(executor)
        assert executor == "codex"
        return DiagnosticRunner()

    monkeypatch.setattr(
        "minime.services.execution_pipeline.runner_for_implementer",
        runner_for_selected_executor,
    )
    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path),
        implementer_timeout_seconds=5,
    )
    # RecoveryConvergenceService constructs the canonical OrchestrationService
    # itself; supply its actual execution pipeline with deterministic Git/runner
    # boundaries rather than simulating recovery's result.
    monkeypatch.setattr(
        "minime.services.orchestration_service.ExecutionPipelineService",
        lambda *args, **kwargs: pipeline,
    )
    control = ControlPlaneService(in_memory_uow, project_root=tmp_path)
    reassigned = control.execute_action(
        OperatorActionRequest(
            action_request_id="n01-human-reassign-codex",
            project_id=project.project_id,
            change_name=change_name,
            run_id=run.run_id,
            action_type=OperatorActionType.REASSIGN,
            parameters={"target_executor": "codex"},
            actor_identity="authorized-human",
            source_interface="cli",
            expected_stage=OrchestrationStage.IMPLEMENTING,
            expected_generation=1,
        )
    )
    assert reassigned.status.value == "COMPLETED"
    assert reassigned.payload["execution_started"] is False
    assert in_memory_uow.jobs.get_by_id(job.job_id).attempt_count == 3
    assert selected_runners == []

    continued = control.execute_action(
        OperatorActionRequest(
            action_request_id="n01-human-continue-after-reassign",
            project_id=project.project_id,
            change_name=change_name,
            run_id=run.run_id,
            action_type=OperatorActionType.CONTINUE,
            actor_identity="authorized-human",
            source_interface="cli",
            expected_stage=OrchestrationStage.IMPLEMENTING,
            expected_generation=1,
        )
    )

    persisted_job = in_memory_uow.jobs.get_by_id(job.job_id)
    assert selected_runners == ["codex"], (
        continued.summary,
        persisted_job.status,
        persisted_job.waiting_provider,
        persisted_job.capacity_block_reason,
        persisted_job.error_message,
    )
    assert continued.payload["request_processed"] is True
    assert in_memory_uow.jobs.get_by_id(job.job_id).attempt_count == 3
    assert len(in_memory_uow.jobs.list_by_project(project.project_id)) == 1
    assert len(in_memory_uow.orchestration_runs.list_runs()) == 1
    assert len(in_memory_uow.job_attempts.list_by_job(job.job_id)) == 4
    assert in_memory_uow.job_attempts.list_by_job(job.job_id)[2].error_details["reason"] == (
        "SAME_SHA_RETRY_SUPPRESSED"
    )


@pytest.mark.asyncio
async def test_execution_pipeline_success_records_evidence_and_cleans_worktree(
    in_memory_uow, tmp_path, test_capacity_strategy, monkeypatch
):
    import builtins

    from minime.services.task_complexity_risk_classifier import TaskComplexityRiskClassifier

    import_original = builtins.__import__

    def reject_local_worker_import(name, *args, **kwargs):
        if name.startswith("minime.local_worker"):
            raise ImportError("optional local AI helper is unavailable")
        return import_original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_local_worker_import)

    test_capacity_strategy()
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

    def unavailable_optional_classifier(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("optional local classification helper unavailable")

    monkeypatch.setattr(
        TaskComplexityRiskClassifier,
        "classify_post_materialization",
        unavailable_optional_classifier,
    )

    job = await service.run_job(
        "mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert job.status == JobStatus.NEEDS_HUMAN
    assert "CODE_REVIEW_CANDIDATE_FREEZE_REQUIRES_ACTIVE_RUN" in (job.error_message or "")
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
        "total_duration_ms",
    }
    assert in_memory_uow.reviews.get_by_job_id(job.job_id) is None
    events = in_memory_uow.events.list_events(project_id="mini-me", limit=500)
    assert any(event.event_type == EventType.AUXILIARY_CLASSIFICATION_FAILED for event in events)
    assert not any(
        event.event_type == EventType.JOB_FAILED
        and event.payload.get("stage") == "post_materialization"
        for event in events
    )


@pytest.mark.asyncio
async def test_unbound_job_cannot_enter_candidate_bound_review_stage(
    in_memory_uow, tmp_path, test_capacity_strategy
):
    test_capacity_strategy(("codex", "antigravity"))
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n## 1. Things\n- [x] 1.1 Done\n",
    )
    worktrees = FakeWorktreeManager(tmp_path)
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(stdout=["candidate ready"]),
        reviewer_runner=MockReviewerRunner(stdout=['{"verdict":"READY_TO_MERGE"}']),
        auditor_runner=MockAuditorRunner(output=['{"risk":"low","findings":[]}']),
        worktree_manager=worktrees,
    )
    job = service.queue_job("mini-me", "synthetic-pipeline-change")

    result = await service.execute_queued_job(
        job.job_id, claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert result.status == JobStatus.NEEDS_HUMAN
    assert result.candidate_sha is not None
    assert in_memory_uow.reviews.get_by_job_id(job.job_id) is None


@pytest.mark.asyncio
async def test_frozen_candidate_resume_skips_apply_and_preserves_manifest(
    in_memory_uow, tmp_path, test_capacity_strategy
):
    """A review-capacity continuation adopts the frozen candidate without rerunning APPLY."""
    test_capacity_strategy(("codex", "antigravity"))
    seed_ready_change(
        in_memory_uow,
        tmp_path,
        "# Tasks\n\n## 1. Work\n- [x] 1.1 Implemented\n",
    )
    manager = FakeWorktreeManager(tmp_path)
    job = Job(
        project_id="mini-me",
        change_name="synthetic-pipeline-change",
        implementer_role="codex",
        current_executor="codex",
        status=JobStatus.WAITING_CAPACITY,
        attempt_count=2,
    )
    in_memory_uow.jobs.save(job)
    initial = await manager.create_worktree(job.job_id, job.change_name, "main")
    branch = f"minime/test-{job.job_id}"
    subprocess.run(["git", "checkout", "-b", branch], cwd=initial.path, check=True)
    base_sha = initial.base_sha
    (initial.path / "implementation.py").write_text("value = 'frozen'\n", encoding="utf-8")
    subprocess.run(["git", "add", "implementation.py"], cwd=initial.path, check=True)
    subprocess.run(["git", "commit", "-m", "freeze candidate"], cwd=initial.path, check=True)
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=initial.path, check=True, capture_output=True, text=True
    ).stdout.strip()
    worktree = WorktreeInfo(path=initial.path, branch_name=branch, base_sha=base_sha)

    from minime.services.candidate_manifest import CandidateManifestService

    manifest = CandidateManifestService().generate_manifest(initial.path, candidate_sha, job.job_id)
    from minime.domain.models import OrchestrationCandidate

    run = OrchestrationRun(
        project_id=job.project_id,
        change_name=job.change_name,
        base_sha=base_sha,
        current_stage=OrchestrationStage.IMPLEMENTING,
        active_job_id=job.job_id,
        current_generation=1,
        current_candidate_sha=candidate_sha,
        is_active=True,
    )
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.candidate_manifests.save(manifest)
    candidate = OrchestrationCandidate(
        run_id=run.run_id,
        generation=1,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        candidate_ref=f"refs/heads/{branch}",
        manifest_id=manifest.manifest_id,
        manifest_hash=manifest.manifest_hash,
        is_frozen=True,
    )
    in_memory_uow.orchestration_candidates.save(candidate)
    in_memory_uow.reviews.save(
        Review(
            job_id=job.job_id,
            project_id=job.project_id,
            change_name=job.change_name,
            reviewer_role="deepseek",
            review_stage="CODE_REVIEW",
            orchestration_run_id=run.run_id,
            candidate_generation=1,
            candidate_sha=candidate_sha,
            base_sha=base_sha,
            manifest_id=manifest.manifest_id,
            manifest_hash=manifest.manifest_hash,
            status=ReviewStatus.REVIEW_RUNNING,
        )
    )
    job.base_sha = base_sha
    job.candidate_sha = candidate_sha
    in_memory_uow.jobs.save(job)
    manager.created_paths[job.job_id] = initial.path

    class ExistingCandidateManager(FakeWorktreeManager):
        async def create_worktree(self, *args, **kwargs):
            self.adoptions = getattr(self, "adoptions", 0) + 1
            return worktree

        async def cleanup_worktree(self, job_id: str) -> None:
            self.cleaned.append(job_id)

    manager = ExistingCandidateManager(tmp_path)
    manager.created_paths[job.job_id] = initial.path

    class InvocationForbiddenRunner:
        def __init__(self):
            self.calls = 0

        async def run(self, worktree_path, prompt_context, timeout_seconds):
            del worktree_path, prompt_context, timeout_seconds
            self.calls += 1
            raise AssertionError("A frozen candidate must not be dispatched to APPLY again")

    runner = InvocationForbiddenRunner()
    pipeline = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=runner,
        worktree_manager=manager,
    )
    for provider in ("codex", "antigravity"):
        health = pipeline.health_service.get_health(provider)
        health.status = ProviderHealthStatus.AUTH_REQUIRED
        in_memory_uow.provider_health.save(health)

    result = await pipeline.execute_queued_job(
        job.job_id, candidate_generation=1, claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert manager.adoptions == 1
    assert runner.calls == 0
    assert result.candidate_sha == candidate_sha
    assert result.base_sha == base_sha
    assert len(in_memory_uow.job_attempts.list_by_job(job.job_id)) == 0
    assert (
        in_memory_uow.candidate_manifests.get_by_id(manifest.manifest_id).manifest_hash
        == manifest.manifest_hash
    )
    assert (
        in_memory_uow.orchestration_candidates.get_by_generation(run.run_id, 1).candidate_sha
        == candidate_sha
    )


@pytest.mark.asyncio
async def test_recovery_evidence_is_committed_before_worktree_removal(
    in_memory_uow, tmp_path, test_capacity_strategy
):
    test_capacity_strategy()
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

    job = await service.run_job(
        "mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert job.status == JobStatus.NEEDS_HUMAN
    assert "CODE_REVIEW_CANDIDATE_FREEZE_REQUIRES_ACTIVE_RUN" in (job.error_message or "")
    assert ordering == ["snapshot", "evidence", "remove"]
    recovery_event = next(
        event
        for event in in_memory_uow.events.list_events()
        if event.event_type == EventType.WORKTREE_RECOVERY_SNAPSHOT
    )
    assert recovery_event.payload["recovery_sha"] == f"recovery-{job.job_id}"
    assert recovery_event.payload["authoritative_candidate"] is False


@pytest.mark.asyncio
async def test_recovery_evidence_failure_blocks_without_removal(
    in_memory_uow, tmp_path, test_capacity_strategy
):
    test_capacity_strategy()
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

    job = await service.run_job(
        "mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert job.status == JobStatus.NEEDS_HUMAN
    assert "CODE_REVIEW_CANDIDATE_FREEZE_REQUIRES_ACTIVE_RUN" in (job.error_message or "")
    assert ordering == ["snapshot"]
    blocked_event = next(
        event
        for event in in_memory_uow.events.list_events()
        if event.event_type == EventType.RECOVERY_BLOCKED
    )
    assert "[REDACTED]" in blocked_event.payload["error"]
    assert "secret-recovery-value" not in blocked_event.payload["error"]


@pytest.mark.asyncio
async def test_execution_pipeline_check_failure_halts_and_records_result(
    in_memory_uow, tmp_path, test_capacity_strategy
):
    test_capacity_strategy(("codex", "antigravity"))
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

    job = await service.run_job(
        "mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert job.status == JobStatus.CHECKS_FAILED
    checks = in_memory_uow.check_results.list_by_job(job.job_id)
    assert [c.check_name for c in checks] == ["fail", "skip"]
    assert checks[0].exit_code == 4


@pytest.mark.asyncio
async def test_execution_pipeline_timeout_fails_and_records_event(
    in_memory_uow, tmp_path, test_capacity_strategy
):
    test_capacity_strategy(("codex", "antigravity"))
    seed_ready_change(in_memory_uow, tmp_path, "# Tasks\n- [x] 1.1 Done\n")
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(timed_out=True),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await service.run_job(
        "mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert job.status in (JobStatus.NEEDS_HUMAN, JobStatus.FAILED)
    events = in_memory_uow.events.list_events(
        project_id="mini-me", change_id="synthetic-pipeline-change"
    )
    assert any(event.event_type == EventType.JOB_TIMEOUT for event in events)


@pytest.mark.asyncio
async def test_execution_pipeline_incomplete_tasks_block_checks(
    in_memory_uow, tmp_path, test_capacity_strategy
):
    test_capacity_strategy(("codex", "antigravity"))
    seed_ready_change(in_memory_uow, tmp_path, "# Tasks\n- [ ] 1.1 Not done\n")
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await service.run_job(
        "mini-me", "synthetic-pipeline-change", claim_context=_dummy_claim_context(in_memory_uow)
    )

    assert job.status in (JobStatus.NEEDS_HUMAN, JobStatus.FAILED)
    assert in_memory_uow.check_results.list_by_job(job.job_id) == []
    events = in_memory_uow.events.list_events(
        project_id="mini-me", change_id="synthetic-pipeline-change"
    )
    assert any(event.event_type == EventType.INCOMPLETE_TASKS for event in events)
