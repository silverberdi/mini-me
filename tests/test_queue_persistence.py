"""Persistence tests for Autonomous Queue and Scheduler Decision repositories."""

from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.db.models import Base
from minime.domain.enums import (
    AdmissionDecision,
    AdmissionRefusalCode,
    QueuePriority,
    ReadinessState,
)
from minime.domain.models import (
    SchedulerDecisionRecord,
    WorkQueueItem,
)


def test_metadata_contains_queue_and_scheduler_tables():
    tables = Base.metadata.tables
    assert "work_queue_snapshots" in tables
    assert "scheduler_decision_records" in tables

    wq_table = tables["work_queue_snapshots"]
    constraint_names = {c.name for c in wq_table.constraints}
    assert "uq_work_queue_snapshots_project_change" in constraint_names


def test_in_memory_work_queue_repository_crud(in_memory_uow: InMemoryPersistenceUnitOfWork):
    item1 = WorkQueueItem(
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        github_issue_number=45,
        priority=QueuePriority.HIGH,
        roadmap_stage=16,
        readiness_state=ReadinessState.READY,
        admission_eligible=True,
        priority_score=5000.0,
    )
    in_memory_uow.work_queue.save(item1)

    fetched = in_memory_uow.work_queue.get_by_id(item1.queue_item_id)
    assert fetched is not None
    assert fetched.change_name == "016-autonomous-queue-work-selection"
    assert fetched.priority == QueuePriority.HIGH

    by_change = in_memory_uow.work_queue.get_by_project_and_change(
        "mini-me", "016-autonomous-queue-work-selection"
    )
    assert by_change is not None
    assert by_change.queue_item_id == item1.queue_item_id

    # Update item
    item1_updated = item1.model_copy(update={"priority_score": 5200.0, "blocked_reason": None})
    in_memory_uow.work_queue.save(item1_updated)
    all_items = in_memory_uow.work_queue.list_all("mini-me")
    assert len(all_items) == 1
    assert all_items[0].priority_score == 5200.0

    ready_items = in_memory_uow.work_queue.list_ready("mini-me")
    assert len(ready_items) == 1

    in_memory_uow.work_queue.delete(item1.queue_item_id)
    assert in_memory_uow.work_queue.get_by_id(item1.queue_item_id) is None


def test_in_memory_scheduler_decision_repository(in_memory_uow: InMemoryPersistenceUnitOfWork):
    d1 = SchedulerDecisionRecord(
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        github_issue_number=45,
        decision=AdmissionDecision.ADMITTED,
        reason_summary="READY and capacity available.",
        priority_score=5200.0,
        selected_implementer="codex",
    )
    d2 = SchedulerDecisionRecord(
        project_id="mini-me",
        change_name="017-pwa-control-center",
        github_issue_number=46,
        decision=AdmissionDecision.REFUSED,
        reason_code=AdmissionRefusalCode.ROADMAP_PREDECESSOR_INCOMPLETE,
        reason_summary="Stage 16 not complete.",
        priority_score=1000.0,
    )
    in_memory_uow.scheduler_decisions.save(d1)
    in_memory_uow.scheduler_decisions.save(d2)

    recent = in_memory_uow.scheduler_decisions.list_recent("mini-me")
    assert len(recent) == 2

    by_change = in_memory_uow.scheduler_decisions.list_by_change(
        "mini-me", "016-autonomous-queue-work-selection"
    )
    assert len(by_change) == 1
    assert by_change[0].decision == AdmissionDecision.ADMITTED
