"""Comprehensive unit and integration tests for Canonical Lifecycle Transition Authority."""

from __future__ import annotations

from pathlib import Path

import pytest

from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ReadinessState,
    WorkItemSource,
    WorkItemStatus,
)
from minime.domain.exceptions import (
    LifecycleBypassError,
    LifecycleInvalidTransitionError,
    LifecycleTransitionConflictError,
)
from minime.domain.models import BacklogItem, Change, Project, utc_now
from minime.services.intake_service import IntakeService
from minime.services.lifecycle_transition_authority import (
    LifecycleTransitionAuthority,
)
from minime.services.post_merge_service import PostMergeReconciliationService
from minime.services.readiness_service import ReadinessService


def _setup_project(uow, project_id="test-proj") -> Project:
    project = Project(
        project_id=project_id,
        display_name="Test Project",
        repository="owner/repo",
        base_branch="main",
        openspec_path="openspec",
    )
    uow.projects.save(project)
    return project


def test_valid_and_invalid_change_matrices(in_memory_uow):
    """Test all valid Change transitions succeed and invalid transitions fail."""
    _setup_project(in_memory_uow)
    authority = LifecycleTransitionAuthority(in_memory_uow)
    now = utc_now()

    # Initial creation
    c = Change(project_id="test-proj", name="ch-1", status=ChangeStatus.DISCOVERED, discovered_at=now, updated_at=now)
    in_memory_uow.changes.save(c)

    # Valid: DISCOVERED -> READY
    c1 = authority.transition_change("test-proj", "ch-1", ChangeStatus.DISCOVERED, ChangeStatus.READY)
    assert c1.status == ChangeStatus.READY

    # Valid: READY -> IN_PROGRESS
    c2 = authority.transition_change("test-proj", "ch-1", ChangeStatus.READY, ChangeStatus.IN_PROGRESS)
    assert c2.status == ChangeStatus.IN_PROGRESS

    # Valid: IN_PROGRESS -> DONE
    c3 = authority.transition_change("test-proj", "ch-1", ChangeStatus.IN_PROGRESS, ChangeStatus.DONE)
    assert c3.status == ChangeStatus.DONE

    # Invalid: DONE -> READY (Terminal regression)
    with pytest.raises(LifecycleInvalidTransitionError):
        authority.transition_change("test-proj", "ch-1", ChangeStatus.DONE, ChangeStatus.READY)


def test_valid_and_invalid_work_item_matrices(in_memory_uow):
    """Test all valid WorkItem transitions succeed and invalid transitions fail."""
    _setup_project(in_memory_uow)
    authority = LifecycleTransitionAuthority(in_memory_uow)
    now = utc_now()

    # Initial creation
    bk = BacklogItem(
        project_id="test-proj",
        item_key="bk-1",
        title="Test item",
        description="desc",
        status=WorkItemStatus.BACKLOG,
        source=WorkItemSource.ROADMAP,
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)

    # Valid: BACKLOG -> CONTEXT_CHECK
    i1 = authority.transition_backlog_item("test-proj", "bk-1", WorkItemStatus.BACKLOG, WorkItemStatus.CONTEXT_CHECK)
    assert i1.status == WorkItemStatus.CONTEXT_CHECK

    # Valid: CONTEXT_CHECK -> PREPARING
    i2 = authority.transition_backlog_item("test-proj", "bk-1", WorkItemStatus.CONTEXT_CHECK, WorkItemStatus.PREPARING)
    assert i2.status == WorkItemStatus.PREPARING

    # Valid: PREPARING -> READY
    i3 = authority.transition_backlog_item("test-proj", "bk-1", WorkItemStatus.PREPARING, WorkItemStatus.READY)
    assert i3.status == WorkItemStatus.READY

    # Valid: READY -> ADMITTED
    i4 = authority.transition_backlog_item("test-proj", "bk-1", WorkItemStatus.READY, WorkItemStatus.ADMITTED)
    assert i4.status == WorkItemStatus.ADMITTED

    # Valid: ADMITTED -> RUNNING
    i5 = authority.transition_backlog_item("test-proj", "bk-1", WorkItemStatus.ADMITTED, WorkItemStatus.RUNNING)
    assert i5.status == WorkItemStatus.RUNNING

    # Valid: RUNNING -> COMPLETED
    i6 = authority.transition_backlog_item("test-proj", "bk-1", WorkItemStatus.RUNNING, WorkItemStatus.COMPLETED)
    assert i6.status == WorkItemStatus.COMPLETED

    # Invalid: COMPLETED -> READY (Terminal regression)
    with pytest.raises(LifecycleInvalidTransitionError):
        authority.transition_backlog_item("test-proj", "bk-1", WorkItemStatus.COMPLETED, WorkItemStatus.READY)


