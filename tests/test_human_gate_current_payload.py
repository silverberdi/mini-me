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
        result={
            "status": "changes_required",
            "summary": "Material gap in data filtering logic introduces financial misrepresentation risk.",
            "findings": [
                {
                    "severity": "MAJOR",
                    "location": "Design Decision #2",
                    "violated_requirement": "preserve traceability and keep the ledger as financial authority",
                    "expected_correction": "include provider aggregates for null or unrecognized model entries when provider identity is verified",
                }
            ],
        },
        worktree_path=Path("/tmp/human-gate-test"),
        thinker_provider="codex",
        change_name=run.change_name,
    )

    stored = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert result.status == "HUMAN_REQUIRED"
    assert stored.stop_details["human_payload"] == result.human_payload
    assert result.human_payload["gate"] == "proposal_review_escalation"
    assert result.human_payload["question"] != "resolved old question"
    assert "se agotaron los intentos" in result.human_payload["question"]
    assert "tu respuesta no la aprueba" in result.human_payload["question"]
    assert result.human_payload["review_findings"] == [
        {
            "severity": "MAJOR",
            "location": "Design Decision #2",
            "violated_requirement": "preserve traceability and keep the ledger as financial authority",
            "expected_correction": "include provider aggregates for null or unrecognized model entries when provider identity is verified",
        }
    ]
    assert result.human_payload["reviewer_summary"].startswith("Material gap")
    assert result.human_payload["options_source"] == "system_generated"
    option = result.human_payload["options"][0]
    assert option["id"] == "apply_all_proposal_review_corrections"
    assert option["source"] == "system_generated"
    assert "include provider aggregates for null or unrecognized model entries" in option["description"]
    assert option["response_text"] == option["description"]
    assert "Pedir corrección y nueva revisión" not in option["label"]
    assert stored.human_gate == HumanGate.NEEDS_HUMAN
    assert stored.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN


@pytest.mark.asyncio
async def test_proposal_review_escalation_omits_absent_optional_finding_fields(in_memory_uow):
    run = _run(OrchestrationStage.PROPOSAL_REVIEW)
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
        result={
            "status": "changes_required",
            "summary": "A finding has no location.",
            "findings": [
                {
                    "severity": "MAJOR",
                    "location": None,
                    "violated_requirement": "preserve ledger traceability",
                    "expected_correction": "include verified provider aggregates",
                }
            ],
        },
        worktree_path=Path("/tmp/human-gate-test"),
        thinker_provider="codex",
        change_name=run.change_name,
    )

    assert result.human_payload["review_findings"][0]["location"] is None
    assert result.human_payload["reviewer_summary"] == "A finding has no location."
    assert result.human_payload["options_source"] == "system_generated"
    assert result.human_payload["options"][0]["response_text"]


@pytest.mark.asyncio
async def test_proposal_review_escalation_preserves_supplied_options(in_memory_uow):
    run = _run(OrchestrationStage.PROPOSAL_REVIEW)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.projects.save(
        Project(
            project_id=run.project_id,
            display_name="Human gate test",
            repository="org/human-gate-test",
            execution_policy={"max_review_rounds": 1},
        )
    )

    native_options = [{"id": "revise", "label": "Revisar el cambio"}]
    result = await _coordinator(in_memory_uow)._route_proposal_changes_required(
        uow=in_memory_uow,
        project_id=run.project_id,
        run=run,
        result={
            "status": "changes_required",
            "findings": [{
                "severity": "MAJOR",
                "location": "spec.md",
                "violated_requirement": "preserve the required behavior",
                "expected_correction": "include the missing case",
            }],
            "options": native_options,
        },
        worktree_path=Path("/tmp/human-gate-test"),
        thinker_provider="codex",
        change_name=run.change_name,
    )

    assert result.human_payload["options"][:1] == native_options
    assert result.human_payload["options_source"] == "mixed"
    generated = result.human_payload["options"][1]
    assert generated["source"] == "system_generated"
    assert generated["response_text"] == generated["description"]


@pytest.mark.asyncio
async def test_proposal_review_correction_directive_includes_all_findings_in_order(in_memory_uow):
    run = _run(OrchestrationStage.PROPOSAL_REVIEW)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.projects.save(Project(
        project_id=run.project_id,
        display_name="Human gate test",
        repository="org/human-gate-test",
        execution_policy={"max_review_rounds": 1},
    ))
    findings = [
        {"severity": "BLOCKER", "location": "proposal.md", "violated_requirement": "scope", "expected_correction": "Keep the approved scope."},
        {"severity": "MAJOR", "location": "spec.md", "violated_requirement": "coverage", "expected_correction": "Add the missing failure scenario."},
    ]

    result = await _coordinator(in_memory_uow)._route_proposal_changes_required(
        uow=in_memory_uow, project_id=run.project_id, run=run,
        result={"status": "changes_required", "findings": findings},
        worktree_path=Path("/tmp/human-gate-test"), thinker_provider="codex", change_name=run.change_name,
    )

    directive = result.human_payload["options"][0]["response_text"]
    assert directive.index("Keep the approved scope.") < directive.index("Add the missing failure scenario.")
    assert "proposal.md" in directive and "scope" in directive
    assert "spec.md" in directive and "coverage" in directive
    assert "no consideres esta instrucción como aprobación" in directive
    revision_prompt = NativeOrchestrationCoordinator._proposal_revision_prompt({
        "clarification": directive, "findings": findings
    })
    assert f"Operator guidance: {directive}" in revision_prompt


