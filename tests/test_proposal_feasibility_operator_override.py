from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from minime.domain.enums import OrchestrationStage, HumanGate
from minime.domain.models import OrchestrationRun
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.proposal_feasibility import ProposalFeasibilityEvaluator


def test_evaluator_includes_override_option_when_blocked(tmp_path: Path):
    status, tasks, scenarios, blockers, actions = ProposalFeasibilityEvaluator.validate_report(
        report={
            "blockers": ["task 1.1 has missing capability"],
            "resolution_options": ["Custom Option 1"],
            "tasks": [],
            "scenarios": [],
        },
        inputs={
            "status": "READY",
            "tasks": [],
            "scenarios": [],
            "capabilities": [],
        },
        worktree_path=tmp_path,
    )

    assert status == "BLOCKED"
    assert "task 1.1 has missing capability" in blockers
    # Both CANONICAL_OVERRIDE_OPTION and CANONICAL_UPDATE_OPTION must be present
    assert ProposalFeasibilityEvaluator.CANONICAL_OVERRIDE_OPTION in actions
    assert ProposalFeasibilityEvaluator.CANONICAL_UPDATE_OPTION in actions
    assert "Custom Option 1" in actions


def test_is_feasibility_override_response():
    # Canonical override option
    assert NativeOrchestrationCoordinator._is_feasibility_override_response(
        ProposalFeasibilityEvaluator.CANONICAL_OVERRIDE_OPTION
    ) is True

    # Common operator expressions in Spanish
    assert NativeOrchestrationCoordinator._is_feasibility_override_response(
        "Proceder a la implementación bajo autorización del operador"
    ) is True
    assert NativeOrchestrationCoordinator._is_feasibility_override_response(
        "Ignorar advertencia de precondición y continuar"
    ) is True
    assert NativeOrchestrationCoordinator._is_feasibility_override_response(
        "Aprobar y continuar con la etapa"
    ) is True
    assert NativeOrchestrationCoordinator._is_feasibility_override_response(
        "override"
    ) is True

    # Non-override options
    assert NativeOrchestrationCoordinator._is_feasibility_override_response(
        ProposalFeasibilityEvaluator.CANONICAL_UPDATE_OPTION
    ) is False
    assert NativeOrchestrationCoordinator._is_feasibility_override_response("") is False
    assert NativeOrchestrationCoordinator._is_feasibility_override_response(None) is False
    assert NativeOrchestrationCoordinator._is_feasibility_override_response(
        "Aportar evidencia verificable para verify"
    ) is False


@pytest.mark.asyncio
async def test_check_stage_feasibility_respects_override():
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=MagicMock(),
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        openspec_adapter=MagicMock(),
    )
    uow = MagicMock()
    run = OrchestrationRun(
        project_id="test-proj",
        change_name="req-1",
        base_sha="abcdef1234567890abcdef1234567890abcdef12",
        current_stage=OrchestrationStage.IMPLEMENTING,
        stop_details={"feasibility_overridden": True},
    )

    # When feasibility_overridden is already set, it bypasses stage check immediately
    result = await coordinator._check_stage_feasibility(
        uow,
        run,
        project_id="test-proj",
        worktree_path=Path("/tmp"),
        thinker_provider="antigravity",
        implementer_provider="codex",
        stage="verify",
    )
    assert result is None


@pytest.mark.asyncio
async def test_check_stage_feasibility_clears_gate_with_clarification():
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=MagicMock(),
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        openspec_adapter=MagicMock(),
    )
    uow = MagicMock()
    run = OrchestrationRun(
        project_id="test-proj",
        change_name="req-1",
        base_sha="abcdef1234567890abcdef1234567890abcdef12",
        current_stage=OrchestrationStage.IMPLEMENTING,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_details={
            "human_payload": {
                "gate": "proposal_feasibility",
                "question": "Precondition missing",
            }
        },
    )

    # When operator clarifies with an override response, the gate is cleared and it bypasses
    result = await coordinator._check_stage_feasibility(
        uow,
        run,
        project_id="test-proj",
        worktree_path=Path("/tmp"),
        thinker_provider="antigravity",
        implementer_provider="codex",
        stage="verify",
        operator_clarification="Aprobar y continuar con verify",
    )
    assert result is None
    assert run.human_gate is None
    assert (run.stop_details or {}).get("feasibility_overridden") is True
