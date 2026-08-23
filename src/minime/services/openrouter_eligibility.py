"""Strict 10-point eligibility evaluator for OpenRouter drain fallback."""

from __future__ import annotations

from dataclasses import dataclass, field

from minime.domain.enums import JobStatus, ProviderHealthStatus, SchedulerMode
from minime.domain.models import Job, OpenRouterBudgetPolicy, Project, ProviderHealth
from minime.services.budget_service import BudgetHeadroom


@dataclass
class OpenRouterEligibilityResult:
    eligible: bool
    denial_reason: str | None = None
    reasons: list[str] = field(default_factory=list)


class OpenRouterEligibilityEvaluator:
    """Evaluates all 10 OpenRouter drain fallback conditions before invocation."""

    def evaluate(self, checks: list[tuple[bool, str]]) -> OpenRouterEligibilityResult:
        """Evaluate a custom list of boolean checks."""
        reasons = [reason for ok, reason in checks if not ok]
        return OpenRouterEligibilityResult(
            eligible=not reasons,
            denial_reason=reasons[0] if reasons else None,
            reasons=reasons,
        )

    def evaluate_10_points(
        self,
        *,
        scheduler_mode: SchedulerMode,
        job: Job,
        role: str,
        is_new_ready_change: bool,
        primary_health_records: list[ProviderHealth],
        project: Project,
        policy: OpenRouterBudgetPolicy | None,
        headroom: BudgetHeadroom | None,
        model_identity_valid: bool = True,
        candidate_integrity_valid: bool = True,
        pipeline_invariants_valid: bool = True,
    ) -> OpenRouterEligibilityResult:
        """Evaluate all 10 canonical OpenRouter fallback eligibility conditions."""
        # 1. Scheduler mode in DRAIN
        check_1 = (scheduler_mode == SchedulerMode.DRAIN, "Scheduler is not in DRAIN mode")

        # 2. Existing in-flight job
        in_flight_statuses = {
            JobStatus.RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.CHECKS_PASSED,
            JobStatus.REVIEW_RUNNING,
            JobStatus.WAITING_CAPACITY,
        }
        check_2 = (
            job.status in in_flight_statuses,
            f"Job '{job.job_id}' is not in an active in-flight status",
        )

        # 3. Blocked on implementer or reviewer stage
        check_3 = (
            role in {"implementer", "reviewer"},
            f"Role '{role}' is not eligible for fallback",
        )

        # 4. No new READY work admitted
        check_4 = (
            not is_new_ready_change,
            "Cannot admit new READY change into OpenRouter fallback",
        )

        # 5. Dual-primary exhaustion verified
        codex_health = next((h for h in primary_health_records if h.provider == "codex"), None)
        agy_health = next((h for h in primary_health_records if h.provider == "antigravity"), None)
        codex_unavail = (
            codex_health is not None and codex_health.status != ProviderHealthStatus.AVAILABLE
        )
        agy_unavail = agy_health is not None and agy_health.status != ProviderHealthStatus.AVAILABLE
        dual_exhausted = codex_unavail and agy_unavail
        check_5 = (
            dual_exhausted,
            "Dual-primary exhaustion is not verified (both Codex and Antigravity must be unavailable)",
        )

        # 6. Fallback explicitly enabled and policy not breached
        enabled = (
            project.openrouter_drain_allowed
            and policy is not None
            and policy.enabled
            and not policy.is_breached
        )
        check_6 = (enabled, "OpenRouter fallback is disabled or policy is breached")

        # 7. Reservable budget available
        budget_avail = (
            policy is not None
            and policy.daily_cap_usd > 0
            and policy.monthly_cap_usd > 0
            and headroom is not None
            and headroom.daily_headroom_usd > 0
            and headroom.monthly_headroom_usd > 0
        )
        check_7 = (budget_avail, "Reservable budget is exhausted or unconfigured")

        # 8. Valid independent model selected
        check_8 = (model_identity_valid, "Valid distinct canonical model identity is unavailable")

        # 9. Valid candidate identity bindings
        check_9 = (
            candidate_integrity_valid,
            "Candidate integrity or worktree binding validation failed",
        )

        # 10. Pipeline invariants preserved
        check_10 = (pipeline_invariants_valid, "Pipeline invariants are not preserved")

        checks = [
            check_1,
            check_2,
            check_3,
            check_4,
            check_5,
            check_6,
            check_7,
            check_8,
            check_9,
            check_10,
        ]
        return self.evaluate(checks)
