"""Unit tests for ValidationAuthorityService and candidate validation authority."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from minime.domain.enums import ValidationVerdict
from minime.domain.models import Project, ValidationRun
from minime.services.validation_authority_service import ValidationAuthorityService


@pytest.fixture
def mock_uow():
    uow = MagicMock()
    uow.validation_runs = MagicMock()
    uow.events = MagicMock()
    return uow


def test_is_preview_required_detects_ui_surface_in_openspec(mock_uow, tmp_path):
    # Setup mock openspec change directory
    change_dir = tmp_path / "openspec" / "changes" / "013-test-change"
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text("# Proposal\nsurface: ui\nVisual preview required.")

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        openspec_path="openspec",
        deployment_preview={"required_for_ui_changes": True},
    )

    svc = ValidationAuthorityService(uow=mock_uow)
    required = svc.is_preview_required(project, "013-test-change", project_root=tmp_path)
    assert required is True


def test_is_preview_required_returns_false_for_backend_only_changes(mock_uow, tmp_path):
    change_dir = tmp_path / "openspec" / "changes" / "002-backend-fix"
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text("# Proposal\nsurface: backend\nDatabase indexing only.")

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        openspec_path="openspec",
        deployment_preview={"required_for_ui_changes": False},
    )

    svc = ValidationAuthorityService(uow=mock_uow)
    required = svc.is_preview_required(project, "002-backend-fix", project_root=tmp_path)
    assert required is False


def test_get_validation_scenarios_parses_spec_scenarios(mock_uow, tmp_path):
    specs_dir = tmp_path / "openspec" / "changes" / "013-test-change" / "specs" / "feature"
    specs_dir.mkdir(parents=True)
    spec_content = """
## ADDED Requirements

### Requirement: Interactive Dashboard
The system SHALL provide an interactive preview pane.

#### Scenario: Inspect Live Preview
Given a candidate container is running
When the operator clicks the preview URL
Then the application renders without errors
"""
    (specs_dir / "spec.md").write_text(spec_content)

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        openspec_path="openspec",
    )

    svc = ValidationAuthorityService(uow=mock_uow)
    scenarios = svc.get_validation_scenarios(project, "013-test-change", project_root=tmp_path)
    assert len(scenarios) == 1
    assert scenarios[0].title == "Inspect Live Preview"
    assert "Given a candidate container is running" in scenarios[0].ordered_steps[0]


def test_evaluate_candidate_validation_authority_authorizes_matching_candidate(mock_uow):
    head_sha = "head_sha_123"
    base_sha = "base_sha_456"
    image_digest = "sha256:image_digest_789"

    matching_val = ValidationRun(
        validation_id="val_01",
        project_id="mini-me",
        change_name="013-preview",
        head_sha=head_sha,
        base_sha=base_sha,
        image_digest=image_digest,
        verdict=ValidationVerdict.PASS,
    )
    mock_uow.validation_runs.get_latest_for_candidate.return_value = matching_val

    svc = ValidationAuthorityService(uow=mock_uow)
    is_auth, val, is_stale = svc.evaluate_candidate_validation_authority(
        project_id="mini-me",
        change_name="013-preview",
        head_sha=head_sha,
        base_sha=base_sha,
        image_digest=image_digest,
    )

    assert is_auth is True
    assert val == matching_val
    assert is_stale is False


def test_evaluate_candidate_validation_authority_marks_stale_when_candidate_mutated(mock_uow):
    head_sha_old = "head_sha_old"
    head_sha_new = "head_sha_new"
    base_sha = "base_sha_456"
    image_digest = "sha256:image_digest_789"

    # Exact match for new candidate does not exist
    mock_uow.validation_runs.get_latest_for_candidate.return_value = None

    # Older validation exists for old candidate
    older_val = ValidationRun(
        validation_id="val_old",
        project_id="mini-me",
        change_name="013-preview",
        head_sha=head_sha_old,
        base_sha=base_sha,
        image_digest=image_digest,
        verdict=ValidationVerdict.PASS,
    )
    mock_uow.validation_runs.list_by_change.return_value = [older_val]

    svc = ValidationAuthorityService(uow=mock_uow)
    is_auth, val, is_stale = svc.evaluate_candidate_validation_authority(
        project_id="mini-me",
        change_name="013-preview",
        head_sha=head_sha_new,
        base_sha=base_sha,
        image_digest=image_digest,
    )

    assert is_auth is False
    assert is_stale is True
    assert val == older_val


def test_evaluate_candidate_validation_authority_rejects_fail_verdict(mock_uow):
    head_sha = "head_sha_123"
    base_sha = "base_sha_456"
    image_digest = "sha256:image_digest_789"

    failing_val = ValidationRun(
        validation_id="val_fail",
        project_id="mini-me",
        change_name="013-preview",
        head_sha=head_sha,
        base_sha=base_sha,
        image_digest=image_digest,
        verdict=ValidationVerdict.FAIL,
    )
    mock_uow.validation_runs.get_latest_for_candidate.return_value = failing_val

    svc = ValidationAuthorityService(uow=mock_uow)
    is_auth, val, is_stale = svc.evaluate_candidate_validation_authority(
        project_id="mini-me",
        change_name="013-preview",
        head_sha=head_sha,
        base_sha=base_sha,
        image_digest=image_digest,
    )

    assert is_auth is False


def test_record_validation_saves_and_emits_event(mock_uow):
    svc = ValidationAuthorityService(uow=mock_uow)
    val = svc.record_validation(
        project_id="mini-me",
        change_name="013-preview",
        head_sha="head_sha_123",
        base_sha="base_sha_456",
        image_digest="sha256:digest_789",
        verdict=ValidationVerdict.PASS,
        scenario_results=[{"scenario_id": "sc_01", "verdict": "PASS"}],
        notes="Visual inspection verified without defect.",
        operator="alice",
    )

    assert val.verdict == ValidationVerdict.PASS
    assert val.operator == "alice"
    assert mock_uow.validation_runs.save.called
    assert mock_uow.events.save.called
    assert mock_uow.commit.called
