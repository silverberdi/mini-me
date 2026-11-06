from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.api.app import app, get_current_operator, get_uow
from minime.domain.enums import (
    HumanGate,
    OrchestrationStage,
    OrchestrationStopOutcome,
)
from minime.domain.models import (
    AuthorizedOperator,
    OrchestrationRun,
    Project,
)
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


def _coordinator(uow: InMemoryPersistenceUnitOfWork) -> NativeOrchestrationCoordinator:
    return NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
    )


def _run(
    stage: OrchestrationStage,
    *,
    details: dict | None = None,
) -> OrchestrationRun:
    return OrchestrationRun(
        run_id="run-human-gate",
        project_id="project-human-gate",
        change_name="issue-262",
        base_sha="base-sha",
        current_stage=stage,
        resumable_stage=stage,
        stop_details=details or {},
    )


@pytest.mark.asyncio
async def test_proposal_review_escalation_replaces_and_persists_payload(in_memory_uow):
    run = _run(
        OrchestrationStage.PROPOSAL_REVIEW,
        details={
            "proposal_review": {"round": 1, "findings": ["old finding"]},
            "human_payload": {"question": "resolved old question", "options": ["old"]},
        },
    )
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.projects.save(
        Project(
            project_id=run.project_id,
            display_name="Human gate test",
            repository="org/human-gate-test",
            execution_policy={"max_review_rounds": 1},
        )
    )

    result = await _coordinator(in_memory_uow)._route_proposal_changes_required(
        uow=in_memory_uow,
        project_id=run.project_id,
        run=run,
        result={"status": "changes_required", "findings": ["current finding"]},
        worktree_path=Path("/tmp/human-gate-test"),
        thinker_provider="codex",
        change_name=run.change_name,
    )

    stored = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert result.status == "HUMAN_REQUIRED"
    assert stored.stop_details["human_payload"] == result.human_payload
    assert result.human_payload["gate"] == "proposal_review_escalation"
    assert result.human_payload["question"] != "resolved old question"
    assert result.human_payload["options"] == []
    assert stored.human_gate == HumanGate.NEEDS_HUMAN
    assert stored.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN


def test_code_review_escalation_replaces_and_persists_payload(in_memory_uow):
    run = _run(
        OrchestrationStage.CODE_REVIEW,
        details={
            "code_review": {"round": 1},
            "human_payload": {"question": "resolved old question", "options": ["old"]},
        },
    )
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.projects.save(
        Project(
            project_id=run.project_id,
            display_name="Human gate test",
            repository="org/human-gate-test",
            execution_policy={"max_review_rounds": 1},
        )
    )

    result = _coordinator(in_memory_uow)._route_changes_required(
        in_memory_uow,
        run.project_id,
        run,
        {"status": "changes_required", "summary": "Review needs operator direction", "findings": []},
    )

    stored = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert stored.stop_details["human_payload"] == result.human_payload
    assert result.human_payload["gate"] == "code_review_escalation"
    assert result.human_payload["stage"] == OrchestrationStage.CODE_REVIEW.value
    assert result.human_payload["options"] == []
    assert stored.human_gate == HumanGate.NEEDS_HUMAN


@pytest.mark.parametrize(
    ("gate", "question"),
    [
        ("apply_escalation", "Apply recovery stopped"),
        ("physical_validation", "Physical validation is required"),
    ],
)
def test_apply_and_physical_validation_gates_replace_payload(in_memory_uow, gate, question):
    run = _run(
        OrchestrationStage.IMPLEMENTING,
        details={"human_payload": {"question": "resolved review", "options": ["old"]}},
    )
    in_memory_uow.orchestration_runs.save(run)

    result = _coordinator(in_memory_uow)._escalate_apply_to_human(
        in_memory_uow,
        run,
        question,
        gate=gate,
    )

    stored = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert stored.stop_details["human_payload"] == result.human_payload
    assert result.human_payload["gate"] == gate
    assert result.human_payload["question"] == question
    assert result.human_payload["options"] == []
    assert stored.human_gate == HumanGate.NEEDS_HUMAN


def test_pr1_acknowledgement_gate_persists_current_question_and_option(in_memory_uow):
    run = _run(
        OrchestrationStage.PR1_PENDING,
        details={"human_payload": {"question": "resolved review", "options": ["old"]}},
    )
    in_memory_uow.orchestration_runs.save(run)

    payload = _coordinator(in_memory_uow)._record_pr1_acknowledgement_gate(
        in_memory_uow,
        run,
        issue_number=262,
        issue_title="Current human gate payload",
        pr_number=272,
    )

    stored = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert stored.stop_details["human_payload"] == payload
    assert payload["gate"] == "pr1_merge_acknowledgement"
    assert payload["question"] == payload["prompt"]
    assert payload["options"] == ["Estoy enterado"]


