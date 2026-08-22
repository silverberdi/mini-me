"""Tests for blocker validation service, fingerprinting, and continuation engine."""

from __future__ import annotations

from minime.domain.enums import (
    BlockerValidationVerdict,
    ContinuationDecision,
    ExecutionOutcome,
)
from minime.domain.models import BlockerClaim, BlockerClaimPayload, CheckResult
from minime.services.blocker_validation import (
    BlockerValidationContext,
    BlockerValidationService,
    compute_blocker_fingerprint,
)
from minime.services.continuation_engine import (
    ContinuationContext,
    ContinuationEngine,
)
from minime.services.openspec_tasks import OpenSpecTask


def test_compute_blocker_fingerprint_reproducibility():
    fp1 = compute_blocker_fingerprint("MISSING_FILE", "req-1", "inv-1", "reason-1")
    fp2 = compute_blocker_fingerprint("missing_file ", " req-1", "INV-1", "reason-1")
    assert fp1 == fp2

    fp3 = compute_blocker_fingerprint("MISSING_FILE", "req-2", "inv-1", "reason-1")
    assert fp1 != fp3


def test_blocker_validation_missing_file_false_blocker():
    service = BlockerValidationService()
    ctx = BlockerValidationContext(change_name="007-change")
    payload = BlockerClaimPayload(
        blocker_type="MISSING_FILE",
        rationale="File src/minime/services/new_service.py does not exist yet",
        is_agent_solvable=True,
    )

    res = service.validate(payload, ctx)
    assert res.verdict == BlockerValidationVerdict.FALSE_BLOCKER
    assert res.is_agent_solvable is True
    assert "implementation responsibility" in res.rationale


def test_blocker_validation_requirement_contradiction_real_blocker():
    service = BlockerValidationService()
    ctx = BlockerValidationContext(change_name="007-change")
    payload = BlockerClaimPayload(
        blocker_type="REQUIREMENT_CONTRADICTION",
        affected_requirement="spec-1.2",
        failing_invariant="Invariant 4 cannot be satisfied with upstream API",
        rationale="Spec contradicts existing immutable protocol",
        is_agent_solvable=False,
    )

    res = service.validate(payload, ctx)
    assert res.verdict == BlockerValidationVerdict.REAL_BLOCKER
    assert res.is_agent_solvable is False


def test_continuation_engine_real_blocker_escalates():
    engine = ContinuationEngine()
    claim = BlockerClaim(
        claim_id="c1",
        job_id="j1",
        attempt_id="a1",
        blocker_type="REQUIREMENT_CONTRADICTION",
        blocker_fingerprint="fp1",
        validation_verdict=BlockerValidationVerdict.REAL_BLOCKER,
        rationale="Cannot satisfy contradiction",
    )
    ctx = ContinuationContext(
        job_id="j1",
        attempt_number=1,
        current_executor_role="codex",
        current_model_identity="codex-default",
        outcome=ExecutionOutcome.REAL_BLOCKER,
        blocker_claim=claim,
    )

    res = engine.decide(ctx)
    assert res.decision == ContinuationDecision.NEEDS_HUMAN
    assert "Validated real blocker" in (res.escalation_reason or "")


def test_continuation_engine_false_blocker_retry_then_reassign_then_escalate():
    engine = ContinuationEngine(
        max_corrective_retries_per_executor=2,
        max_reassignments_per_job=1,
        max_same_false_blocker_streak=2,
    )
    claim = BlockerClaim(
        claim_id="c1",
        job_id="j1",
        attempt_id="a1",
        blocker_type="MISSING_FILE",
        blocker_fingerprint="fp1",
        validation_verdict=BlockerValidationVerdict.FALSE_BLOCKER,
        validation_rationale="Create the file yourself.",
    )

    # 1. First false blocker attempt -> Correct and retry
    ctx1 = ContinuationContext(
        job_id="j1",
        attempt_number=1,
        current_executor_role="codex",
        current_model_identity="codex-default",
        outcome=ExecutionOutcome.FALSE_BLOCKER,
        blocker_claim=claim,
        corrective_retries_for_current_executor=0,
        same_blocker_fingerprint_streak=1,
    )
    res1 = engine.decide(ctx1)
    assert res1.decision == ContinuationDecision.CORRECT_AND_RETRY
    assert "FALSE BLOCKER" in (res1.corrective_prompt or "")

    # 2. Repeated false blocker streak reaches 2 -> Reassign
    ctx2 = ContinuationContext(
        job_id="j1",
        attempt_number=2,
        current_executor_role="codex",
        current_model_identity="codex-default",
        outcome=ExecutionOutcome.FALSE_BLOCKER,
        blocker_claim=claim,
        corrective_retries_for_current_executor=1,
        same_blocker_fingerprint_streak=2,
        reassignment_count=0,
    )
    res2 = engine.decide(ctx2)
    assert res2.decision == ContinuationDecision.REASSIGN_AGENT
    assert res2.should_handoff is True

    # 3. Reassignments exhausted -> Needs human
    ctx3 = ContinuationContext(
        job_id="j1",
        attempt_number=3,
        current_executor_role="antigravity",
        current_model_identity="agy-default",
        outcome=ExecutionOutcome.FALSE_BLOCKER,
        blocker_claim=claim,
        corrective_retries_for_current_executor=0,
        same_blocker_fingerprint_streak=2,
        reassignment_count=1,
    )
    res3 = engine.decide(ctx3)
    assert res3.decision == ContinuationDecision.NEEDS_HUMAN


def test_continuation_engine_premature_stop_guidance():
    engine = ContinuationEngine()
    ctx = ContinuationContext(
        job_id="j1",
        attempt_number=1,
        current_executor_role="codex",
        current_model_identity="codex-default",
        outcome=ExecutionOutcome.PREMATURE_STOP,
        incomplete_tasks=[OpenSpecTask("1.2", "Implement models", "Phase 1", False)],
        corrective_retries_for_current_executor=0,
    )

    res = engine.decide(ctx)
    assert res.decision == ContinuationDecision.CORRECT_AND_RETRY
    assert "1.2: Implement models" in (res.corrective_prompt or "")


def test_continuation_engine_failing_checks_guidance():
    engine = ContinuationEngine()
    ctx = ContinuationContext(
        job_id="j1",
        attempt_number=1,
        current_executor_role="codex",
        current_model_identity="codex-default",
        outcome=ExecutionOutcome.CHANGES_REQUIRED,
        failing_checks=[
            CheckResult(
                result_id="c1",
                job_id="j1",
                check_name="pytest",
                command="pytest",
                exit_code=1,
                duration_ms=50,
                output_snippet="AssertionError: expected 1 got 2",
            )
        ],
        corrective_retries_for_current_executor=0,
    )

    res = engine.decide(ctx)
    assert res.decision == ContinuationDecision.CORRECT_AND_RETRY
    assert "AssertionError: expected 1 got 2" in (res.corrective_prompt or "")
