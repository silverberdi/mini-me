"""Test suite verifying projection non-resurrection and zero side effects on terminal items."""

from __future__ import annotations

from minime.domain.enums import ChangeStatus, WorkItemStatus
from minime.domain.models import BacklogItem, Change, Project
from minime.services.dashboard_service import OperationsDashboardService
from minime.services.intake_service import IntakeService


def test_backlog_projection_does_not_resurrect_completed_item(in_memory_uow):
    uow = in_memory_uow

    proj = Project(
        project_id="p-proj-test",
        display_name="Projection Test",
        repository="owner/repo",
    )
    uow.projects.save(proj)

    item = BacklogItem(
        project_id="p-proj-test",
        item_key="item-done-1",
        title="Completed Backlog Item",
        status=WorkItemStatus.COMPLETED,
    )
    uow.backlog_items.save(item)

    change = Change(
        project_id="p-proj-test",
        name="item-done-1",
        status=ChangeStatus.DONE,
    )
    uow.changes.save(change)
    uow.commit()
    uow.committed = False

    intake_svc = IntakeService(uow)
    projected = intake_svc.reconcile_backlog_projections("p-proj-test")

    assert len(projected) == 1
    assert projected[0].status == WorkItemStatus.COMPLETED

    # Verify canonical DB item status remains COMPLETED and zero commits executed
    db_item = uow.backlog_items.get_by_project_and_key("p-proj-test", "item-done-1")
    assert db_item.status == WorkItemStatus.COMPLETED
    assert uow.committed is False


def test_dashboard_overview_leaves_terminal_change_status_intact(in_memory_uow):
    uow = in_memory_uow

    proj = Project(
        project_id="p-dash-test",
        display_name="Dashboard Test",
        repository="owner/repo",
    )
    uow.projects.save(proj)

    change = Change(
        project_id="p-dash-test",
        name="change-done-1",
        status=ChangeStatus.DONE,
    )
    uow.changes.save(change)
    uow.commit()
    uow.committed = False

    dash_svc = OperationsDashboardService(uow)
    overview = dash_svc.get_overview()

    assert overview is not None
    db_change = uow.changes.get_by_name("p-dash-test", "change-done-1")
    assert db_change.status == ChangeStatus.DONE
    assert uow.committed is False
