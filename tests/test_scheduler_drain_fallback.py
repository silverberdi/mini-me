"""Integration and unit tests for OpenRouter drain fallback, 10-point eligibility, and scheduler decoupling."""

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from minime.adapters.openrouter_adapter import MockOpenRouterAdapter
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    JobStatus,
    ProviderHealthStatus,
    ProviderResultClass,
    ReadinessState,
    ReviewVerdict,
    SchedulerMode,
)
from minime.domain.models import (
    Change,
    Job,
    NormalizedProviderResult,
    OpenRouterBudgetPolicy,
    OpenRouterPricingSnapshot,
    Project,
    ProviderHealth,
)
from minime.services.budget_service import BudgetHeadroom
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.deepseek_auditor_runner import MockAuditorRunner
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.openrouter_eligibility import OpenRouterEligibilityEvaluator
from minime.services.worktree_manager import WorktreeInfo


class GitFakeWorktreeManager:
    """Mock WorktreeManager that initializes a genuine lightweight git repo."""

    def __init__(self, root: Path):
        self.root = root
        self.created_paths: dict[str, Path] = {}
        self.cleaned: list[str] = []

    async def create_worktree(
        self, job_id: str, change_name: str, base_branch: str, project_id: str | None = None
    ) -> WorktreeInfo:
        del change_name, base_branch, project_id
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
            ["git", "commit", "--allow-empty", "-m", "init"],
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

    async def cleanup_worktree(self, job_id: str, project_id: str | None = None) -> None:
        del project_id
        self.cleaned.append(job_id)


def _setup_openspec_change(root: Path, change_name: str) -> None:
    change_dir = root / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
    (change_dir / "tasks.md").write_text("# Tasks\n- [x] 1.1 Done\n", encoding="utf-8")
    (change_dir / "design.md").write_text("# Design\n", encoding="utf-8")
    (change_dir / "specs" / "feature").mkdir(parents=True, exist_ok=True)
    (change_dir / "specs" / "feature" / "spec.md").write_text("# Spec\n", encoding="utf-8")


def _project(project_id: str = "mini-me", drain_allowed: bool = True) -> Project:
    return Project(
        project_id=project_id,
        display_name="mini me",
        repository="owner/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
        openrouter_drain_allowed=drain_allowed,
        checks=[{"name": "test-check", "command": f"{sys.executable} -c 'print(1)'"}],
    )


def _policy(
    project_id: str = "mini-me",
    enabled: bool = True,
    daily_cap: str = "10.00",
    monthly_cap: str = "25.00",
) -> OpenRouterBudgetPolicy:
    return OpenRouterBudgetPolicy(
        project_id=project_id,
        enabled=enabled,
        daily_cap_usd=Decimal(daily_cap),
        monthly_cap_usd=Decimal(monthly_cap),
        currency="USD",
        policy_version=1,
        is_breached=False,
        updated_at=datetime(2026, 8, 21, tzinfo=UTC),
    )


def test_10_point_eligibility_evaluator_all_pass():
    evaluator = OpenRouterEligibilityEvaluator()
    job = Job(
        project_id="mini-me",
        change_name="change-1",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    project = _project()
    policy = _policy()
    headroom = BudgetHeadroom(
        daily_cap_usd=Decimal("10.00"),
        monthly_cap_usd=Decimal("25.00"),
        committed_today_usd=Decimal("0.00"),
        committed_month_usd=Decimal("0.00"),
        reserved_today_usd=Decimal("0.00"),
        reserved_month_usd=Decimal("0.00"),
        unresolved_usd=Decimal("0.00"),
        unresolved_count=0,
        daily_headroom_usd=Decimal("10.00"),
        monthly_headroom_usd=Decimal("25.00"),
    )
    primary_health = [
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED),
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.EXHAUSTED),
    ]

    result = evaluator.evaluate_10_points(
        scheduler_mode=SchedulerMode.DRAIN,
        job=job,
        role="implementer",
        is_new_ready_change=False,
        primary_health_records=primary_health,
        project=project,
        policy=policy,
        headroom=headroom,
        model_identity_valid=True,
        candidate_integrity_valid=True,
        pipeline_invariants_valid=True,
    )
    assert result.eligible is True
    assert result.denial_reason is None
    assert len(result.reasons) == 0


