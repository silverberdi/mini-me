"""Acceptance tests for scheduler capacity policy convergence.

Verifies:
1. SAFE_EXECUTABLE_PAIR_EXISTS evaluation (implementer + independent reviewer)
2. Accurate 4-decision operational taxonomy (RUN, DRAIN, WAIT, NEEDS_HUMAN)
3. Strict drain isolation (in-flight only, new READY work excluded)
4. Settled EVIDENCE_INSUFFICIENT contract (NEEDS_HUMAN, no retry, no capacity wait)
5. Precise human gate vs predecessor progression separation
6. Epistemic honesty in recovery timers (no fabricated ETA)
7. Entry point convergence across CLI, REST API, TUI, and daemon
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from tests.conftest import (
    InMemoryPersistenceUnitOfWork,
    create_isolated_openspec_change,
    init_git_repo,
)

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import (
    AdmissionBlockCondition,
    AdmissionDecisionKind,
    CapacitySignalSource,
    ChangeStatus,
    ExecutionOutcome,
    JobStatus,
    OrchestrationStage,
    ProviderHealthStatus,
    QueuePriority,
    ReadinessState,
    SchedulerMode,
)
from minime.domain.models import (
    CapacityWindow,
    Change,
    Job,
    JobAttempt,
    OpenRouterBudgetPolicy,
    OrchestrationRun,
    Project,
    ProjectBinding,
    ProviderHealth,
    WorkQueueItem,
    utc_now,
)
from minime.services.model_independence_policy import ModelIndependencePolicy
from minime.services.provider_health_service import ProviderHealthService
from minime.services.readiness_service import ReadinessService
from minime.services.scheduler_service import SchedulerService


def setup_test_environment(
    root: Path,
    uow: InMemoryPersistenceUnitOfWork,
    change_name: str = "016-autonomous-queue-work-selection",
    issue_number: int = 45,
    implementer: str = "codex",
    reviewer: str = "antigravity",
    implementer_status: ProviderHealthStatus = ProviderHealthStatus.AVAILABLE,
    reviewer_status: ProviderHealthStatus = ProviderHealthStatus.AVAILABLE,
    external_providers_allowed: list[str] | None = None,
    auto_admit: bool = True,
    save_health: bool = True,
) -> tuple[Project, SchedulerService]:
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        implementer=implementer,
        reviewer=reviewer,
        external_providers_allowed=external_providers_allowed or [implementer, reviewer],
        auto_admit=auto_admit,
    )
    uow.projects.save(project)

    change = Change(
        project_id="mini-me",
        name=change_name,
        status=ChangeStatus.READY,
    )
    uow.changes.save(change)

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=issue_number,
        openspec_change_name=change_name,
        is_valid=True,
    )
    uow.bindings.save(binding)

    if save_health:
        uow.provider_health.save(
            ProviderHealth(
                health_id=f"ph-{implementer}",
                provider=implementer,
                status=implementer_status,
            )
        )
        uow.provider_health.save(
            ProviderHealth(
                health_id=f"ph-{reviewer}",
                provider=reviewer,
                status=reviewer_status,
            )
        )

    create_isolated_openspec_change(root, change_name=change_name)

    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.validate_issue_binding.return_value = (True, None)

    readiness = ReadinessService(uow, github_adapter=mock_gh)
    scheduler = SchedulerService(
        uow=uow,
        project_root=root,
        readiness_service=readiness,
        provider_health_service=ProviderHealthService(uow),
        model_independence_policy=ModelIndependencePolicy(),
    )
    return project, scheduler


def _seed_active_inflight_run(
    uow: InMemoryPersistenceUnitOfWork,
    change_name: str = "016-autonomous-queue-work-selection",
    job_status: JobStatus = JobStatus.WAITING_CAPACITY,
    attempt_count: int = 1,
    candidate_sha: str | None = None,
) -> tuple[Job, OrchestrationRun]:
    """Seed an active in-flight orchestration run with a materially-started job."""
    job = Job(
        job_id="job-drain-active",
        project_id="mini-me",
        change_name=change_name,
        implementer_role="codex",
        status=job_status,
        attempt_count=attempt_count,
        candidate_sha=candidate_sha,
    )
    uow.jobs.save(job)

    run = OrchestrationRun(
        run_id="run-drain-active",
        project_id="mini-me",
        change_name=change_name,
        base_sha="2c476eafb1baec38e70aa51dcc239a81c6c6be69",
        current_stage=OrchestrationStage.IMPLEMENTING,
        active_job_id=job.job_id,
        is_active=True,
    )
    uow.orchestration_runs.save(run)
    return job, run


def _enable_drain_budget(
    uow: InMemoryPersistenceUnitOfWork,
    project: Project,
    daily_cap_usd: Decimal = Decimal("10.0"),
    monthly_cap_usd: Decimal = Decimal("100.0"),
) -> None:
    """Enable drain fallback with a bounded budget headroom for a project."""
    project.openrouter_drain_allowed = True
    uow.projects.save(project)
    uow.budget_policies.save(
        OpenRouterBudgetPolicy(
            project_id=project.project_id,
            enabled=True,
            daily_cap_usd=daily_cap_usd,
            monthly_cap_usd=monthly_cap_usd,
        )
    )


# 1. Implementer + independent reviewer available → RUN
def test_safe_executable_pair_admits_run(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(tmp_path, in_memory_uow)
    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.RUN
    assert res.safe_executable_pair_exists is True
    assert res.eligible_implementer == "codex"
    assert res.eligible_reviewer == "antigravity"
    assert res.block_condition is None


# 2. Implementer exhausted → WAIT
def test_implementer_exhausted_yields_wait(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer_status=ProviderHealthStatus.EXHAUSTED,
    )
    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.WAIT
    assert res.safe_executable_pair_exists is False
    assert res.block_condition == AdmissionBlockCondition.CAPACITY_EXHAUSTED


# 3. Reviewer temporarily exhausted → WAIT
def test_reviewer_exhausted_yields_wait(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        reviewer_status=ProviderHealthStatus.EXHAUSTED,
    )
    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.WAIT
    assert res.safe_executable_pair_exists is False
    assert res.block_condition == AdmissionBlockCondition.CAPACITY_EXHAUSTED


# 4. Reviewer independence structurally impossible → NEEDS_HUMAN
def test_reviewer_independence_structurally_impossible_yields_needs_human(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer="codex",
        reviewer="codex",
        external_providers_allowed=["codex"],
    )
    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.NEEDS_HUMAN
    assert res.safe_executable_pair_exists is False
    assert res.block_condition == AdmissionBlockCondition.REVIEWER_INDEPENDENCE_UNAVAILABLE


# 5. Auth missing → NEEDS_HUMAN
def test_auth_missing_yields_needs_human(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer_status=ProviderHealthStatus.AUTH_REQUIRED,
    )
    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.NEEDS_HUMAN
    assert res.block_condition == AdmissionBlockCondition.AUTH_REQUIRED


# 6. Invalid config → NEEDS_HUMAN
def test_invalid_config_yields_needs_human(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer_status=ProviderHealthStatus.MISCONFIGURED,
    )
    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.NEEDS_HUMAN
    assert res.block_condition == AdmissionBlockCondition.CONFIGURATION_INVALID


# 7. Known recovery/reset → WAIT with truthful recovery metadata
def test_known_recovery_reset_sets_deterministic_eta(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer_status=ProviderHealthStatus.EXHAUSTED,
    )
    reset_time = utc_now() + timedelta(minutes=15)
    window = CapacityWindow(
        provider="codex",
        capacity_reset_at=reset_time,
        source_signal=CapacitySignalSource.HEADER_RETRY_AFTER,
    )
    in_memory_uow.capacity_windows.save(window)

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.WAIT
    assert res.has_deterministic_eta is True
    assert res.cooldown_until == reset_time


# 8. Unknown recovery time → no fabricated ETA
def test_unknown_recovery_time_suppresses_eta(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer_status=ProviderHealthStatus.EXHAUSTED,
    )
    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.WAIT
    assert res.has_deterministic_eta is False
    assert res.cooldown_until is None


# 9. EVIDENCE_INSUFFICIENT → NEEDS_HUMAN, no retry
def test_evidence_insufficient_outcome_yields_needs_human_no_retry(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(tmp_path, in_memory_uow)

    change = in_memory_uow.changes.get_by_name("mini-me", "016-autonomous-queue-work-selection")
    job = Job(
        job_id="job-prev",
        project_id="mini-me",
        change_name=change.name,
        implementer_role="codex",
        status=JobStatus.FAILED,
        attempt_count=1,
    )
    in_memory_uow.jobs.save(job)

    attempt = JobAttempt(
        attempt_id="att-prev",
        job_id="job-prev",
        attempt_number=1,
        executor_role="codex",
        model_identity="codex-5.2",
        normalized_outcome=ExecutionOutcome.EVIDENCE_INSUFFICIENT,
        failure_reason="Text-only output without git diff",
    )
    in_memory_uow.job_attempts.save(attempt)

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.NEEDS_HUMAN
    assert res.block_condition == AdmissionBlockCondition.EVIDENCE_INSUFFICIENT


# 10. Structural harness absence → NEEDS_HUMAN
def test_structural_harness_absence_yields_needs_human(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(tmp_path, in_memory_uow)

    change = in_memory_uow.changes.get_by_name("mini-me", "016-autonomous-queue-work-selection")
    job = Job(
        job_id="job-harness",
        project_id="mini-me",
        change_name=change.name,
        implementer_role="codex",
        status=JobStatus.FAILED,
        attempt_count=1,
    )
    in_memory_uow.jobs.save(job)

    attempt = JobAttempt(
        attempt_id="att-harness",
        job_id="job-harness",
        attempt_number=1,
        executor_role="codex",
        model_identity="codex-5.2",
        normalized_outcome=ExecutionOutcome.ENVIRONMENT_UNAVAILABLE,
        failure_reason="HARNESS_UNAVAILABLE: Required tool binary missing",
    )
    in_memory_uow.job_attempts.save(attempt)

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.NEEDS_HUMAN
    assert res.block_condition == AdmissionBlockCondition.HARNESS_UNAVAILABLE


# 14. Configured implementer exhausted -> WAIT; the scheduler must NOT search
# external_providers_allowed for an alternative implementer/reviewer pair.
def test_no_alternate_provider_fallback_for_fresh_admission(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer="codex",
        reviewer="antigravity",
        implementer_status=ProviderHealthStatus.EXHAUSTED,
        reviewer_status=ProviderHealthStatus.AVAILABLE,
        external_providers_allowed=["codex", "antigravity", "anthropic/claude-3.5-sonnet"],
    )

    orig_get_health = scheduler.provider_health_service.get_health

    def mock_get_health(p: str):
        if p == "codex":
            return ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
        if p == "antigravity":
            return ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE)
        if p == "anthropic/claude-3.5-sonnet":
            return ProviderHealth(
                provider="anthropic/claude-3.5-sonnet", status=ProviderHealthStatus.AVAILABLE
            )
        return orig_get_health(p)

    scheduler.provider_health_service.get_health = mock_get_health

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    # The canonically assigned implementer ("codex") is exhausted. An alternate
    # provider ("anthropic/claude-3.5-sonnet") is available, but the scheduler must
    # not silently substitute it: temporary capacity failure -> WAIT.
    assert res.decision == AdmissionDecisionKind.WAIT
    assert res.safe_executable_pair_exists is False
    assert res.block_condition == AdmissionBlockCondition.CAPACITY_EXHAUSTED


# 16. Predecessor progressing → WAIT
def test_predecessor_progressing_yields_wait(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        change_name="017-pwa-control-center",
        issue_number=46,
    )
    # Stage 16 is in progress
    in_memory_uow.changes.save(
        Change(
            project_id="mini-me",
            name="016-autonomous-queue-work-selection",
            status=ChangeStatus.IN_PROGRESS,
        )
    )

    res = scheduler.evaluate_admission("mini-me", "017-pwa-control-center")

    assert res.decision == AdmissionDecisionKind.WAIT
    assert res.block_condition == AdmissionBlockCondition.LIFECYCLE_BLOCKED


# 17. Human approval required / auto_admit=False → NEEDS_HUMAN
def test_auto_admit_disabled_yields_needs_human(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        auto_admit=False,
    )
    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.NEEDS_HUMAN
    assert res.block_condition == AdmissionBlockCondition.HUMAN_APPROVAL_REQUIRED


# 20. UNKNOWN_CAPACITY unprobeable → NEEDS_HUMAN
def test_unprobeable_unknown_capacity_yields_needs_human(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer_status=ProviderHealthStatus.UNREACHABLE,
    )
    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.NEEDS_HUMAN
    assert res.block_condition == AdmissionBlockCondition.UNKNOWN_CAPACITY


# 20b. Provider health lookup failure must fail closed: never RUN.
def test_provider_health_lookup_failure_never_run(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(tmp_path, in_memory_uow)

    def failing_get_existing_health(provider: str):
        raise RuntimeError("provider health store unavailable")

    scheduler.provider_health_service.get_existing_health = failing_get_existing_health

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    # Truth unavailable -> UNKNOWN, with an authorized probe path for primary
    # providers -> WAIT. It must NEVER be synthesized into AVAILABLE/RUN.
    assert res.decision == AdmissionDecisionKind.WAIT
    assert res.safe_executable_pair_exists is False
    assert res.block_condition == AdmissionBlockCondition.UNKNOWN_CAPACITY


# 20c. Absent provider-health record must fail closed: never RUN.
def test_missing_provider_health_record_never_run(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(
        tmp_path, in_memory_uow, save_health=False
    )

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    # No persisted health row -> UNKNOWN truth, not AVAILABLE. Primary providers
    # have an authorized probe path -> WAIT. Never RUN.
    assert res.decision == AdmissionDecisionKind.WAIT
    assert res.safe_executable_pair_exists is False
    assert res.block_condition == AdmissionBlockCondition.UNKNOWN_CAPACITY


# 21. DRAIN requires an active in-flight continuation with truthful runtime state.
def test_drain_eligible_inflight_continuation_drains(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    project, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer_status=ProviderHealthStatus.EXHAUSTED,
        reviewer_status=ProviderHealthStatus.EXHAUSTED,
    )
    scheduler.mode = SchedulerMode.DRAIN
    _seed_active_inflight_run(in_memory_uow)
    _enable_drain_budget(in_memory_uow, project)

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.DRAIN
    assert res.safe_executable_pair_exists is True


# 21a. Historical completed/materialized job without an active in-flight run -> NOT DRAIN.
def test_drain_historical_completed_job_not_drain(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(tmp_path, in_memory_uow)
    scheduler.mode = SchedulerMode.DRAIN

    change = in_memory_uow.changes.get_by_name("mini-me", "016-autonomous-queue-work-selection")
    job = Job(
        job_id="job-done",
        project_id="mini-me",
        change_name=change.name,
        implementer_role="codex",
        status=JobStatus.COMPLETED,
        attempt_count=2,
        candidate_sha="0123456789abcdef",
    )
    in_memory_uow.jobs.save(job)

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision != AdmissionDecisionKind.DRAIN
    assert res.decision == AdmissionDecisionKind.WAIT


# 21b. Active material in-flight execution but drain eligibility denied -> NOT DRAIN.
def test_drain_active_inflight_eligibility_denied_not_drain(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    # Dual-primary is NOT exhausted (both AVAILABLE), so drain fallback is ineligible.
    project, scheduler = setup_test_environment(tmp_path, in_memory_uow)
    scheduler.mode = SchedulerMode.DRAIN
    _seed_active_inflight_run(in_memory_uow)
    _enable_drain_budget(in_memory_uow, project)

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision != AdmissionDecisionKind.DRAIN
    assert res.decision == AdmissionDecisionKind.WAIT


# 21c. Drain budget/headroom denied -> NOT DRAIN (halt with BUDGET_EXCEEDED).
def test_drain_budget_denied_not_drain(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    project, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer_status=ProviderHealthStatus.EXHAUSTED,
        reviewer_status=ProviderHealthStatus.EXHAUSTED,
    )
    scheduler.mode = SchedulerMode.DRAIN
    _seed_active_inflight_run(in_memory_uow)
    _enable_drain_budget(
        in_memory_uow, project, daily_cap_usd=Decimal("0.0"), monthly_cap_usd=Decimal("0.0")
    )

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision != AdmissionDecisionKind.DRAIN
    assert res.decision == AdmissionDecisionKind.NEEDS_HUMAN
    assert res.block_condition == AdmissionBlockCondition.BUDGET_EXCEEDED


# 21d. DRAIN must never invoke fresh admission; it routes to the existing continuation path.
def test_drain_never_invokes_fresh_admission(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    project, scheduler = setup_test_environment(
        tmp_path,
        in_memory_uow,
        implementer_status=ProviderHealthStatus.EXHAUSTED,
        reviewer_status=ProviderHealthStatus.EXHAUSTED,
    )
    scheduler.mode = SchedulerMode.DRAIN
    _seed_active_inflight_run(in_memory_uow)
    _enable_drain_budget(in_memory_uow, project)

    mock_run = OrchestrationRun(
        run_id="run-drain-active",
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        base_sha="2c476eafb1baec38e70aa51dcc239a81c6c6be69",
        is_active=True,
    )
    scheduler.orchestration_service = MagicMock()
    scheduler.orchestration_service.resume.return_value = mock_run

    dec, record, run = scheduler.admit_work_item(
        "mini-me", "016-autonomous-queue-work-selection"
    )

    assert scheduler.orchestration_service.admit_change.call_count == 0
    assert scheduler.orchestration_service.resume.call_count == 1
    assert record.operational_decision == AdmissionDecisionKind.DRAIN


# 22. New READY work never uses DRAIN
def test_drain_mode_refuses_new_ready_work(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(tmp_path, in_memory_uow)
    scheduler.mode = SchedulerMode.DRAIN

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.WAIT
    assert res.block_condition == AdmissionBlockCondition.CAPACITY_EXHAUSTED


# 23. Entry-point convergence: same state produces identical operational decision
def test_entry_point_convergence_consistency(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    from minime.domain.models import AdmissionResult, OrchestrationRun

    _, scheduler = setup_test_environment(tmp_path, in_memory_uow)

    mock_run = OrchestrationRun(
        run_id="run-1",
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        base_sha="2c476eafb1baec38e70aa51dcc239a81c6c6be69",
    )
    scheduler.orchestration_service = MagicMock()
    scheduler.orchestration_service.admit_change.return_value = AdmissionResult(
        admitted=True,
        run=mock_run,
    )

    eval_direct = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")
    dec, record, _ = scheduler.admit_work_item("mini-me", "016-autonomous-queue-work-selection")

    assert record.operational_decision == eval_direct.decision
    assert record.block_condition == eval_direct.block_condition
    assert record.safe_executable_pair_exists == eval_direct.safe_executable_pair_exists


# 24. A scheduler tick must not synthesize UNKNOWN provider health into AVAILABLE.
def test_tick_missing_health_never_run(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    init_git_repo(tmp_path)
    _, scheduler = setup_test_environment(tmp_path, in_memory_uow, save_health=False)

    in_memory_uow.work_queue.save(
        WorkQueueItem(
            project_id="mini-me",
            change_name="016-autonomous-queue-work-selection",
            github_issue_number=45,
            priority=QueuePriority.HIGH,
            roadmap_stage=16,
            readiness_state=ReadinessState.READY,
            admission_eligible=True,
        )
    )

    decisions = scheduler.tick("mini-me")

    assert decisions
    record = decisions[0]
    # Missing provider health must fail closed, never become RUN. The admission
    # decision reflects UNKNOWN truth (captured before readiness helpers may
    # synthesize fresh-install defaults for their own DoR bookkeeping).
    assert record.operational_decision != AdmissionDecisionKind.RUN
    assert record.operational_decision == AdmissionDecisionKind.WAIT
    assert record.block_condition == AdmissionBlockCondition.UNKNOWN_CAPACITY


# 25. An actual existing AVAILABLE record still yields normal eligibility through tick.
def test_tick_existing_available_yields_run(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    init_git_repo(tmp_path)
    _, scheduler = setup_test_environment(tmp_path, in_memory_uow)

    in_memory_uow.work_queue.save(
        WorkQueueItem(
            project_id="mini-me",
            change_name="016-autonomous-queue-work-selection",
            github_issue_number=45,
            priority=QueuePriority.HIGH,
            roadmap_stage=16,
            readiness_state=ReadinessState.READY,
            admission_eligible=True,
        )
    )

    decisions = scheduler.tick("mini-me")

    assert decisions
    record = decisions[0]
    assert record.operational_decision == AdmissionDecisionKind.RUN


# 26. Existing exhausted/cooldown state remains non-RUN through tick (no probe recovery).
def test_tick_existing_exhausted_stays_non_run(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    init_git_repo(tmp_path)
    _, scheduler = setup_test_environment(
        tmp_path, in_memory_uow, implementer_status=ProviderHealthStatus.EXHAUSTED
    )

    async def no_probe():
        return []

    scheduler.provider_health_service.probe_unavailable_providers = no_probe

    in_memory_uow.work_queue.save(
        WorkQueueItem(
            project_id="mini-me",
            change_name="016-autonomous-queue-work-selection",
            github_issue_number=45,
            priority=QueuePriority.HIGH,
            roadmap_stage=16,
            readiness_state=ReadinessState.READY,
            admission_eligible=True,
        )
    )

    decisions = scheduler.tick("mini-me")

    assert decisions
    record = decisions[0]
    assert record.operational_decision != AdmissionDecisionKind.RUN
    assert record.operational_decision == AdmissionDecisionKind.WAIT
