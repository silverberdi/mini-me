"""Deterministic local worker policy: LOW-risk eligibility, authority, escalation.

The eligibility gate and authority sets are decided deterministically by mini me, never by
the model. Local Qwen executes only admissible LOW-risk envelopes and never carries
review/audit/merge/approve authority.
"""

from __future__ import annotations

import fnmatch
import logging

from minime.local_worker.model_identity import (
    LOCAL_QWEN_FORBIDDEN_AUTHORITIES,
    OLLAMA_PROVIDER,
    local_qwen_model_identity,
)
from minime.local_worker.models import (
    EligibilityDecision,
    EligibilityVerdict,
    EscalationDecision,
    EscalationTarget,
    LocalTaskClass,
)
from minime.local_worker.task_classes import (
    ForbiddenSurfaceKind,
    offending_forbidden_surface,
)

logger = logging.getLogger(__name__)


def local_worker_authorities(*, model: str | None = None) -> frozenset[str]:
    """Return the authority labels the local Qwen worker is allowed (implement only).

    Reviewer/audit/merge/approve and self-approval labels are always excluded for local Qwen,
    mirroring the canonical rule that the same provider/model never reviews its own work.
    """
    if model is not None and model != local_qwen_model_identity():
        logger.warning("Unknown local model identity requested for authority evaluation")
    return frozenset({"implement"}) - LOCAL_QWEN_FORBIDDEN_AUTHORITIES


def evaluate_eligibility(
    *,
    task_class: str,
    instruction: str,
    allowed_files: list[str] | None = None,
    forbidden_files: list[str] | None = None,
    touched_files: list[str] | None = None,
) -> EligibilityDecision:
    """Evaluate a LOW-risk task for LOCAL execution.

    Admit only when the class is allowlisted and no forbidden surface/file is touched.
    Otherwise refuse with a deterministic reason and an escalation target.
    """
    model = local_qwen_model_identity()
    surface_names = list(forbidden_files or [])
    surface_names.extend(touched_files or [])
    forbidden = offending_forbidden_surface(
        task_description=instruction,
        touched_surfaces=surface_names,
        task_class=task_class,
    )

    if forbidden is not None:
        reason = (
            f"Task class '{task_class}' is not a canonical LOW-risk allowlisted class"
            if not allowed_local(task_class)
            else f"Task touches forbidden surface '{forbidden.value}'"
        )
        return EligibilityDecision(
            verdict=EligibilityVerdict.REFUSE,
            task_class=task_class,
            model=model,
            reason=reason,
            forbidden_surface=forbidden.value,
            escalation_target=EscalationTarget.EXISTING_PROVIDER_POLICY,
        )

    # Even when the surface scan passes, enforce the allowlist via a file allowlist when one
    # is declared: admittance is limited to the allowed_files set.
    if allowed_files is not None and touched_files:
        for touched in touched_files:
            if not _within_allowlist(touched, allowed_files):
                return EligibilityDecision(
                    verdict=EligibilityVerdict.REFUSE,
                    task_class=task_class,
                    model=model,
                    reason=f"Touched file '{touched}' is outside the explicit allowed_files allowlist",
                    escalation_target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                )

    return EligibilityDecision(
        verdict=EligibilityVerdict.ADMIT,
        task_class=task_class,
        model=model,
        reason=f"Task class '{task_class}' admitted for LOW-risk local execution",
    )


def allowed_local(task_class: str) -> bool:
    from minime.local_worker.task_classes import allowed_local_task_class

    return allowed_local_task_class(task_class)


def _within_allowlist(path: str, allowed_files: list[str]) -> bool:
    for pattern in allowed_files:
        if fnmatch.fnmatch(path, pattern):
            return True
    return False


def decision_as_escalation(
    decision: EligibilityDecision | None = None,
    *,
    reason: str = "",
) -> EscalationDecision:
    """Build a clean escalation to the existing provider policy when warranted."""
    required = False
    aggregated = reason
    if decision is not None and decision.verdict is EligibilityVerdict.REFUSE:
        required = True
        aggregated = decision.reason if not aggregated else f"{decision.reason}; {aggregated}"
    if not required and not aggregated:
        return EscalationDecision(required=False, target=EscalationTarget.NONE)
    return EscalationDecision(
        required=required or bool(aggregated),
        target=EscalationTarget.EXISTING_PROVIDER_POLICY,
        reason=aggregated or "Escalation to existing provider policy",
    )


def assert_no_local_authority(*, authority: str) -> None:
    """Raise if ``authority`` is forbidden for local Qwen (e.g. 'review', 'audit', 'merge')."""
    normalized = authority.strip().lower()
    if normalized in LOCAL_QWEN_FORBIDDEN_AUTHORITIES or normalized not in {
        "implement"
    }:
        raise PermissionError(
            f"Local Qwen has no '{authority}' authority. It may only implement. "
            "Use the existing provider policy for reviewer/audit/merge/approve gates."
        )


__all__ = [
    "ForbiddenSurfaceKind",
    "LocalTaskClass",
    "OLLAMA_PROVIDER",
    "assert_no_local_authority",
    "decision_as_escalation",
    "evaluate_eligibility",
    "local_worker_authorities",
]
