"""Bounded local worker harness: timeout/cancel/cleanup + at most one corrective attempt.

Every attempt runs under an asyncio deadline; a missed deadline cancels in-flight work and
invokes ``cleanup``. Deterministic validation (mini me, never the model) decides success.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable

from minime.local_worker.model_identity import local_qwen_model_identity
from minime.local_worker.models import (
    EscalationDecision,
    EscalationTarget,
    LocalExecutionEvidence,
    LocalResultKind,
    LocalTaskEnvelope,
    LocalValidationVerdict,
    LocalWorkerResult,
    ValidationResult,
)

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

# Dispatch returns the model's raw bounded text answer for a given attempt number.
Dispatch = Callable[[LocalTaskEnvelope, int], Awaitable[str]]
# Deterministic validation authority.
Validator = Callable[[LocalTaskEnvelope, LocalWorkerResult, int], Awaitable[ValidationResult]]
Cleanup = Callable[[int], Awaitable[None] | None]


def _first_json(text: str) -> str:
    text = (_FENCE.search(text) or [None, text])[1]
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text


def parse_structured_result(raw: str) -> LocalWorkerResult:
    """Parse constrained bounded JSON into a structured result."""
    payload_raw = _first_json(raw)
    try:
        payload = json.loads(payload_raw)
    except ValueError as exc:
        raise ValueError(f"Model output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Model output is not a JSON object")

    kind_val = str(payload.get("kind", "")).upper()
    if kind_val == "NO_CHANGE_JUSTIFIED":
        kind = LocalResultKind.NO_CHANGE_JUSTIFIED
    elif kind_val in {"CHANGES_PROPOSED", ""}:
        kind = LocalResultKind.CHANGES_PROPOSED
    else:
        kind = LocalResultKind.UNCERTAIN
    try:
        confidence = float(payload.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return LocalWorkerResult(
        kind=kind,
        summary=str(payload.get("summary", "")),
        files_changed=[str(item) for item in payload.get("files_changed", [])],
        confidence=confidence,
        escalation_required=bool(payload.get("escalation_required", False)),
        escalation_reason=str(payload.get("escalation_reason", "")),
        next_action=str(payload.get("next_action", "")),
    )


class LocalWorkerHarness:
    """Deterministic-boundedness harness: deadline per attempt, one corrective, no self-ok."""

    def __init__(
        self,
        *,
        model: str | None = None,
        dispatch: Dispatch | None = None,
        cleanup: Cleanup | None = None,
        max_corrective_attempts: int = 1,
    ) -> None:
        self.model = model or local_qwen_model_identity()
        self._dispatch = dispatch
        self._cleanup = cleanup
        # Spec: exactly one corrective attempt after a failed initial one.
        self.max_corrective_attempts = max(0, int(max_corrective_attempts))
        self.timeout_cleanup_calls = 0

    async def run(self, task: LocalTaskEnvelope, *, validator: Validator) -> LocalExecutionEvidence:
        """Run under the deadline, cancelling and cleaning up (never unbounded)."""
        dispatch = self._dispatch
        if dispatch is None:
            raise ValueError("No dispatch callable configured")
        cleanup = self._cleanup
        corrections = 0
        validated = False
        last: LocalWorkerResult | None = None
        last_validation = ValidationResult(
            verdict=LocalValidationVerdict.NOT_APPLICABLE, reason="no result"
        )
        outcome_class = "NO_RESULT"
        outcome_kind = LocalResultKind.UNCERTAIN
        escalation: EscalationDecision | None = None
        attempt = 1

        while True:
            raw = await self._bounded(task, attempt, dispatch, cleanup)
            if raw is None:
                outcome_class = "TIMEOUT"
                last = None
                last_validation = ValidationResult(
                    verdict=LocalValidationVerdict.FAIL,
                    reason="Bounded execution deadline exceeded and in-flight work was cancelled",
                )
                escalation = escalation or EscalationDecision(
                    required=True,
                    target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                    reason="Local worker timed out; escalate to existing provider policy",
                )
                break

            try:
                result = parse_structured_result(raw)
            except ValueError as exc:
                if corrections >= self.max_corrective_attempts:
                    outcome_class = "MALFORMED_OUTPUT"
                    last = None
                    last_validation = ValidationResult(
                        verdict=LocalValidationVerdict.FAIL,
                        reason=f"Malformed structured output; corrective budget exhausted: {exc}",
                    )
                    escalation = escalation or EscalationDecision(
                        required=True,
                        target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                        reason="Local worker produced malformed structured output; escalate",
                    )
                    break
                corrections += 1
                attempt += 1
                continue

            last = result
            last_validation = await validator(task, result, attempt)
            if last_validation.passed:
                validated = True
                outcome_kind = result.kind
                outcome_class = "SUCCESS"
                break

            if corrections >= self.max_corrective_attempts:
                outcome_kind = result.kind
                outcome_class = "VALIDATION_FAILED"
                escalation = escalation or EscalationDecision(
                    required=True,
                    target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                    reason="Deterministic validation failed after the single corrective budget; escalate",
                )
                break

            # Next loop iteration is the single corrective attempt (max allowed).
            corrections += 1
            attempt += 1

        # Resolve the escalation decision from observed outcome.
        if last is not None and escalation is None:
            if validated and last.escalation_required:
                escalation = EscalationDecision(
                    required=True,
                    target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                    reason=last.escalation_reason
                    or "Structured result requested escalation to existing provider policy",
                )
            else:
                escalation = EscalationDecision(
                    required=False, target=EscalationTarget.NONE
                )
        else:
            escalation = escalation or EscalationDecision(
                required=False, target=EscalationTarget.NONE
            )

        return LocalExecutionEvidence(
            provider="ollama",
            model=self.model,
            task_class=task.task_class.value,
            attempt=max(attempt, 1),
            result=outcome_kind,
            result_class=outcome_class,
            validation_result=last_validation.verdict,
            escalation=escalation,
            summary=(last.summary if last else ""),
            corrections_used=corrections,
        )

    async def _bounded(
        self,
        task: LocalTaskEnvelope,
        attempt: int,
        dispatch: Dispatch,
        cleanup: Cleanup | None,
    ) -> str | None:
        """Dispatch under task.timeout_seconds, cancelling and cleaning up on timeout."""
        try:
            return await asyncio.wait_for(dispatch(task, attempt), timeout=task.timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning("Local worker dispatch attempt %s exceeded its deadline", attempt)
            if cleanup is not None:
                try:
                    await cleanup(attempt)
                except Exception:  # noqa: BLE001 - cleanup never masks the timeout signal
                    logger.exception("Local worker timeout cleanup failed on attempt %s", attempt)
            self.timeout_cleanup_calls += 1
            return None

