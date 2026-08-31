"""Unit and integration tests for Operator Control Plane service."""

from __future__ import annotations

import pytest

from minime.domain.enums import (
    ChangeStatus,
    HumanGate,
    OperatorActionErrorCode,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ValidationVerdict,
)
from minime.domain.models import (
    Change,
    OperatorActionRequest,
    OrchestrationRun,
    Project,
    generate_uuid,
)
from minime.services.control_plane_service import ControlPlaneService


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

    # Second call with the same action_request_id should return recorded result immediately
    result2 = service.execute_action(req)
    assert result2.status == OperatorActionStatus.COMPLETED
    assert result2.action_request_id == req_id

    # Verify only 1 record is created in DB
    records = in_memory_uow.operator_actions.list_by_run("run-101")
    assert len(records) == 1


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
