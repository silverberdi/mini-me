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

        # 5. Provider Failure (unrecoverable provider error / auth error)
        if outcome == ExecutionOutcome.PROVIDER_FAILURE:
            if ctx.reassignment_count < self.max_reassignments:
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.REASSIGN_AGENT,
                    should_handoff=True,
                    escalation_reason="Provider failure occurred; reassigning to alternative executor.",
                )
            return ContinuationDecisionResult(
                decision=ContinuationDecision.NEEDS_HUMAN,
                escalation_reason=f"Provider failures exceeded maximum reassignment limit ({self.max_reassignments}).",
            )

        # 6. False Blocker
        if outcome == ExecutionOutcome.FALSE_BLOCKER:
            # Check false blocker streak
            if ctx.same_blocker_fingerprint_streak >= self.max_same_false_blocker_streak:
                if ctx.reassignment_count < self.max_reassignments:
                    return ContinuationDecisionResult(
                        decision=ContinuationDecision.REASSIGN_AGENT,
                        should_handoff=True,
                        escalation_reason=f"Repeated false blocker streak ({ctx.same_blocker_fingerprint_streak}) reached threshold; reassigning executor.",
                    )
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.NEEDS_HUMAN,
                    escalation_reason=f"Repeated false blocker streak exceeded ceiling ({self.max_same_false_blocker_streak}) and reassignment limit reached.",
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
            if ctx.reassignment_count < self.max_reassignments:
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.REASSIGN_AGENT,
                    should_handoff=True,
                    escalation_reason="Corrective retry limit reached on false blocker; reassigning executor.",
                )

            return ContinuationDecisionResult(
                decision=ContinuationDecision.NEEDS_HUMAN,
                escalation_reason="False blocker persisted after exhausting all corrective retries and reassignments.",
            )

        # 7. Premature Stop
        if outcome == ExecutionOutcome.PREMATURE_STOP:
            if ctx.same_outcome_streak >= self.max_same_outcome_streak:
                if ctx.reassignment_count < self.max_reassignments:
                    return ContinuationDecisionResult(
                        decision=ContinuationDecision.REASSIGN_AGENT,
                        should_handoff=True,
                        escalation_reason=f"Repeated premature stops ({ctx.same_outcome_streak}) reached limit; reassigning executor.",
                    )
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.NEEDS_HUMAN,
                    escalation_reason="Premature stops persisted past all retry and reassignment limits.",
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

            if ctx.reassignment_count < self.max_reassignments:
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.REASSIGN_AGENT,
                    should_handoff=True,
                    escalation_reason="Executor exhausted retries without completing tasks; reassigning.",
                )

            return ContinuationDecisionResult(
                decision=ContinuationDecision.NEEDS_HUMAN,
                escalation_reason="Incomplete tasks remain after exhausting all corrective retries and reassignments.",
            )

        # 8. Changes Required (failing deterministic checks)
        if outcome == ExecutionOutcome.CHANGES_REQUIRED:
            if ctx.same_outcome_streak >= self.max_same_outcome_streak:
                if ctx.reassignment_count < self.max_reassignments:
                    return ContinuationDecisionResult(
                        decision=ContinuationDecision.REASSIGN_AGENT,
                        should_handoff=True,
                        escalation_reason="Persistent failing checks; reassigning executor.",
                    )
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.NEEDS_HUMAN,
                    escalation_reason="Deterministic checks failing persistently after maximum reassignments.",
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

            if ctx.reassignment_count < self.max_reassignments:
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.REASSIGN_AGENT,
                    should_handoff=True,
                    escalation_reason="Corrective retry limit reached for check failures; reassigning executor.",
                )

            return ContinuationDecisionResult(
                decision=ContinuationDecision.NEEDS_HUMAN,
                escalation_reason="Failing checks could not be resolved within allowed attempts.",
            )

        # 9. No Progress
        if outcome == ExecutionOutcome.NO_PROGRESS:
            if (
                ctx.same_outcome_streak >= self.max_same_outcome_streak
                or ctx.corrective_retries_for_current_executor >= self.max_corrective_retries
            ):
                if ctx.reassignment_count < self.max_reassignments:
                    return ContinuationDecisionResult(
                        decision=ContinuationDecision.REASSIGN_AGENT,
                        should_handoff=True,
                        escalation_reason="Executor made zero progress; reassigning executor.",
                    )
                return ContinuationDecisionResult(
                    decision=ContinuationDecision.NEEDS_HUMAN,
                    escalation_reason="No progress made across maximum attempts and reassignments.",
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

        if ctx.reassignment_count < self.max_reassignments:
            return ContinuationDecisionResult(
                decision=ContinuationDecision.REASSIGN_AGENT,
                should_handoff=True,
                escalation_reason="Malformed execution results exceeded retry threshold; reassigning.",
            )

        return ContinuationDecisionResult(
            decision=ContinuationDecision.NEEDS_HUMAN,
            escalation_reason="Execution failed to produce valid verifiable output within limits.",
        )