@pytest.mark.asyncio
async def test_incomplete_proposal_corrections_keep_native_options_without_generated_instruction(in_memory_uow):
    run = _run(OrchestrationStage.PROPOSAL_REVIEW)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.projects.save(Project(
        project_id=run.project_id,
        display_name="Human gate test",
        repository="org/human-gate-test",
        execution_policy={"max_review_rounds": 1},
    ))
    native_options = [{"id": "revise", "label": "Revisar el cambio"}]

    result = await _coordinator(in_memory_uow)._route_proposal_changes_required(
        uow=in_memory_uow, project_id=run.project_id, run=run,
        result={"status": "changes_required", "options": native_options, "findings": [
            {"severity": "MAJOR", "location": "spec.md", "expected_correction": "Add the missing case."},
            {"severity": "BLOCKER", "location": "design.md", "expected_correction": " "},
        ]},
        worktree_path=Path("/tmp/human-gate-test"), thinker_provider="codex", change_name=run.change_name,
    )

    assert result.human_payload["options"] == native_options
    assert result.human_payload["options_source"] == "native"
    assert "escribe la instrucción de corrección" in result.human_payload["question"]
    assert NativeOrchestrationCoordinator._proposal_revision_prompt({
        "clarification": "Exact accepted directive", "findings": []
    }) .endswith("Operator guidance: Exact accepted directive")


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
    assert payload["question_es"] == payload["question"]
    assert payload["options_es"] == payload["options"]


def test_active_gate_persists_parallel_spanish_presentation_without_rewriting_source(in_memory_uow):
    run = _run(OrchestrationStage.PROPOSING)
    in_memory_uow.orchestration_runs.save(run)
    source_options = [
        {"id": "continue", "label": "Continue with the current candidate", "response_text": "CONTINUE"},
        {"id": "stop", "label": "Preservar el candidato", "response_text": "STOP"},
    ]
    payload = _coordinator(in_memory_uow)._record_current_human_gate(
        in_memory_uow,
        run,
        gate="proposal_feasibility",
        question="The preview database has no public connection.",
        options=source_options,
        question_es="La base de datos de vista previa no tiene una conexión pública.",
        options_es=["Continuar con el candidato actual", "Preservar el candidato"],
    )

    stored = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert payload["question"] == "The preview database has no public connection."
    assert payload["question_es"] == "La base de datos de vista previa no tiene una conexión pública."
    assert payload["options"] == source_options
    assert payload["options_es"] == ["Continuar con el candidato actual", "Preservar el candidato"]
    assert stored.stop_details["human_payload"] == payload


@pytest.mark.parametrize(
    "gate",
    [
        "explore_clarification",
        "propose_clarification",
        "proposal_feasibility",
        "proposal_review_escalation",
        "apply_checkpoint_recovery",
        "apply_gate_update",
        "apply_escalation",
        "physical_validation",
        "code_review_escalation",
        "pr1_merge_acknowledgement",
        "doc_closing_sync",
    ],
)
def test_every_gate_projection_includes_description_evidence_diff_and_option_consequences(
    in_memory_uow, gate
):
    run = _run(OrchestrationStage.IMPLEMENTING)
    in_memory_uow.orchestration_runs.save(run)
    options = [{"id": "continue", "label": "Continue", "response_text": "CONTINUE"}]
    payload = _coordinator(in_memory_uow)._record_current_human_gate(
        in_memory_uow,
        run,
        gate=gate,
        question="The run needs an operator decision.",
        options=options,
        payload={"blockers": ["task 2.1 needs evidence"]},
    )

    assert payload["description"] == "The run needs an operator decision."
    assert payload["affected_items"] == [
        {"id": "task 2.1 needs evidence", "description": "task 2.1 needs evidence"}
    ]
    assert payload["diff"]["status"] == (
        "UNAVAILABLE" if gate == "proposal_review_escalation" else "NOT_APPLICABLE"
    )
    assert payload["option_explanations"][0]["action"] == "Continue"
    assert payload["option_explanations"][0]["consequence"]
    assert payload["options"] == options
    assert payload["options"][0]["response_text"] == "CONTINUE"


