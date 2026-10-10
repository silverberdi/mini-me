"""Unit and integration tests for Autonomous Intake Persisted State Convergence."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ProviderHealthStatus,
    QueuePriority,
    ReadinessState,
    WorkItemSource,
    WorkItemStatus,
)
from minime.domain.models import (
    BacklogItem,
    Change,
    Project,
    ProjectBinding,
    ProviderHealth,
    utc_now,
)
from minime.services.discovery_service import WorkDiscoveryService
from minime.services.intake_service import IntakeService
from minime.services.scheduler_service import SchedulerService


@pytest.fixture
def test_setup(in_memory_uow: InMemoryPersistenceUnitOfWork, tmp_path: Path):
    repo_dir = tmp_path / "test-repo"
    setup_managed_repository_fixture(
        in_memory_uow,
        "test-proj",
        repo_dir,
        repo_dir / ".minime" / "worktrees",
        canonical_repository_identity="github.com/silverberdi/test-repo",
    )
    openspec_dir = repo_dir / "openspec"
    openspec_dir.mkdir(exist_ok=True)
    changes_dir = openspec_dir / "changes"
    changes_dir.mkdir(exist_ok=True)
    archive_dir = changes_dir / "archive"
    archive_dir.mkdir(exist_ok=True)

    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="silverberdi/test-repo",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
        auto_prepare=True,
        auto_admit=True,
        max_concurrent_jobs=1,
    )
    in_memory_uow.projects.save(project)

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE)
    )

    intake_svc = IntakeService(in_memory_uow, project_root=repo_dir)
    scheduler_svc = SchedulerService(in_memory_uow, project_root=repo_dir)
    discovery_svc = WorkDiscoveryService(in_memory_uow, project_root=repo_dir)

    return {
        "uow": in_memory_uow,
        "repo_dir": repo_dir,
        "changes_dir": changes_dir,
        "archive_dir": archive_dir,
        "project": project,
        "intake_svc": intake_svc,
        "scheduler_svc": scheduler_svc,
        "discovery_svc": discovery_svc,
    }


def test_ready_ready_valid_artifacts_remains_ready(test_setup):
    """1. READY + READY + valid active artifacts => remains READY, not re-prepared."""
    uow = test_setup["uow"]
    changes_dir = test_setup["changes_dir"]
    intake_svc = test_setup["intake_svc"]

    change_name = "valid-ready-change"
    c_dir = changes_dir / change_name
    c_dir.mkdir()
    (c_dir / ".openspec.yaml").write_text("schema: spec-driven\n")
    (c_dir / "proposal.md").write_text("# Proposal")
    (c_dir / "tasks.md").write_text("# Tasks\n- [ ] Task 1")
    (c_dir / "design.md").write_text("# Design")
    (c_dir / "specs").mkdir()
    (c_dir / "specs" / "spec.md").write_text("# Spec")

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key=change_name,
        title="Valid Ready Change",
        status=WorkItemStatus.READY,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.READY,
        openspec_change_name=change_name,
        github_issue_number=101,
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)

    binding = ProjectBinding(
        project_id="test-proj",
        repository="silverberdi/test-repo",
        github_issue_number=101,
        openspec_change_name=change_name,
        is_valid=True,
    )
    uow.bindings.save(binding)
    uow.commit()

    intake_svc.reconcile_and_persist_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", change_name)

    assert res_item.status == WorkItemStatus.READY
    assert res_item.readiness_state == ReadinessState.READY


def test_ready_not_ready_missing_artifacts_converges_to_blocked(test_setup):
    """2. READY + NOT_READY + active artifacts missing => converges to BLOCKED."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    change_name = "missing-artifacts-change"
    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key=change_name,
        title="Missing Artifacts Change",
        status=WorkItemStatus.READY,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.NOT_READY,
        unmet_readiness_reasons=["Change directory missing."],
        openspec_change_name=change_name,
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    intake_svc.reconcile_and_persist_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", change_name)

    assert res_item.status == WorkItemStatus.BLOCKED


