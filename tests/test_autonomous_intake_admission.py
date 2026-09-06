"""Unit and integration tests for Autonomous Intake Preparation & Admission Policy."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import (
    AdmissionDecision,
    AdmissionRefusalCode,
    OrchestrationStage,
    ProviderHealthStatus,
    QueuePriority,
    ReadinessState,
    WorkItemPriority,
    WorkItemStatus,
)
from minime.domain.models import (
    BacklogItem,
    OrchestrationRun,
    Project,
    ProjectBinding,
    ProviderHealth,
    WorkItemAnswerInput,
    WorkItemCreateInput,
    WorkQueueItem,
    utc_now,
)
from minime.services.intake_service import IntakeService
from minime.services.project_service import ProjectService
from minime.services.scheduler_service import SchedulerService


def test_project_admission_policy_defaults(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Verify default admission policy on project registration."""
    service = ProjectService(in_memory_uow)
    project = service.register_project(
        project_id="policy-test",
        display_name="Policy Test Project",
        repository="silverberdi/test-repo",
    )

    assert project.auto_prepare is True
    assert project.auto_admit is True
    assert project.max_concurrent_jobs == 1


def test_project_admission_policy_update(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Verify updating project admission policy settings."""
    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="policy-update-test",
        display_name="Policy Update Test",
        repository="silverberdi/test-repo",
    )

    updated = service.update_project(
        "policy-update-test",
        auto_prepare=False,
        auto_admit=False,
        max_concurrent_jobs=3,
    )

    assert updated.auto_prepare is False
    assert updated.auto_admit is False
    assert updated.max_concurrent_jobs == 3


def test_auto_prepare_on_backlog_creation_happy_path(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Verify automatic preparation, OpenSpec generation, and READY transition upon creation."""
    repo_dir = tmp_path / "auto-repo"
    repo_dir.mkdir()
    openspec_dir = repo_dir / "openspec"
    openspec_dir.mkdir()

    project = Project(
        project_id="auto-project",
        display_name="Auto Project",
        repository="silverberdi/auto-repo",
        base_branch="main",
        openspec_path="openspec",
        auto_prepare=True,
    )
    in_memory_uow.projects.save(project)

    # Set up available provider pair
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE)
    )

    mock_gh = MagicMock()
    mock_gh.create_issue.return_value = {
        "number": 101,
        "html_url": "https://github.com/silverberdi/auto-repo/issues/101",
    }
    mock_gh.add_issue_to_project.return_value = "PVTI_test_101"
    mock_gh.validate_issue_binding.return_value = (True, "Valid issue")

    service = IntakeService(
        in_memory_uow,
        project_root=repo_dir,
        github_adapter=mock_gh,
    )

    item = service.create_work_item(
        "auto-project",
        WorkItemCreateInput(
            title="Implement Token Bucket Rate Limiter",
            priority=WorkItemPriority.HIGH,
            description="Add rate limiting to protect API endpoints from excessive traffic.",
            acceptance_criteria=[
                "Returns HTTP 429 Too Many Requests when quota exceeded",
                "Includes Retry-After header with seconds remaining",
            ],
        ),
        operator_email="lead-supervisor",
    )

    # 1. Backlog item should have automatically prepared and reached READY
    assert item.status == WorkItemStatus.READY
    assert item.readiness_state == ReadinessState.READY
    assert item.github_issue_number == 101
    assert item.openspec_change_name is not None

    # 2. OpenSpec change files must exist on disk
    change_dir = openspec_dir / "changes" / item.openspec_change_name
    assert (change_dir / "proposal.md").exists()
    assert (change_dir / "tasks.md").exists()
    assert (change_dir / "design.md").exists()

    # 3. Durable ProjectBinding must exist
    binding = in_memory_uow.bindings.get_by_project_and_change(
        "auto-project", item.openspec_change_name
    )
    assert binding is not None
    assert binding.github_issue_number == 101
    assert binding.is_valid is True