def test_10_point_eligibility_evaluator_fails_on_run_mode():
    evaluator = OpenRouterEligibilityEvaluator()
    job = Job(
        project_id="mini-me",
        change_name="change-1",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    primary_health = [
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED),
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.EXHAUSTED),
    ]
    result = evaluator.evaluate_10_points(
        scheduler_mode=SchedulerMode.RUN,
        job=job,
        role="implementer",
        is_new_ready_change=False,
        primary_health_records=primary_health,
        project=_project(),
        policy=_policy(),
        headroom=None,
    )
    assert result.eligible is False
    assert "Scheduler is not in DRAIN mode" in result.reasons


def test_10_point_eligibility_evaluator_fails_on_single_primary_exhaustion():
    evaluator = OpenRouterEligibilityEvaluator()
    job = Job(
        project_id="mini-me",
        change_name="change-1",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    primary_health = [
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED),
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE),
    ]
    result = evaluator.evaluate_10_points(
        scheduler_mode=SchedulerMode.DRAIN,
        job=job,
        role="implementer",
        is_new_ready_change=False,
        primary_health_records=primary_health,
        project=_project(),
        policy=_policy(),
        headroom=None,
    )
    assert result.eligible is False
    assert any("Dual-primary exhaustion" in r for r in result.reasons)


def test_10_point_eligibility_evaluator_fails_on_new_ready_change():
    evaluator = OpenRouterEligibilityEvaluator()
    job = Job(
        project_id="mini-me",
        change_name="change-1",
        implementer_role="codex",
        status=JobStatus.QUEUED,
    )
    primary_health = [
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED),
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.EXHAUSTED),
    ]
    result = evaluator.evaluate_10_points(
        scheduler_mode=SchedulerMode.DRAIN,
        job=job,
        role="implementer",
        is_new_ready_change=True,
        primary_health_records=primary_health,
        project=_project(),
        policy=_policy(),
        headroom=None,
    )
    assert result.eligible is False
    assert any("Cannot admit new READY change" in r for r in result.reasons)