def test_ready_missing_openspec_archived_change_converges_to_completed(test_setup):
    """3. READY + missing active OpenSpec + archived corresponding change => COMPLETED."""
    uow = test_setup["uow"]
    archive_dir = test_setup["archive_dir"]
    intake_svc = test_setup["intake_svc"]

    change_name = "archived-feature"
    (archive_dir / f"2026-10-09-{change_name}").mkdir()

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key=change_name,
        title="Archived Feature",
        status=WorkItemStatus.READY,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.READY,
        openspec_change_name=change_name,
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    intake_svc.reconcile_and_persist_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", change_name)

    assert res_item.status == WorkItemStatus.COMPLETED


def test_ready_change_done_converges_to_completed(test_setup):
    """4. READY + missing active OpenSpec + Change DONE => COMPLETED."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    change_name = "change-done-feature"
    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key=change_name,
        title="Change Done Feature",
        status=WorkItemStatus.READY,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.READY,
        openspec_change_name=change_name,
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)

    c_rec = Change(
        project_id="test-proj",
        name=change_name,
        status=ChangeStatus.DONE,
        discovered_at=now,
        updated_at=now,
    )
    uow.changes.save(c_rec)
    uow.commit()

    intake_svc.reconcile_and_persist_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", change_name)

    assert res_item.status == WorkItemStatus.COMPLETED


def test_ready_cancelled_change_converges_to_cancelled(test_setup):
    """5. READY + cancelled Change => CANCELLED."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    change_name = "cancelled-feature"
    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key=change_name,
        title="Cancelled Feature",
        status=WorkItemStatus.READY,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.READY,
        openspec_change_name=change_name,
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)

    c_rec = Change(
        project_id="test-proj",
        name=change_name,
        status=ChangeStatus.CANCELLED,
        discovered_at=now,
        updated_at=now,
    )
    uow.changes.save(c_rec)
    uow.commit()

    intake_svc.reconcile_and_persist_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", change_name)

    assert res_item.status == WorkItemStatus.CANCELLED


def test_roadmap_022_projected_backlog_never_autonomously_prepared(test_setup):
    """6. ROADMAP 022 projected BACKLOG => never autonomously prepared."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key="022-operational-greenfield-proving",
        title="022 Operational Greenfield Proving",
        status=WorkItemStatus.BLOCKED,
        source=WorkItemSource.ROADMAP,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.NOT_READY,
        openspec_change_name="022-operational-greenfield-proving",
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    prepared = intake_svc.sweep_unprepared_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", "022-operational-greenfield-proving")

    assert res_item.status == WorkItemStatus.BLOCKED
    assert len(prepared) == 0


def test_historical_invalid_multi_never_resurrected(test_setup):
    """7. Historical invalid Multi => never resurrected."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key="Multi",
        title="Multi project binding",
        status=WorkItemStatus.CANCELLED,
        source=WorkItemSource.ROADMAP,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.NOT_READY,
        openspec_change_name="Multi",
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    intake_svc.reconcile_and_persist_backlog_items("test-proj")
    prepared = intake_svc.sweep_unprepared_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", "Multi")

    assert res_item.status == WorkItemStatus.CANCELLED
    assert len(prepared) == 0