def test_auto_prepare_needs_human_on_ambiguity_and_resume(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Verify that underspecified items transition to NEEDS_HUMAN and resume on answer."""
    repo_dir = tmp_path / "ambiguous-repo"
    repo_dir.mkdir()
    openspec_dir = repo_dir / "openspec"
    openspec_dir.mkdir()

    project = Project(
        project_id="ambiguous-project",
        display_name="Ambiguous Project",
        repository="silverberdi/ambiguous-repo",
        auto_prepare=True,
    )
    in_memory_uow.projects.save(project)

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE)
    )

    mock_gh = MagicMock()
    mock_gh.create_issue.return_value = {
        "number": 105,
        "html_url": "https://github.com/silverberdi/ambiguous-repo/issues/105",
    }
    mock_gh.validate_issue_binding.return_value = (True, "Valid issue")

    service = IntakeService(
        in_memory_uow,
        project_root=repo_dir,
        github_adapter=mock_gh,
    )

    # Create item with sparse description (< 10 chars) and 0 acceptance criteria
    item = service.create_work_item(
        "ambiguous-project",
        WorkItemCreateInput(
            title="Vague Feature",
            description="fix",
            acceptance_criteria=[],
        ),
    )

    assert item.status == WorkItemStatus.NEEDS_HUMAN
    assert len(item.human_questions) > 0

    # Answer human question
    answered_item = service.answer_human_question(
        "ambiguous-project",
        item.item_key,
        WorkItemAnswerInput(
            question=item.human_questions[0],
            answer="Feature specifically adds Prometheus metrics endpoint at /metrics with request latency counters.",
        ),
    )

    # Should resume preparation and reach READY
    assert answered_item.status == WorkItemStatus.READY


def test_auto_admit_single_concurrency_deterministic_selection(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Verify scheduler auto-admits the highest priority item when max_concurrent_jobs = 1."""
    repo_dir = tmp_path / "sched-repo"
    repo_dir.mkdir()

    project = Project(
        project_id="sched-project",
        display_name="Sched Project",
        repository="silverberdi/sched-repo",
        auto_prepare=True,
        auto_admit=True,
        max_concurrent_jobs=1,
        implementer="codex",
    )
    in_memory_uow.projects.save(project)

    # Set codex provider to AVAILABLE
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
    )

    now = utc_now()

    # Create 2 items: normal priority and critical priority
    in_memory_uow.backlog_items.save(
        BacklogItem(
            project_id="sched-project",
            item_key="item-normal",
            title="Normal Task",
            priority=WorkItemPriority.NORMAL,
            status=WorkItemStatus.READY,
            readiness_state=ReadinessState.READY,
            openspec_change_name="item-normal",
            github_issue_number=201,
            created_at=now,
            updated_at=now,
        )
    )
    in_memory_uow.bindings.save(
        ProjectBinding(
            project_id="sched-project",
            repository="silverberdi/sched-repo",
            openspec_change_name="item-normal",
            github_issue_number=201,
            is_valid=True,
        )
    )
    in_memory_uow.work_queue.save(
        WorkQueueItem(
            project_id="sched-project",
            change_name="item-normal",
            github_issue_number=201,
            priority=QueuePriority.NORMAL,
            admission_eligible=True,
            readiness_state=ReadinessState.READY,
            discovered_at=now,
        )
    )

    in_memory_uow.backlog_items.save(
        BacklogItem(
            project_id="sched-project",
            item_key="item-critical",
            title="Critical Security Patch",
            priority=WorkItemPriority.CRITICAL,
            status=WorkItemStatus.READY,
            readiness_state=ReadinessState.READY,
            openspec_change_name="item-critical",
            github_issue_number=202,
            created_at=now,
            updated_at=now,
        )
    )
    in_memory_uow.bindings.save(
        ProjectBinding(
            project_id="sched-project",
            repository="silverberdi/sched-repo",
            openspec_change_name="item-critical",
            github_issue_number=202,
            is_valid=True,
        )
    )
    in_memory_uow.work_queue.save(
        WorkQueueItem(
            project_id="sched-project",
            change_name="item-critical",
            github_issue_number=202,
            priority=QueuePriority.CRITICAL,
            admission_eligible=True,
            readiness_state=ReadinessState.READY,
            discovered_at=now,
        )
    )

    mock_orch = MagicMock()
    mock_run = OrchestrationRun(
        run_id="run-critical",
        project_id="sched-project",
        change_name="item-critical",
        base_sha="base123",
        current_stage=OrchestrationStage.IMPLEMENTING,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    mock_orch.admit_change.return_value = MagicMock(admitted=True, run=mock_run)

    mock_readiness = MagicMock()
    mock_readiness.evaluate_change_readiness.return_value = MagicMock(
        is_ready=True, status=ReadinessState.READY, unmet_reasons=[]
    )

    scheduler = SchedulerService(
        in_memory_uow,
        project_root=repo_dir,
        orchestration_service=mock_orch,
        readiness_service=mock_readiness,
        max_global_jobs=1,
    )

    # Tick scheduler
    decisions = scheduler.tick()

    # Verify item-critical was evaluated first and admitted
    admitted = [d for d in decisions if d.decision == AdmissionDecision.ADMITTED]
    assert len(admitted) == 1
    assert admitted[0].change_name == "item-critical"

    # Verify item-normal was refused due to concurrency limit
    refused = [d for d in decisions if d.decision == AdmissionDecision.REFUSED]
    assert len(refused) >= 1
    assert refused[0].change_name == "item-normal"
    assert refused[0].reason_code in (
        AdmissionRefusalCode.GLOBAL_CONCURRENCY_LIMIT,
        AdmissionRefusalCode.PROJECT_CONCURRENCY_LIMIT,
    )


def test_primary_provider_unavailable_waiting_prevents_drain(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    """Verify that when primary implementer is exhausted, work waits and OpenRouter is NOT used as starter."""
    repo_dir = tmp_path / "exhausted-repo"
    repo_dir.mkdir()

    project = Project(
        project_id="exhausted-project",
        display_name="Exhausted Project",
        repository="silverberdi/exhausted-repo",
        auto_admit=True,
        max_concurrent_jobs=1,
        implementer="codex",
    )
    in_memory_uow.projects.save(project)

    # Set codex provider to TEMPORARILY_UNAVAILABLE
    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="codex",
            status=ProviderHealthStatus.TEMPORARILY_UNAVAILABLE,
            status_detail="Quota exhausted until reset window",
        )
    )

    now = utc_now()
    in_memory_uow.backlog_items.save(
        BacklogItem(
            project_id="exhausted-project",
            item_key="item-waiting",
            title="Waiting Task",
            priority=WorkItemPriority.HIGH,
            status=WorkItemStatus.READY,
            readiness_state=ReadinessState.READY,
            openspec_change_name="item-waiting",
            github_issue_number=301,
            created_at=now,
            updated_at=now,
        )
    )
    in_memory_uow.bindings.save(
        ProjectBinding(
            project_id="exhausted-project",
            repository="silverberdi/exhausted-repo",
            openspec_change_name="item-waiting",
            github_issue_number=301,
            is_valid=True,
        )
    )
    in_memory_uow.work_queue.save(
        WorkQueueItem(
            project_id="exhausted-project",
            change_name="item-waiting",
            github_issue_number=301,
            priority=QueuePriority.HIGH,
            admission_eligible=True,
            readiness_state=ReadinessState.READY,
            discovered_at=now,
        )
    )

    mock_readiness = MagicMock()
    mock_readiness.evaluate_change_readiness.return_value = MagicMock(
        is_ready=True, status=ReadinessState.READY, unmet_reasons=[]
    )

    scheduler = SchedulerService(
        in_memory_uow,
        project_root=repo_dir,
        readiness_service=mock_readiness,
    )

    decisions = scheduler.tick()

    assert len(decisions) == 1
    assert decisions[0].decision == AdmissionDecision.REFUSED
    assert decisions[0].reason_code == AdmissionRefusalCode.PROVIDER_UNAVAILABLE
    assert "codex" in decisions[0].reason_summary.lower()

    # Zero runs or jobs created
    assert len(in_memory_uow.orchestration_runs.list_runs()) == 0
    assert len(in_memory_uow.jobs.list_by_project("exhausted-project")) == 0
