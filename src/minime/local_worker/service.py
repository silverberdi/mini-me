"""LocalWorkerService: eligibility -> preflight -> bounded dispatch -> validation -> evidence.

Mini me decides success deterministically; the local Qwen model only produces a constrained
candidate result and never approves its own work.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import httpx

from minime.domain.enums import ProviderResultClass
from minime.local_worker.harness import LocalWorkerHarness
from minime.local_worker.model_identity import (
    LOCAL_WORKER_ROLE,
    OLLAMA_PROVIDER,
    assert_local_qwen_model,
    local_qwen_model_identity,
)
from minime.local_worker.models import (
    EscalationDecision,
    EscalationTarget,
    LocalExecutionEvidence,
    LocalResultKind,
    LocalTaskEnvelope,
    LocalValidationVerdict,
    LocalWorkerResult,
    PreflightResult,
    PreflightStatus,
    ValidationResult,
)
from minime.local_worker.ollama_adapter import LocalOllamaAdapter
from minime.local_worker.policy import evaluate_eligibility

logger = logging.getLogger(__name__)

Validator = Callable[
    [LocalTaskEnvelope, LocalWorkerResult, int], Awaitable[ValidationResult]
]

SYSTEM_PROMPT = (
    "You are the mini me local worker. Take only the smallest possible patch within the "
    "strict allowed files; never redesign architecture. Reply ONLY with a flat JSON object "
    '{"kind":"CHANGES_PROPOSED"|"NO_CHANGE_JUSTIFIED","summary":"...","files_changed":[],'
    '"confidence":0.0,"escalation_required":false,"escalation_reason":"",'
    '"next_action":"..."}. You do not decide success; mini me does, deterministically.'
)


class LocalWorkerService:
    """Bounded LOW-risk local worker orchestration with injected transport."""

    def __init__(
        self,
        *,
        model: str | None = None,
        adapter: LocalOllamaAdapter | None = None,
        max_corrective_attempts: int = 1,
    ) -> None:
        self.model = model or local_qwen_model_identity()
        assert_local_qwen_model(self.model)
        self.adapter = adapter or LocalOllamaAdapter(model=self.model)
        self.harness = LocalWorkerHarness(
            model=self.model, max_corrective_attempts=max_corrective_attempts
        )

    async def run(
        self,
        task: LocalTaskEnvelope,
        *,
        validator: Validator,
        client: httpx.AsyncClient | None = None,
        preflight: PreflightResult | None = None,
    ):
        """Eligibility gate -> preflight -> bounded dispatch -> validation -> evidence."""
        eligibility = evaluate_eligibility(
            task_class=task.task_class.value,
            instruction=task.instruction,
            allowed_files=task.allowed_files,
            forbidden_files=task.forbidden_files,
        )
        if not eligibility.admitted:
            return _refusal(eligibility)

        preflight = preflight or await self.adapter.preflight(client=client)
        if preflight.status is not PreflightStatus.READY:
            return ServiceOutcome(eligibility, preflight, _preflight_failed_evidence(preflight))

        async def bounded_dispatch(envelope: LocalTaskEnvelope, attempt: int) -> str:
            body = (
                envelope.instruction
                + "\nAllowed: "
                + ", ".join(envelope.allowed_files)
                + "\nForbidden: "
                + ", ".join(envelope.forbidden_files)
                + "\nContext:\n"
                + envelope.context
            )
            response = await self.adapter.generate(
                system_prompt=SYSTEM_PROMPT,
                prompt=f"{LOCAL_WORKER_ROLE}\n{body}",
                client=client,
            )
            if response.result_class is not ProviderResultClass.SUCCESS:
                return ""
            return response.text

        self.harness._dispatch = bounded_dispatch
        self.harness._cleanup = None
        try:
            evidence = await self.harness.run(task, validator=validator)
        except Exception:  # noqa: BLE001 - escalate, never crash the caller
            logger.exception("Local worker execution failed unexpectedly")
            evidence = _unexpected_failure_evidence(eligibility.task_class)
        return ServiceOutcome(eligibility, preflight, evidence)


class ServiceOutcome:
    """Structured eligibility + preflight + evidence for one local run."""

    def __init__(self, eligibility, preflight, evidence) -> None:
        self.eligibility = eligibility
        self.preflight = preflight
        self.evidence = evidence


def _escalate(reason: str) -> EscalationDecision:
    """Clean escalation decision always routed to the existing provider policy."""
    return EscalationDecision(
        required=True, target=EscalationTarget.EXISTING_PROVIDER_POLICY, reason=reason
    )


def _refusal(eligibility) -> ServiceOutcome:
    """Deterministic refusal outcome: never execute forbidden/uncertain local work."""
    from minime.local_worker.models import PreflightResult

    preflight = PreflightResult(
        provider=OLLAMA_PROVIDER,
        model=eligibility.model,
        status=PreflightStatus.NOT_QUALIFIED,
        reason=eligibility.reason,
        reachable=False,
        model_present=False,
    )
    evidence = LocalExecutionEvidence(
        provider=OLLAMA_PROVIDER,
        model=eligibility.model,
        task_class=eligibility.task_class,
        attempt=0,
        result=LocalResultKind.UNCERTAIN,
        result_class="REFUSED",
        validation_result=LocalValidationVerdict.NOT_APPLICABLE,
        escalation=_escalate(eligibility.reason),
        summary=eligibility.reason,
    )
    return ServiceOutcome(eligibility, preflight, evidence)


def _preflight_failed_evidence(preflight: PreflightResult) -> LocalExecutionEvidence:
    return LocalExecutionEvidence(
        provider=preflight.provider,
        model=preflight.model,
        task_class="NOT_STARTED",
        attempt=0,
        result=LocalResultKind.UNCERTAIN,
        result_class="PREFLIGHT_FAILED",
        validation_result=LocalValidationVerdict.NOT_APPLICABLE,
        escalation=_escalate(preflight.reason or "Preflight for local worker not ready"),
        summary=preflight.reason,
    )


def _unexpected_failure_evidence(task_class: str) -> LocalExecutionEvidence:
    return LocalExecutionEvidence(
        provider=OLLAMA_PROVIDER,
        model=local_qwen_model_identity(),
        task_class=task_class,
        attempt=1,
        result=LocalResultKind.UNCERTAIN,
        result_class="UNEXPECTED_FAILURE",
        validation_result=LocalValidationVerdict.FAIL,
        escalation=_escalate("Unexpected local worker failure; escalate"),
    )

