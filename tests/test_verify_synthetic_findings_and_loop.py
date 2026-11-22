from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
from types import SimpleNamespace

from minime.domain.enums import OrchestrationStage
from minime.services.orchestration_coordinator import (
    NativeOrchestrationCoordinator,
    VerifyOutcome,
)


@pytest.mark.asyncio
async def test_run_verify_filters_synthetic_human_validation_findings(tmp_path: Path):
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=MagicMock(),
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
    )
    coordinator.agent_runner.resolve_workflow.return_value = SimpleNamespace(
        dispatch_command="verify"
    )

    # Agent returns CHANGES_REQUIRED due solely to pending human visual validation
    simulated_output = {
        "verdict": "CHANGES_REQUIRED",
        "summary": "Tests and build pass. Human visual validation remains pending.",
        "findings": [
            {
                "severity": "MAJOR",
                "location": "evidence/visual-audit.md:38",
                "violated_requirement": "La validación UI humana requerida permanece pendiente.",
                "expected_correction": "Completar la revisión visual humana en el PR.",
            }
        ],
    }
    coordinator.agent_runner.run = AsyncMock(
        return_value=SimpleNamespace(
            exit_code=0,
            success=True,
            response_output=json.dumps(simulated_output),
            workflow_handoff_required=False,
            structured_output_missing=False,
            structured_output_too_large=False,
        )
    )

    outcome = await coordinator._run_verify(
        worktree_path=tmp_path,
        provider="codex",
        change_name="test-change",
    )

    assert outcome.status == "COMPLETE"
    assert len(outcome.findings) == 0


@pytest.mark.asyncio
async def test_run_verify_retains_real_actionable_findings(tmp_path: Path):
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=MagicMock(),
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
    )
    coordinator.agent_runner.resolve_workflow.return_value = SimpleNamespace(
        dispatch_command="verify"
    )

    simulated_output = {
        "verdict": "CHANGES_REQUIRED",
        "summary": "Broken links found in layout.",
        "findings": [
            {
                "severity": "MAJOR",
                "location": "src/layouts/BaseLayout.astro:42",
                "violated_requirement": "Internal navigation links must resolve.",
                "expected_correction": "Fix broken href in navigation.",
            }
        ],
    }
    coordinator.agent_runner.run = AsyncMock(
        return_value=SimpleNamespace(
            exit_code=0,
            success=True,
            response_output=json.dumps(simulated_output),
            workflow_handoff_required=False,
            structured_output_missing=False,
            structured_output_too_large=False,
        )
    )

    outcome = await coordinator._run_verify(
        worktree_path=tmp_path,
        provider="codex",
        change_name="test-change",
    )

    assert outcome.status == "FAILED"
    assert len(outcome.findings) == 1
    assert "broken href" in outcome.findings[0]["expected_correction"]


def test_verify_outcome_falsy_when_failed_with_findings():
    outcome = VerifyOutcome(
        status="FAILED",
        summary="Found 1 issue",
        findings=({"severity": "MAJOR", "location": "file.js", "violated_requirement": "r", "expected_correction": "c"},),
    )
    assert not outcome
    assert len(outcome.findings) == 1
