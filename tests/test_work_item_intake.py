"""Unit and integration tests for 021.3 Work Item Intake."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import WorkItemPriority
from minime.domain.models import Project, WorkItemCreateInput, WorkItemUpdateInput
from minime.services.intake_service import IntakeService


def test_create_and_update_work_item(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "work-repo"
    repo_dir.mkdir()

    project = Project(
        project_id="work-project",
        display_name="Work Project",
        repository=str(repo_dir),
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    service = IntakeService(in_memory_uow, project_root=repo_dir)

    # 1. Create work item
    item = service.create_work_item(
        "work-project",
        WorkItemCreateInput(
            title="Implement Rate Limiting",
            priority=WorkItemPriority.HIGH,
            description="Protect API endpoints from abuse.",
            acceptance_criteria=["Returns HTTP 429 when quota exceeded"],
        ),
        operator_email="operator@example.com",
    )

    assert item.project_id == "work-project"
    assert "rate-limiting" in item.item_key
    assert item.priority == WorkItemPriority.HIGH
    assert len(item.acceptance_criteria) == 1

    # 2. Update priority and description
    updated = service.update_work_item(
        "work-project",
        item.item_key,
        WorkItemUpdateInput(
            priority=WorkItemPriority.CRITICAL,
            description="Updated description with security rationale.",
        ),
        operator_email="operator@example.com",
    )

    assert updated.priority == WorkItemPriority.CRITICAL
    assert updated.description == "Updated description with security rationale."

    # 3. Delete work item
    service.delete_work_item("work-project", item.item_key, operator_email="operator@example.com")
    deleted = in_memory_uow.backlog_items.get_by_project_and_key("work-project", item.item_key)
    assert deleted is None


def test_create_duplicate_work_item_fails(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "work-repo"
    repo_dir.mkdir()

    project = Project(
        project_id="work-project",
        display_name="Work Project",
        repository=str(repo_dir),
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    service = IntakeService(in_memory_uow, project_root=repo_dir)

    service.create_work_item(
        "work-project",
        WorkItemCreateInput(
            item_key="022-unique-key",
            title="First task",
        ),
        operator_email="operator@example.com",
    )

    with pytest.raises(ValueError, match="already exists"):
        service.create_work_item(
            "work-project",
            WorkItemCreateInput(
                item_key="022-unique-key",
                title="Duplicate task",
            ),
            operator_email="operator@example.com",
        )


def test_reconcile_backlog_projections_with_terminal_and_human_states(
    in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path
) -> None:
    from minime.domain.enums import (
        ChangeStatus,
        OrchestrationStage,
        OrchestrationStopOutcome,
        ReadinessState,
        WorkItemStatus,
    )
    from minime.domain.models import BacklogItem, Change, OrchestrationRun, utc_now

    repo_dir = tmp_path / "work-repo"
    repo_dir.mkdir()

    project = Project(
        project_id="work-project",
        display_name="Work Project",
        repository=str(repo_dir),
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    service = IntakeService(in_memory_uow, project_root=repo_dir)

    now = utc_now()
    # 1. Backlog item stuck in PREPARING for a merged/completed change
    item_merged = BacklogItem(
        project_id="work-project",
        item_key="generic-provider-capacity-recovery-drain",
        title="Generic Provider Recovery",
        status=WorkItemStatus.PREPARING,
        readiness_state=ReadinessState.NOT_READY,
        openspec_change_name="generic-provider-capacity-recovery-drain",
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(item_merged)
    in_memory_uow.changes.save(
        Change(
            project_id="work-project",
            name="generic-provider-capacity-recovery-drain",
            status=ChangeStatus.DONE,
            discovered_at=now,
            updated_at=now,
        )
    )
    in_memory_uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-merged",
            project_id="work-project",
            change_name="generic-provider-capacity-recovery-drain",
            base_sha="base123",
            current_stage=OrchestrationStage.COMPLETED,
            stop_outcome=OrchestrationStopOutcome.COMPLETED,
            is_active=False,
            created_at=now,
            updated_at=now,
        )
    )

    # 2. Backlog item stuck in RUNNING with a run waiting for human action (READY_FOR_HUMAN_MERGE)
    item_pr = BacklogItem(
        project_id="work-project",
        item_key="021-runtime-latency-header",
        title="Runtime Latency Header",
        status=WorkItemStatus.RUNNING,
        readiness_state=ReadinessState.READY,
        openspec_change_name="021-runtime-latency-header",
        run_id="run-pr",
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(item_pr)
    in_memory_uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-pr",
            project_id="work-project",
            change_name="021-runtime-latency-header",
            base_sha="base123",
            current_stage=OrchestrationStage.PR_PREPARED,
            stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
            is_active=False,
            created_at=now,
            updated_at=now,
        )
    )

    # 3. Pristine backlog item untouched in BACKLOG/NOT_READY
    item_pristine = BacklogItem(
        project_id="work-project",
        item_key="autonomous-intake-preparation-admission",
        title="Autonomous Intake Preparation",
        status=WorkItemStatus.BACKLOG,
        readiness_state=ReadinessState.NOT_READY,
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(item_pristine)

    # Run reconciliation
    service.reconcile_backlog_projections("work-project")

    # Verify item_merged transitioned to COMPLETED
    rec_merged = in_memory_uow.backlog_items.get_by_project_and_key("work-project", "generic-provider-capacity-recovery-drain")
    assert rec_merged is not None
    assert rec_merged.status == WorkItemStatus.COMPLETED
    assert rec_merged.readiness_state == ReadinessState.READY

    # Verify item_pr transitioned to NEEDS_HUMAN
    rec_pr = in_memory_uow.backlog_items.get_by_project_and_key("work-project", "021-runtime-latency-header")
    assert rec_pr is not None
    assert rec_pr.status == WorkItemStatus.NEEDS_HUMAN

    # Verify item_pristine remains strictly BACKLOG / NOT_READY
    rec_pristine = in_memory_uow.backlog_items.get_by_project_and_key("work-project", "autonomous-intake-preparation-admission")
    assert rec_pristine is not None
    assert rec_pristine.status == WorkItemStatus.BACKLOG
    assert rec_pristine.readiness_state == ReadinessState.NOT_READY