def test_openrouter_never_admits_new_ready_changes(in_memory_uow):
    project = _project()
    in_memory_uow.projects.save(project)
    in_memory_uow.budget_policies.save(_policy())

    # Exhaust both primary providers
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.EXHAUSTED)
    )

    change = Change(
        project_id=project.project_id,
        name="new-ready-change",
        status=ChangeStatus.READY,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    lifecycle = CapacityLifecycleService(in_memory_uow)
    can_admit, reason = lifecycle.can_admit_change(project.project_id)
    assert can_admit is False
    assert "admission of new READY work is blocked" in reason


def _seed_verified_snapshots(uow):
    snapshots = [
        OpenRouterPricingSnapshot(
            snapshot_id="snap-claude",
            canonical_model_identity="anthropic:claude-3.5-sonnet",
            routed_model_identity="anthropic/claude-3.5-sonnet",
            prompt_price_per_token=Decimal("0.000003"),
            output_price_per_token=Decimal("0.000015"),
            source="openrouter_catalog_verified",
            observed_at=datetime(2026, 8, 21, tzinfo=UTC),
        ),
        OpenRouterPricingSnapshot(
            snapshot_id="snap-gpt4o",
            canonical_model_identity="openai:gpt-4o",
            routed_model_identity="openai/gpt-4o",
            prompt_price_per_token=Decimal("0.0000025"),
            output_price_per_token=Decimal("0.000010"),
            source="openrouter_catalog_verified",
            observed_at=datetime(2026, 8, 21, tzinfo=UTC),
        ),
        OpenRouterPricingSnapshot(
            snapshot_id="snap-llama",
            canonical_model_identity="meta:llama-3.3-70b-instruct",
            routed_model_identity="meta-llama/llama-3.3-70b-instruct",
            prompt_price_per_token=Decimal("0.00000010"),
            output_price_per_token=Decimal("0.00000032"),
            source="openrouter_catalog_verified",
            observed_at=datetime(2026, 8, 21, tzinfo=UTC),
        ),
        OpenRouterPricingSnapshot(
            snapshot_id="snap-mistral",
            canonical_model_identity="mistral:mistral-large",
            routed_model_identity="mistralai/mistral-large",
            prompt_price_per_token=Decimal("0.000002"),
            output_price_per_token=Decimal("0.000006"),
            source="openrouter_catalog_verified",
            observed_at=datetime(2026, 8, 21, tzinfo=UTC),
        ),
    ]
    for s in snapshots:
        uow.pricing_snapshots.save(s)


@pytest.mark.asyncio
async def test_fallback_implementer_execution_flow(in_memory_uow, tmp_path):
    project = _project()
    in_memory_uow.projects.save(project)
    in_memory_uow.budget_policies.save(_policy())
    _seed_verified_snapshots(in_memory_uow)

    # Both primary providers are exhausted
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.EXHAUSTED)
    )

    change_name = "in-flight-change"
    _setup_openspec_change(tmp_path, change_name)

    change = Change(
        project_id=project.project_id,
        name=change_name,
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        project_id=project.project_id,
        change_name=change.name,
        implementer_role=project.implementer,
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.commit()

    mock_openrouter = MockOpenRouterAdapter(
        canned_result=NormalizedProviderResult(
            result_class=ProviderResultClass.SUCCESS,
            provider="openrouter",
            role="fallback",
            model="anthropic/claude-3.5-sonnet",
            summary="Implementation verified.",
            raw_output=json.dumps(
                {
                    "verdict": "READY_TO_MERGE",
                    "summary": "Implementation verified.",
                    "findings": [],
                }
            ),
        ),
        canned_meta={
            "prompt_tokens": 500,
            "completion_tokens": 200,
            "total_tokens": 700,
            "actual_cost_usd": 0.005,
        },
    )

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        worktree_manager=GitFakeWorktreeManager(tmp_path),
        openrouter_adapter=mock_openrouter,
        auditor_runner=MockAuditorRunner(
            output=[json.dumps({"risk": "low", "summary": "Audit passed cleanly", "findings": []})]
        ),
    )

    result_job = await pipeline.execute_queued_job(job.job_id)
    assert result_job.status in {
        JobStatus.READY_TO_MERGE,
        JobStatus.AUDIT_BLOCKED,
        JobStatus.CHANGES_REQUIRED,
    }

    # 1. OpenRouter adapter was called
    assert len(mock_openrouter.calls) >= 1
    assert mock_openrouter.calls[0].model == "anthropic/claude-3.5-sonnet"

    # 2. Reservation and settlement ledger records exist
    reservations = in_memory_uow.budget_reservations.list_by_project(project.project_id)
    assert len(reservations) >= 1
    assert any(r.status == "SETTLED" for r in reservations)

    ledger = in_memory_uow.budget_ledger.list_by_project(project.project_id)
    assert len(ledger) >= 1
    assert any(e.entry_type == "SETTLEMENT" for e in ledger)

    # 3. Primary provider health was NOT altered by OpenRouter outcome
    codex_health = in_memory_uow.provider_health.get_by_provider("codex")
    agy_health = in_memory_uow.provider_health.get_by_provider("antigravity")
    assert codex_health.status == ProviderHealthStatus.EXHAUSTED
    assert agy_health.status == ProviderHealthStatus.EXHAUSTED

    # 4. Events emitted
    events = in_memory_uow.events.list_events(project_id=project.project_id)
    event_types = [e.event_type for e in events]
    assert EventType.FALLBACK_MODEL_SELECTED in event_types
    assert EventType.FALLBACK_INVOKED in event_types
    assert EventType.BUDGET_RESERVED in event_types
    assert EventType.BUDGET_SETTLED in event_types


