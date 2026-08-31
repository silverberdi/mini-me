"""Tests for admission control, roadmap stage gating, concurrency limits, and provider modes."""

from pathlib import Path
from unittest.mock import MagicMock

from tests.conftest import InMemoryPersistenceUnitOfWork, create_isolated_openspec_change

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import (
    AdmissionDecision,
    AdmissionRefusalCode,
    ChangeStatus,
    OrchestrationStage,
    ProviderHealthStatus,
    SchedulerMode,
)
from minime.domain.models import (
    Change,
    OrchestrationRun,
    Project,
    ProjectBinding,
    ProviderHealth,
    WorkQueueItem,
)
from minime.services.readiness_service import ReadinessService
from minime.services.scheduler_service import SchedulerService


def setup_test_project_and_change(
    root: Path,
    uow: InMemoryPersistenceUnitOfWork,
    change_name: str = "016-autonomous-queue-work-selection",
    issue_number: int = 45,
    implementer: str = "codex",
    reviewer: str = "antigravity",
) -> Project:
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        implementer=implementer,
        reviewer=reviewer,
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

    # Provider health
    uow.provider_health.save(
        ProviderHealth(
            health_id=f"ph-{implementer}",
            provider=implementer,
            status=ProviderHealthStatus.AVAILABLE,
        )
    )
    uow.provider_health.save(
        ProviderHealth(
            health_id=f"ph-{reviewer}",
            provider=reviewer,
            status=ProviderHealthStatus.AVAILABLE,
        )
    )

    create_isolated_openspec_change(root, change_name=change_name)
    return project


def test_admit_valid_ready_item(tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork):
    setup_test_project_and_change(tmp_path, in_memory_uow)

    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.validate_issue_binding.return_value = (True, None)

    scheduler = SchedulerService(
        uow=in_memory_uow,
        project_root=tmp_path,
        readiness_service=ReadinessService(in_memory_uow, github_adapter=mock_gh),
    )

    decision, refusal_code, summary, impl = scheduler.evaluate_admission(
        "mini-me", "016-autonomous-queue-work-selection"
    )
    assert decision == AdmissionDecision.ADMITTED
    assert refusal_code is None
    assert impl == "codex"


def test_roadmap_predecessor_incomplete_blocks_future_stage(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    setup_test_project_and_change(
        tmp_path, in_memory_uow, change_name="017-pwa-control-center", issue_number=46
    )

    # Add earlier stage 16 in progress
    in_memory_uow.changes.save(
        Change(
            project_id="mini-me",
            name="016-autonomous-queue-work-selection",
            status=ChangeStatus.IN_PROGRESS,
        )
    )

    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.validate_issue_binding.return_value = (True, None)

    scheduler = SchedulerService(
        uow=in_memory_uow,
        project_root=tmp_path,
        readiness_service=ReadinessService(in_memory_uow, github_adapter=mock_gh),
    )

    decision, refusal_code, summary, _ = scheduler.evaluate_admission(
        "mini-me", "017-pwa-control-center"
    )
    assert decision == AdmissionDecision.REFUSED
    assert refusal_code == AdmissionRefusalCode.ROADMAP_PREDECESSOR_INCOMPLETE
    assert "016" in summary


def test_dependency_blocked_when_incomplete(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    setup_test_project_and_change(
        tmp_path, in_memory_uow, change_name="016-feature-b", issue_number=50
    )

    # Incomplete dependency feature A
    in_memory_uow.changes.save(
        Change(
            project_id="mini-me",
            name="016-feature-a",
            status=ChangeStatus.IN_PROGRESS,
        )
    )

    item_b = WorkQueueItem(
        project_id="mini-me",
        change_name="016-feature-b",
        dependencies=["016-feature-a"],
    )
    in_memory_uow.work_queue.save(item_b)

    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.validate_issue_binding.return_value = (True, None)

    scheduler = SchedulerService(
        uow=in_memory_uow,
        project_root=tmp_path,
        readiness_service=ReadinessService(in_memory_uow, github_adapter=mock_gh),
    )

    decision, refusal_code, summary, _ = scheduler.evaluate_admission("mini-me", "016-feature-b")
    assert decision == AdmissionDecision.REFUSED
    assert refusal_code == AdmissionRefusalCode.DEPENDENCY_BLOCKED


def test_scheduler_drain_mode_blocks_new_admissions(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    setup_test_project_and_change(tmp_path, in_memory_uow)

    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.validate_issue_binding.return_value = (True, None)

    scheduler = SchedulerService(
        uow=in_memory_uow,
        project_root=tmp_path,
        readiness_service=ReadinessService(in_memory_uow, github_adapter=mock_gh),
        mode=SchedulerMode.DRAIN,
    )

    decision, refusal_code, summary, _ = scheduler.evaluate_admission(
        "mini-me", "016-autonomous-queue-work-selection"
    )
    assert decision == AdmissionDecision.REFUSED
    assert refusal_code == AdmissionRefusalCode.PROVIDER_DRAIN


def test_concurrency_limit_blocks_admission(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    setup_test_project_and_change(tmp_path, in_memory_uow)

    # Active run already exists
    active_run = OrchestrationRun(
        run_id="run-active-1",
        project_id="mini-me",
        change_name="015-operator-actions-control-plane",
        base_sha="base123456",
        current_stage=OrchestrationStage.IMPLEMENTING,
        is_active=True,
    )
    in_memory_uow.orchestration_runs.save(active_run)

    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.validate_issue_binding.return_value = (True, None)

    scheduler = SchedulerService(
        uow=in_memory_uow,
        project_root=tmp_path,
        readiness_service=ReadinessService(in_memory_uow, github_adapter=mock_gh),
        max_global_jobs=1,
        one_active_implementation_per_project=True,
    )

    decision, refusal_code, summary, _ = scheduler.evaluate_admission(
        "mini-me", "016-autonomous-queue-work-selection"
    )
    assert decision == AdmissionDecision.REFUSED
    assert refusal_code in (
        AdmissionRefusalCode.PROJECT_CONCURRENCY_LIMIT,
        AdmissionRefusalCode.GLOBAL_CONCURRENCY_LIMIT,
    )
