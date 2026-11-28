import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from minime.domain.enums import HumanGate, OrchestrationStage
from minime.domain.models import OrchestrationRun, OrchestrationStageEvent, Project, ProjectManagedRepositoryBinding
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from tests.conftest import InMemoryPersistenceUnitOfWork


def _coordinator(uow):
    worktree = MagicMock()
    worktree.rebaseline_apply_worktree = AsyncMock()
    worktree.create_request_worktree = AsyncMock(return_value=SimpleNamespace(path=MagicMock()))
    runner = MagicMock()
    runner.resolve_workflow.return_value = SimpleNamespace(dispatch_command="openspec apply change")
    coord = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=MagicMock(),
        worktree_manager=worktree,
        agent_runner=runner,
    )
    coord.watchdog_mechanical_remediation = True
    return coord


def _git_candidate(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    (path / "README.md").write_text("candidate\n")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "candidate"], check=True)


def test_watchdog_can_auto_recover_escalation_when_process_is_gone(monkeypatch):
    uow = InMemoryPersistenceUnitOfWork()
    candidate_sha = "c" * 40
    run = OrchestrationRun(
        project_id="auto-rec-test",
        change_name="auto-rec",
        base_sha="main",
        current_stage=OrchestrationStage.IMPLEMENTING,
        current_candidate_sha=candidate_sha,
        human_gate=HumanGate.NEEDS_HUMAN,
    )
    uow.orchestration_runs.save(run)

    attempt_id = "dead-attempt-1"
    claim_key = f"stage-invocation:{run.run_id}:IMPLEMENTING:fp123"
    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run.run_id,
            event_type="STAGE_INVOCATION_STARTED",
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            evidence_references={
                "attempt_id": attempt_id,
                "claim_key": claim_key,
                "candidate": {"candidate_sha": candidate_sha},
                "coordinator_process": {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 99999, "start_marker": "marker1"},
                "recovery_count": 0,
            },
        )
    )
    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run.run_id,
            event_type="STAGE_INVOCATION_PROCESS_STARTED",
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            evidence_references={
                "attempt_id": attempt_id,
                "claim_key": claim_key,
                "process_identity": {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 99998, "start_marker": "marker2"},
            },
        )
    )

    coordinator = _coordinator(uow)

    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_identity",
        lambda _pid=None: {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 11111, "start_marker": "marker3"},
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_identity_state",
        lambda proc: "GONE",
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_group_state",
        lambda pgid: "GONE",
    )

    pending_gate = {
        "gate": "watchdog_escalation",
        "question": "Watchdog detected a stall",
    }
    assert coordinator._can_auto_recover_watchdog_escalation(uow, run, pending_gate) is True


def test_watchdog_escalation_preserves_original_gate_question_and_options():
    uow = InMemoryPersistenceUnitOfWork()
    question = "¿Qué opción de producto eliges?"
    options = [
        {"id": "keep", "label": "Mantener alcance", "response_text": "keep"},
        {"id": "expand", "label": "Ampliar alcance", "response_text": "expand"},
    ]
    run = OrchestrationRun(
        project_id="gate-preservation",
        change_name="gate-preservation",
        base_sha="main",
        current_stage=OrchestrationStage.PROPOSING,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_details={"human_payload": {
            "gate_id": "original-gate-id", "gate": "propose_clarification",
            "question": question, "options": options,
        }},
    )
    uow.orchestration_runs.save(run)
    coordinator = _coordinator(uow)

    payload = coordinator._record_watchdog_escalation(
        uow, run, reason="ambiguous technical context", evidence={"finding": "not deterministic"}
    )
    events = uow.orchestration_stage_events.list_by_run(run.run_id)

    assert payload["gate_id"] == "original-gate-id"
    assert payload["question"] == question
    assert payload["options"] == options
    assert payload["sre_unblocker_diagnostic"]["reason"] == "ambiguous technical context"
    assert [event.event_type for event in events].count("SRE_UNBLOCKER_ESCALATED") == 1
    assert events[-1].evidence_references["original_gate"] == {
        "question": question, "options": options,
    }


