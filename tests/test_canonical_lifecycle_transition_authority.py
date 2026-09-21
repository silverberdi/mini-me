"""Comprehensive unit, integration, concurrency, and purity tests for Canonical Lifecycle Transition Authority."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from minime.api.app import app, get_uow
from minime.db.models import BacklogItemModel, Base, EventModel, ProjectModel
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProjectStatus,
    ReadinessState,
    WorkItemSource,
    WorkItemStatus,
)
from minime.domain.exceptions import (
    LifecycleBypassError,
    LifecycleInvalidTransitionError,
    LifecycleTransitionConflictError,
)
from minime.domain.models import BacklogItem, Change, OrchestrationRun, Project, utc_now
from minime.services.intake_service import IntakeService
from minime.services.lifecycle_transition_authority import (
    ALLOWED_CHANGE_TRANSITIONS,
    ALLOWED_WORK_ITEM_TRANSITIONS,
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


@pytest.mark.parametrize("state", list(ChangeStatus))
def test_exhaustive_change_matrix(in_memory_uow, state):
    """Exhaustively verify every allowed target succeeds and every disallowed target fails for ChangeStatus."""
    _setup_project(in_memory_uow)
    authority = LifecycleTransitionAuthority(in_memory_uow)
    now = utc_now()

    allowed = ALLOWED_CHANGE_TRANSITIONS[state]
    all_states = set(ChangeStatus)
    disallowed = all_states - allowed

    for target in allowed:
        c = Change(project_id="test-proj", name=f"ch-{state.value}-{target.value}", status=state, discovered_at=now, updated_at=now)
        in_memory_uow.changes.save(c)
        res = authority.transition_change("test-proj", f"ch-{state.value}-{target.value}", state, target)
        assert res.status == target

    for target in disallowed:
        c = Change(project_id="test-proj", name=f"ch-dis-{state.value}-{target.value}", status=state, discovered_at=now, updated_at=now)
        in_memory_uow.changes.save(c)
        with pytest.raises(LifecycleInvalidTransitionError):
            authority.transition_change("test-proj", f"ch-dis-{state.value}-{target.value}", state, target)


@pytest.mark.parametrize("state", list(WorkItemStatus))
def test_exhaustive_work_item_matrix(in_memory_uow, state):
    """Exhaustively verify every allowed target succeeds and every disallowed target fails for WorkItemStatus."""
    _setup_project(in_memory_uow)
    authority = LifecycleTransitionAuthority(in_memory_uow)
    now = utc_now()

    allowed = ALLOWED_WORK_ITEM_TRANSITIONS[state]
    all_states = set(WorkItemStatus)
    disallowed = all_states - allowed

    for target in allowed:
        key = f"bk-{state.value}-{target.value}"
        bk = BacklogItem(
            project_id="test-proj",
            item_key=key,
            title=key,
            description="desc",
            status=state,
            source=WorkItemSource.ROADMAP,
            created_at=now,
            updated_at=now,
        )
        in_memory_uow.backlog_items.save(bk)
        res = authority.transition_backlog_item("test-proj", key, state, target)
        assert res.status == target

    for target in disallowed:
        key = f"bk-dis-{state.value}-{target.value}"
        bk = BacklogItem(
            project_id="test-proj",
            item_key=key,
            title=key,
            description="desc",
            status=state,
            source=WorkItemSource.ROADMAP,
            created_at=now,
            updated_at=now,
        )
        in_memory_uow.backlog_items.save(bk)
        with pytest.raises(LifecycleInvalidTransitionError):
            authority.transition_backlog_item("test-proj", key, state, target)


def test_generic_save_bypass_protection_change(in_memory_uow):
    """Generic repository.save() must raise LifecycleBypassError on status change for existing Change."""
    _setup_project(in_memory_uow)
    now = utc_now()
    c = Change(project_id="test-proj", name="ch-bypass", status=ChangeStatus.READY, discovered_at=now, updated_at=now)
    in_memory_uow.changes.save(c)

    bypassed_c = c.model_copy(update={"status": ChangeStatus.DONE})
    with pytest.raises(LifecycleBypassError):
        in_memory_uow.changes.save(bypassed_c)

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

    bypassed_bk = bk.model_copy(update={"status": WorkItemStatus.RUNNING, "description": "bypassed desc"})
    with pytest.raises(LifecycleBypassError):
        in_memory_uow.backlog_items.save(bypassed_bk)

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

    with pytest.raises(LifecycleTransitionConflictError):
        authority.transition_backlog_item("test-proj", "bk-cas", WorkItemStatus.ADMITTED, WorkItemStatus.RUNNING)

    events = [e for e in in_memory_uow.events.list_events("test-proj") if e.event_type == EventType.LIFECYCLE_TRANSITION]
    assert len(events) == 0

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
    assert db_bk.readiness_state == ReadinessState.NOT_READY


# -----------------------------------------------------------------------------
# Projection Purity Tests (Requirement 8)
# -----------------------------------------------------------------------------

def test_projection_purity_archive_directory_no_persistence(in_memory_uow, tmp_path: Path):
    """A. Archive directory exists + Backlog nonterminal -> reconcile_backlog_projections() does NOT persist COMPLETED in DB."""
    _setup_project(in_memory_uow)
    now = utc_now()

    openspec_dir = tmp_path / "openspec" / "changes" / "archive" / "0001-archived-change"
    openspec_dir.mkdir(parents=True)

    bk = BacklogItem(
        project_id="test-proj",
        item_key="archived-change",
        title="Archived Item",
        status=WorkItemStatus.BACKLOG,
        openspec_change_name="archived-change",
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)

    intake = IntakeService(in_memory_uow, project_root=tmp_path)
    projections = intake.reconcile_backlog_projections("test-proj")

    assert len(projections) == 1
    assert projections[0].status == WorkItemStatus.COMPLETED

    db_bk = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "archived-change")
    assert db_bk.status == WorkItemStatus.BACKLOG

    events = [e for e in in_memory_uow.events.list_events("test-proj") if e.event_type == EventType.LIFECYCLE_TRANSITION]
    assert len(events) == 0


def test_projection_purity_active_run_no_persistence(in_memory_uow):
    """B. Latest Run active -> projection call returns RUNNING display status but does NOT persist in DB."""
    _setup_project(in_memory_uow)
    now = utc_now()
    bk = BacklogItem(
        project_id="test-proj",
        item_key="active-item",
        title="Active Item",
        status=WorkItemStatus.BACKLOG,
        openspec_change_name="active-item",
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)
    in_memory_uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-active",
            project_id="test-proj",
            change_name="active-item",
            base_sha="base123",
            current_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )

    intake = IntakeService(in_memory_uow, project_root=".")
    projections = intake.reconcile_backlog_projections("test-proj")

    assert len(projections) == 1
    assert projections[0].status == WorkItemStatus.RUNNING

    db_bk = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "active-item")
    assert db_bk.status == WorkItemStatus.BACKLOG

    events = [e for e in in_memory_uow.events.list_events("test-proj") if e.event_type == EventType.LIFECYCLE_TRANSITION]
    assert len(events) == 0


def test_projection_purity_stop_outcome_no_persistence(in_memory_uow):
    """C. Run stop_outcome = READY_FOR_HUMAN_MERGE -> projection returns NEEDS_HUMAN display status but does NOT persist in DB."""
    _setup_project(in_memory_uow)
    now = utc_now()
    bk = BacklogItem(
        project_id="test-proj",
        item_key="pr-item",
        title="PR Item",
        status=WorkItemStatus.BACKLOG,
        openspec_change_name="pr-item",
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)
    in_memory_uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-pr",
            project_id="test-proj",
            change_name="pr-item",
            base_sha="base123",
            current_stage=OrchestrationStage.PR_PREPARED,
            stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
            is_active=False,
            created_at=now,
            updated_at=now,
        )
    )

    intake = IntakeService(in_memory_uow, project_root=".")
    projections = intake.reconcile_backlog_projections("test-proj")

    assert projections[0].status == WorkItemStatus.NEEDS_HUMAN

    db_bk = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "pr-item")
    assert db_bk.status == WorkItemStatus.BACKLOG

    events = [e for e in in_memory_uow.events.list_events("test-proj") if e.event_type == EventType.LIFECYCLE_TRANSITION]
    assert len(events) == 0


def test_projection_purity_repeated_calls_zero_events(in_memory_uow):
    """D. Repeated reconcile_backlog_projections() calls produce zero lifecycle transition events."""
    _setup_project(in_memory_uow)
    now = utc_now()
    bk = BacklogItem(
        project_id="test-proj",
        item_key="rep-item",
        title="Repeated Item",
        status=WorkItemStatus.READY,
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)

    intake = IntakeService(in_memory_uow, project_root=".")
    for _ in range(5):
        intake.reconcile_backlog_projections("test-proj")

    events = [e for e in in_memory_uow.events.list_events("test-proj") if e.event_type == EventType.LIFECYCLE_TRANSITION]
    assert len(events) == 0


def test_terminal_item_no_resurrection_on_external_evidence(in_memory_uow):
    """E. Terminal COMPLETED/CANCELLED items must not be resurrected by active run evidence."""
    _setup_project(in_memory_uow)
    now = utc_now()
    bk_completed = BacklogItem(
        project_id="test-proj",
        item_key="term-completed",
        title="Completed Item",
        status=WorkItemStatus.COMPLETED,
        openspec_change_name="term-completed",
        created_at=now,
        updated_at=now,
    )
    bk_cancelled = BacklogItem(
        project_id="test-proj",
        item_key="term-cancelled",
        title="Cancelled Item",
        status=WorkItemStatus.CANCELLED,
        openspec_change_name="term-cancelled",
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk_completed)
    in_memory_uow.backlog_items.save(bk_cancelled)

    in_memory_uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-stale-1",
            project_id="test-proj",
            change_name="term-completed",
            base_sha="base123",
            current_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    in_memory_uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-stale-2",
            project_id="test-proj",
            change_name="term-cancelled",
            base_sha="base123",
            current_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )

    intake = IntakeService(in_memory_uow, project_root=".")
    projections = intake.reconcile_backlog_projections("test-proj")
    proj_map = {p.item_key: p.status for p in projections}
    assert proj_map["term-completed"] == WorkItemStatus.COMPLETED
    assert proj_map["term-cancelled"] == WorkItemStatus.CANCELLED

    db_completed = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "term-completed")
    db_cancelled = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "term-cancelled")
    assert db_completed.status == WorkItemStatus.COMPLETED
    assert db_cancelled.status == WorkItemStatus.CANCELLED

    authority = LifecycleTransitionAuthority(in_memory_uow)
    with pytest.raises(LifecycleInvalidTransitionError):
        authority.transition_backlog_item("test-proj", "term-completed", WorkItemStatus.COMPLETED, WorkItemStatus.RUNNING)
    with pytest.raises(LifecycleInvalidTransitionError):
        authority.transition_backlog_item("test-proj", "term-cancelled", WorkItemStatus.CANCELLED, WorkItemStatus.RUNNING)


# -----------------------------------------------------------------------------
# Concurrency & Event Transactionality Proofs (Requirements 6 & 9)
# -----------------------------------------------------------------------------

def test_real_persistence_concurrency_cas_conflict():
    """Requirement 9: Prove concurrent CAS using two SQLAlchemy sessions against real persistence engine (stale-CAS integration proof)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as init_session:
        init_session.add(
            ProjectModel(
                id="concurr-proj",
                display_name="Concurrency Project",
                repository="owner/repo",
                checks=[],
                external_providers_allowed=[],
                deployment_preview={},
                deployment_production={},
                status=ProjectStatus.ACTIVE.value,
            )
        )
        init_session.add(
            BacklogItemModel(
                id="item-conc-id",
                project_id="concurr-proj",
                item_key="conc-item",
                title="Concurrent Item",
                status=WorkItemStatus.READY.value,
                source=WorkItemSource.ROADMAP.value,
                dependencies=[],
                readiness_state=ReadinessState.READY.value,
                unmet_readiness_reasons=[],
                human_questions=[],
                human_answers=[],
                acceptance_criteria=[],
            )
        )
        init_session.commit()

    session_a = SessionLocal()
    session_b = SessionLocal()

    uow_a = PostgresPersistenceUnitOfWork(session_a)
    uow_b = PostgresPersistenceUnitOfWork(session_b)

    auth_a = LifecycleTransitionAuthority(uow_a)
    auth_b = LifecycleTransitionAuthority(uow_b)

    # Session A executes READY -> ADMITTED successfully
    auth_a.transition_backlog_item("concurr-proj", "conc-item", WorkItemStatus.READY, WorkItemStatus.ADMITTED)
    session_a.commit()

    # Session B attempts stale READY -> ADMITTED
    with pytest.raises(LifecycleTransitionConflictError):
        auth_b.transition_backlog_item("concurr-proj", "conc-item", WorkItemStatus.READY, WorkItemStatus.ADMITTED)
        session_b.commit()
    session_b.rollback()

    session_a.close()
    session_b.close()

    with SessionLocal() as verify_session:
        item = verify_session.query(BacklogItemModel).filter_by(item_key="conc-item").first()
        assert item.status == WorkItemStatus.ADMITTED.value

        event_count = verify_session.query(EventModel).filter_by(event_type=EventType.LIFECYCLE_TRANSITION.value).count()
        assert event_count == 1


