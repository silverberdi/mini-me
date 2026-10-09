"""LocalWorkerService: eligibility -> preflight -> bounded dispatch -> validation -> evidence.

Mini me decides success deterministically; the local Qwen model only produces a constrained
candidate result and never approves its own work.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from minime.domain.enums import ProviderResultClass
from minime.domain.models import TaskClassificationSnapshot
from minime.local_worker.capability_router import LocalWorkerCapabilityRouter
from minime.local_worker.context_packager import package_task_context
from minime.local_worker.evidence_authority import LocalRoutingEvidenceAuthority
from minime.local_worker.harness import LocalWorkerHarness
from minime.local_worker.model_identity import (
    LOCAL_WORKER_ROLE,
    OLLAMA_PROVIDER,
    assert_local_qwen_model,
    local_qwen_model_identity,
)
from minime.local_worker.models import (
    DEFAULT_CONTEXT_BUDGET_CHARS,
    LOCAL_WORKER_RESPONSE_SCHEMA,
    EligibilityDecision,
    EligibilityVerdict,
    EscalationDecision,
    EscalationTarget,
    LocalExecutionEvidence,
    LocalResultKind,
    LocalRoutingDecision,
    LocalRoutingVerdict,
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

Validator = Callable[[LocalTaskEnvelope, LocalWorkerResult, int], Awaitable[ValidationResult]]

SYSTEM_PROMPT = (
    "You are the mini me local worker. Implement only the requested change using the "
    "smallest possible patch within the strict allowed files; never redesign architecture. "
    'Reply ONLY with a flat JSON object {"kind":"CHANGES_PROPOSED"|"NO_CHANGE_JUSTIFIED","summary":"...","files_changed":[],'
    '"patch":"<unified diff>"|null,"confidence":0.0,"escalation_required":false,"escalation_reason":"","next_action":"..."}. '
    "Do not use Markdown or code block fences. The patch field must be a unified diff string with escaped newlines, or null if no change. "
    "You do not decide success; mini me does deterministically."
)


class LocalWorkerService:
    """Bounded LOW-risk local worker orchestration with injected transport."""

    def __init__(
        self,
        *,
        model: str | None = None,
        adapter: LocalOllamaAdapter | None = None,
        max_corrective_attempts: int = 1,
        capability_router: LocalWorkerCapabilityRouter | None = None,
    ) -> None:
        self.model = model or local_qwen_model_identity()
        assert_local_qwen_model(self.model)
        self.adapter = adapter or LocalOllamaAdapter(model=self.model)
        adapter_model = getattr(self.adapter, "model", None)
        if adapter_model is not None and isinstance(adapter_model, str):
            if adapter_model != self.model:
                raise ValueError(
                    f"LocalWorkerService model mismatch: service model '{self.model}' "
                    f"does not match adapter model '{adapter_model}'"
                )
            assert_local_qwen_model(adapter_model)

        self.harness = LocalWorkerHarness(
            model=self.model, max_corrective_attempts=max_corrective_attempts
        )
        self.capability_router = capability_router or LocalWorkerCapabilityRouter()

    async def run(
        self,
        task: LocalTaskEnvelope,
        *,
        validator: Validator,
        client: httpx.AsyncClient | None = None,
        preflight: PreflightResult | None = None,
        worktree_path: Any | None = None,
        uow: Any | None = None,
        project_id: str = "mini-me",
        job_id: str | None = None,
        routing_source: Any | None = None,
        classification_snapshot: TaskClassificationSnapshot | None = None,
    ):
        """Source-backed evidence authority -> capability routing gate -> preflight -> bounded dispatch -> validation -> evidence."""
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(routing_source)
        effective_adapter_model = getattr(self.adapter, "model", None)
        if not isinstance(effective_adapter_model, str):
            effective_adapter_model = None

        if not auth_res.success:
            task_cls_str = (
                task.task_class.value
                if hasattr(task.task_class, "value")
                else str(task.task_class)
            )
            refusal_decision = LocalRoutingDecision(
                verdict=LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY,
                reason_code=auth_res.reason_code,
                reason_summary=auth_res.reason,
                classification_snapshot_id=classification_snapshot.id
                if classification_snapshot
                else None,
                task_class=task_cls_str,
                complexity=classification_snapshot.complexity if classification_snapshot else None,
                classification_stage=classification_snapshot.stage if classification_snapshot else None,
                classification_completeness=classification_snapshot.classification_completeness if classification_snapshot else None,
                surface_kind=classification_snapshot.surface_kind if classification_snapshot else None,
                allowed_files_evidence=list(task.allowed_files or []),
                routing_evidence=None,
                selected_local_model=None,
                escalation_target=EscalationTarget.EXISTING_PROVIDER_POLICY,
                policy_version="1.0.0",
            )
            return _routing_refusal(refusal_decision, effective_adapter_model or self.model)

        routing_decision = self.capability_router.evaluate_capability_routing(
            task=task,
            snapshot=classification_snapshot,
            evidence=auth_res.evidence,
            effective_model_identity=effective_adapter_model,
            worktree_path=worktree_path,
        )
        if routing_decision.verdict is not LocalRoutingVerdict.LOCAL_ELIGIBLE:
            return _routing_refusal(routing_decision, effective_adapter_model or self.model)

        eligibility = evaluate_eligibility(
            task_class=task.task_class.value,
            instruction=task.instruction,
            allowed_files=task.allowed_files,
            forbidden_files=task.forbidden_files,
        )
        if not eligibility.admitted:
            return _refusal(eligibility, routing_decision=routing_decision)

        preflight = preflight or await self.adapter.preflight(client=client)
        if preflight.status is not PreflightStatus.READY:
            return ServiceOutcome(
                eligibility,
                preflight,
                _preflight_failed_evidence(preflight),
                routing_decision=routing_decision,
            )

        effective_task = task
        if worktree_path:
            pkg_res = package_task_context(
                instruction=task.instruction,
                task_class=task.task_class,
                allowed_files=task.allowed_files,
                worktree_path=worktree_path,
                max_budget_chars=DEFAULT_CONTEXT_BUDGET_CHARS,
            )
            if pkg_res.success and pkg_res.context:
                effective_task = task.model_copy(update={"context": pkg_res.context})
            elif task.context and len(task.context) <= DEFAULT_CONTEXT_BUDGET_CHARS:
                effective_task = task
            else:
                # FAIL CLOSED: Do NOT call adapter.generate(); escalate with CONTEXT_NOT_READY evidence
                return ServiceOutcome(
                    eligibility,
                    preflight,
                    _context_not_ready_evidence(task, pkg_res.status, self.model),
                    routing_decision=routing_decision,
                )
        elif task.context and len(task.context) > DEFAULT_CONTEXT_BUDGET_CHARS:
            # FAIL CLOSED: Oversized caller context exceeds canonical hard budget
            return ServiceOutcome(
                eligibility,
                preflight,
                _context_not_ready_evidence(task, "CALLER_CONTEXT_EXCEEDS_BUDGET", self.model),
                routing_decision=routing_decision,
            )

        async def bounded_dispatch(
            envelope: LocalTaskEnvelope, attempt: int, corrective_reason: str | None = None
        ) -> str:
            body = (
                envelope.instruction
                + "\nAllowed: "
                + ", ".join(envelope.allowed_files)
                + "\nForbidden: "
                + ", ".join(envelope.forbidden_files)
                + "\nContext:\n"
                + envelope.context
            )
            if attempt > 1 and corrective_reason:
                body += f"\n\nIMPORTANT CORRECTIVE INSTRUCTION:\n{corrective_reason}"
            elif attempt > 1:
                body += (
                    "\n\nIMPORTANT CORRECTIVE INSTRUCTION:\n"
                    "Your previous response did not satisfy the required structured output contract.\n"
                    "Return only an object matching the supplied schema.\n"
                    "Do not use Markdown or code fences.\n"
                    "The patch value must be a JSON string containing the unified diff with escaped newlines."
                )

            response = await self.adapter.generate(
                system_prompt=SYSTEM_PROMPT,
                prompt=f"{LOCAL_WORKER_ROLE}\n{body}",
                client=client,
                response_format=LOCAL_WORKER_RESPONSE_SCHEMA,
            )
            if response.result_class is not ProviderResultClass.SUCCESS:
                return ""
            return response.text

        self.harness._dispatch = bounded_dispatch
        self.harness._cleanup = None
        try:
            evidence = await self.harness.run(
                effective_task,
                validator=validator,
                worktree_path=worktree_path,
                uow=uow,
                project_id=project_id,
                job_id=job_id,
            )
        except Exception:  # noqa: BLE001 - escalate, never crash the caller
            logger.exception("Local worker execution failed unexpectedly")
            evidence = _unexpected_failure_evidence(eligibility.task_class)
        return ServiceOutcome(
            eligibility,
            preflight,
            evidence,
            routing_decision=routing_decision,
        )


class ServiceOutcome:
    """Structured eligibility + preflight + evidence + routing decision for one local run."""

    def __init__(
        self,
        eligibility,
        preflight,
        evidence,
        routing_decision: LocalRoutingDecision | None = None,
    ) -> None:
        self.eligibility = eligibility
        self.preflight = preflight
        self.evidence = evidence
        self.routing_decision = routing_decision


def _escalate(reason: str) -> EscalationDecision:
    """Clean escalation decision always routed to the existing provider policy."""
    return EscalationDecision(
        required=True, target=EscalationTarget.EXISTING_PROVIDER_POLICY, reason=reason
    )


def _routing_refusal(decision: LocalRoutingDecision, model: str) -> ServiceOutcome:
    """Deterministic refusal outcome produced when capability routing or authority verification fails."""
    eligibility = EligibilityDecision(
        verdict=EligibilityVerdict.REFUSE,
        task_class=decision.task_class,
        model=model,
        reason=decision.reason_summary,
        escalation_target=decision.escalation_target,
    )
    preflight = PreflightResult(
        provider=OLLAMA_PROVIDER,
        model=model,
        status=PreflightStatus.NOT_QUALIFIED,
        reason=decision.reason_summary,
        reachable=False,
        model_present=False,
    )
    evidence = LocalExecutionEvidence(
        provider=OLLAMA_PROVIDER,
        model=model,
        task_class=decision.task_class,
        attempt=0,
        result=LocalResultKind.UNCERTAIN,
        result_class="REFUSED",
        validation_result=LocalValidationVerdict.NOT_APPLICABLE,
        escalation=_escalate(decision.reason_summary),
        summary=decision.reason_summary,
    )
    return ServiceOutcome(eligibility, preflight, evidence, routing_decision=decision)


def _refusal(eligibility, routing_decision: LocalRoutingDecision | None = None) -> ServiceOutcome:
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
    return ServiceOutcome(eligibility, preflight, evidence, routing_decision=routing_decision)


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


def _context_not_ready_evidence(
    task: LocalTaskEnvelope,
    status: str,
    model: str,
) -> LocalExecutionEvidence:
    task_cls_str = task.task_class.value if hasattr(task.task_class, "value") else str(task.task_class)
    return LocalExecutionEvidence(
        provider=OLLAMA_PROVIDER,
        model=model,
        task_class=task_cls_str,
        attempt=0,
        result=LocalResultKind.UNCERTAIN,
        result_class="CONTEXT_NOT_READY",
        validation_result=LocalValidationVerdict.NOT_APPLICABLE,
        escalation=_escalate(f"Context packaging for local worker failed: {status}"),
        summary=f"Context packaging failed: {status}",
        model_output_failure_reason=f"Context packaging status: {status}",
    )
