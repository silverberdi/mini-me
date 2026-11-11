from __future__ import annotations

import asyncio

import pytest

from minime.domain.enums import HumanGate, OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import OrchestrationRun, OrchestrationWorktreeOwnership
from minime.services.run_cancellation_service import RunCancellationError, RunCancellationService


def _run(uow, *, run_id="run-1", project_id="project-1", **changes):
    values = dict(
        run_id=run_id,
        project_id=project_id,
        change_name="issue-7",
        base_sha="base-sha",
        current_stage=OrchestrationStage.IMPLEMENTING,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_details={"issue_number": 7, "prior": "preserved"},
    )
    values.update(changes)
    run = OrchestrationRun(**values)
    uow.orchestration_runs.save(run)
    return run


def test_cancellation_releases_active_slot_and_is_idempotent(in_memory_uow):
    _run(in_memory_uow)
    service = RunCancellationService(in_memory_uow)
    arguments = dict(
        project_id="project-1",
        run_id="run-1",
        reason="Operator stopped this Run",
        actor_identity="operator@example.test",
        source_interface="test",
        idempotency_key="cancel-run-1",
    )

    first = asyncio.run(service.cancel(**arguments))
    second = asyncio.run(service.cancel(**arguments))

    stored = in_memory_uow.orchestration_runs.get_by_id("run-1")
    assert first == second
    assert first["status"] == "CANCELLED"
    assert first["workspace_cleanup"] == "NOT_REQUIRED"
    assert stored.is_active is False
    assert stored.stop_outcome == OrchestrationStopOutcome.CANCELLED
    assert stored.human_gate is None
    assert stored.stop_details["issue_number"] == 7
    assert stored.stop_details["prior"] == "preserved"
    assert stored.stop_details["cancellation"]["actor"] == "operator@example.test"
    assert stored.stop_details["cancellation"]["reason"] == arguments["reason"]
    assert in_memory_uow.orchestration_runs.list_runs(project_id="project-1", is_active=True) == []
    events = in_memory_uow.orchestration_stage_events.list_by_run("run-1")
    assert [event.event_type for event in events] == ["RUN_CANCELLED"]


def test_cancellation_supports_orphaned_admitted_run_without_gate(in_memory_uow):
    _run(
        in_memory_uow,
        current_stage=OrchestrationStage.ADMITTED,
        stop_outcome=None,
        human_gate=None,
    )
    result = asyncio.run(
        RunCancellationService(in_memory_uow).cancel(
            project_id="project-1",
            run_id="run-1",
            reason="Close orphaned admission",
            actor_identity="operator@example.test",
            source_interface="test",
            idempotency_key="cancel-orphan",
        )
    )
    assert result["status"] == "CANCELLED"
    assert in_memory_uow.orchestration_runs.get_by_id("run-1").is_active is False


@pytest.mark.parametrize(
    "project_id,changes",
    [
        ("other-project", {}),
        ("project-1", {"active_job_id": "job-running"}),
        ("project-1", {"is_active": False}),
        ("project-1", {"stop_outcome": OrchestrationStopOutcome.COMPLETED}),
    ],
)
def test_cancellation_fails_closed_without_mutating_ineligible_run(in_memory_uow, project_id, changes):
    run = _run(in_memory_uow, **changes)
    before = in_memory_uow.orchestration_runs.get_by_id(run.run_id)

    with pytest.raises(RunCancellationError):
        asyncio.run(
            RunCancellationService(in_memory_uow).cancel(
                project_id=project_id,
                run_id=run.run_id,
                reason="Stop safely",
                actor_identity="operator@example.test",
                source_interface="test",
                idempotency_key="reject-this-cancel",
            )
        )

    after = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert after.is_active == before.is_active
    assert after.stop_outcome == before.stop_outcome
    assert after.active_job_id == before.active_job_id


def test_cleanup_without_verified_binding_preserves_ownership_and_reports_pending(in_memory_uow):
    _run(in_memory_uow)
    ownership = OrchestrationWorktreeOwnership(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        change_name="issue-7",
        canonical_worktree_path="/tmp/unverified-owned-worktree",
        source_repository_identity="github.com/example/repo",
        source_base_sha="base-sha",
        branch="issue-7",
    )
    in_memory_uow.orchestration_worktree_ownerships.save(ownership)

    result = asyncio.run(
        RunCancellationService(in_memory_uow).cancel(
            project_id="project-1",
            run_id="run-1",
            reason="Stop and retain unverified workspace",
            actor_identity="operator@example.test",
            source_interface="test",
            idempotency_key="cancel-cleanup-pending",
        )
    )

    assert result["status"] == "CANCELLED"
    assert result["workspace_cleanup"] == "PENDING"
    assert in_memory_uow.orchestration_worktree_ownerships.get_by_id(ownership.worktree_id)
    stored = in_memory_uow.orchestration_runs.get_by_id("run-1")
    assert stored.is_active is False
    assert stored.stop_details["cancellation"]["workspace_cleanup"] == "PENDING"