def test_event_transactionality_and_rollback():
    """Requirement 6: Prove event insert failure causes automatic transaction rollback leaving original status."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as init_session:
        init_session.add(
            ProjectModel(
                id="roll-proj",
                display_name="Rollback Project",
                repository="owner/repo",
                checks=[],
                external_providers_allowed=[],
                deployment_preview={},
                deployment_production={},
                status=ProjectStatus.ACTIVE.value,
            )
        )
        init_session.add(
            BacklogItemModel(
                id="item-roll-id",
                project_id="roll-proj",
                item_key="roll-item",
                title="Rollback Item",
                status=WorkItemStatus.READY.value,
                source=WorkItemSource.ROADMAP.value,
                dependencies=[],
                readiness_state=ReadinessState.READY.value,
                unmet_readiness_reasons=[],
                human_questions=[],
                human_answers=[],
                acceptance_criteria=[],
            )
        )
        init_session.commit()

    session = SessionLocal()
    uow = PostgresPersistenceUnitOfWork(session)

    # Mock uow.events.save to raise an exception simulating DB event insert failure
    def failing_event_save(event):
        raise RuntimeError("DB event write failure")

    uow.events.save = failing_event_save

    authority = LifecycleTransitionAuthority(uow)
    # Authority automatically calls session.rollback() before re-raising exception
    with pytest.raises(RuntimeError, match="DB event write failure"):
        authority.transition_backlog_item("roll-proj", "roll-item", WorkItemStatus.READY, WorkItemStatus.ADMITTED)

    session.close()

    with SessionLocal() as verify_session:
        item = verify_session.query(BacklogItemModel).filter_by(item_key="roll-item").first()
        assert item.status == WorkItemStatus.READY.value

        event_count = verify_session.query(EventModel).filter_by(event_type=EventType.LIFECYCLE_TRANSITION.value).count()
        assert event_count == 0


# -----------------------------------------------------------------------------
# GET Purity Test (Requirement 10)
# -----------------------------------------------------------------------------

def test_get_purity_endpoint_zero_mutations(in_memory_uow):
    """Requirement 10: Prove HTTP GET requests on status/backlog produce zero lifecycle mutations or transition events."""
    _setup_project(in_memory_uow)
    now = utc_now()
    bk = BacklogItem(
        project_id="test-proj",
        item_key="get-pure-item",
        title="GET Pure Item",
        status=WorkItemStatus.READY,
        created_at=now,
        updated_at=now,
    )
    in_memory_uow.backlog_items.save(bk)

    initial_bk = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "get-pure-item")
    initial_status = initial_bk.status
    initial_events = len([e for e in in_memory_uow.events.list_events("test-proj") if e.event_type == EventType.LIFECYCLE_TRANSITION])

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    # Perform HTTP GET request on project backlog endpoint
    response = client.get("/api/v1/projects/test-proj/backlog")
    assert response.status_code == 200

    final_bk = in_memory_uow.backlog_items.get_by_project_and_key("test-proj", "get-pure-item")
    final_events = len([e for e in in_memory_uow.events.list_events("test-proj") if e.event_type == EventType.LIFECYCLE_TRANSITION])

    assert final_bk.status == initial_status
    assert final_events == initial_events
    app.dependency_overrides.clear()