@pytest.mark.asyncio
async def test_fallback_reviewer_model_independence(in_memory_uow, tmp_path):
    project = _project()
    in_memory_uow.projects.save(project)
    in_memory_uow.budget_policies.save(_policy())
    _seed_verified_snapshots(in_memory_uow)

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.EXHAUSTED)
    )

    change_name = "review-fallback-change"
    _setup_openspec_change(tmp_path, change_name)

    change = Change(
        project_id=project.project_id,
        name=change_name,
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        project_id=project.project_id,
        change_name=change.name,
        implementer_role=project.implementer,
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.commit()

    # Provide OpenRouter mock that returns a valid review verdict
    canned_review_output = json.dumps(
        {
            "verdict": "READY_TO_MERGE",
            "summary": "Implementation verified independent.",
            "findings": [],
        }
    )
    mock_openrouter = MockOpenRouterAdapter(
        canned_result=NormalizedProviderResult(
            result_class=ProviderResultClass.SUCCESS,
            provider="openrouter",
            role="fallback",
            model="openai/gpt-4o",
            raw_output=canned_review_output,
            summary="Review completed",
        ),
        canned_meta={
            "prompt_tokens": 400,
            "completion_tokens": 50,
            "total_tokens": 450,
            "actual_cost_usd": 0.002,
        },
    )

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        worktree_manager=GitFakeWorktreeManager(tmp_path),
        openrouter_adapter=mock_openrouter,
        auditor_runner=MockAuditorRunner(
            output=[json.dumps({"risk": "low", "summary": "Audit passed cleanly", "findings": []})]
        ),
    )

    result_job = await pipeline.execute_queued_job(job.job_id)
    assert result_job.status in {JobStatus.READY_TO_MERGE, JobStatus.AUDIT_BLOCKED}

    # Reviewer model selected must be distinct from implementer
    reviews = in_memory_uow.reviews.list_by_project(project.project_id)
    assert len(reviews) >= 1
    assert "openrouter:" in reviews[0].reviewer_role
    assert reviews[0].verdict == ReviewVerdict.READY_TO_MERGE

    # Scheduler remains in DRAIN or WAIT (OpenRouter success NEVER returns scheduler to RUN)
    lifecycle = CapacityLifecycleService(in_memory_uow)
    status = lifecycle.get_scheduler_status(project.project_id)
    assert status.mode in {SchedulerMode.DRAIN, SchedulerMode.WAIT}
    assert status.admission_allowed is False


@pytest.mark.asyncio
async def test_fallback_reviewer_model_collision_fails_closed(in_memory_uow, tmp_path):
    project = _project()
    in_memory_uow.projects.save(project)
    in_memory_uow.budget_policies.save(_policy())
    _seed_verified_snapshots(in_memory_uow)

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.EXHAUSTED)
    )

    change_name = "collision-change"
    _setup_openspec_change(tmp_path, change_name)

    change = Change(
        project_id=project.project_id,
        name=change_name,
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        project_id=project.project_id,
        change_name=change.name,
        implementer_role=project.implementer,
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.commit()

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        worktree_manager=GitFakeWorktreeManager(tmp_path),
        openrouter_adapter=MockOpenRouterAdapter(),
        auditor_runner=MockAuditorRunner(),
    )
    # Restrict allowed reviewer models to same family as implementer default (e.g. anthropic)
    pipeline.default_implementer_model = "anthropic/claude-3.5-sonnet"
    pipeline.allowed_reviewer_models = [
        "anthropic/claude-3.5-haiku",
        "anthropic/claude-3.5-sonnet:beta",
    ]

    result_job = await pipeline.execute_queued_job(job.job_id)

    # Must fail closed with DISTINCT_REVIEWER_UNAVAILABLE in WAITING_CAPACITY
    assert result_job.status == JobStatus.WAITING_CAPACITY
    assert result_job.capacity_block_reason == "DISTINCT_REVIEWER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_atomic_reservation_denial_prevents_http_dispatch(in_memory_uow, tmp_path):
    project = _project()
    in_memory_uow.projects.save(project)
    # Budget policy daily cap $0.00 -> will deny reservation
    in_memory_uow.budget_policies.save(_policy(daily_cap=0.0, monthly_cap=0.0))
    _seed_verified_snapshots(in_memory_uow)

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.EXHAUSTED)
    )

    job = Job(
        project_id=project.project_id,
        change_name="denied-change",
        implementer_role=project.implementer,
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.commit()

    mock_adapter = MockOpenRouterAdapter()
    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        worktree_manager=GitFakeWorktreeManager(tmp_path),
        openrouter_adapter=mock_adapter,
        auditor_runner=MockAuditorRunner(),
    )

    result_job = await pipeline.execute_queued_job(job.job_id)

    # Reservation denied -> ZERO HTTP requests must be dispatched!
    assert len(mock_adapter.calls) == 0
    assert result_job.status == JobStatus.WAITING_CAPACITY


