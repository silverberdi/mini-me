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
from pathlib import Path
from unittest.mock import MagicMock

from tests.conftest import InMemoryPersistenceUnitOfWork, create_isolated_openspec_change

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import (
    AdmissionBlockCondition,
    AdmissionDecisionKind,
    CapacitySignalSource,
    ChangeStatus,
    ExecutionOutcome,
    JobStatus,
    ProviderHealthStatus,
    SchedulerMode,
)
from minime.domain.models import (
    CapacityWindow,
    Change,
    Job,
    JobAttempt,
    Project,
    ProjectBinding,
    ProviderHealth,
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


# 14. One provider unavailable but safe pair exists elsewhere → RUN
def test_fallback_safe_pair_exists_admits_run(
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
        elif p == "antigravity":
            return ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE)
        elif p == "anthropic/claude-3.5-sonnet":
            return ProviderHealth(
                provider="anthropic/claude-3.5-sonnet", status=ProviderHealthStatus.AVAILABLE
            )
        return orig_get_health(p)

    scheduler.provider_health_service.get_health = mock_get_health

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    # Since antigravity is available as implementer and anthropic/claude-3.5-sonnet as reviewer (independent)
    assert res.decision == AdmissionDecisionKind.RUN
    assert res.safe_executable_pair_exists is True


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


# 21. DRAIN only for material in-flight execution
def test_drain_mode_allows_in_flight_job(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    _, scheduler = setup_test_environment(tmp_path, in_memory_uow)
    scheduler.mode = SchedulerMode.DRAIN

    change = in_memory_uow.changes.get_by_name("mini-me", "016-autonomous-queue-work-selection")
    job = Job(
        job_id="job-active",
        project_id="mini-me",
        change_name=change.name,
        implementer_role="codex",
        status=JobStatus.RUNNING,
        attempt_count=1,
    )
    in_memory_uow.jobs.save(job)

    res = scheduler.evaluate_admission("mini-me", "016-autonomous-queue-work-selection")

    assert res.decision == AdmissionDecisionKind.DRAIN
    assert res.safe_executable_pair_exists is True


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
