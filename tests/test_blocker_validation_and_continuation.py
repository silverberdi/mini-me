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


# ---------------------------------------------------------------------------
# Rule K (Alternative Executor Eligibility Gate) Tests
# ---------------------------------------------------------------------------


def test_rule_k_alternative_eligible_allows_reassign():
    engine = ContinuationEngine(max_reassignments_per_job=2)
    ctx = ContinuationContext(
        job_id="j1",
        attempt_number=2,
        current_executor_role="codex",
        current_model_identity="codex-default",
        outcome=ExecutionOutcome.NO_PROGRESS,
        same_outcome_streak=2,
        reassignment_count=0,
        alternative_executor_eligible=True,
        target_executor_role="antigravity",
        target_model_identity="antigravity",
    )
    res = engine.decide(ctx)
    assert res.decision == ContinuationDecision.REASSIGN_AGENT
    assert res.should_handoff is True
    assert res.target_executor_role == "antigravity"


def test_rule_k_no_alternative_configured_escalates_to_needs_human():
    engine = ContinuationEngine(max_reassignments_per_job=2)
    ctx = ContinuationContext(
        job_id="j1",
        attempt_number=2,
        current_executor_role="codex",
        current_model_identity="codex-default",
        outcome=ExecutionOutcome.NO_PROGRESS,
        same_outcome_streak=2,
        reassignment_count=0,
        alternative_executor_eligible=False,  # No alternative configured in project pairing
    )
    res = engine.decide(ctx)
    assert res.decision == ContinuationDecision.NEEDS_HUMAN
    assert "Alternative executor ineligible" in (res.escalation_reason or "")


def test_rule_k_alternative_same_executor_or_prohibited_model_escalates():
    engine = ContinuationEngine(max_reassignments_per_job=2)
    ctx = ContinuationContext(
        job_id="j1",
        attempt_number=2,
        current_executor_role="codex",
        current_model_identity="codex-default",
        outcome=ExecutionOutcome.FALSE_BLOCKER,
        same_blocker_fingerprint_streak=2,
        reassignment_count=0,
        alternative_executor_eligible=False,  # Prohibited model / self-reassignment
    )
    res = engine.decide(ctx)
    assert res.decision == ContinuationDecision.NEEDS_HUMAN
    assert "Alternative executor ineligible" in (res.escalation_reason or "")


def test_rule_k_reassignment_ceiling_available_but_ineligible_escalates():
    engine = ContinuationEngine(max_reassignments_per_job=3)
    ctx = ContinuationContext(
        job_id="j1",
        attempt_number=1,
        current_executor_role="codex",
        current_model_identity="codex-default",
        outcome=ExecutionOutcome.PREMATURE_STOP,
        same_outcome_streak=2,
        reassignment_count=1,  # 1 < 3 ceiling available
        alternative_executor_eligible=False,
    )
    res = engine.decide(ctx)
    assert res.decision == ContinuationDecision.NEEDS_HUMAN
    assert "Alternative executor ineligible" in (res.escalation_reason or "")


def test_rule_k_all_reassignment_branches_respect_eligibility_gate():
    engine = ContinuationEngine(max_corrective_retries_per_executor=1, max_reassignments_per_job=2)
    outcomes = [
        ExecutionOutcome.PREMATURE_STOP,
        ExecutionOutcome.FALSE_BLOCKER,
        ExecutionOutcome.CHANGES_REQUIRED,
        ExecutionOutcome.NO_PROGRESS,
        ExecutionOutcome.PROVIDER_FAILURE,
    ]

    for outcome in outcomes:
        # Eligible alternative -> REASSIGN_AGENT
        ctx_eligible = ContinuationContext(
            job_id="j1",
            attempt_number=2,
            current_executor_role="codex",
            current_model_identity="codex",
            outcome=outcome,
            corrective_retries_for_current_executor=2,  # exhausted
            same_outcome_streak=2,
            same_blocker_fingerprint_streak=2,
            reassignment_count=0,
            alternative_executor_eligible=True,
            target_executor_role="antigravity",
        )
        res_eligible = engine.decide(ctx_eligible)
        assert res_eligible.decision == ContinuationDecision.REASSIGN_AGENT, f"Failed for {outcome}"
        assert res_eligible.should_handoff is True
        assert res_eligible.target_executor_role == "antigravity"

        # Ineligible alternative -> NEEDS_HUMAN
        ctx_ineligible = ContinuationContext(
            job_id="j1",
            attempt_number=2,
            current_executor_role="codex",
            current_model_identity="codex",
            outcome=outcome,
            corrective_retries_for_current_executor=2,
            same_outcome_streak=2,
            same_blocker_fingerprint_streak=2,
            reassignment_count=0,
            alternative_executor_eligible=False,
        )
        res_ineligible = engine.decide(ctx_ineligible)
        assert res_ineligible.decision == ContinuationDecision.NEEDS_HUMAN, f"Failed for {outcome}"


def test_rule_k_ceiling_reached_escalates_to_needs_human():
    """When reassignment ceiling is exhausted, continuation engine escalates to NEEDS_HUMAN."""
    engine = ContinuationEngine(max_reassignments_per_job=2)
    ctx = ContinuationContext(
        job_id="j1",
        attempt_number=3,
        current_executor_role="codex",
        current_model_identity="codex",
        outcome=ExecutionOutcome.PREMATURE_STOP,
        same_outcome_streak=2,
        reassignment_count=2,  # ceiling reached
        alternative_executor_eligible=True,
        target_executor_role="antigravity",
    )
    res = engine.decide(ctx)
    assert res.decision == ContinuationDecision.NEEDS_HUMAN
    assert "Maximum reassignment limit" in (res.escalation_reason or "")