@pytest.mark.asyncio
async def test_missing_verified_pricing_snapshot_denies_fallback_with_zero_http(
    in_memory_uow, tmp_path
):
    """Prove that fallback is denied and 0 HTTP requests are made when no verified snapshot exists in DB."""
    project = _project()
    in_memory_uow.projects.save(project)
    in_memory_uow.budget_policies.save(_policy(daily_cap=100.0, monthly_cap=1000.0))
    # Deliberately DO NOT seed verified snapshots in in_memory_uow!

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.EXHAUSTED)
    )

    change_name = "no-snap-change"
    _setup_openspec_change(tmp_path, change_name)
    change = Change(
        project_id=project.project_id,
        name=change_name,
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        project_id=project.project_id,
        change_name=change_name,
        implementer_role=project.implementer,
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.commit()

    mock_adapter = MockOpenRouterAdapter()
    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        worktree_manager=GitFakeWorktreeManager(tmp_path),
        openrouter_adapter=mock_adapter,
        auditor_runner=MockAuditorRunner(),
    )

    result_job = await pipeline.execute_queued_job(job.job_id)

    # 1. Zero HTTP dispatched
    assert len(mock_adapter.calls) == 0

    # 2. Job paused in WAITING_CAPACITY
    assert result_job.status == JobStatus.WAITING_CAPACITY
    assert "PRICING_SNAPSHOT_MISSING" in result_job.capacity_block_reason

    # 3. Fallback denied event recorded
    events = in_memory_uow.events.list_events(project_id=project.project_id)
    denial_events = [e for e in events if e.event_type == EventType.FALLBACK_DENIED]
    assert len(denial_events) == 1
    assert denial_events[0].payload["reason"] == "PRICING_SNAPSHOT_MISSING"


@pytest.mark.asyncio
async def test_unverified_pinned_default_snapshot_in_db_denies_fallback_with_zero_http(
    in_memory_uow, tmp_path
):
    """Prove that legacy/unverified 'pinned_default' snapshots in DB cannot authorize spend."""
    project = _project()
    in_memory_uow.projects.save(project)
    in_memory_uow.budget_policies.save(_policy(daily_cap=100.0, monthly_cap=1000.0))

    # Save an unverified pinned_default snapshot
    in_memory_uow.pricing_snapshots.save(
        OpenRouterPricingSnapshot(
            snapshot_id="openrouter:anthropic/claude-3.5-sonnet:pinned",
            canonical_model_identity="anthropic:claude-3.5-sonnet",
            routed_model_identity="anthropic/claude-3.5-sonnet",
            prompt_price_per_token=Decimal("0.0000005"),
            output_price_per_token=Decimal("0.0000015"),
            source="pinned_default",  # UNVERIFIED
            observed_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.EXHAUSTED)
    )

    change_name = "pinned-snap-change"
    _setup_openspec_change(tmp_path, change_name)
    change = Change(
        project_id=project.project_id,
        name=change_name,
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        project_id=project.project_id,
        change_name=change_name,
        implementer_role=project.implementer,
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.commit()

    mock_adapter = MockOpenRouterAdapter()
    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        worktree_manager=GitFakeWorktreeManager(tmp_path),
        openrouter_adapter=mock_adapter,
        auditor_runner=MockAuditorRunner(),
    )

    result_job = await pipeline.execute_queued_job(job.job_id)

    # 1. Zero HTTP dispatched
    assert len(mock_adapter.calls) == 0

    # 2. Job paused in WAITING_CAPACITY because pinned_default cannot authorize spend
    assert result_job.status == JobStatus.WAITING_CAPACITY
    assert "PRICING_SNAPSHOT_MISSING" in result_job.capacity_block_reason
