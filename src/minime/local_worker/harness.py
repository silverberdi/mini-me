"""Bounded local worker harness: timeout/cancel/cleanup + at most one corrective attempt.

Every attempt runs under an asyncio deadline; a missed deadline cancels in-flight work and
invokes ``cleanup``. Deterministic validation (mini me, never the model) decides success.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

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
from minime.local_worker.patch_applier import (
    LocalPatchApplier,
    validate_patch_policy,
)
from minime.logging import redact_secrets

logger = logging.getLogger(__name__)

REQUIRED_MODEL_FIELDS = {
    "kind",
    "summary",
    "files_changed",
    "patch",
    "confidence",
    "escalation_required",
    "escalation_reason",
    "next_action",
}

# Dispatch returns the model's raw bounded text answer for a given attempt number and optional corrective reason.
Dispatch = Callable[[LocalTaskEnvelope, int, str | None], Awaitable[str]]
# Deterministic validation authority.
Validator = Callable[[LocalTaskEnvelope, LocalWorkerResult, int], Awaitable[ValidationResult]]
Cleanup = Callable[[int], Awaitable[None] | None]


def parse_structured_result(raw: str) -> LocalWorkerResult:
    """Strictly parse constrained bounded JSON into a structured result."""
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"Model output is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Model output is not a JSON object")

    keys = set(payload.keys())
    missing = REQUIRED_MODEL_FIELDS - keys
    if missing:
        raise ValueError(f"Model output missing required fields: {sorted(missing)}")
    extra = keys - REQUIRED_MODEL_FIELDS
    if extra:
        raise ValueError(f"Model output contains unexpected additional properties: {sorted(extra)}")

    kind_val = payload["kind"]
    if not isinstance(kind_val, str) or kind_val not in ("CHANGES_PROPOSED", "NO_CHANGE_JUSTIFIED"):
        raise ValueError(
            f"Model output kind '{kind_val}' is invalid; must be CHANGES_PROPOSED or NO_CHANGE_JUSTIFIED"
        )

    summary_val = payload["summary"]
    if not isinstance(summary_val, str):
        raise ValueError("Model output field 'summary' must be a string")

    fc_val = payload["files_changed"]
    if not isinstance(fc_val, list) or not all(isinstance(x, str) for x in fc_val):
        raise ValueError("Model output field 'files_changed' must be an array of strings")

    patch_val = payload["patch"]
    if patch_val is not None and not isinstance(patch_val, str):
        raise ValueError("Model output field 'patch' must be a string or null")

    conf_val = payload["confidence"]
    if isinstance(conf_val, bool) or not isinstance(conf_val, (int, float)):
        raise ValueError("Model output field 'confidence' must be a number between 0.0 and 1.0")
    conf_float = float(conf_val)
    if not (0.0 <= conf_float <= 1.0):
        raise ValueError(f"Model output field 'confidence' {conf_float} out of bounds [0.0, 1.0]")

    esc_req = payload["escalation_required"]
    if not isinstance(esc_req, bool):
        raise ValueError("Model output field 'escalation_required' must be a boolean")

    esc_reason = payload["escalation_reason"]
    if not isinstance(esc_reason, str):
        raise ValueError("Model output field 'escalation_reason' must be a string")

    next_action = payload["next_action"]
    if not isinstance(next_action, str):
        raise ValueError("Model output field 'next_action' must be a string")

    kind = (
        LocalResultKind.CHANGES_PROPOSED
        if kind_val == "CHANGES_PROPOSED"
        else LocalResultKind.NO_CHANGE_JUSTIFIED
    )

    return LocalWorkerResult(
        kind=kind,
        summary=summary_val,
        files_changed=fc_val,
        patch=patch_val,
        confidence=conf_float,
        escalation_required=esc_req,
        escalation_reason=esc_reason,
        next_action=next_action,
    )


FORMAT_FAILURE_SUBSTRINGS = (
    "no valid touched files",
    "malformed patch",
    "requires a non-empty patch",
    "missing or empty",
)


def format_patch_policy_corrective_reason(reason: str) -> str:
    """Format sanitized corrective instruction for patch policy failures."""
    sanitized = redact_secrets(reason)
    r_lower = sanitized.lower()

    if any(sub in r_lower for sub in FORMAT_FAILURE_SUBSTRINGS):
        return (
            f"Previous patch failed policy validation: {sanitized}\n"
            "When kind is CHANGES_PROPOSED, the patch field must be a valid unified diff string containing:\n"
            "--- a/<allowed-relative-path>\n"
            "+++ b/<allowed-relative-path>\n"
            "@@ ... @@\n"
            "and actual changed lines."
        )

    return (
        f"Previous patch failed policy validation: {sanitized}\n"
        "Return a valid patch touching only authorized files."
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
        patch_applier: LocalPatchApplier | None = None,
    ) -> None:
        self.model = model or local_qwen_model_identity()
        self._dispatch = dispatch
        self._cleanup = cleanup
        # Spec: exactly one corrective attempt after a failed initial one.
        self.max_corrective_attempts = max(0, int(max_corrective_attempts))
        self.timeout_cleanup_calls = 0
        self.patch_applier = patch_applier

    async def run(
        self,
        task: LocalTaskEnvelope,
        *,
        validator: Validator,
        worktree_path: str | Path | None = None,
        uow: Any | None = None,
        project_id: str = "mini-me",
        job_id: str | None = None,
    ) -> LocalExecutionEvidence:
        """Run under the deadline, cancelling and cleaning up (never unbounded)."""
        dispatch = self._dispatch
        if dispatch is None:
            raise ValueError("No dispatch callable configured")
        cleanup = self._cleanup
        patch_applier = self.patch_applier or (LocalPatchApplier(uow=uow) if uow else None)

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
        corrective_reason: str | None = None

        patch_proposed = False
        patch_applied = False
        authoritative_changed: tuple[str, ...] = ()
        last_raw_excerpt: str | None = None
        last_failure_reason: str | None = None
        last_raw_length: int | None = None

        while True:
            raw = await self._bounded(task, attempt, corrective_reason, dispatch, cleanup)
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
                sanitized_raw = redact_secrets(raw) if raw else ""
                last_raw_excerpt = sanitized_raw[:300]
                last_failure_reason = redact_secrets(str(exc))
                last_raw_length = len(raw) if raw else 0
                logger.warning(
                    "Local worker malformed structured output (attempt %d, length=%d): %s | Excerpt: %r",
                    attempt,
                    last_raw_length,
                    last_failure_reason,
                    last_raw_excerpt[:200],
                )
                if corrections >= self.max_corrective_attempts:
                    outcome_class = "MALFORMED_OUTPUT"
                    last = None
                    last_validation = ValidationResult(
                        verdict=LocalValidationVerdict.FAIL,
                        reason=f"Malformed structured output; corrective budget exhausted: {last_failure_reason}",
                    )
                    escalation = escalation or EscalationDecision(
                        required=True,
                        target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                        reason="Local worker produced malformed structured output; escalate",
                    )
                    break
                corrections += 1
                attempt += 1
                corrective_reason = (
                    "Previous response did not satisfy the required structured response contract."
                )
                continue

            last = result
            patch_proposed = bool(result.patch and result.patch.strip())

            # 1. Patch Policy Validation
            policy_decision = validate_patch_policy(result.patch, task, kind=result.kind)
            if not policy_decision.valid:
                last_failure_reason = f"Patch policy validation failed: {policy_decision.reason}"
                if corrections < self.max_corrective_attempts:
                    corrections += 1
                    attempt += 1
                    corrective_reason = format_patch_policy_corrective_reason(
                        policy_decision.reason
                    )
                    continue
                outcome_kind = result.kind
                outcome_class = "PATCH_POLICY_FAILED"
                last_validation = ValidationResult(
                    verdict=LocalValidationVerdict.FAIL,
                    reason=f"Patch policy validation failed: {policy_decision.reason}",
                )
                escalation = EscalationDecision(
                    required=True,
                    target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                    reason=f"Patch policy failed: {policy_decision.reason}",
                )
                break

            # 2. Patch Application (if CHANGES_PROPOSED)
            patch_applied = False
            authoritative_changed = ()

            if result.kind is LocalResultKind.CHANGES_PROPOSED:
                if (
                    not worktree_path
                    or not uow
                    or not project_id
                    or not str(project_id).strip()
                    or not job_id
                    or not str(job_id).strip()
                    or not patch_applier
                ):
                    outcome_kind = result.kind
                    outcome_class = "PATCH_APPLY_FAILED"
                    last_validation = ValidationResult(
                        verdict=LocalValidationVerdict.FAIL,
                        reason="CHANGES_PROPOSED requires worktree_path, uow, project_id, and job_id",
                    )
                    escalation = EscalationDecision(
                        required=True,
                        target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                        reason="Execution context (worktree_path, uow, project_id, job_id) missing for CHANGES_PROPOSED",
                    )
                    break

                app_res = patch_applier.apply_patch(
                    worktree_path=worktree_path,
                    envelope=task,
                    patch=result.patch or "",
                    project_id=project_id,
                    job_id=job_id,
                )
                patch_applied = app_res.applied
                authoritative_changed = app_res.authoritative_changed_files

                if not app_res.success:
                    last_failure_reason = f"Patch application failed: {app_res.error}"
                    if app_res.applied:
                        # Filesystem mutated: NO retry allowed!
                        outcome_kind = result.kind
                        outcome_class = "PATCH_APPLY_FAILED"
                        last_validation = ValidationResult(
                            verdict=LocalValidationVerdict.FAIL,
                            reason=f"Patch application failed post-apply: {app_res.error}",
                        )
                        escalation = EscalationDecision(
                            required=True,
                            target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                            reason=f"Patch application failed post-apply: {app_res.error}",
                        )
                        break

                    if corrections < self.max_corrective_attempts:
                        corrections += 1
                        attempt += 1
                        corrective_reason = (
                            "Previous patch could not be applied before any filesystem mutation. "
                            "Return a valid unified diff against the supplied context."
                        )
                        continue

                    outcome_kind = result.kind
                    outcome_class = "PATCH_APPLY_FAILED"
                    last_validation = ValidationResult(
                        verdict=LocalValidationVerdict.FAIL,
                        reason=f"Patch application failed: {app_res.error}",
                    )
                    escalation = EscalationDecision(
                        required=True,
                        target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                        reason=f"Patch application failed: {app_res.error}",
                    )
                    break

            # 3. Deterministic Validation Authority Callback
            last_validation = await validator(task, result, attempt)
            if last_validation.passed:
                if result.kind is LocalResultKind.CHANGES_PROPOSED and not patch_applied:
                    outcome_kind = result.kind
                    outcome_class = "PATCH_APPLY_FAILED"
                    last_validation = ValidationResult(
                        verdict=LocalValidationVerdict.FAIL,
                        reason="CHANGES_PROPOSED result cannot be marked SUCCESS without patch application",
                    )
                    escalation = EscalationDecision(
                        required=True,
                        target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                        reason="CHANGES_PROPOSED result cannot be marked SUCCESS without patch application",
                    )
                    break

                validated = True
                outcome_kind = result.kind
                outcome_class = "SUCCESS"
                break

            # Validation failed.
            if patch_applied:
                # A patch was applied to disk and validation failed.
                # Stop local correction on dirty worktree, preserve evidence, escalate.
                outcome_kind = result.kind
                outcome_class = "VALIDATION_FAILED"
                escalation = EscalationDecision(
                    required=True,
                    target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                    reason=f"Deterministic validation failed after patch application: {last_validation.reason}",
                )
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

            corrections += 1
            attempt += 1

        # Resolve escalation decision from observed outcome
        if last is not None and escalation is None:
            if validated and last.escalation_required:
                escalation = EscalationDecision(
                    required=True,
                    target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                    reason=last.escalation_reason
                    or "Structured result requested escalation to existing provider policy",
                )
            else:
                escalation = EscalationDecision(required=False, target=EscalationTarget.NONE)
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
            patch_proposed=patch_proposed,
            patch_applied=patch_applied,
            authoritative_changed_files=list(authoritative_changed),
            worktree_path=str(worktree_path) if worktree_path else None,
            raw_output_excerpt=last_raw_excerpt,
            model_output_failure_reason=last_failure_reason,
            raw_output_length=last_raw_length,
        )

    async def _bounded(
        self,
        task: LocalTaskEnvelope,
        attempt: int,
        corrective_reason: str | None,
        dispatch: Dispatch,
        cleanup: Cleanup | None,
    ) -> str | None:
        """Dispatch under task.timeout_seconds, cancelling and cleaning up on timeout."""
        accepts_corrective_reason = False
        try:
            sig = inspect.signature(dispatch)
            params = list(sig.parameters.values())
            accepts_corrective_reason = len(params) >= 3 or any(
                p.kind == inspect.Parameter.VAR_POSITIONAL for p in params
            )
        except Exception:  # noqa: BLE001
            accepts_corrective_reason = False

        try:
            if accepts_corrective_reason:
                coro = dispatch(task, attempt, corrective_reason)
            else:
                coro = dispatch(task, attempt)
            return await asyncio.wait_for(coro, timeout=task.timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning("Local worker dispatch attempt %s exceeded its deadline", attempt)
            if cleanup is not None:
                try:
                    await cleanup(attempt)
                except Exception:  # noqa: BLE001 - cleanup never masks the timeout signal
                    logger.exception("Local worker timeout cleanup failed on attempt %s", attempt)
            self.timeout_cleanup_calls += 1
            return None
