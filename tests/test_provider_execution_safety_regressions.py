# Regression tests for provider-execution-safety-stabilization (Task Group 1).
#
# These tests reproduce two confirmed production defects and are expected to FAIL
# against the current implementation until Task Groups 3-5 land:
#   1. unknown-reset Codex probe storm across scheduler cycles
#   2. fabricated OpenRouter candidate_impl.py on textual fallback success

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from minime.adapters.openrouter_adapter import MockOpenRouterAdapter
from minime.adapters.provider_adapter import FakeProviderAdapter
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ExecutionOutcome,
    JobStatus,
    ProviderHealthStatus,
    ProviderResultClass,
    ReadinessState,
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
from minime.services.deepseek_auditor_runner import MockAuditorRunner
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.worktree_manager import WorktreeInfo


def _setup_openspec_change(root: Path, change_name: str) -> None:
    change_dir = root / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text("# Proposal" + chr(10), encoding="utf-8")
    (change_dir / "tasks.md").write_text(
        "# Tasks" + chr(10) + "- [x] 1.1 Done" + chr(10), encoding="utf-8"
    )
    (change_dir / "design.md").write_text("# Design" + chr(10), encoding="utf-8")
    spec_dir = change_dir / "specs" / "feature"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_text("# Spec" + chr(10), encoding="utf-8")


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
        checks=[
            {"name": "test-check", "command": f"{sys.executable} -c print(1)"}
        ],
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


def _seed_verified_snapshots(uow) -> None:
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
    ]
    for snapshot in snapshots:
        uow.pricing_snapshots.save(snapshot)


class GitFakeWorktreeManager:
    # Mock WorktreeManager that initializes a genuine lightweight git repository.

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
            ["git", "rev-parse", "HEAD"], cwd=str(path), check=True, capture_output=True, text=True
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


async def test_unknown_reset_codex_probe_storm_is_bounded_across_scheduler_cycles(
    in_memory_uow, monkeypatch
):
    # Regression: a missing capacity_reset_at must NOT make an unavailable provider
    # probe-eligible on every scheduler cycle. ProviderHealthService.check_and_probe_provider
    # currently sets is_reset_elapsed = True for unknown reset timing, so the
    # scheduler-level probe_unavailable_providers() path probes Codex once per tick.
    service = ProviderHealthService(in_memory_uow)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex",
            role="implementer",
            result_class=ProviderResultClass.QUOTA_LIMIT,
            summary="Quota exhausted; reset time unknown",
        )
    )
    assert service.get_health("codex").status == ProviderHealthStatus.EXHAUSTED
    latest_window = in_memory_uow.capacity_windows.get_latest_for_provider("codex")
    assert latest_window is not None
    assert latest_window.capacity_reset_at is None
    # Only Codex is unavailable; Antigravity must never be probed.
    assert service.get_health("antigravity").status == ProviderHealthStatus.AVAILABLE

    counting_adapter = FakeProviderAdapter(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter",
        lambda provider: counting_adapter,
    )

    for _ in range(100):
        await service.probe_unavailable_providers()

    # Bounded recovery expectation (acceptance scenario 3): once the cooldown/backoff
    # gate lands, 100 scheduler cycles must stay far below one probe per cycle.
    assert counting_adapter.probe_call_count <= 5, (
        "probe storm reproduced: "
        + str(counting_adapter.probe_call_count)
        + " Codex probes across 100 scheduler cycles; expected bounded cooldown/backoff recovery"
    )


async def test_openrouter_fallback_success_creates_no_fabricated_candidate(in_memory_uow, tmp_path):
    # Regression: OpenRouter implementer fallback returning a textual SUCCESS must NOT
    # fabricate candidate_impl.py or a candidate commit when no repository-editing harness
    # materialized the requested change. execution_pipeline.py currently writes a placeholder
    # candidate_impl.py and commits it as "openrouter candidate changes".
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

    change_name = "in-flight-openrouter"
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

    canned_success = NormalizedProviderResult(
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
    )
    worktrees = GitFakeWorktreeManager(tmp_path)
    mock_openrouter = MockOpenRouterAdapter(
        canned_result=canned_success,
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
        worktree_manager=worktrees,
        openrouter_adapter=mock_openrouter,
        auditor_runner=MockAuditorRunner(
            output=[
                json.dumps({"risk": "low", "summary": "Audit passed cleanly", "findings": []})
            ]
        ),
    )

    result_job = await pipeline.execute_queued_job(job.job_id)

    # Confirm the OpenRouter fallback implementer path was actually exercised.
    assert len(mock_openrouter.calls) >= 1

    # Leaf D: no candidate SHA without material repository materialization.
    assert result_job.candidate_sha is None
    assert result_job.status != JobStatus.WAITING_CAPACITY

    worktree_path = worktrees.created_paths[job.job_id]

    # No placeholder candidate artifact may be materialized without real repository changes.
    assert not (worktree_path / "candidate_impl.py").exists(), (
        "OpenRouter fallback fabricated candidate_impl.py without real repository materialization"
    )

    # No fabricated candidate commit may be created by the fallback branch.
    log_proc = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=str(worktree_path),
        check=True,
        capture_output=True,
        text=True,
    )
    assert "openrouter candidate changes" not in log_proc.stdout


async def test_openrouter_success_without_harness_returns_truthful_outcome(
    in_memory_uow, tmp_path
):
    # Textual provider success must never become implementation success without a
    # material repository change. Assert a truthful governed outcome and no false
    # progress/lifecycle evidence.
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
    change_name = "truthful-outcome"
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

    canned_success = NormalizedProviderResult(
        result_class=ProviderResultClass.SUCCESS,
        provider="openrouter",
        role="fallback",
        model="anthropic/claude-3.5-sonnet",
        summary="Text only",
        raw_output=json.dumps({"verdict": "READY_TO_MERGE", "summary": "Text only", "findings": []}),
    )
    worktrees = GitFakeWorktreeManager(tmp_path)
    mock_openrouter = MockOpenRouterAdapter(
        canned_result=canned_success,
        canned_meta={"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700, "actual_cost_usd": 0.005},
    )
    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        worktree_manager=worktrees,
        openrouter_adapter=mock_openrouter,
        auditor_runner=MockAuditorRunner(),
    )

    result_job = await pipeline.execute_queued_job(job.job_id)

    # Leaf E: a missing repository-editing harness is NOT recoverable capacity.
    assert result_job.status != JobStatus.WAITING_CAPACITY
    # Truthful non-capacity, non-transport outcome.
    assert result_job.latest_outcome == ExecutionOutcome.EVIDENCE_INSUFFICIENT
    # Leaf D: base SHA must never be promoted to candidate SHA without materialization.
    assert result_job.candidate_sha is None
    assert not (worktrees.created_paths[job.job_id] / "candidate_impl.py").exists()

    events = in_memory_uow.events.list_events(project_id=project.project_id)
    event_types = {e.event_type for e in events}
    forbidden = {
        EventType.ATTEMPT_COMPLETED,
        EventType.COMPLETION_VERIFIED,
        EventType.CANDIDATE_FROZEN,
        EventType.JOB_READY_TO_MERGE,
    }
    assert not (event_types & forbidden)
    assert in_memory_uow.reviews.list_by_project(project.project_id) == []