def test_confirmed_resolution_clears_only_active_payload(in_memory_uow):
    run = _run(
        OrchestrationStage.IMPLEMENTING,
        details={
            "human_payload": {
                "gate": "physical_validation",
                "stage": "IMPLEMENTING",
                "question": "Validate on device",
                "options": [],
            },
            "apply_snapshot": {"completed": ["1.1"]},
        },
    )
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    in_memory_uow.orchestration_runs.save(run)

    _coordinator(in_memory_uow)._clear_current_human_gate(in_memory_uow, run)

    stored = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert "human_payload" not in stored.stop_details
    assert stored.stop_details["apply_snapshot"] == {"completed": ["1.1"]}
    assert stored.human_gate is None
    assert stored.stop_outcome is None


def _get_runs_client(uow):
    app.dependency_overrides[get_uow] = lambda: uow
    return TestClient(app)


@pytest.mark.parametrize(
    ("stage", "stop_outcome"),
    [
        (OrchestrationStage.COMPLETED, OrchestrationStopOutcome.COMPLETED),
        (OrchestrationStage.ADMITTED, OrchestrationStopOutcome.FAILED),
        (OrchestrationStage.ADMITTED, OrchestrationStopOutcome.CANCELLED),
        (OrchestrationStage.COMPLETED, OrchestrationStopOutcome.NEEDS_HUMAN),
    ],
)
def test_terminal_run_projection_ignores_stale_human_gate(
    in_memory_uow, stage, stop_outcome
):
    run = _run(
        stage,
        details={
            "human_payload": {
                "stage": stage.value,
                "question": "Stale terminal question",
                "options": ["old option"],
            }
        },
    )
    run.is_active = False
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = stop_outcome
    in_memory_uow.orchestration_runs.save(run)

    try:
        with _get_runs_client(in_memory_uow) as client:
            response = client.get("/api/v1/orchestration/runs")
        projected = response.json()[0]
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert projected["status"] == "COMPLETED"
    assert projected["status"] != "HUMAN_REQUIRED"


def test_run_projection_ignores_payload_from_resolved_earlier_checkpoint(in_memory_uow):
    run = _run(
        OrchestrationStage.PR1_PENDING,
        details={
            "human_payload": {
                "gate": "proposal_review_escalation",
                "stage": "PROPOSAL_REVIEW",
                "question": "Resolved proposal review question",
                "options": ["old option"],
            },
            "explore_checkpoint": {
                "status": "HUMAN_REQUIRED",
                "human_payload": {"question": "Resolved Explore question", "options": ["old"]},
            },
            "propose_human_required": {
                "human_payload": {"question": "Resolved Propose question", "options": ["old"]}
            },
        },
    )
    in_memory_uow.orchestration_runs.save(run)

    try:
        with _get_runs_client(in_memory_uow) as client:
            response = client.get("/api/v1/orchestration/runs")
        projected = response.json()[0]
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert projected["stage"] == OrchestrationStage.PR1_PENDING.value
    assert "human_payload" not in projected["stop_details"]
    assert projected["status"] == "RUNNING"


def test_inactive_run_with_residual_human_gate_projects_completed(in_memory_uow):
    run = _run(OrchestrationStage.VERIFYING)
    run.is_active = False
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    in_memory_uow.orchestration_runs.save(run)

    try:
        with _get_runs_client(in_memory_uow) as client:
            response = client.get("/api/v1/orchestration/runs")
        projected = response.json()[0]
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert projected["is_active"] is False
    assert projected["stage"] == OrchestrationStage.VERIFYING.value
    assert projected["status"] == "COMPLETED"
    assert projected["status"] != "HUMAN_REQUIRED"


def test_run_projection_exposes_only_active_payload(in_memory_uow):
    run = _run(
        OrchestrationStage.PR1_PENDING,
        details={
            "human_payload": {
                "gate": "pr1_merge_acknowledgement",
                "stage": "PR1_PENDING",
                "question": "Acknowledge PR1 merge",
                "options": ["Estoy enterado"],
            },
            "proposal_review": {
                "status": "changes_required",
                "human_payload": {"question": "resolved proposal review", "options": ["old"]},
            },
        },
    )
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    in_memory_uow.orchestration_runs.save(run)

    try:
        with _get_runs_client(in_memory_uow) as client:
            response = client.get("/api/v1/orchestration/runs")
        projected = response.json()[0]
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert projected["status"] == "HUMAN_REQUIRED"
    assert projected["stop_details"]["human_payload"]["question"] == "Acknowledge PR1 merge"
    assert projected["stop_details"]["human_payload"]["options"] == ["Estoy enterado"]