def test_terminal_completed_cancelled_never_reprepared(test_setup):
    """8. Terminal COMPLETED/CANCELLED => never re-prepared."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    now = utc_now()
    item_c = BacklogItem(
        project_id="test-proj",
        item_key="completed-item",
        title="Completed Item",
        status=WorkItemStatus.COMPLETED,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.READY,
        openspec_change_name="completed-item",
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item_c)
    uow.commit()

    prepared = intake_svc.sweep_unprepared_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", "completed-item")

    assert res_item.status == WorkItemStatus.COMPLETED
    assert len(prepared) == 0


def test_legitimate_backlog_manual_intake_still_autoprepared(test_setup):
    """9. Legitimate BACKLOG manual intake => still auto-prepared."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key="manual-feature",
        title="Manual Feature",
        description="Detailed description for manual feature.",
        status=WorkItemStatus.BACKLOG,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.NOT_READY,
        openspec_change_name="manual-feature",
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    prepared = intake_svc.sweep_unprepared_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", "manual-feature")

    # Item was swept and prepared (producing generated change files)
    assert len(prepared) == 1
    assert res_item.status in (WorkItemStatus.READY, WorkItemStatus.PREPARING, WorkItemStatus.NEEDS_HUMAN)


def test_scheduler_tick_performs_convergence_before_sweep(test_setup):
    """10. Scheduler tick performs convergence before sweep."""
    uow = test_setup["uow"]
    scheduler_svc = test_setup["scheduler_svc"]
    archive_dir = test_setup["archive_dir"]

    change_name = "stale-scheduler-item"
    (archive_dir / f"2026-10-09-{change_name}").mkdir()

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key=change_name,
        title="Stale Scheduler Item",
        status=WorkItemStatus.READY,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.READY,
        openspec_change_name=change_name,
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    scheduler_svc.tick("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", change_name)

    assert res_item.status == WorkItemStatus.COMPLETED


def test_discovery_remains_lifecycle_pure(test_setup):
    """11. Discovery remains lifecycle-pure (does not mutate BacklogItem status)."""
    uow = test_setup["uow"]
    discovery_svc = test_setup["discovery_svc"]

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key="discovery-item",
        title="Discovery Item",
        status=WorkItemStatus.READY,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.READY,
        openspec_change_name="discovery-item",
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    discovery_svc.discover_work("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", "discovery-item")

    # BacklogItem status unchanged by pure discovery
    assert res_item.status == WorkItemStatus.READY


def test_no_direct_lifecycle_writes_outside_transition_authority(test_setup):
    """12. No direct lifecycle writes outside LifecycleTransitionAuthority."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]
    archive_dir = test_setup["archive_dir"]

    change_name = "cas-event-check"
    (archive_dir / f"2026-10-09-{change_name}").mkdir()

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key=change_name,
        title="CAS Event Check",
        status=WorkItemStatus.READY,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.READY,
        openspec_change_name=change_name,
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    intake_svc.reconcile_and_persist_backlog_items("test-proj")

    events = uow.events.list_events(project_id="test-proj")
    lifecycle_events = [
        e for e in events if e.event_type == EventType.LIFECYCLE_TRANSITION
    ]
    assert len(lifecycle_events) >= 1
    le = lifecycle_events[-1]
    assert le.payload["item_key"] == change_name
    assert le.payload["from_state"] == WorkItemStatus.READY.value
    assert le.payload["to_state"] == WorkItemStatus.COMPLETED.value


def test_idempotent_repeated_ticks(test_setup):
    """13. Idempotent repeated ticks."""
    uow = test_setup["uow"]
    scheduler_svc = test_setup["scheduler_svc"]
    archive_dir = test_setup["archive_dir"]

    change_name = "idempotent-item"
    (archive_dir / f"2026-10-09-{change_name}").mkdir()

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key=change_name,
        title="Idempotent Item",
        status=WorkItemStatus.READY,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.READY,
        openspec_change_name=change_name,
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    scheduler_svc.tick("test-proj")
    st1 = uow.backlog_items.get_by_project_and_key("test-proj", change_name).status

    scheduler_svc.tick("test-proj")
    st2 = uow.backlog_items.get_by_project_and_key("test-proj", change_name).status

    assert st1 == WorkItemStatus.COMPLETED
    assert st2 == WorkItemStatus.COMPLETED


def test_concurrency_remains_one(test_setup):
    """14. Concurrency remains 1."""
    uow = test_setup["uow"]
    scheduler_svc = test_setup["scheduler_svc"]

    project = uow.projects.get_by_id("test-proj")
    assert project.max_concurrent_jobs == 1
    assert scheduler_svc.max_global_jobs == 1


def test_blocked_unresolved_readiness_no_retry(test_setup):
    """15. BLOCKED with unresolved readiness blocker => no retry."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key="blocked-readiness-item",
        title="Blocked Readiness Item",
        status=WorkItemStatus.BLOCKED,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.NOT_READY,
        unmet_readiness_reasons=["Spec requirement incomplete."],
        openspec_change_name="blocked-readiness-item",
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    prepared = intake_svc.sweep_unprepared_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", "blocked-readiness-item")

    assert res_item.status == WorkItemStatus.BLOCKED
    assert len(prepared) == 0


