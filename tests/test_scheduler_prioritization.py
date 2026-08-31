"""Tests for deterministic prioritization, aging, roadmap precedence, and explainability."""

from datetime import timedelta

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import (
    QueuePriority,
    ReadinessState,
)
from minime.domain.models import (
    Project,
    WorkQueueItem,
    utc_now,
)
from minime.services.scheduler_service import SchedulerService


def test_priority_ordering_across_priority_levels(in_memory_uow: InMemoryPersistenceUnitOfWork):
    scheduler = SchedulerService(uow=in_memory_uow)

    now = utc_now()
    item_crit = WorkQueueItem(
        project_id="mini-me",
        change_name="016-crit",
        priority=QueuePriority.CRITICAL,
        discovered_at=now,
    )
    item_high = WorkQueueItem(
        project_id="mini-me",
        change_name="016-high",
        priority=QueuePriority.HIGH,
        discovered_at=now,
    )
    item_norm = WorkQueueItem(
        project_id="mini-me",
        change_name="016-norm",
        priority=QueuePriority.NORMAL,
        discovered_at=now,
    )
    item_low = WorkQueueItem(
        project_id="mini-me",
        change_name="016-low",
        priority=QueuePriority.LOW,
        discovered_at=now,
    )

    ranked = scheduler.rank_candidates([item_low, item_norm, item_crit, item_high], now=now)
    assert [r.change_name for r in ranked] == ["016-crit", "016-high", "016-norm", "016-low"]


def test_starvation_aging_bonus(in_memory_uow: InMemoryPersistenceUnitOfWork):
    scheduler = SchedulerService(uow=in_memory_uow)

    now = utc_now()
    # Old NORMAL item discovered 40 hours ago (aging bonus = 40 * 50 = 2000 capped)
    item_old = WorkQueueItem(
        project_id="mini-me",
        change_name="016-old-normal",
        priority=QueuePriority.NORMAL,
        discovered_at=now - timedelta(hours=40),
    )
    # Fresh NORMAL item discovered just now (aging bonus = 0)
    item_fresh = WorkQueueItem(
        project_id="mini-me",
        change_name="016-fresh-normal",
        priority=QueuePriority.NORMAL,
        discovered_at=now,
    )

    ranked = scheduler.rank_candidates([item_fresh, item_old], now=now)
    assert [r.change_name for r in ranked] == ["016-old-normal", "016-fresh-normal"]
    assert ranked[0].priority_score > ranked[1].priority_score


def test_deterministic_tie_breaking(in_memory_uow: InMemoryPersistenceUnitOfWork):
    scheduler = SchedulerService(uow=in_memory_uow)

    now = utc_now()
    item_earlier = WorkQueueItem(
        project_id="mini-me",
        change_name="016-item-1",
        github_issue_number=10,
        priority=QueuePriority.HIGH,
        roadmap_stage=16,
        discovered_at=now - timedelta(minutes=10),
    )
    item_later = WorkQueueItem(
        project_id="mini-me",
        change_name="016-item-2",
        github_issue_number=20,
        priority=QueuePriority.HIGH,
        roadmap_stage=16,
        discovered_at=now,
    )

    ranked = scheduler.rank_candidates([item_later, item_earlier], now=now)
    assert ranked[0].change_name == "016-item-1"
    assert ranked[1].change_name == "016-item-2"


def test_explain_item_priority_report(in_memory_uow: InMemoryPersistenceUnitOfWork):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
    )
    in_memory_uow.projects.save(project)

    now = utc_now()
    item = WorkQueueItem(
        project_id="mini-me",
        change_name="016-test",
        github_issue_number=45,
        priority=QueuePriority.HIGH,
        roadmap_stage=16,
        readiness_state=ReadinessState.READY,
        admission_eligible=True,
        discovered_at=now - timedelta(hours=2),
    )
    in_memory_uow.work_queue.save(item)

    scheduler = SchedulerService(uow=in_memory_uow)
    report = scheduler.explain_item_priority("mini-me", "016-test")

    assert report.change_name == "016-test"
    assert report.priority == QueuePriority.HIGH
    assert report.base_score == 5000.0
    assert report.aging_bonus == pytest.approx(100.0, rel=1e-2)  # ~2 hours * 50
    assert report.queue_position == 1
    assert "Ranked #1" in report.selection_rationale