def test_explore_checkpoint_is_not_promoted_to_active_payload(in_memory_uow):
    run = _run(
        OrchestrationStage.EXPLORING,
        details={
            "explore_checkpoint": {
                "status": "HUMAN_REQUIRED",
                "human_payload": {"question": "Current Explore question", "options": ["one", "two"]},
            }
        },
    )
    in_memory_uow.orchestration_runs.save(run)

    try:
        with _get_runs_client(in_memory_uow) as client:
            response = client.get("/api/v1/orchestration/runs")
        projected = response.json()[0]
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert projected["status"] == "RUNNING"
    assert "human_payload" not in projected["stop_details"]


def test_operator_response_endpoint_keeps_existing_run_response_path(
    in_memory_uow, monkeypatch, tmp_path: Path
):
    repo_root = tmp_path / "repo"
    worktrees = tmp_path / "worktrees"
    repo_root.mkdir()
    worktrees.mkdir()
    setup_managed_repository_fixture(
        in_memory_uow,
        "project-human-gate",
        repo_root,
        worktrees,
        canonical_repository_identity="github.com/org/project-human-gate",
    )
    in_memory_uow.projects.save(
        Project(
            project_id="project-human-gate",
            display_name="Human gate response",
            repository="org/project-human-gate",
        )
    )
    run = _run(OrchestrationStage.PROPOSAL_REVIEW)
    run.project_id = "project-human-gate"
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    run.stop_details = {
        "human_payload": {
            "gate_id": "gate-human-response",
            "gate": "proposal_review_escalation",
            "stage": OrchestrationStage.PROPOSAL_REVIEW.value,
            "question": "Provide current review direction",
            "options": [],
        }
    }
    in_memory_uow.orchestration_runs.save(run)
    operator = AuthorizedOperator(email="operator@example.com", name="Operator", roles=["admin"])
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_current_operator] = lambda: operator
    schedule = MagicMock(return_value="operation-human-gate")
    monkeypatch.setattr("minime.api.app._schedule_request_worker", schedule)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/projects/project-human-gate/requests/run",
                json={
                    "operator_clarification": "Please address the current review finding.",
                    "idempotency_key": "stable-review-gate-response",
                },
            )
            duplicate = client.post(
                "/api/v1/projects/project-human-gate/requests/run",
                json={
                    "operator_clarification": "Please address the current review finding.",
                    "idempotency_key": "stable-review-gate-response",
                },
            )
            action = in_memory_uow.operator_actions.list_by_run(run.run_id)[0]
            action.status = "COMPLETED"
            action.result_payload_json = {
                "status": "HUMAN_REQUIRED", "run_id": run.run_id,
                "current_stage": OrchestrationStage.PROPOSAL_REVIEW.value,
                "message": "A later gate is waiting.",
            }
            in_memory_uow.operator_actions.save(action)
            run.stop_details = {}
            run.human_gate = None
            run.stop_outcome = None
            in_memory_uow.orchestration_runs.save(run)
            in_memory_uow.commit()
            completed_duplicate = client.post(
                "/api/v1/projects/project-human-gate/requests/run",
                json={
                    "operator_clarification": "Please address the current review finding.",
                    "idempotency_key": "stable-review-gate-response",
                },
            )
            run.current_stage = OrchestrationStage.CODE_REVIEW
            run.human_gate = HumanGate.NEEDS_HUMAN
            run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
            run.stop_details = {
                "human_payload": {
                    "gate_id": "gate-code-review-response",
                    "gate": "code_review_escalation",
                    "stage": OrchestrationStage.CODE_REVIEW.value,
                    "question": "Address the current code review finding",
                    "options": [],
                }
            }
            in_memory_uow.orchestration_runs.save(run)
            in_memory_uow.commit()
            later_gate_response = client.post(
                "/api/v1/projects/project-human-gate/requests/run",
                json={
                    "operator_clarification": "Please address the current review finding.",
                    "idempotency_key": "distinct-code-review-response",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["status"] == "ACCEPTED"
    assert duplicate.status_code == 202
    assert duplicate.json()["operation_id"] == response.json()["operation_id"]
    assert response.json()["idempotency_key"] == "stable-review-gate-response"
    assert completed_duplicate.status_code == 202
    assert completed_duplicate.json()["message"] == "A later gate is waiting."
    assert later_gate_response.status_code == 202
    assert schedule.call_count == 2
    assert schedule.call_count == 2
    assert schedule.call_args.args[1].operator_clarification == "Please address the current review finding."
    action_records = in_memory_uow.operator_actions.list_by_run(run.run_id)
    assert len(action_records) == 2
    assert action_records[0].action_type.value == "RESOLVE_GATE"
    assert action_records[0].parameters_json["accepted_response"] == "Please address the current review finding."
    from minime.api.app import _accepted_operations

    _accepted_operations.pop(("project-human-gate", schedule.call_args.args[2]), None)
