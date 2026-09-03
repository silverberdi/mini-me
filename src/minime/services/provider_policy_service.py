"""Multi-factor Provider Policy and Selection Governance Service.

Enforces:
- Mandatory Rule A: Codex is default workhorse; Antigravity is ineligible for routine tasks when Codex is available.
- Mandatory Rule E: Antigravity assignments require verified premium reason codes.
- Mandatory Rule F: Provider exhaustion transitions to DRAIN mode without tight reassign loops.
- Mandatory Rule H: Multi-factor deterministic provider selection with explainability.
"""

from __future__ import annotations

import logging
from typing import Any

from minime.domain.enums import (
    EventType,
    ExecutionOutcome,
    PremiumProviderReasonCode,
    PrimaryProvider,
    ProviderHealthStatus,
    ProviderResultClass,
    SchedulerMode,
    TaskClass,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    JobAttempt,
    Project,
    ProviderHealth,
    ProviderSelectionExplanation,
    utc_now,
)

logger = logging.getLogger(__name__)


class ProviderPolicyService:
    """Canonical provider selection and capacity governance policy engine."""

    def __init__(self, uow: PersistenceUnitOfWork | None = None):
        self.uow = uow

    def evaluate_selection(
        self,
        *,
        task_class: TaskClass,
        role: str = "implementer",
        project: Project | None = None,
        provider_health_records: dict[str, ProviderHealth] | list[ProviderHealth] | None = None,
        attempts: list[JobAttempt] | None = None,
        disqualified_providers: set[str] | list[str] | None = None,
        requested_premium_reason: PremiumProviderReasonCode | None = None,
        scheduler_mode: SchedulerMode = SchedulerMode.RUN,
    ) -> ProviderSelectionExplanation:
        """Deterministically select the optimal provider based on canonical multi-factor policy."""
        disqualified = set(disqualified_providers or [])
        health_map: dict[str, ProviderHealth] = {}
        if isinstance(provider_health_records, dict):
            health_map = provider_health_records
        elif isinstance(provider_health_records, list):
            health_map = {h.provider: h for h in provider_health_records}
        elif self.uow:
            health_map = {h.provider: h for h in self.uow.provider_health.list_all()}

        codex_health = health_map.get(
            PrimaryProvider.CODEX.value,
            ProviderHealth(
                provider=PrimaryProvider.CODEX.value,
                status=ProviderHealthStatus.AVAILABLE,
            ),
        )
        ag_health = health_map.get(
            PrimaryProvider.ANTIGRAVITY.value,
            ProviderHealth(
                provider=PrimaryProvider.ANTIGRAVITY.value,
                status=ProviderHealthStatus.AVAILABLE,
            ),
        )

        codex_available = (
            codex_health.status == ProviderHealthStatus.AVAILABLE
            and PrimaryProvider.CODEX.value not in disqualified
        )
        ag_available = (
            ag_health.status == ProviderHealthStatus.AVAILABLE
            and PrimaryProvider.ANTIGRAVITY.value not in disqualified
        )

        # Factor snapshot
        factors: dict[str, Any] = {
            "task_class": task_class.value,
            "role": role,
            "codex_status": codex_health.status.value,
            "ag_status": ag_health.status.value,
            "disqualified": list(disqualified),
            "scheduler_mode": scheduler_mode.value,
        }

        # -------------------------------------------------------------------------
        # MANDATORY RULE E: Check explicit premium reasons & non-convergence first
        # -------------------------------------------------------------------------
        inferred_reason: PremiumProviderReasonCode | None = requested_premium_reason

        if task_class == TaskClass.ARCHITECTURE:
            inferred_reason = PremiumProviderReasonCode.ARCHITECTURE_REQUIRED
        elif task_class == TaskClass.UX_VISUAL_QA:
            inferred_reason = PremiumProviderReasonCode.UX_VISUAL_QA
        elif task_class == TaskClass.PLATFORM_RECOVERY:
            inferred_reason = PremiumProviderReasonCode.PLATFORM_RECOVERY
        elif self._verify_codex_non_convergence(attempts or []):
            inferred_reason = PremiumProviderReasonCode.CODEX_NON_CONVERGENCE

        # -------------------------------------------------------------------------
        # MANDATORY RULE A: Routine Implementation selects Codex, excludes AG
        # -------------------------------------------------------------------------
        if task_class in {
            TaskClass.ROUTINE_IMPLEMENTATION,
            TaskClass.ORDINARY_REMEDIATION,
            TaskClass.TEST_FIX,
            TaskClass.SPECIALIZED,
        } and not inferred_reason:
            if codex_available:
                return ProviderSelectionExplanation(
                    selected_provider=PrimaryProvider.CODEX.value,
                    role=role,
                    task_class=task_class,
                    is_premium=False,
                    premium_reason_code=None,
                    explanation=(
                        f"Codex selected as canonical primary workhorse for '{task_class.value}'. "
                        f"Antigravity eligibility is FALSE (PREMIUM_PROVIDER_NOT_REQUIRED)."
                    ),
                    factors=factors,
                )

        if ag_available and inferred_reason and inferred_reason != PremiumProviderReasonCode.PREMIUM_PROVIDER_NOT_REQUIRED:
            return ProviderSelectionExplanation(
                selected_provider=PrimaryProvider.ANTIGRAVITY.value,
                role=role,
                task_class=task_class,
                is_premium=True,
                premium_reason_code=inferred_reason,
                explanation=(
                    f"Antigravity selected as premium constrained provider under authorized reason: '{inferred_reason.value}'."
                ),
                factors=factors,
            )

        # If Antigravity was considered for a routine task but had no premium reason
        if not codex_available and not inferred_reason:
            # Reject AG assignment without premium reason
            return ProviderSelectionExplanation(
                selected_provider="none",
                role=role,
                task_class=task_class,
                is_premium=False,
                premium_reason_code=None,
                explanation=(
                    "Codex is unavailable and Antigravity assignment is REJECTED because no verified premium reason code was satisfied."
                ),
                factors=factors,
            )

        # Fallback to Codex if AG is not applicable
        if codex_available:
            return ProviderSelectionExplanation(
                selected_provider=PrimaryProvider.CODEX.value,
                role=role,
                task_class=task_class,
                is_premium=False,
                premium_reason_code=None,
                explanation=f"Codex selected as available primary provider for role '{role}'.",
                factors=factors,
            )

        # Neither primary is available
        return ProviderSelectionExplanation(
            selected_provider="none",
            role=role,
            task_class=task_class,
            is_premium=False,
            premium_reason_code=None,
            explanation="No eligible primary provider is available under current capacity and policy constraints.",
            factors=factors,
        )

    def _verify_codex_non_convergence(self, attempts: list[JobAttempt]) -> bool:
        """Verify that CODEX_NON_CONVERGENCE requirements are satisfied:
        1. Normal Codex attempt occurred.
        2. One corrective retry occurred.
        3. Attempts did not achieve completion.
        """
        if not attempts:
            return False

        codex_attempts = [
            a for a in attempts if a.executor_role == PrimaryProvider.CODEX.value
        ]
        if len(codex_attempts) < 2:
            return False

        # Verify initial attempt and corrective retry
        initial = codex_attempts[0]
        retry = codex_attempts[1]
        if initial.attempt_number >= 1 and retry.attempt_number >= 2:
            # Check that both attempts failed or made partial/no progress
            if all(
                a.normalized_outcome
                in {
                    ExecutionOutcome.CHANGES_REQUIRED,
                    ExecutionOutcome.NO_PROGRESS,
                    ExecutionOutcome.FALSE_BLOCKER,
                    ExecutionOutcome.EVIDENCE_INSUFFICIENT,
                }
                for a in [initial, retry]
            ):
                return True
        return False

    def handle_exhaustion_event(
        self,
        provider: str,
        result_class: ProviderResultClass,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record provider exhaustion and transition provider health to DRAIN / EXHAUSTED."""
        if not self.uow:
            return

        now = utc_now()
        health = self.uow.provider_health.get_by_provider(provider)
        if health:
            health.status = ProviderHealthStatus.EXHAUSTED
            health.last_result_class = result_class
            health.consecutive_failures += 1
            health.updated_at = now
            self.uow.provider_health.save(health)

        event_payload = {
            "provider": provider,
            "result_class": result_class.value,
            "transition_to": "EXHAUSTED",
            "timestamp": now.isoformat(),
            "details": details or {},
        }
        self.uow.events.save(
            Event(
                event_type=EventType.PROVIDER_DRAIN_TRANSITION,
                project_id=details.get("project_id", "system") if details else "system",
                change_id=details.get("change_name") if details else None,
                payload=event_payload,
            )
        )
        self.uow.commit()
