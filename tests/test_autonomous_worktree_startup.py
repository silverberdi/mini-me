"""Tests for autonomous candidate worktree creation and execution startup upon admission."""

from pathlib import Path
from unittest.mock import MagicMock

from tests.conftest import InMemoryPersistenceUnitOfWork, create_isolated_openspec_change

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import (
    AdmissionDecision,
    ChangeStatus,
    OrchestrationStage,
    ProviderHealthStatus,
)
from minime.domain.models import (
    Change,
    Project,
    ProjectBinding,
    ProviderHealth,
)
from minime.services.readiness_service import ReadinessService
from minime.services.scheduler_service import SchedulerService


def test_autonomous_admission_and_run_creation(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="mini-me",
        name="016-autonomous-queue-work-selection",
        status=ChangeStatus.READY,
    )
    in_memory_uow.changes.save(change)

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=45,
        openspec_change_name="016-autonomous-queue-work-selection",
        is_valid=True,
    )
    in_memory_uow.bindings.save(binding)

    in_memory_uow.provider_health.save(
        ProviderHealth(
            health_id="ph-codex",
            provider="codex",
            status=ProviderHealthStatus.AVAILABLE,
        )
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(
            health_id="ph-antigravity",
            provider="antigravity",
            status=ProviderHealthStatus.AVAILABLE,
        )
    )

    create_isolated_openspec_change(tmp_path, change_name="016-autonomous-queue-work-selection")

    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.validate_issue_binding.return_value = (True, None)

    scheduler = SchedulerService(
        uow=in_memory_uow,
        project_root=tmp_path,
        readiness_service=ReadinessService(in_memory_uow, github_adapter=mock_gh),
    )

    # Execute admission
    decision, decision_record, run = scheduler.admit_work_item(
        "mini-me", "016-autonomous-queue-work-selection"
    )

    assert decision == AdmissionDecision.ADMITTED
    assert decision_record.decision == AdmissionDecision.ADMITTED
    assert run is not None
    assert run.project_id == "mini-me"
    assert run.change_name == "016-autonomous-queue-work-selection"
    assert run.current_stage == OrchestrationStage.ADMITTED
    assert run.is_active is True

    # Repeated tick / admission must be refused / idempotent
    dec2, rec2, run2 = scheduler.admit_work_item("mini-me", "016-autonomous-queue-work-selection")
    assert dec2 == AdmissionDecision.REFUSED
    assert run2 is None
    assert rec2.decision == AdmissionDecision.REFUSED