def test_generic_save_bypass_protection_change(in_memory_uow):
    """Generic repository.save() must raise LifecycleBypassError on status change for existing Change."""
    _setup_project(in_memory_uow)
    now = utc_now()
    c = Change(project_id="test-proj", name="ch-bypass", status=ChangeStatus.READY, discovered_at=now, updated_at=now)
    in_memory_uow.changes.save(c)

    # Attempt to bypass authority via save() with modified status
    bypassed_c = c.model_copy(update={"status": ChangeStatus.DONE})
    with pytest.raises(LifecycleBypassError):
        in_memory_uow.changes.save(bypassed_c)

    # Durable status in DB must remain READY
    db_c = in_memory_uow.changes.get_by_name("test-proj", "ch-bypass")
    assert db_c.status == ChangeStatus.READY


def test_generic_save_bypass_protection_backlog_item(in_memory_uow):
    """Generic repository.save() must raise LifecycleBypassError on status change for existing BacklogItem."""
    _setup_project(in_memory_uow)
    now = utc_now()
    bk = BacklogItem(
        project_id="test-proj",
        item_key="bk-bypass",
        title="Bypass item",
        description="desc",
        status=WorkItemStatus.READY,
        source=WorkItemSource.ROADMAP,
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)

    # Attempt to bypass authority via save() with modified status and metadata
    bypassed_bk = bk.model_copy(update={"status": WorkItemStatus.RUNNING, "description": "bypassed desc"})
    with pytest.raises(LifecycleBypassError):
        in_memory_uow.backlog_items.save(bypassed_bk)

    # Durable status in DB must remain READY and metadata unchanged from failed attempt
    db_bk = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "bk-bypass")
    assert db_bk.status == WorkItemStatus.READY
    assert db_bk.description == "desc"


def test_generic_save_same_status_metadata_update_allowed(in_memory_uow):
    """Generic repository save() allows updating non-lifecycle metadata when status is unchanged."""
    _setup_project(in_memory_uow)
    now = utc_now()
    bk = BacklogItem(
        project_id="test-proj",
        item_key="bk-meta",
        title="Initial Title",
        description="desc",
        status=WorkItemStatus.READY,
        source=WorkItemSource.ROADMAP,
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)

    updated_meta = bk.model_copy(update={"title": "Updated Title", "description": "updated desc"})
    in_memory_uow.backlog_items.save(updated_meta)

    db_bk = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "bk-meta")
    assert db_bk.status == WorkItemStatus.READY
    assert db_bk.title == "Updated Title"
    assert db_bk.description == "updated desc"