@pytest.mark.asyncio
async def test_begin_stage_invocation_reclaims_dead_claim_with_unexpired_lease(tmp_path, monkeypatch):
    uow = InMemoryPersistenceUnitOfWork()
    candidate = tmp_path / "candidate"
    _git_candidate(candidate)

    run = OrchestrationRun(
        project_id="reclaim-test",
        change_name="reclaim-test",
        base_sha="main",
        current_stage=OrchestrationStage.IMPLEMENTING,
    )
    uow.orchestration_runs.save(run)

    coordinator = _coordinator(uow)
    candidate_id = await coordinator._stage_candidate_identity(run, candidate, "APPLY")
    claim_key = f"stage-invocation:{run.run_id}:APPLY:{candidate_id['fingerprint']}"

    # Previous coordinator acquired claim with 120s lease (unexpired)
    uow.claims.acquire_or_reacquire(claim_key, "dead-coordinator-owner", lease_seconds=120)

    # Record previous attempt started with that claim
    attempt_id = "dead-attempt-apply"
    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run.run_id,
            event_type="STAGE_INVOCATION_STARTED",
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            evidence_references={
                "attempt_id": attempt_id,
                "claim_key": claim_key,
                "candidate": candidate_id,
                "coordinator_process": {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 99999, "start_marker": "marker1"},
                "recovery_count": 0,
            },
        )
    )
    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run.run_id,
            event_type="STAGE_INVOCATION_PROCESS_STARTED",
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            evidence_references={
                "attempt_id": attempt_id,
                "claim_key": claim_key,
                "process_identity": {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 99998, "start_marker": "marker2"},
            },
        )
    )

    # Mock process_identity_state to report GONE for the dead processes
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_identity",
        lambda _pid=None: {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 11111, "start_marker": "marker3"},
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_identity_state",
        lambda proc: "GONE",
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_group_state",
        lambda pgid: "GONE",
    )

    # Now begin_stage_invocation should successfully reclaim the unexpired dead claim!
    invocation = await coordinator._begin_stage_invocation(uow, run, candidate, "APPLY")
    assert invocation is not None
    assert invocation.recovery_count == 1
    assert invocation.recovered_from_attempt_id == "dead-attempt-apply"


@pytest.mark.asyncio
async def test_coordinate_active_run_autonomously_clears_watchdog_escalation_gate(tmp_path, monkeypatch):
    uow = InMemoryPersistenceUnitOfWork()
    candidate = tmp_path / "candidate"
    _git_candidate(candidate)

    project_id = "test-proj"
    uow.projects.save(Project(
        project_id=project_id,
        display_name="Test Project",
        repository="org/test-proj",
    ))
    uow.project_managed_repository_bindings.save(ProjectManagedRepositoryBinding(
        project_id=project_id,
        canonical_repository_identity="github.com/org/test-proj",
        managed_repository_root=str(tmp_path / "managed"),
        worktree_parent_dir=str(tmp_path / "worktrees"),
    ))

    run = OrchestrationRun(
        project_id=project_id,
        change_name="auto-unblock-gate",
        base_sha="main",
        current_stage=OrchestrationStage.IMPLEMENTING,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_details={
            "issue_number": 123,
            "issue_title": "Test Issue",
            "request_normalization": {"normalized_body": "feature description"},
            "human_payload": {
                "gate": "watchdog_escalation",
                "question": "Watchdog detectó una detención",
                "options": [{"id": "retry_same_candidate", "label": "Autorizar"}],
            }
        },
    )
    uow.orchestration_runs.save(run)

    coordinator = _coordinator(uow)
    candidate_id = await coordinator._stage_candidate_identity(run, candidate, "APPLY")
    claim_key = f"stage-invocation:{run.run_id}:IMPLEMENTING:{candidate_id['fingerprint']}"
    run.current_candidate_sha = candidate_id["candidate_sha"]
    uow.orchestration_runs.save(run)

    # Incomplete attempt with dead processes
    attempt_id = "dead-attempt-implementing"
    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run.run_id,
            event_type="STAGE_INVOCATION_STARTED",
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            evidence_references={
                "attempt_id": attempt_id,
                "claim_key": claim_key,
                "candidate": candidate_id,
                "coordinator_process": {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 99999, "start_marker": "marker1"},
                "recovery_count": 0,
            },
        )
    )
    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run.run_id,
            event_type="STAGE_INVOCATION_PROCESS_STARTED",
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            evidence_references={
                "attempt_id": attempt_id,
                "claim_key": claim_key,
                "process_identity": {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 99998, "start_marker": "marker2"},
            },
        )
    )

    diagnosis = {
        "id": "diag-123",
        "run_id": run.run_id,
        "stage": "IMPLEMENTING",
        "candidate_generation": 1,
        "status": "ESCALATED",
    }
    updated_diagnoses = {}
    uow.watchdog = SimpleNamespace(
        get_by_run_stage_generation=lambda r, s, g: diagnosis,
        update_diagnosis=lambda d_id, updates: updated_diagnoses.update(updates),
    )

    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_identity",
        lambda _pid=None: {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 11111, "start_marker": "marker3"},
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_identity_state",
        lambda proc: "GONE",
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_group_state",
        lambda pgid: "GONE",
    )

    # Mock worktree creation to point to candidate
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=SimpleNamespace(path=candidate)
    )
    coordinator.agent_runner.execute_stage = AsyncMock(
        return_value=SimpleNamespace(status="COMPLETE", message="Applied cleanly")
    )

    # When execute_project_request is invoked WITHOUT any operator clarification
    result = await coordinator.execute_project_request("test-proj")

    # Assert gate was autonomously unblocked!
    persisted_run = uow.orchestration_runs.get_by_id(run.run_id)
    assert persisted_run.human_gate is None
    assert updated_diagnoses.get("status") == "RESOLVED"
    assert updated_diagnoses.get("action") == "auto_recovered_by_watchdog"
    assert result.status != "HUMAN_REQUIRED"


