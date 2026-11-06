"""Focused unit coverage for durable stage invocation and process recovery decisions."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import OrchestrationStage
from minime.domain.models import OrchestrationRun, OrchestrationStageEvent
from minime.services import agent_confinement as confinement_module
from minime.services import orchestration_coordinator as coordinator_module
from minime.services.agent_confinement import process_identity, process_identity_state
from minime.services.dashboard_service import OperationsDashboardService
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


def _coordinator(uow):
    return NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
    )


def _git_candidate(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    (path / "README.md").write_text("candidate\n")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "candidate"], check=True)


@pytest.mark.asyncio
async def test_active_claim_suppresses_duplicate_and_completed_verify_reentry(tmp_path):
    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="project-stage-test",
        change_name="stage-lifecycle",
        base_sha="main",
        current_stage=OrchestrationStage.VERIFYING,
    )
    uow.orchestration_runs.save(run)
    candidate = tmp_path / "candidate"
    _git_candidate(candidate)
    coordinator = _coordinator(uow)

    first = await coordinator._begin_stage_invocation(uow, run, candidate, "VERIFY")
    duplicate = await coordinator._begin_stage_invocation(uow, run, candidate, "VERIFY")
    assert first is not None
    assert first.claim_key.endswith(first.candidate["fingerprint"])
    assert duplicate is None
    original = (candidate / "README.md").read_text()
    (candidate / "README.md").write_text("new candidate content\n")
    changed_candidate = await coordinator._stage_candidate_identity(run, candidate, "VERIFY")
    assert changed_candidate["fingerprint"] != first.candidate["fingerprint"]
    assert await coordinator._begin_stage_invocation(
        uow, run, candidate, "VERIFY"
    ) is None
    (candidate / "README.md").write_text(original)

    await coordinator._finish_stage_invocation(
        uow, run, first, "COMPLETE", {"summary": "native Verify result"}
    )
    reentry = await coordinator._begin_stage_invocation(uow, run, candidate, "VERIFY")
    assert reentry is None
    events = uow.orchestration_stage_events.list_by_run(run.run_id)
    assert [event.event_type for event in events] == [
        "STAGE_INVOCATION_STARTED",
        "STAGE_INVOCATION_COMPLETED",
    ]
    assert events[1].evidence_references["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_human_required_blocks_reentry_until_operator_response(tmp_path):
    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="project-stage-test", change_name="stage-lifecycle", base_sha="main",
        current_stage=OrchestrationStage.VERIFYING,
    )
    uow.orchestration_runs.save(run)
    candidate = tmp_path / "candidate"
    _git_candidate(candidate)
    coordinator = _coordinator(uow)
    invocation = await coordinator._begin_stage_invocation(uow, run, candidate, "VERIFY")
    await coordinator._finish_stage_invocation(
        uow, run, invocation, "HUMAN_REQUIRED",
        {"question": "Choose", "options": ["A", "B"]},
    )
    assert await coordinator._begin_stage_invocation(uow, run, candidate, "VERIFY") is None
    resumed = await coordinator._begin_stage_invocation(
        uow, run, candidate, "VERIFY", allow_human_resume=True,
    )
    assert resumed is not None


@pytest.mark.asyncio
async def test_stale_fence_cannot_record_terminal_invocation(tmp_path):
    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="project-stage-test", change_name="stage-lifecycle", base_sha="main",
        current_stage=OrchestrationStage.VERIFYING,
    )
    uow.orchestration_runs.save(run)
    candidate = tmp_path / "candidate"
    _git_candidate(candidate)
    coordinator = _coordinator(uow)
    invocation = await coordinator._begin_stage_invocation(uow, run, candidate, "VERIFY")
    uow.claims.validate_cas = lambda *args: False
    with pytest.raises(RuntimeError, match="stale fence"):
        await coordinator._finish_stage_invocation(
            uow, run, invocation, "COMPLETE", {"summary": "must not persist"},
        )
    assert [event.event_type for event in uow.orchestration_stage_events.list_by_run(run.run_id)] == [
        "STAGE_INVOCATION_STARTED",
    ]


@pytest.mark.asyncio
async def test_native_boolean_workflow_uses_durable_invocation_wrapper(tmp_path):
    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="project-stage-test", change_name="stage-lifecycle", base_sha="main",
        current_stage=OrchestrationStage.VALIDATING,
    )
    uow.orchestration_runs.save(run)
    candidate = tmp_path / "candidate"
    _git_candidate(candidate)
    coordinator = _coordinator(uow)
    observed = []

    async def dispatch(observer):
        observed.append(observer)
        return True

    assert await coordinator._run_native_boolean_stage(
        uow, run, candidate, "UPDATE", dispatch,
    )
    events = uow.orchestration_stage_events.list_by_run(run.run_id)
    assert [event.event_type for event in events] == [
        "STAGE_INVOCATION_STARTED", "STAGE_INVOCATION_COMPLETED",
    ]
    assert observed


@pytest.mark.asyncio
async def test_unavailable_process_identity_is_durably_marked_for_no_recovery(tmp_path):
    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="project-stage-test", change_name="stage-lifecycle", base_sha="main",
        current_stage=OrchestrationStage.VERIFYING,
    )
    uow.orchestration_runs.save(run)
    candidate = tmp_path / "candidate"
    _git_candidate(candidate)
    coordinator = _coordinator(uow)
    invocation = await coordinator._begin_stage_invocation(uow, run, candidate, "VERIFY")
    coordinator._observe_stage_process(uow, run, invocation)(
        {"status": "UNAVAILABLE", "pid": 123}
    )
    event = uow.orchestration_stage_events.list_by_run(run.run_id)[-1]
    assert event.event_type == "STAGE_INVOCATION_PROCESS_STARTED"
    assert event.evidence_references["recovery_proof"] == "UNAVAILABLE"
    assert event.evidence_references["process_identity"]["status"] == "UNAVAILABLE"


def test_recovery_gate_requires_same_candidate_and_proven_process_group_exit(monkeypatch):
    coordinator_identity = {"status": "AVAILABLE", "host": "h", "boot_id": "b"}
    workflow_identity = {"status": "AVAILABLE", "host": "h", "boot_id": "b", "pgid": 42}
    current_identity = {"host": "h", "boot_id": "b"}
    monkeypatch.setattr(coordinator_module, "process_identity_state", lambda _: "GONE")
    monkeypatch.setattr(coordinator_module, "process_group_state", lambda _: "GONE")
    assert NativeOrchestrationCoordinator._stage_recovery_is_safe(
        coordinator_identity, workflow_identity, current_identity,
        candidate_matches=True, recovery_count=0,
    )

    monkeypatch.setattr(coordinator_module, "process_group_state", lambda _: "LIVE")
    assert not NativeOrchestrationCoordinator._stage_recovery_is_safe(
        coordinator_identity, workflow_identity, current_identity,
        candidate_matches=True, recovery_count=0,
    )
    states = iter(["GONE", "GONE"])
    monkeypatch.setattr(coordinator_module, "process_identity_state", lambda _: next(states))
    monkeypatch.setattr(coordinator_module, "process_group_state", lambda _: "LIVE")
    assert not NativeOrchestrationCoordinator._stage_recovery_is_safe(
        coordinator_identity, workflow_identity, current_identity,
        candidate_matches=True, recovery_count=0,
    )
    monkeypatch.setattr(coordinator_module, "process_group_state", lambda _: "GONE")
    assert not NativeOrchestrationCoordinator._stage_recovery_is_safe(
        coordinator_identity, workflow_identity, current_identity,
        candidate_matches=False, recovery_count=0,
    )
    assert not NativeOrchestrationCoordinator._stage_recovery_is_safe(
        coordinator_identity, workflow_identity, current_identity,
        candidate_matches=True, recovery_count=1,
    )
    assert not NativeOrchestrationCoordinator._stage_recovery_is_safe(
        {"status": "UNAVAILABLE"}, workflow_identity, current_identity,
        candidate_matches=True, recovery_count=0,
    )
    assert not NativeOrchestrationCoordinator._stage_recovery_is_safe(
        coordinator_identity, None, current_identity,
        candidate_matches=True, recovery_count=0,
    )


def test_live_coordinator_or_reused_process_identity_stops_recovery(monkeypatch):
    coordinator_identity = {"status": "AVAILABLE", "host": "h", "boot_id": "b"}
    workflow_identity = {"status": "AVAILABLE", "host": "h", "boot_id": "b", "pgid": 42}
    current_identity = {"host": "h", "boot_id": "b"}
    states = iter(["LIVE", "GONE"])
    monkeypatch.setattr(coordinator_module, "process_identity_state", lambda _: next(states))
    monkeypatch.setattr(coordinator_module, "process_group_state", lambda _: "GONE")
    assert not NativeOrchestrationCoordinator._stage_recovery_is_safe(
        coordinator_identity, workflow_identity, current_identity,
        candidate_matches=True, recovery_count=0,
    )


def test_process_identity_treats_pid_reuse_as_gone(monkeypatch):
    monkeypatch.setattr(
        confinement_module, "process_identity",
        lambda _pid: {"status": "AVAILABLE", "boot_id": "boot", "start_marker": "new"},
    )
    monkeypatch.setattr(confinement_module.socket, "gethostname", lambda: "host")
    assert process_identity_state({
        "status": "AVAILABLE", "host": "host", "boot_id": "boot",
        "pid": 12, "start_marker": "old",
    }) == "GONE"


def test_process_identity_is_unavailable_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr("minime.services.agent_confinement.platform.system", lambda: "plan9")
    identity = process_identity(123)
    assert identity["status"] == "UNAVAILABLE"
    assert identity["pid"] == 123


def test_absent_and_unobservable_processes_are_distinguished(monkeypatch):
    monkeypatch.setattr(
        confinement_module, "process_identity",
        lambda _pid: {"status": "UNAVAILABLE", "pid": 123},
    )

    def absent(_pid, _signal):
        raise ProcessLookupError

    monkeypatch.setattr(confinement_module.os, "kill", absent)
    identity = {"status": "AVAILABLE", "host": confinement_module.socket.gethostname(), "pid": 123}
    assert process_identity_state(identity) == "GONE"

    def unobservable(_pid, _signal):
        raise PermissionError

    monkeypatch.setattr(confinement_module.os, "kill", unobservable)
    assert process_identity_state(identity) == "LIVE"

    assert process_identity_state({"status": "UNAVAILABLE", "pid": 123}) == "UNKNOWN"


@pytest.mark.asyncio
async def test_verify_passes_accepted_gate_response_to_same_native_workflow(tmp_path):
    runner = MagicMock()
    runner.resolve_workflow.return_value = SimpleNamespace(dispatch_command="openspec verify change")
    captured = {}
    handoff = SimpleNamespace(status="HUMAN_REQUIRED", summary="Clarify this requirement", pending=("Option A",))

    async def run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            workflow_handoff_required=True,
            workflow_handoff=handoff,
            exit_code=0,
            timed_out=False,
            preflight_error=None,
            environment_error=False,
            final_response_status="COMPLETE",
        )

    runner.run.side_effect = run
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=MagicMock(), github_adapter=MagicMock(),
        worktree_manager=MagicMock(), agent_runner=runner,
    )
    outcome = await coordinator._run_verify(
        tmp_path, "codex", "change", operator_response="Use option A",
    )
    assert outcome.status == "HUMAN_REQUIRED"
    assert outcome.human_question == handoff.summary
    assert outcome.human_options == handoff.pending
    assert "Use option A" in captured["prompt_context"]
    assert captured["workflow"].dispatch_command == "openspec verify change"


@pytest.mark.asyncio
async def test_apply_preserves_native_human_handoff_question_and_options(tmp_path):
    worktree = tmp_path / "candidate"
    _git_candidate(worktree)
    change_dir = worktree / "openspec" / "changes" / "stage-lifecycle"
    change_dir.mkdir(parents=True)
    (change_dir / "tasks.md").write_text("- [ ] 1.1 Complete the task\n")
    runner = MagicMock()
    runner.resolve_workflow.return_value = SimpleNamespace(
        dispatch_command="openspec apply stage-lifecycle"
    )
    handoff = SimpleNamespace(
        status="HUMAN_REQUIRED", summary="Choose the retention boundary.",
        pending=("90 days", "180 days"),
    )
    runner.run = AsyncMock(return_value=SimpleNamespace(
        workflow_handoff_required=True, workflow_handoff=handoff,
        exit_code=0, timed_out=False, preflight_error=None, environment_error=False,
        final_response_status="COMPLETE", response_output="HUMAN_REQUIRED",
    ))
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=MagicMock(), github_adapter=MagicMock(),
        worktree_manager=MagicMock(), agent_runner=runner,
    )
    outcome = await coordinator._run_apply(
        worktree, "codex", "stage-lifecycle", base_branch="HEAD",
    )
    assert outcome.status == "HUMAN_REQUIRED"
    assert outcome.human_question == handoff.summary
    assert outcome.human_options == handoff.pending

def test_dashboard_timeline_does_not_project_invocation_events_as_transitions():
    run = OrchestrationRun(
        project_id="project-stage-test",
        change_name="stage-lifecycle",
        base_sha="main",
        current_stage=OrchestrationStage.VERIFYING,
    )
    transition = OrchestrationStageEvent(
        run_id=run.run_id,
        from_stage=OrchestrationStage.RUNNING_TESTS,
        to_stage=OrchestrationStage.VERIFYING,
    )
    invocation = OrchestrationStageEvent(
        run_id=run.run_id,
        from_stage=OrchestrationStage.VERIFYING,
        to_stage=OrchestrationStage.VERIFYING,
        event_type="STAGE_INVOCATION_STARTED",
        evidence_references={"attempt_id": "attempt-1"},
    )
    fake_uow = SimpleNamespace(
        orchestration_runs=SimpleNamespace(get_by_id=lambda _: run),
        orchestration_stage_events=SimpleNamespace(list_by_run=lambda _: [transition, invocation]),
        events=SimpleNamespace(list_events=lambda **_: []),
    )
    timeline = OperationsDashboardService(fake_uow)._project_timeline(run=run)
    assert [item.event_id for item in timeline] == [transition.event_id]