@pytest.mark.parametrize(
    ("gate", "option", "expected_consequence"),
    [
        ("explore_clarification", "Use this answer", "workflow nativo Explore"),
        ("propose_clarification", "Use this answer", "workflow nativo Propose"),
        ("proposal_feasibility", "Provide evidence", "vuelve a comprobar la evidencia"),
        ("proposal_review_escalation", "Correct the findings", "revisión independiente"),
        ("proposal_correction_failed", "Correct findings", "workflow nativo OpenSpec Update"),
        ("proposal_correction_no_change", "Correct findings", "workflow nativo OpenSpec Update"),
        ("apply_escalation", "Continue", "validaciones y límites de Apply"),
        ("physical_validation", "Mark done", "solo se satisface con evidencia observada"),
        ("apply_gate_update", "Conservar el candidato detenido", "no inicia Update ni Apply"),
        ("code_review_escalation", "Correct and review", "revisión independiente del código"),
        ("doc_closing_sync", "Continue Sync", "workflow nativo OpenSpec Sync"),
        ("doc_closing_archive", "Continue Archive", "workflow nativo OpenSpec Archive"),
    ],
)
def test_gate_option_explanations_describe_stage_specific_consequences(
    gate, option, expected_consequence
):
    projected = NativeOrchestrationCoordinator._human_gate_option_explanations(
        gate, [option], {}
    )

    assert projected[0]["action"] == option
    assert expected_consequence in projected[0]["consequence"]


