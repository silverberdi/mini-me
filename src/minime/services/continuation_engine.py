"""Continuation engine and deterministic decision-making rules for mini me."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from minime.domain.enums import (
    ContinuationDecision,
    ExecutionOutcome,
    ProgressClassification,
)
from minime.domain.models import BlockerClaim, CheckResult
from minime.services.openspec_tasks import OpenSpecTask

logger = logging.getLogger(__name__)


@dataclass
class ContinuationContext:
    """Deterministic runtime context passed to the continuation engine."""

    job_id: str
    attempt_number: int
    current_executor_role: str
    current_model_identity: str
    outcome: ExecutionOutcome
    progress: ProgressClassification | None = None
    blocker_claim: BlockerClaim | None = None
    corrective_retries_for_current_executor: int = 0
    reassignment_count: int = 0
    same_outcome_streak: int = 1
    same_blocker_fingerprint_streak: int = 0
    incomplete_tasks: list[OpenSpecTask] = field(default_factory=list)
    failing_checks: list[CheckResult] = field(default_factory=list)
    error_message: str | None = None
    alternative_executor_eligible: bool = True
    target_executor_role: str | None = None
    target_model_identity: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContinuationDecisionResult:
    """Outcome of continuation engine decision evaluation."""

    decision: ContinuationDecision
    corrective_prompt: str | None = None
    target_executor_role: str | None = None
    target_model_identity: str | None = None
    escalation_reason: str | None = None
    should_handoff: bool = False


class ContinuationEngine:
    """Deterministic continuation engine applying hard configurable limits."""

    def __init__(
        self,
        max_corrective_retries_per_executor: int = 2,
        max_reassignments_per_job: int = 2,
        max_same_outcome_streak: int = 2,
        max_same_false_blocker_streak: int = 2,
    ):
        self.max_corrective_retries = max_corrective_retries_per_executor
        self.max_reassignments = max_reassignments_per_job
        self.max_same_outcome_streak = max_same_outcome_streak
        self.max_same_false_blocker_streak = max_same_false_blocker_streak

    def _reassign_or_escalate(
        self, ctx: ContinuationContext, reason: str
    ) -> ContinuationDecisionResult:
        """Apply Rule K: reassign only if ceiling available and alternative is structurally eligible."""
        if ctx.reassignment_count >= self.max_reassignments:
            return ContinuationDecisionResult(
                decision=ContinuationDecision.NEEDS_HUMAN,
                escalation_reason=f"Maximum reassignment limit ({self.max_reassignments}) reached: {reason}",
            )
        if not ctx.alternative_executor_eligible:
            return ContinuationDecisionResult(
                decision=ContinuationDecision.NEEDS_HUMAN,
                escalation_reason=f"Alternative executor ineligible or not configured under policy: {reason}",
            )
        return ContinuationDecisionResult(
            decision=ContinuationDecision.REASSIGN_AGENT,
            should_handoff=True,
            target_executor_role=ctx.target_executor_role,
            target_model_identity=ctx.target_model_identity,
            escalation_reason=reason,
        )

    def decide(self, ctx: ContinuationContext) -> ContinuationDecisionResult:
        """Evaluate continuation state and deterministically choose the next action."""
        outcome = ctx.outcome

        # 1. Terminal success / no continuation needed
        if outcome == ExecutionOutcome.COMPLETED:
            return ContinuationDecisionResult(
                decision=ContinuationDecision.CONTINUE_SAME_AGENT,  # or complete
                corrective_prompt=None,
            )

        # 2. Real Blocker -> Human Escalation
        if outcome == ExecutionOutcome.REAL_BLOCKER:
            return ContinuationDecisionResult(
                decision=ContinuationDecision.NEEDS_HUMAN,
                escalation_reason=f"Validated real blocker encountered: {ctx.blocker_claim.rationale if ctx.blocker_claim else 'External blocker'}",
            )

        # 3. Policy Violation -> Human Escalation
        if outcome == ExecutionOutcome.POLICY_VIOLATION:
            return ContinuationDecisionResult(
                decision=ContinuationDecision.NEEDS_HUMAN,
                escalation_reason=f"Policy violation detected: {ctx.error_message or 'Security/repository policy breached'}",
            )

        # 4. Capacity / Quota Exhaustion -> Wait External
        if outcome == ExecutionOutcome.PROVIDER_EXHAUSTED:
            return ContinuationDecisionResult(
                decision=ContinuationDecision.WAIT_EXTERNAL,
                escalation_reason="Primary capacity exhausted; waiting for reset window.",
            )

        if outcome == ExecutionOutcome.ENVIRONMENT_UNAVAILABLE:
            return ContinuationDecisionResult(
                decision=ContinuationDecision.WAIT_EXTERNAL,
                escalation_reason="External execution environment is temporarily unavailable; waiting without consuming retry or reassignment budget.",
            )

        # 5. Provider Failure (unrecoverable provider error / auth error)
        if outcome == ExecutionOutcome.PROVIDER_FAILURE:
            return self._reassign_or_escalate(
                ctx, "Provider failure occurred; reassigning to alternative executor."
            )

        # 6. False Blocker
        if outcome == ExecutionOutcome.FALSE_BLOCKER:
            # Check false blocker streak
            if ctx.same_blocker_fingerprint_streak >= self.max_same_false_blocker_streak:
                return self._reassign_or_escalate(
                    ctx,
                    f"Repeated false blocker streak ({ctx.same_blocker_fingerprint_streak}) reached threshold; reassigning executor.",
                )

            # Try corrective retry if within executor budget
            if ctx.corrective_retries_for_current_executor < self.max_corrective_retries:
                prompt = (
                    f"CORRECTIVE GUIDANCE: The reported blocker '{ctx.blocker_claim.blocker_type if ctx.blocker_claim else ''}' "
                    f"was evaluated as a FALSE BLOCKER. "
                    f"{ctx.blocker_claim.validation_rationale if ctx.blocker_claim else 'You are responsible for creating missing files/classes.'} "
                    f"Please proceed with implementation."
                )
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.CORRECT_AND_RETRY,
                    corrective_prompt=prompt,
                )

            # Reassign if retries exhausted
            return self._reassign_or_escalate(
                ctx, "Corrective retry limit reached on false blocker; reassigning executor."
            )

        # 7. Premature Stop
        if outcome == ExecutionOutcome.PREMATURE_STOP:
            if ctx.same_outcome_streak >= self.max_same_outcome_streak:
                return self._reassign_or_escalate(
                    ctx,
                    f"Repeated premature stops ({ctx.same_outcome_streak}) reached limit; reassigning executor.",
                )

            if ctx.corrective_retries_for_current_executor < self.max_corrective_retries:
                task_list = "\n".join(f"- {t.task_id}: {t.text}" for t in ctx.incomplete_tasks)
                prompt = (
                    f"CORRECTIVE GUIDANCE: Execution stopped prematurely with uncompleted tasks. "
                    f"Please complete all remaining OpenSpec tasks:\n{task_list}"
                )
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.CORRECT_AND_RETRY,
                    corrective_prompt=prompt,
                )

            return self._reassign_or_escalate(
                ctx, "Executor exhausted retries without completing tasks; reassigning."
            )

        # 8. Changes Required (failing deterministic checks)
        if outcome == ExecutionOutcome.CHANGES_REQUIRED:
            if ctx.same_outcome_streak >= self.max_same_outcome_streak:
                return self._reassign_or_escalate(
                    ctx, "Persistent failing checks; reassigning executor."
                )

            if ctx.corrective_retries_for_current_executor < self.max_corrective_retries:
                check_summary = "\n".join(
                    f"- {c.check_name} (exit code {c.exit_code}): {c.output_snippet}"
                    for c in ctx.failing_checks
                )
                prompt = f"CORRECTIVE GUIDANCE: Deterministic checks failed. Fix the following failures:\n{check_summary}"
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.CORRECT_AND_RETRY,
                    corrective_prompt=prompt,
                )

            return self._reassign_or_escalate(
                ctx, "Corrective retry limit reached for check failures; reassigning executor."
            )

        # 9. No Progress
        if outcome == ExecutionOutcome.NO_PROGRESS:
            if (
                ctx.same_outcome_streak >= self.max_same_outcome_streak
                or ctx.corrective_retries_for_current_executor >= self.max_corrective_retries
            ):
                return self._reassign_or_escalate(
                    ctx, "Executor made zero progress; reassigning executor."
                )

            return ContinuationDecisionResult(
                decision=ContinuationDecision.CORRECT_AND_RETRY,
                corrective_prompt="CORRECTIVE GUIDANCE: No progress detected. Please produce required file modifications for the active OpenSpec change.",
            )

        # 10. Malformed Result / Insufficient Evidence / Other
        if ctx.corrective_retries_for_current_executor < self.max_corrective_retries:
            return ContinuationDecisionResult(
                decision=ContinuationDecision.CORRECT_AND_RETRY,
                corrective_prompt="CORRECTIVE GUIDANCE: Execution resulted in malformed or insufficient evidence. Please retry with valid output format.",
            )

        return self._reassign_or_escalate(
            ctx, "Malformed execution results exceeded retry threshold; reassigning."
        )