def test_atomic_cas_stale_conflict_and_event_exactness(in_memory_uow):
    """Transition must emit exactly 1 event on success, and zero events on CAS conflict."""
    _setup_project(in_memory_uow)
    authority = LifecycleTransitionAuthority(in_memory_uow)
    now = utc_now()

    bk = BacklogItem(
        project_id="test-proj",
        item_key="bk-cas",
        title="CAS Item",
        description="desc",
        status=WorkItemStatus.READY,
        source=WorkItemSource.ROADMAP,
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)

    # Attempt transition expecting wrong state (ADMITTED instead of READY, but ADMITTED->RUNNING is valid in matrix)
    with pytest.raises(LifecycleTransitionConflictError):
        authority.transition_backlog_item("test-proj", "bk-cas", WorkItemStatus.ADMITTED, WorkItemStatus.RUNNING)

    # Zero transition events emitted
    events = [e for e in in_memory_uow.events.list_events("test-proj") if e.event_type == EventType.LIFECYCLE_TRANSITION]
    assert len(events) == 0

    # Successful transition
    authority.transition_backlog_item("test-proj", "bk-cas", WorkItemStatus.READY, WorkItemStatus.ADMITTED)
    events = [e for e in in_memory_uow.events.list_events("test-proj") if e.event_type == EventType.LIFECYCLE_TRANSITION]
    assert len(events) == 1
    assert events[0].payload["from_state"] == WorkItemStatus.READY.value
    assert events[0].payload["to_state"] == WorkItemStatus.ADMITTED.value


def test_non_destructive_cancellation(in_memory_uow):
    """delete_work_item() must transition to CANCELLED without row deletion."""
    _setup_project(in_memory_uow)
    now = utc_now()
    bk = BacklogItem(
        project_id="test-proj",
        item_key="bk-cancel",
        title="Cancel Item",
        description="desc",
        status=WorkItemStatus.READY,
        source=WorkItemSource.ROADMAP,
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)

    intake = IntakeService(in_memory_uow, project_root=".")
    intake.delete_work_item("test-proj", "bk-cancel", operator_email="operator@test.com")

    # Item must still exist in DB in CANCELLED status
    db_bk = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "bk-cancel")
    assert db_bk is not None
    assert db_bk.status == WorkItemStatus.CANCELLED


def test_readiness_service_purity(in_memory_uow, tmp_path: Path):
    """ReadinessService.evaluate must be side-effect-free with respect to Change.status."""
    _setup_project(in_memory_uow)
    now = utc_now()
    c = Change(project_id="test-proj", name="ch-pure", status=ChangeStatus.DISCOVERED, discovered_at=now, updated_at=now)
    in_memory_uow.changes.save(c)

    readiness = ReadinessService(in_memory_uow)
    eval_res = readiness.evaluate_change_readiness("test-proj", "ch-pure", project_root=str(tmp_path))

    # Evaluation returns result without altering Change.status
    db_c = in_memory_uow.changes.get_by_name("test-proj", "ch-pure")
    assert db_c.status == ChangeStatus.DISCOVERED
    assert db_c.last_readiness_status == eval_res.status


def test_post_merge_authority_integration_and_readiness_orthogonality(in_memory_uow):
    """PostMergeService reconciliation routes DONE/COMPLETED through authority and preserves readiness_state."""
    _setup_project(in_memory_uow)
    now = utc_now()
    c = Change(project_id="test-proj", name="ch-pm", status=ChangeStatus.IN_PROGRESS, discovered_at=now, updated_at=now)
    in_memory_uow.changes.save(c)
    bk = BacklogItem(
        project_id="test-proj",
        item_key="ch-pm",
        title="PM Item",
        description="desc",
        status=WorkItemStatus.RUNNING,
        readiness_state=ReadinessState.NOT_READY,
        source=WorkItemSource.ROADMAP,
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)

    post_merge = PostMergeReconciliationService(in_memory_uow, project_root=".", github_adapter=None)
    post_merge._reconcile_change_and_backlog_item("test-proj", "ch-pm")

    db_c = in_memory_uow.changes.get_by_name("test-proj", "ch-pm")
    assert db_c.status == ChangeStatus.DONE

    db_bk = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "ch-pm")
    assert db_bk.status == WorkItemStatus.COMPLETED
    # Readiness state is preserved as NOT_READY (not forced to READY)
    assert db_bk.readiness_state == ReadinessState.NOT_READY