@pytest.mark.asyncio
async def test_watchdog_can_recover_apply_invocation_with_prior_recovery_count_1(tmp_path, monkeypatch):
    candidate = tmp_path / "worktree"
    _git_candidate(candidate)
    head_sha = subprocess.check_output(
        ["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True
    ).strip()

    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="test-proj",
        change_name="test-change",
        base_sha="main",
        current_stage=OrchestrationStage.IMPLEMENTING,
        current_candidate_sha=head_sha,
        current_generation=1,
    )
    uow.orchestration_runs.save(run)

    coordinator = _coordinator(uow)
    real_candidate = await coordinator._stage_candidate_identity(run, candidate, "APPLY")

    claim_prefix = f"stage-invocation:{run.run_id}:APPLY:"
    claim_key = f"{claim_prefix}{real_candidate['fingerprint']}"
    attempt_id = "attempt-recovery-1"

    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run.run_id,
            event_type="STAGE_INVOCATION_STARTED",
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            evidence_references={
                "attempt_id": attempt_id,
                "claim_key": claim_key,
                "candidate": real_candidate,
                "coordinator_process": {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 99999, "start_marker": "marker1"},
                "recovery_count": 1,
            },
        )
    )
    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run.run_id,
            event_type="STAGE_INVOCATION_PROCESS_STARTED",
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            evidence_references={
                "attempt_id": attempt_id,
                "claim_key": claim_key,
                "process_identity": {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 99998, "start_marker": "marker2"},
            },
        )
    )

    uow.claims.acquire_or_reacquire(claim_key, "owner1", lease_seconds=120)

    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_identity",
        lambda _pid=None: {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 11111, "start_marker": "marker3"},
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_identity_state",
        lambda proc: "GONE",
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_group_state",
        lambda pgid: "GONE",
    )

    handled, recovered = await coordinator._recover_dirty_apply_invocation(
        uow, run, candidate, "APPLY", allow_human_resume=False
    )
    assert handled is True
    assert recovered is not None
    assert recovered.recovery_count == 2


@pytest.mark.asyncio
async def test_recover_dirty_apply_invocation_allows_worktree_fingerprint_change(
    tmp_path, monkeypatch
):
    candidate = tmp_path / "worktree"
    _git_candidate(candidate)
    head_sha = subprocess.check_output(
        ["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True
    ).strip()

    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="test-proj",
        change_name="test-change",
        base_sha="main",
        current_stage=OrchestrationStage.IMPLEMENTING,
        current_candidate_sha=head_sha,
        current_generation=1,
    )
    uow.orchestration_runs.save(run)

    coordinator = _coordinator(uow)
    real_candidate = await coordinator._stage_candidate_identity(run, candidate, "APPLY")

    claim_prefix = f"stage-invocation:{run.run_id}:APPLY:"
    claim_key = f"{claim_prefix}{real_candidate['fingerprint']}"
    attempt_id = "attempt-recovery-fp-change"

    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run.run_id,
            event_type="STAGE_INVOCATION_STARTED",
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            evidence_references={
                "attempt_id": attempt_id,
                "claim_key": claim_key,
                "candidate": real_candidate,
                "coordinator_process": {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 99999, "start_marker": "marker1"},
                "recovery_count": 0,
            },
        )
    )
    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run.run_id,
            event_type="STAGE_INVOCATION_PROCESS_STARTED",
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            evidence_references={
                "attempt_id": attempt_id,
                "claim_key": claim_key,
                "process_identity": {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 99998, "start_marker": "marker2"},
            },
        )
    )

    uow.claims.acquire_or_reacquire(claim_key, "owner1", lease_seconds=120)

    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_identity",
        lambda _pid=None: {"status": "AVAILABLE", "host": "testhost", "boot_id": "boot1", "pid": 11111, "start_marker": "marker3"},
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_identity_state",
        lambda proc: "GONE",
    )
    monkeypatch.setattr(
        "minime.services.orchestration_coordinator.process_group_state",
        lambda pgid: "GONE",
    )

    # Modify an untracked file to simulate partial progress / task marking
    (candidate / "new_debris.txt").write_text("debris from interrupted apply\n")

    handled, recovered = await coordinator._recover_dirty_apply_invocation(
        uow, run, candidate, "APPLY", allow_human_resume=False
    )
    assert handled is True
    assert recovered is not None
    assert recovered.recovery_count == 1



