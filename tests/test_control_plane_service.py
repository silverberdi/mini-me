"""Unit and integration tests for Operator Control Plane service."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from minime.domain.enums import (
    ChangeStatus,
    ExecutionOutcome,
    HumanGate,
    JobStatus,
    OperatorActionErrorCode,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProgressClassification,
    RecoveryClassification,
    RecoveryDecisionStatus,
    RecoverySource,
    ValidationVerdict,
)
from minime.domain.models import (
    Change,
    Job,
    JobAttempt,
    JobHandoff,
    OperatorActionRecord,
    OperatorActionRequest,
    OrchestrationRun,
    OrchestrationWorktreeOwnership,
    Project,
    RecoveryClaim,
    RecoveryDecision,
    generate_uuid,
    utc_now,
)
from minime.services.control_plane_service import ControlPlaneService
from minime.services.operator_executor_selection import effective_job_executor


@pytest.fixture
def seeded_project_and_run(in_memory_uow):
    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="test/repo",
        external_providers_allowed=["codex", "antigravity"],
        deployment_preview={"enabled": True, "type": "docker", "port": 3000},
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="test-proj",
        name="015-test-change",
        status=ChangeStatus.READY,
    )
    in_memory_uow.changes.save(change)

    run = OrchestrationRun(
        run_id="run-101",
        project_id="test-proj",
        change_name="015-test-change",
        current_stage=OrchestrationStage.RUNNING_CHECKS,
        resumable_stage=OrchestrationStage.RUNNING_CHECKS,
        current_generation=1,
        candidate_sha="abc1234567890",
        base_sha="base00000000",
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.FAILED,
        stop_reason="Checks failed: ruff lint error",
        retry_count=0,
    )
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()

    return project, change, run


def test_get_available_actions_discovery(in_memory_uow, seeded_project_and_run):
    project, change, run = seeded_project_and_run
    service = ControlPlaneService(in_memory_uow)

    actions = service.get_available_actions(run.run_id)
    action_map = {a.action: a for a in actions}

    # Verify all expected action types are present
    assert OperatorActionType.CONTINUE in action_map
    assert OperatorActionType.RETRY in action_map
    assert OperatorActionType.REASSIGN in action_map
    assert OperatorActionType.RESOLVE_GATE in action_map
    assert OperatorActionType.CANCEL in action_map
    assert OperatorActionType.START_PREVIEW in action_map
    assert OperatorActionType.TEARDOWN_PREVIEW in action_map
    assert OperatorActionType.RECOVER_LOCKS in action_map

    # CONTINUE is enabled because resumable_stage is set and run is inactive
    assert action_map[OperatorActionType.CONTINUE].enabled is True
    # RETRY is enabled because current_stage is RUNNING_CHECKS and retry_count < 3
    assert action_map[OperatorActionType.RETRY].enabled is True
    assert action_map[OperatorActionType.RETRY].requires_confirmation is True
    # REASSIGN is enabled because project allows 2 providers and run is inactive
    assert action_map[OperatorActionType.REASSIGN].enabled is True
    # CANCEL is disabled because run is not active
    assert action_map[OperatorActionType.CANCEL].enabled is False
    assert "not active" in action_map[OperatorActionType.CANCEL].disabled_reason.lower()
    # START_PREVIEW is enabled because candidate_sha exists and preview is enabled
    assert action_map[OperatorActionType.START_PREVIEW].enabled is True


def test_deepseek_review_has_no_implicit_spend_ceiling(in_memory_uow, seeded_project_and_run):
    _, _, run = seeded_project_and_run
    service = ControlPlaneService(in_memory_uow)

    assert service._deepseek_combined_review_limit({}) is None
    assert (
        service._deepseek_combined_review_limit(
            {"maximum_contract_review_usd": "0.50", "maximum_code_review_usd": "1.00"}
        )
        is None
    )
    assert service._deepseek_review_total_within_limit(run, {}, Decimal("1000000"))
    assert not service._deepseek_review_total_within_limit(
        run, {"maximum_combined_review_usd": "1.50"}, Decimal("1.50") + Decimal("0.01")
    )


def _seed_stale_continue_checkpoint(uow, project, change, run):
    now = utc_now()
    job = Job(
        job_id="job-stale-continue",
        project_id=project.project_id,
        change_name=change.name,
        implementer_role="codex",
        current_executor="codex",
        status=JobStatus.CHECKS_FAILED,
        attempt_count=1,
        base_sha="base00000000",
        candidate_sha="candidate00000000",
    )
    run.current_stage = OrchestrationStage.IMPLEMENTING
    run.resumable_stage = OrchestrationStage.IMPLEMENTING
    run.active_job_id = job.job_id
    run.current_candidate_sha = None
    run.stop_outcome = None
    run.human_gate = None
    run.is_active = True
    uow.jobs.save(job)
    uow.orchestration_runs.save(run)
    uow.job_attempts.save(
        JobAttempt(
            attempt_id="attempt-stale-continue",
            job_id=job.job_id,
            attempt_number=1,
            executor_role="codex",
            model_identity="codex-test",
            start_sha="base00000000",
            end_sha="candidate00000000",
            normalized_outcome=ExecutionOutcome.COMPLETED,
            progress_classification=ProgressClassification.NO_PROGRESS,
            started_at=now - timedelta(seconds=30),
            completed_at=now - timedelta(seconds=20),
            duration_ms=10_000,
        )
    )
    claim_key = f"run:{run.run_id}"
    claim = RecoveryClaim(
        claim_key=claim_key,
        fence_token=7,
        owner_instance_id="prior-instance",
        claimed_at=now - timedelta(minutes=2),
        heartbeat_at=now - timedelta(minutes=1),
        lease_expires_at=now - timedelta(seconds=10),
    )
    uow.claims._claims[claim_key] = claim
    uow.recovery_decisions.create_decision(
        RecoveryDecision(
            decision_id="decision-stale-continue",
            cycle_id="cycle-stale-continue",
            claim_key=claim_key,
            identity_type="RUN",
            identity_id=run.run_id,
            project_id=run.project_id,
            change_name=run.change_name,
            source=RecoverySource.CONTROL_PLANE,
            classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
            planned_action="DRIVE_CONTINUATION",
            fence_token=7,
            status=RecoveryDecisionStatus.EXECUTING,
            created_at=now - timedelta(seconds=40),
        )
    )
    uow.operator_actions.save(
        OperatorActionRecord(
            action_request_id="failed-continue-request",
            project_id=run.project_id,
            change_name=run.change_name,
            run_id=run.run_id,
            # The durable legacy record is Run-bound; the current Run's
            # active_job_id is the authoritative Job association.
            job_id=None,
            action_type=OperatorActionType.CONTINUE,
            actor_identity="operator-authorized",
            source_interface="cli",
            precondition_stage=run.current_stage.value,
            status=OperatorActionStatus.FAILED,
            error_code=OperatorActionErrorCode.ACTION_EXECUTION_FAILED,
            summary="Continuation failed after its stage checkpoint was committed.",
            result_payload_json={
                "error": "Fenced stage update failed: claim fence is stale, expired, or superseded."
            },
            created_at=now - timedelta(seconds=5),
        )
    )
    uow.commit()
    return job, claim_key


def test_stale_active_checkpoint_allows_only_new_governed_continue(
    in_memory_uow, seeded_project_and_run
):
    project, change, run = seeded_project_and_run
    job, _ = _seed_stale_continue_checkpoint(in_memory_uow, project, change, run)
    service = ControlPlaneService(in_memory_uow)

    assert service._has_stale_active_checkpoint(
        in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    )
    actions = {item.action: item for item in service.get_available_actions(run.run_id)}
    assert actions[OperatorActionType.CONTINUE].enabled
    assert job.candidate_sha == "candidate00000000"


@pytest.mark.parametrize(
    "mutation",
    [
        "live_claim",
        "wrong_action_job",
        "wrong_action_stage",
        "blocked_decision",
        "running_job",
        "candidate_mismatch",
        "run_candidate_frozen",
        "unrelated_action_failure",
    ],
)
def test_stale_active_checkpoint_rejects_ambiguous_or_live_state(
    in_memory_uow, seeded_project_and_run, mutation
):
    project, change, run = seeded_project_and_run
    job, claim_key = _seed_stale_continue_checkpoint(in_memory_uow, project, change, run)
    if mutation == "live_claim":
        claim = in_memory_uow.claims.get_by_key(claim_key)
        claim.lease_expires_at = utc_now() + timedelta(minutes=1)
        in_memory_uow.claims._claims[claim_key] = claim
    elif mutation == "wrong_action_job":
        action = in_memory_uow.operator_actions.list_by_run(run.run_id)[0]
        action.job_id = "another-job"
        in_memory_uow.operator_actions.save(action)
    elif mutation == "wrong_action_stage":
        action = in_memory_uow.operator_actions.list_by_run(run.run_id)[0]
        action.precondition_stage = OrchestrationStage.RUNNING_CHECKS.value
        in_memory_uow.operator_actions.save(action)
    elif mutation == "blocked_decision":
        decision = in_memory_uow.recovery_decisions.list_by_claim_key(claim_key)[0]
        decision.status = RecoveryDecisionStatus.BLOCKED
        in_memory_uow.recovery_decisions.update_decision(decision)
    elif mutation == "candidate_mismatch":
        persisted_job = in_memory_uow.jobs.get_by_id(job.job_id)
        persisted_job.candidate_sha = "different-candidate"
        in_memory_uow.jobs.save(persisted_job)
    elif mutation == "run_candidate_frozen":
        persisted_run = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
        persisted_run.current_candidate_sha = job.candidate_sha
        in_memory_uow.orchestration_runs.save(persisted_run)
    elif mutation == "unrelated_action_failure":
        action = in_memory_uow.operator_actions.list_by_run(run.run_id)[0]
        action.result_payload_json = {"error": "some unrelated control-plane failure"}
        in_memory_uow.operator_actions.save(action)
    else:
        persisted_job = in_memory_uow.jobs.get_by_id(job.job_id)
        persisted_job.status = JobStatus.RUNNING
        in_memory_uow.jobs.save(persisted_job)

    assert not ControlPlaneService(in_memory_uow)._has_stale_active_checkpoint(
        in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    )


def test_optimistic_concurrency_rejection(in_memory_uow, seeded_project_and_run):
    project, change, run = seeded_project_and_run
    service = ControlPlaneService(in_memory_uow)

    # Request with stale stage expectation
    req = OperatorActionRequest(
        project_id="test-proj",
        change_name="015-test-change",
        run_id="run-101",
        action_type=OperatorActionType.CONTINUE,
        expected_stage=OrchestrationStage.IMPLEMENTING,  # Mismatch: actual is RUNNING_CHECKS
        actor_identity="test_op",
        source_interface="cli",
    )

    result = service.execute_action(req)
    assert result.status == OperatorActionStatus.REJECTED
    assert result.error_code == OperatorActionErrorCode.STALE_OPERATOR_STATE
    assert "State conflict" in result.summary

    # Verify audit record is saved as REJECTED
    records = in_memory_uow.operator_actions.list_by_run("run-101")
    assert len(records) == 1
    assert records[0].status == OperatorActionStatus.REJECTED
    assert records[0].error_code == OperatorActionErrorCode.STALE_OPERATOR_STATE


def test_idempotent_duplicate_request(in_memory_uow, seeded_project_and_run):
    project, change, run = seeded_project_and_run
    service = ControlPlaneService(in_memory_uow)

    req_id = generate_uuid()
    req = OperatorActionRequest(
        action_request_id=req_id,
        project_id="test-proj",
        change_name="015-test-change",
        run_id="run-101",
        action_type=OperatorActionType.CONTINUE,
        expected_stage=run.current_stage,
        actor_identity="test_op",
        source_interface="cli",
    )

    result1 = service.execute_action(req)
    assert result1.status == OperatorActionStatus.COMPLETED
    assert "Continue request processed" in result1.summary
    assert "resumed successfully" not in result1.summary.lower()
    assert result1.payload["request_processed"] is True
    assert result1.payload["execution_active"] is False

    # Second call with the same action_request_id should return recorded result immediately
    result2 = service.execute_action(req)
    assert result2.status == OperatorActionStatus.COMPLETED
    assert result2.action_request_id == req_id

    # Verify only 1 record is created in DB
    records = in_memory_uow.operator_actions.list_by_run("run-101")
    assert len(records) == 1


def test_continue_reports_persisted_human_and_failed_job_outcome(
    in_memory_uow, seeded_project_and_run
):
    project, change, run = seeded_project_and_run
    job = Job(
        job_id="job-continue-failed",
        project_id=project.project_id,
        change_name=change.name,
        implementer_role="codex",
        current_executor="codex",
        status=JobStatus.NEEDS_HUMAN,
        base_sha=run.base_sha,
    )
    run.active_job_id = job.job_id
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.is_active = False
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()

    class FailedContinuation:
        def request_run_continuation(self, run_id, *, source, force, drive_admitted):
            assert drive_admitted is True
            assert force is True
            persisted_run = in_memory_uow.orchestration_runs.get_by_id(run_id)
            persisted_run.is_active = False
            persisted_run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
            persisted_run.human_gate = HumanGate.NEEDS_HUMAN
            persisted_job = in_memory_uow.jobs.get_by_id(job.job_id)
            persisted_job.status = JobStatus.FAILED
            in_memory_uow.orchestration_runs.save(persisted_run)
            in_memory_uow.jobs.save(persisted_job)
            in_memory_uow.commit()

    service = ControlPlaneService(in_memory_uow)
    service.recovery_convergence_service = FailedContinuation()
    request = OperatorActionRequest(
        project_id=project.project_id,
        change_name=change.name,
        run_id=run.run_id,
        action_type=OperatorActionType.CONTINUE,
        actor_identity="operator",
        source_interface="cli",
    )

    result = service.execute_action(request)

    assert result.status == OperatorActionStatus.COMPLETED
    assert result.resulting_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
    assert result.payload["run_active"] is False
    assert result.payload["execution_active"] is False
    assert result.payload["linked_job_status"] == JobStatus.FAILED.value
    assert "outcome=NEEDS_HUMAN" in result.summary
    assert "linked_job_status=FAILED" in result.summary
    assert "resumed successfully" not in result.summary.lower()


def test_cancel_active_run_safety(in_memory_uow, seeded_project_and_run):
    project, change, run = seeded_project_and_run
    run.is_active = True
    run.stop_outcome = None
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()

    service = ControlPlaneService(in_memory_uow)

    req = OperatorActionRequest(
        project_id="test-proj",
        change_name="015-test-change",
        run_id="run-101",
        action_type=OperatorActionType.CANCEL,
        actor_identity="supervisor",
        source_interface="tui",
    )

    result = service.execute_action(req)
    assert result.status == OperatorActionStatus.COMPLETED
    assert result.resulting_outcome == OrchestrationStopOutcome.CANCELLED

    # Check that run in DB is inactive and stopped with CANCELLED outcome
    updated_run = in_memory_uow.orchestration_runs.get_by_id("run-101")
    assert updated_run.is_active is False
    assert updated_run.stop_outcome == OrchestrationStopOutcome.CANCELLED
    assert "Cancelled by supervisor via tui" in updated_run.stop_reason

    # Verify candidate SHA and lineage are preserved!
    assert updated_run.candidate_sha == "abc1234567890"
    assert updated_run.current_generation == 1


def _link_active_job(in_memory_uow, run, status: JobStatus = JobStatus.QUEUED) -> Job:
    job = Job(
        job_id="job-101",
        project_id=run.project_id,
        change_name=run.change_name,
        status=status,
        implementer_role="codex",
        candidate_sha=run.candidate_sha,
        base_sha=run.base_sha,
    )
    in_memory_uow.jobs.save(job)
    run.active_job_id = job.job_id
    run.is_active = True
    run.stop_outcome = None
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()
    return job


def _cancel_request(run: OrchestrationRun) -> OperatorActionRequest:
    return OperatorActionRequest(
        project_id=run.project_id,
        change_name=run.change_name,
        run_id=run.run_id,
        action_type=OperatorActionType.CANCEL,
        expected_stage=run.current_stage,
        expected_generation=run.current_generation,
        expected_candidate_sha=run.candidate_sha,
        actor_identity="test-operator",
        source_interface="cli",
    )


@pytest.mark.parametrize("job_status", [JobStatus.QUEUED, JobStatus.RUNNING])
def test_cancel_active_run_converges_nonterminal_linked_job(
    in_memory_uow, seeded_project_and_run, job_status
):
    _, _, run = seeded_project_and_run
    job = _link_active_job(in_memory_uow, run, job_status)

    result = ControlPlaneService(in_memory_uow).execute_action(_cancel_request(run))

    assert result.status == OperatorActionStatus.COMPLETED
    assert in_memory_uow.orchestration_runs.get_by_id(run.run_id).is_active is False
    assert (
        in_memory_uow.orchestration_runs.get_by_id(run.run_id).stop_outcome
        == OrchestrationStopOutcome.CANCELLED
    )
    assert in_memory_uow.jobs.get_by_id(job.job_id).status == JobStatus.CANCELLED
    assert in_memory_uow.jobs.get_by_id(job.job_id).candidate_sha == run.candidate_sha
    assert job.job_id not in {item.job_id for item in in_memory_uow.jobs.list_active_jobs()}


@pytest.mark.parametrize("job_status", [JobStatus.CANCELLED, JobStatus.COMPLETED])
def test_cancel_active_run_preserves_terminal_linked_job(
    in_memory_uow, seeded_project_and_run, job_status
):
    _, _, run = seeded_project_and_run
    job = _link_active_job(in_memory_uow, run, job_status)

    result = ControlPlaneService(in_memory_uow).execute_action(_cancel_request(run))

    assert result.status == OperatorActionStatus.COMPLETED
    assert in_memory_uow.jobs.get_by_id(job.job_id).status == job_status
    assert (
        in_memory_uow.orchestration_runs.get_by_id(run.run_id).stop_outcome
        == OrchestrationStopOutcome.CANCELLED
    )


def test_cancel_active_run_fails_closed_for_missing_linked_job(
    in_memory_uow, seeded_project_and_run
):
    _, _, run = seeded_project_and_run
    run.active_job_id = "missing-job"
    run.is_active = True
    run.stop_outcome = None
    in_memory_uow.orchestration_runs.save(run)

    result = ControlPlaneService(in_memory_uow).execute_action(_cancel_request(run))

    assert result.status == OperatorActionStatus.FAILED
    persisted = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert persisted.is_active is True
    assert persisted.stop_outcome is None


def test_cancel_rolls_back_before_recording_transition_failure(
    in_memory_uow, seeded_project_and_run, monkeypatch
):
    _, _, run = seeded_project_and_run
    job = _link_active_job(in_memory_uow, run)

    def fail_transition(*_args, **_kwargs):
        raise RuntimeError("injected job transition failure")

    monkeypatch.setattr(in_memory_uow.jobs, "transition", fail_transition)
    result = ControlPlaneService(in_memory_uow).execute_action(_cancel_request(run))

    assert result.status == OperatorActionStatus.FAILED
    assert in_memory_uow.rolled_back is True
    assert in_memory_uow.orchestration_runs.get_by_id(run.run_id).is_active is True
    assert in_memory_uow.jobs.get_by_id(job.job_id).status == JobStatus.QUEUED
    assert (
        in_memory_uow.operator_actions.get_by_request_id(result.action_request_id).status
        == OperatorActionStatus.FAILED
    )


def test_reconcile_cancelled_run_linked_job_is_idempotent_and_preserves_ownership(
    in_memory_uow, seeded_project_and_run
):
    _, _, run = seeded_project_and_run
    job = _link_active_job(in_memory_uow, run)
    run.is_active = False
    run.stop_outcome = OrchestrationStopOutcome.CANCELLED
    in_memory_uow.orchestration_runs.save(run)
    ownership = OrchestrationWorktreeOwnership(
        project_id=run.project_id,
        job_id=job.job_id,
        run_id=run.run_id,
        change_name=run.change_name,
        canonical_worktree_path="/worktrees/job-101",
        source_repository_identity="owner/repo",
        source_base_sha=run.base_sha,
        branch="minime/test-job-101",
    )
    in_memory_uow.orchestration_worktree_ownerships.save(ownership)

    service = ControlPlaneService(in_memory_uow)
    events_before = list(in_memory_uow.events.list_events())
    reconciled = service.reconcile_cancelled_run_linked_job(run.run_id)
    repeated = service.reconcile_cancelled_run_linked_job(run.run_id)

    assert reconciled.is_active is False
    assert repeated.stop_outcome == OrchestrationStopOutcome.CANCELLED
    assert in_memory_uow.jobs.get_by_id(job.job_id).status == JobStatus.CANCELLED
    assert in_memory_uow.orchestration_worktree_ownerships.get_by_job_id(job.job_id) == ownership
    assert in_memory_uow.events.list_events() == events_before


def test_resolve_gate_ui_validation(in_memory_uow, seeded_project_and_run):
    project, change, run = seeded_project_and_run
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    run.stop_reason = "UI_VALIDATION_REQUIRED: Human visual inspection needed"
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()

    service = ControlPlaneService(in_memory_uow)

    # Check available actions: resolve gate should be enabled
    actions = service.get_available_actions(run.run_id)
    gate_action = next(a for a in actions if a.action == OperatorActionType.RESOLVE_GATE)
    assert gate_action.enabled is True
    assert gate_action.requires_confirmation is True

    # Execute resolve gate with PASS verdict
    req = OperatorActionRequest(
        project_id="test-proj",
        change_name="015-test-change",
        run_id="run-101",
        action_type=OperatorActionType.RESOLVE_GATE,
        parameters={"verdict": "PASS", "notes": "Approved in TUI console", "operator": "lead_op"},
        actor_identity="lead_op",
        source_interface="tui",
    )

    result = service.execute_action(req)
    assert result.status == OperatorActionStatus.COMPLETED
    assert result.evidence_reference is not None
    assert result.payload.get("verdict") == "PASS"

    # Verify validation was recorded in DB
    validations = in_memory_uow.validation_runs.list_by_change("test-proj", "015-test-change")
    assert len(validations) == 1
    assert validations[0].verdict == ValidationVerdict.PASS
    assert validations[0].operator == "lead_op"


def test_secret_redaction_in_action_records(in_memory_uow, seeded_project_and_run):
    project, change, run = seeded_project_and_run
    service = ControlPlaneService(in_memory_uow)

    req = OperatorActionRequest(
        project_id="test-proj",
        change_name="015-test-change",
        run_id="run-101",
        action_type=OperatorActionType.REASSIGN,
        parameters={
            "target_executor": "codex",
            "secret_token": "sk-proj-123456789abcdef",
            "api_key": "Bearer my-secret-key",
        },
        actor_identity="operator",
        source_interface="cli",
    )

    _ = service.execute_action(req)
    records = in_memory_uow.operator_actions.list_by_run("run-101")
    assert len(records) == 1

    stored_params = records[0].parameters_json
    # Secrets should be sanitized / redacted
    assert "sk-proj-123456789abcdef" not in str(stored_params)
    assert "my-secret-key" not in str(stored_params)


def test_get_available_actions_disables_continue_for_genuine_human_gates(
    in_memory_uow, seeded_project_and_run
):
    project, change, run = seeded_project_and_run
    service = ControlPlaneService(in_memory_uow)

    # 1. UI validation gate: CONTINUE should be disabled, RESOLVE_GATE enabled
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    run.stop_reason = "UI_VALIDATION_REQUIRED: Human visual check needed"
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()

    actions = service.get_available_actions(run.run_id)
    action_map = {a.action: a for a in actions}
    assert action_map[OperatorActionType.CONTINUE].enabled is False
    assert "Resolve Gate" in action_map[OperatorActionType.CONTINUE].disabled_reason
    assert action_map[OperatorActionType.RESOLVE_GATE].enabled is True

    # 2. Preserved candidate conflict: CONTINUE should be disabled, RESOLVE_GATE enabled
    run.stop_reason = "PRESERVED_CANDIDATE_CONFLICT: Base branch advanced"
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()

    actions = service.get_available_actions(run.run_id)
    action_map = {a.action: a for a in actions}
    assert action_map[OperatorActionType.CONTINUE].enabled is False
    assert "Resolve Gate" in action_map[OperatorActionType.CONTINUE].disabled_reason
    assert action_map[OperatorActionType.RESOLVE_GATE].enabled is True

    # 3. Non-convergence / automated recovery: CONTINUE enabled
    run.stop_reason = "NON_CONVERGENT_EXECUTION: Maximum reassignment limit reached"
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()

    actions = service.get_available_actions(run.run_id)
    action_map = {a.action: a for a in actions}
    assert action_map[OperatorActionType.CONTINUE].enabled is True


def test_operator_action_result_computed_success(in_memory_uow, seeded_project_and_run):
    project, change, run = seeded_project_and_run
    service = ControlPlaneService(in_memory_uow)

    req = OperatorActionRequest(
        project_id="test-proj",
        change_name="015-test-change",
        run_id="run-101",
        action_type=OperatorActionType.CONTINUE,
        actor_identity="operator",
        source_interface="pwa",
    )

    result = service.execute_action(req)
    assert result.status == OperatorActionStatus.COMPLETED
    assert result.success is True
    # Test JSON / dict serialization has success=True
    dumped = result.model_dump()
    assert dumped["success"] is True


def test_continue_preserves_reassignment_counters(in_memory_uow, seeded_project_and_run):
    from minime.domain.enums import JobStatus
    from minime.domain.models import Job

    project, change, run = seeded_project_and_run

    job = Job(
        job_id="job-c-1",
        project_id="test-proj",
        change_name="015-test-change",
        implementer_role="codex",
        current_executor="codex",
        status=JobStatus.NEEDS_HUMAN,
        attempt_count=3,
        reassignment_count=2,
    )
    in_memory_uow.jobs.save(job)

    run.active_job_id = "job-c-1"
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    run.stop_reason = "NON_CONVERGENT_EXECUTION"
    run.is_active = False
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()

    service = ControlPlaneService(in_memory_uow)

    req = OperatorActionRequest(
        project_id="test-proj",
        change_name="015-test-change",
        run_id="run-101",
        action_type=OperatorActionType.CONTINUE,
        actor_identity="operator",
        source_interface="pwa",
    )

    result = service.execute_action(req)
    assert result.status == OperatorActionStatus.COMPLETED

    # Counter preservation check: reassignment_count must NOT be reset to 0
    updated_job = in_memory_uow.jobs.get_by_id("job-c-1")
    assert updated_job.reassignment_count == 2
    assert updated_job.attempt_count == 3


def test_human_reassign_is_fenced_durable_and_precedes_older_handoff(
    in_memory_uow, seeded_project_and_run
):
    from datetime import timedelta

    from minime.domain.enums import ExecutionOutcome, ProgressClassification
    from minime.domain.models import utc_now

    project, change, run = seeded_project_and_run
    run.current_stage = OrchestrationStage.IMPLEMENTING
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.is_active = False
    job = Job(
        job_id="job-n01-reassign",
        project_id=project.project_id,
        change_name=change.name,
        implementer_role="antigravity",
        current_executor="antigravity",
        status=JobStatus.NEEDS_HUMAN,
        attempt_count=3,
        reassignment_count=1,
    )
    run.active_job_id = job.job_id
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.save(run)
    for number in range(1, 4):
        in_memory_uow.job_attempts.save(
            JobAttempt(
                attempt_id=f"attempt-n01-{number}",
                job_id=job.job_id,
                attempt_number=number,
                executor_role="antigravity",
                model_identity="antigravity:model",
                normalized_outcome=ExecutionOutcome.PREMATURE_STOP.value,
                progress_classification=ProgressClassification.NO_PROGRESS,
                is_same_sha_duplicate=number == 3,
                error_details={
                    "continuation_reason": (
                        "SAME_SHA_RETRY_SUPPRESSED" if number == 3 else "historical failure"
                    )
                },
            )
        )
    stale_handoff = JobHandoff(
        job_id=job.job_id,
        from_attempt_id="attempt-n01-2",
        from_executor="codex",
        to_executor="antigravity",
        worktree_path="/managed/worktree",
        base_sha="base-sha",
        candidate_sha="candidate-sha",
        is_consumed=False,
        created_at=utc_now() - timedelta(days=1),
    )
    in_memory_uow.job_handoffs.save(stale_handoff)
    in_memory_uow.commit()

    service = ControlPlaneService(in_memory_uow)
    service.recovery_convergence_service.request_run_continuation = lambda *a, **k: pytest.fail(
        "REASSIGN must not invoke execution"
    )
    request = OperatorActionRequest(
        action_request_id="operator-reassign-n01-codex",
        project_id=project.project_id,
        change_name=change.name,
        run_id=run.run_id,
        action_type=OperatorActionType.REASSIGN,
        parameters={"target_executor": "codex"},
        actor_identity="human-operator",
        source_interface="cli",
        expected_stage=OrchestrationStage.IMPLEMENTING,
        expected_generation=run.current_generation,
    )
    result = service.execute_action(request)
    replay = service.execute_action(request)

    assert result.status == OperatorActionStatus.COMPLETED
    assert replay.status == OperatorActionStatus.COMPLETED
    assert result.payload["executor_assignment_applied"] is True
    assert result.payload["execution_started"] is False
    updated = in_memory_uow.jobs.get_by_id(job.job_id)
    assert updated.current_executor == "codex"
    assert updated.attempt_count == 3
    assert updated.reassignment_count == 2
    assert in_memory_uow.job_handoffs.get_by_id(stale_handoff.handoff_id).is_consumed is False
    action = in_memory_uow.operator_actions.get_by_request_id(request.action_request_id)
    assert action.status == OperatorActionStatus.COMPLETED
    assert action.job_id == job.job_id
    effective_executor, applicable_handoff, operator_selected = effective_job_executor(
        in_memory_uow, in_memory_uow.orchestration_runs.get_by_id(run.run_id), updated
    )
    assert effective_executor == "codex"
    assert applicable_handoff is None
    assert operator_selected is True
    assert len(in_memory_uow.job_attempts.list_by_job(job.job_id)) == 3


def test_reassign_fails_closed_when_fenced_executor_write_fails(
    in_memory_uow, seeded_project_and_run, monkeypatch
):
    project, change, run = seeded_project_and_run
    run.current_stage = OrchestrationStage.IMPLEMENTING
    run.is_active = False
    run.active_job_id = "job-reassign-write-failure"
    job = Job(
        job_id=run.active_job_id,
        project_id=project.project_id,
        change_name=change.name,
        implementer_role="antigravity",
        current_executor="antigravity",
        status=JobStatus.NEEDS_HUMAN,
        attempt_count=3,
        reassignment_count=1,
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()

    def fail_fenced_write(*_args, **_kwargs):
        raise RuntimeError("fenced executor update rejected")

    monkeypatch.setattr(in_memory_uow.jobs, "update_executor_fenced", fail_fenced_write)
    result = ControlPlaneService(in_memory_uow).execute_action(
        OperatorActionRequest(
            project_id=project.project_id,
            change_name=change.name,
            run_id=run.run_id,
            action_type=OperatorActionType.REASSIGN,
            parameters={"target_executor": "codex"},
            actor_identity="human-operator",
            source_interface="cli",
        )
    )

    assert result.status == OperatorActionStatus.FAILED
    assert "durably applied" not in result.summary
    updated = in_memory_uow.jobs.get_by_id(job.job_id)
    assert updated.current_executor == "antigravity"
    assert updated.reassignment_count == 1


def test_human_reassign_rejects_unavailable_provider_and_reassignment_ceiling(
    in_memory_uow, seeded_project_and_run
):
    from minime.domain.enums import ProviderHealthStatus
    from minime.domain.models import ProviderHealth

    project, change, run = seeded_project_and_run
    run.current_stage = OrchestrationStage.IMPLEMENTING
    run.is_active = False
    run.active_job_id = "job-reassign-guard"
    job = Job(
        job_id=run.active_job_id,
        project_id=project.project_id,
        change_name=change.name,
        implementer_role="antigravity",
        current_executor="antigravity",
        status=JobStatus.NEEDS_HUMAN,
        reassignment_count=1,
        attempt_count=3,
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.EXHAUSTED)
    )
    in_memory_uow.commit()
    service = ControlPlaneService(in_memory_uow)

    unavailable = service.execute_action(
        OperatorActionRequest(
            project_id=project.project_id,
            change_name=change.name,
            run_id=run.run_id,
            action_type=OperatorActionType.REASSIGN,
            parameters={"target_executor": "codex"},
            actor_identity="human-operator",
            source_interface="cli",
        )
    )
    assert unavailable.status == OperatorActionStatus.REJECTED
    assert in_memory_uow.jobs.get_by_id(job.job_id).current_executor == "antigravity"

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
    )
    job.reassignment_count = 2
    in_memory_uow.jobs.save(job)
    in_memory_uow.commit()
    exhausted = service.execute_action(
        OperatorActionRequest(
            project_id=project.project_id,
            change_name=change.name,
            run_id=run.run_id,
            action_type=OperatorActionType.REASSIGN,
            parameters={"target_executor": "codex"},
            actor_identity="human-operator",
            source_interface="cli",
        )
    )
    assert exhausted.status == OperatorActionStatus.REJECTED
    assert in_memory_uow.jobs.get_by_id(job.job_id).current_executor == "antigravity"