def test_blocked_unresolved_dependency_no_retry(test_setup):
    """16. BLOCKED with unresolved dependency => no retry."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key="blocked-dep-item",
        title="Blocked Dependency Item",
        status=WorkItemStatus.BLOCKED,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.NOT_READY,
        unmet_readiness_reasons=["parent_task_incomplete"],
        openspec_change_name="blocked-dep-item",
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    prepared = intake_svc.sweep_unprepared_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", "blocked-dep-item")

    assert res_item.status == WorkItemStatus.BLOCKED
    assert len(prepared) == 0


def test_blocked_needs_human_no_retry(test_setup):
    """17. BLOCKED with human-required reason => no retry."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key="blocked-human-item",
        title="Blocked Human Item",
        status=WorkItemStatus.BLOCKED,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.NOT_READY,
        unmet_readiness_reasons=["NEEDS_HUMAN validation required."],
        openspec_change_name="blocked-human-item",
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    prepared = intake_svc.sweep_unprepared_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", "blocked-human-item")

    assert res_item.status == WorkItemStatus.BLOCKED
    assert len(prepared) == 0


def test_blocked_stale_artifacts_reprepared_exactly_once(test_setup):
    """18. BLOCKED stale-state case whose authoritative artifacts are absent => allowed exactly once."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key="stale-artifact-item",
        title="Stale Artifact Item",
        description="Detailed description for stale artifact item.",
        status=WorkItemStatus.BLOCKED,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.NOT_READY,
        unmet_readiness_reasons=["stale_ready_artifacts_missing"],
        openspec_change_name="stale-artifact-item",
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    prepared = intake_svc.sweep_unprepared_backlog_items("test-proj")
    res_item = uow.backlog_items.get_by_project_and_key("test-proj", "stale-artifact-item")

    # Prepared exactly once
    assert len(prepared) == 1
    assert res_item.status != WorkItemStatus.BLOCKED or "stale_ready_artifacts_missing" not in (res_item.unmet_readiness_reasons or [])


def test_blocked_retry_idempotence_no_loop(test_setup):
    """19. Repeated ticks on BLOCKED items are idempotent and do not loop preparation."""
    uow = test_setup["uow"]
    intake_svc = test_setup["intake_svc"]

    now = utc_now()
    item = BacklogItem(
        project_id="test-proj",
        item_key="loop-prevention-item",
        title="Loop Prevention Item",
        status=WorkItemStatus.BLOCKED,
        source=WorkItemSource.MANUAL_INTAKE,
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.NOT_READY,
        unmet_readiness_reasons=["unresolved_spec_gap"],
        openspec_change_name="loop-prevention-item",
        created_at=now,
        updated_at=now,
    )
    uow.backlog_items.save(item)
    uow.commit()

    p1 = intake_svc.sweep_unprepared_backlog_items("test-proj")
    p2 = intake_svc.sweep_unprepared_backlog_items("test-proj")
    p3 = intake_svc.sweep_unprepared_backlog_items("test-proj")

    assert len(p1) == 0
    assert len(p2) == 0
    assert len(p3) == 0
