"""Tests for Spanish independent review enforcement and unblocked proposal review re-entry."""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from minime.domain.models import OrchestrationRun, OrchestrationStage
from minime.services.orchestration_coordinator import (
    NativeOrchestrationCoordinator,
    _REVIEW_STALE,
    _REVIEW_AMBIGUOUS,
    _REVIEW_VERDICT_SCHEMA_HINT,
)


def test_review_verdict_schema_hint_mandates_spanish():
    """Verify schema hint explicitly requires Spanish output."""
    hint = _REVIEW_VERDICT_SCHEMA_HINT
    assert "español simple" in hint.lower()
    assert "no uses inglés" in hint.lower() or "not emit findings or summaries in english" in hint.lower()


def test_classify_review_reentry_none_stored_is_stale_even_on_resume():
    """When no review evidence is stored, re-entry on resume must be STALE, not AMBIGUOUS."""
    action = NativeOrchestrationCoordinator._classify_review_reentry(
        stored=None,
        identity_matches=False,
        is_resume=True,
    )
    assert action == _REVIEW_STALE


def test_classify_review_reentry_dispatched_with_different_identity_is_stale():
    """When a dispatched attempt's identity no longer matches (content revised), it is STALE."""
    stored = {
        "status": "dispatched",
        "attempt_id": "old-attempt",
        "artifact_hashes": {"proposal.md": "oldhash"},
    }
    action = NativeOrchestrationCoordinator._classify_review_reentry(
        stored=stored,
        identity_matches=False,
        is_resume=True,
    )
    assert action == _REVIEW_STALE


@pytest.mark.asyncio
async def test_begin_stage_invocation_allows_proposal_review_on_human_resume():
    """Verify proposal review re-entry is permitted when allow_human_resume=True."""
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: MagicMock(),
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
    )
    uow = MagicMock()

    candidate = {
        "run_id": "run-test-363",
        "stage": "PROPOSAL_REVIEW",
        "worktree": "/tmp/test",
        "branch": "test-branch",
        "generation": 1,
        "candidate_sha": "sha123",
        "candidate_fingerprint": "cfp123",
        "fingerprint": "fp123",
    }
    coordinator._stage_candidate_identity = AsyncMock(return_value=candidate)

    prior_claim = MagicMock()
    prior_claim.is_active = False
    uow.claims.get_by_key.return_value = prior_claim

    mock_claim = MagicMock()
    mock_claim.claim_key = "stage-invocation:run-test-363:PROPOSAL_REVIEW:fp123"
    mock_claim.owner_instance_id = "test-owner"
    mock_claim.fence_token = 2
    mock_claim.lease_expires_at = datetime.now(timezone.utc)
    uow.claims.acquire_or_reacquire.return_value = mock_claim

    # Prior attempt finished with COMPLETE
    start_event = MagicMock()
    start_event.event_type = "STAGE_INVOCATION_STARTED"
    start_event.evidence_references = {
        "attempt_id": "attempt-1",
        "claim_key": "stage-invocation:run-test-363:PROPOSAL_REVIEW:fp123",
        "candidate": candidate,
    }

    comp_event = MagicMock()
    comp_event.event_type = "STAGE_INVOCATION_COMPLETED"
    comp_event.evidence_references = {
        "attempt_id": "attempt-1",
        "claim_key": "stage-invocation:run-test-363:PROPOSAL_REVIEW:fp123",
        "status": "COMPLETE",
    }

    uow.orchestration_stage_events.list_by_run.return_value = [start_event, comp_event]

    run = OrchestrationRun(
        project_id="test-proj",
        run_id="run-test-363",
        change_name="req-test",
        base_sha="base123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
    )

    # Without allow_human_resume, prior COMPLETE blocks re-entry
    blocked = await coordinator._begin_stage_invocation(
        uow, run, Path("/tmp/test"), "PROPOSAL_REVIEW",
        allow_human_resume=False,
    )
    assert blocked is None

    # With allow_human_resume=True, re-entry is permitted
    allowed = await coordinator._begin_stage_invocation(
        uow, run, Path("/tmp/test"), "PROPOSAL_REVIEW",
        allow_human_resume=True,
    )
    assert allowed is not None
    assert allowed.claim_key == "stage-invocation:run-test-363:PROPOSAL_REVIEW:fp123"
