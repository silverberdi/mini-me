"""Unit tests for UI candidate validation gate integration in OrchestrationService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from minime.domain.enums import (
    HumanGate,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ValidationVerdict,
)
from minime.domain.models import (
    OrchestrationCandidate,
    OrchestrationRun,
    PreviewSession,
    Project,
    ValidationRun,
)
from minime.services.orchestration_service import OrchestrationService


@pytest.fixture
def mock_uow():
    uow = MagicMock()
    uow.projects = MagicMock()
    uow.orchestration_runs = MagicMock()
    uow.orchestration_candidates = MagicMock()
    uow.preview_sessions = MagicMock()
    uow.validation_runs = MagicMock()
    uow.events = MagicMock()
    return uow


def test_ui_change_blocked_at_pr_prepared_without_validation_pass(mock_uow):
    run = OrchestrationRun(
        project_id="mini-me",
        change_name="013-preview",
        base_sha="base_123",
        current_candidate_sha="cand_456",
        current_stage=OrchestrationStage.PR_PREPARED,
    )
    mock_uow.orchestration_runs.get_by_id.return_value = run

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        deployment_preview={"required_for_ui_changes": True},
    )
    mock_uow.projects.get_by_id.return_value = project

    cand = OrchestrationCandidate(
        run_id=run.run_id,
        generation=1,
        candidate_sha="cand_456",
        base_sha="base_123",
        manifest_hash="hash_123",
    )
    mock_uow.orchestration_candidates.get_latest_for_run.return_value = cand
    mock_uow.preview_sessions.get_latest_for_candidate.return_value = None
    mock_uow.validation_runs.get_latest_for_candidate.return_value = None
    mock_uow.validation_runs.list_by_change.return_value = []

    val_svc = MagicMock()
    val_svc.is_preview_required.return_value = True
    val_svc.evaluate_candidate_validation_authority.return_value = (False, None, False)

    orchestrator = OrchestrationService(uow=mock_uow, validation_service=val_svc)

    result = orchestrator.drive_coordinator(run.run_id)
    assert result.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
    assert result.human_gate == HumanGate.NEEDS_HUMAN
    assert "UI visual validation required" in (result.stop_reason or "")
    assert result.stop_details.get("code") == "UI_VALIDATION_REQUIRED"


def test_ui_change_advances_to_ready_for_human_merge_when_validation_passes(mock_uow):
    run = OrchestrationRun(
        project_id="mini-me",
        change_name="013-preview",
        base_sha="base_123",
        current_candidate_sha="cand_456",
        current_stage=OrchestrationStage.PR_PREPARED,
    )
    mock_uow.orchestration_runs.get_by_id.return_value = run

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        deployment_preview={"required_for_ui_changes": True},
    )
    mock_uow.projects.get_by_id.return_value = project

    cand = OrchestrationCandidate(
        run_id=run.run_id,
        generation=1,
        candidate_sha="cand_456",
        base_sha="base_123",
        manifest_hash="hash_123",
    )
    mock_uow.orchestration_candidates.get_latest_for_run.return_value = cand

    prev = PreviewSession(
        preview_id="prev_01",
        project_id="mini-me",
        change_name="013-preview",
        head_sha="cand_456",
        base_sha="base_123",
        image_digest="sha256:digest_789",
    )
    mock_uow.preview_sessions.get_latest_for_candidate.return_value = prev

    val = ValidationRun(
        validation_id="val_01",
        project_id="mini-me",
        change_name="013-preview",
        head_sha="cand_456",
        base_sha="base_123",
        image_digest="sha256:digest_789",
        verdict=ValidationVerdict.PASS,
    )
    mock_uow.validation_runs.get_latest_for_candidate.return_value = val

    val_svc = MagicMock()
    val_svc.is_preview_required.return_value = True
    val_svc.evaluate_candidate_validation_authority.return_value = (True, val, False)

    orchestrator = OrchestrationService(uow=mock_uow, validation_service=val_svc)

    result = orchestrator.drive_coordinator(run.run_id)
    assert result.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert result.human_gate == HumanGate.READY_FOR_HUMAN_MERGE


def test_non_ui_change_advances_directly_to_ready_for_human_merge(mock_uow):
    run = OrchestrationRun(
        project_id="mini-me",
        change_name="002-backend-fix",
        base_sha="base_123",
        current_candidate_sha="cand_456",
        current_stage=OrchestrationStage.PR_PREPARED,
    )
    mock_uow.orchestration_runs.get_by_id.return_value = run

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        deployment_preview={"required_for_ui_changes": False},
    )
    mock_uow.projects.get_by_id.return_value = project

    cand = OrchestrationCandidate(
        run_id=run.run_id,
        generation=1,
        candidate_sha="cand_456",
        base_sha="base_123",
        manifest_hash="hash_123",
    )
    mock_uow.orchestration_candidates.get_latest_for_run.return_value = cand

    val_svc = MagicMock()
    val_svc.is_preview_required.return_value = False

    orchestrator = OrchestrationService(uow=mock_uow, validation_service=val_svc)

    result = orchestrator.drive_coordinator(run.run_id)
    assert result.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert result.human_gate == HumanGate.READY_FOR_HUMAN_MERGE