def test_human_gate_projection_distinguishes_unavailable_artifact_diff(in_memory_uow):
    run = _run(OrchestrationStage.PROPOSAL_REVIEW)
    in_memory_uow.orchestration_runs.save(run)
    payload = _coordinator(in_memory_uow)._record_current_human_gate(
        in_memory_uow,
        run,
        gate="proposal_review_escalation",
        question="The reviewer found a proposal issue.",
        options=[],
        payload={"review_findings": [{"location": "spec.md", "violated_requirement": "Keep the behavior safe."}]},
    )

    assert payload["affected_items"] == [
        {
            "id": "spec.md",
            "description": "Keep the behavior safe.",
        }
    ]
    assert payload["diff"]["status"] == "UNAVAILABLE"
    assert payload["option_explanations"] == []


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
    ("stage", "stop_outcome", "expected_status"),
    [
        (OrchestrationStage.COMPLETED, OrchestrationStopOutcome.COMPLETED, "COMPLETED"),
        (OrchestrationStage.ADMITTED, OrchestrationStopOutcome.FAILED, "FAILED"),
        (OrchestrationStage.ADMITTED, OrchestrationStopOutcome.CANCELLED, "CANCELLED"),
        (OrchestrationStage.COMPLETED, OrchestrationStopOutcome.NEEDS_HUMAN, "COMPLETED"),
    ],
)
def test_terminal_run_projection_ignores_stale_human_gate(
    in_memory_uow, stage, stop_outcome, expected_status
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
    assert projected["status"] == expected_status
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


def test_run_projection_exposes_new_apply_cycle_before_first_attempt(in_memory_uow):
    run = _run(
        OrchestrationStage.IMPLEMENTING,
        details={
            "apply_total_attempts": 0,
            "apply_no_progress": 0,
            "apply_limits": {"max_attempts": 3, "max_no_progress": 2},
            "apply_cycle_started_by_action_id": "accepted-action-375",
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
    assert projected["apply_cycle"] == {
        "attempts": 0,
        "hard_limit": 3,
        "no_progress": 0,
        "no_progress_limit": 2,
        "started_by_action_id": "accepted-action-375",
    }


def test_inactive_run_with_residual_human_gate_projects_completed(in_memory_uow):
    run = _run(
        OrchestrationStage.VERIFYING,
        details={
            "apply_total_attempts": 3,
            "apply_no_progress": 2,
            "apply_limits": {"max_attempts": 3, "max_no_progress": 2},
        },
    )
    run.is_active = False
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = OrchestrationStopOutcome.CANCELLED
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
    assert projected["status"] == "CANCELLED"
    assert projected["stop_details"]["apply_total_attempts"] == 3
    assert "apply_cycle" not in projected
    assert projected["status"] != "HUMAN_REQUIRED"


def test_run_projection_exposes_only_active_payload(in_memory_uow):
    run = _run(
        OrchestrationStage.PR1_PENDING,
        details={
            "human_payload": {
                "gate": "pr1_merge_acknowledgement",
                "stage": "PR1_PENDING",
                "question": "Acknowledge PR1 merge",
                "question_es": "Confirmar la fusión del PR1",
                "options": ["Estoy enterado"],
                "options_es": ["Estoy enterado"],
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
    assert projected["stop_details"]["human_payload"]["question_es"] == "Confirmar la fusión del PR1"
    assert projected["stop_details"]["human_payload"]["options"] == ["Estoy enterado"]
    assert projected["stop_details"]["human_payload"]["options_es"] == ["Estoy enterado"]


def test_explore_checkpoint_is_promoted_to_active_payload(in_memory_uow):
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
    assert projected["status"] == "HUMAN_REQUIRED"
    assert projected["human_gate"] == "HUMAN_REQUIRED"
    assert projected["stop_details"]["human_payload"]["question"] == "Current Explore question"
    assert projected["stop_details"]["human_payload"]["options"] == ["one", "two"]


def test_resolved_explore_checkpoint_does_not_resurface(in_memory_uow):
    run = _run(
        OrchestrationStage.PROPOSING,
        details={
            "explore_checkpoint": {
                "status": "RESOLVED",
                "human_payload": {"question": "Old resolved Explore question", "options": ["one", "two"]},
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


def test_explore_checkpoint_accepts_response_without_409_and_resolves(
    in_memory_uow, monkeypatch, tmp_path: Path
):
    repo_root = tmp_path / "repo"
    worktrees = tmp_path / "worktrees"
    repo_root.mkdir()
    worktrees.mkdir()
    setup_managed_repository_fixture(
        in_memory_uow,
        "project-explore-test",
        repo_root,
        worktrees,
        canonical_repository_identity="github.com/org/project-explore-test",
    )
    in_memory_uow.projects.save(
        Project(
            project_id="project-explore-test",
            display_name="Explore gate test",
            repository="org/project-explore-test",
        )
    )
    run = _run(OrchestrationStage.EXPLORING)
    run.project_id = "project-explore-test"
    run.stop_details = {
        "explore_checkpoint": {
            "status": "HUMAN_REQUIRED",
            "attempt_id": "explore-attempt-1",
            "human_payload": {
                "question": "¿Desea usar PostgreSQL o SQLite?",
                "options": ["PostgreSQL", "SQLite"],
            },
        }
    }
    in_memory_uow.orchestration_runs.save(run)
    operator = AuthorizedOperator(email="operator@example.com", name="Operator", roles=["admin"])
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_current_operator] = lambda: operator
    schedule = MagicMock(return_value="operation-explore-gate")
    monkeypatch.setattr("minime.api.app._schedule_request_worker", schedule)

    try:
        with TestClient(app) as client:
            # 1. Verify Explore gate is projected as HUMAN_REQUIRED
            get_resp = client.get("/api/v1/orchestration/runs")
            assert get_resp.status_code == 200
            proj = get_resp.json()[0]
            assert proj["status"] == "HUMAN_REQUIRED"
            assert proj["human_gate"] == "HUMAN_REQUIRED"
            assert proj["stop_details"]["human_payload"]["question"] == "¿Desea usar PostgreSQL o SQLite?"

            # 2. Submit response to Explore gate - must be accepted without 409 Conflict
            post_resp = client.post(
                "/api/v1/projects/project-explore-test/requests/run",
                json={
                    "operator_clarification": "PostgreSQL",
                    "idempotency_key": "explore-clarification-key-1",
                },
            )
            assert post_resp.status_code == 202
            assert post_resp.json()["status"] == "ACCEPTED"

            # 3. Verify operator action was recorded
            actions = in_memory_uow.operator_actions.list_by_run(run.run_id)
            assert len(actions) == 1
            assert actions[0].parameters_json["accepted_response"] == "PostgreSQL"

            # 4. Process gate resolution via coordinator
            coordinator = NativeOrchestrationCoordinator(
                uow_factory=lambda: in_memory_uow,
                github_adapter=MagicMock(),
                worktree_manager=MagicMock(),
                agent_runner=MagicMock(),
            )
            coordinator._clear_current_human_gate(in_memory_uow, run, response_text="PostgreSQL")
            in_memory_uow.orchestration_runs.save(run)
            in_memory_uow.commit()

            # 5. Verify gate was resolved in database and cleared
            stored = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
            assert stored.stop_details["explore_checkpoint"]["status"] == "RESOLVED"
            assert "human_payload" not in stored.stop_details
            assert stored.human_gate is None
            assert len(stored.stop_details.get("resolved_human_gates", [])) == 1
            assert stored.stop_details["resolved_human_gates"][0]["response"] == "PostgreSQL"

            # 6. Verify reload does not resurrect the answered gate
            get_after = client.get("/api/v1/orchestration/runs")
            assert get_after.status_code == 200
            proj_after = get_after.json()[0]
            assert proj_after["status"] == "RUNNING"
            assert proj_after.get("human_gate") is None
            assert "human_payload" not in proj_after["stop_details"]
    finally:
        app.dependency_overrides.clear()
        from minime.api.app import _accepted_operations
        _accepted_operations.pop(("project-explore-test", "explore-clarification-key-1"), None)

