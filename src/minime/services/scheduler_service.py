"""Autonomous Queue and Work Selection Scheduler Service.

Manages work discovery, deterministic prioritization, roadmap governance,
concurrency limits, admission control, and autonomous candidate execution startup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from minime.domain.enums import (
    PRIMARY_PROVIDERS,
    AdmissionBlockCondition,
    AdmissionDecision,
    AdmissionDecisionKind,
    AdmissionRefusalCode,
    ChangeStatus,
    ExecutionOutcome,
    JobStatus,
    ProjectStatus,
    ProviderHealthStatus,
    QueuePriority,
    RecoveryDecisionStatus,
    RecoverySource,
    SchedulerMode,
    WorkItemStatus,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    AdmissionEvaluationResult,
    Job,
    OrchestrationRun,
    Project,
    ProviderHealth,
    QueueExplainReport,
    ReadinessEvaluation,
    SchedulerDecisionRecord,
    SchedulerStatusView,
    WorkQueueItem,
    utc_now,
)
from minime.services.budget_service import BudgetService
from minime.services.discovery_service import WorkDiscoveryService, extract_roadmap_stage
from minime.services.intake_service import IntakeService
from minime.services.lifecycle_transition_authority import LifecycleTransitionAuthority
from minime.services.model_independence_policy import ModelIndependencePolicy
from minime.services.openrouter_eligibility import (
    OpenRouterEligibilityEvaluator,
    OpenRouterEligibilityResult,
    is_material_execution_started,
)
from minime.services.orchestration_service import OrchestrationService
from minime.services.post_merge_service import PostMergeReconciliationService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.readiness_service import ReadinessService
from minime.services.recovery_convergence_service import RecoveryConvergenceService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedAdmissionEvidence:
    """Immutable evidence gathered during Phase A pre-lock observation."""

    project_id: str
    change_name: str
    observed_at: datetime
    github_issue_number: int | None = None
    github_repo: str | None = None
    readiness_evaluation: ReadinessEvaluation | None = None
    apply_attribution_result: Any | None = None
    observed_base_sha: str | None = None
    project_exists: bool = True
    change_exists: bool = True
    binding_valid: bool = True

PRIORITY_BASE_SCORES: dict[QueuePriority, float] = {
    QueuePriority.CRITICAL: 10000.0,
    QueuePriority.HIGH: 5000.0,
    QueuePriority.NORMAL: 1000.0,
    QueuePriority.LOW: 100.0,
}

MAX_AGING_BONUS: float = 2000.0
HOURLY_AGING_RATE: float = 50.0


CANONICAL_GLOBAL_MAX_JOBS: int = 1


class SchedulerService:
    """Autonomous work scheduler and queue dispatcher."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        discovery_service: WorkDiscoveryService | None = None,
        orchestration_service: OrchestrationService | None = None,
        provider_health_service: ProviderHealthService | None = None,
        readiness_service: ReadinessService | None = None,
        post_merge_service: PostMergeReconciliationService | None = None,
        intake_service: IntakeService | None = None,
        model_independence_policy: ModelIndependencePolicy | None = None,
        max_global_jobs: int = 1,
        _test_global_max_jobs_override: int | None = None,
        one_active_implementation_per_project: bool = True,
        mode: SchedulerMode = SchedulerMode.RUN,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        if readiness_service is not None:
            self.readiness_service = readiness_service
        elif orchestration_service is not None and getattr(orchestration_service, "readiness_service", None) is not None:
            self.readiness_service = orchestration_service.readiness_service
        else:
            self.readiness_service = ReadinessService(uow)
        gh_adapter = getattr(self.readiness_service, "github_adapter", None)
        os_adapter = getattr(self.readiness_service, "openspec_adapter", None)
        self.openspec_adapter = os_adapter
        self.discovery_service = discovery_service or WorkDiscoveryService(
            uow,
            project_root=self.project_root,
            github_adapter=gh_adapter,
            openspec_adapter=os_adapter,
            readiness_service=self.readiness_service,
        )
        self.orchestration_service = orchestration_service or OrchestrationService(
            uow,
            project_root=self.project_root,
            github_adapter=gh_adapter,
            openspec_adapter=os_adapter,
            readiness_service=self.readiness_service,
        )

        self.post_merge_service = post_merge_service or PostMergeReconciliationService(
            uow,
            project_root=self.project_root,
            github_adapter=gh_adapter,
        )
        self.intake_service = intake_service or IntakeService(
            uow,
            project_root=self.project_root,
            github_adapter=gh_adapter,
            openspec_adapter=os_adapter,
            readiness_service=self.readiness_service,
        )
        self.provider_health_service = provider_health_service or ProviderHealthService(uow)
        self.model_independence_policy = model_independence_policy or ModelIndependencePolicy()
        self.recovery_convergence_service = RecoveryConvergenceService(
            uow, project_root=self.project_root, health_service=self.provider_health_service
        )
        if _test_global_max_jobs_override is not None:
            self.max_global_jobs = _test_global_max_jobs_override
        else:
            self.max_global_jobs = CANONICAL_GLOBAL_MAX_JOBS
        self.one_active_implementation_per_project = one_active_implementation_per_project
        self.mode = mode
        self._admission_health_truth: dict[str, ProviderHealth | None] | None = None

    def compute_priority_score(
        self, item: WorkQueueItem, now: datetime | None = None
    ) -> tuple[float, float, float, float]:
        """Compute deterministic priority score: (base_score, aging_bonus, stage_bonus, total_score)."""
        current_time = now or utc_now()
        base_score = PRIORITY_BASE_SCORES.get(item.priority, 1000.0)

        # Aging bonus (prevents starvation of low-priority items over time)
        age_seconds = max(0.0, (current_time - item.discovered_at).total_seconds())
        age_hours = age_seconds / 3600.0
        aging_bonus = min(MAX_AGING_BONUS, age_hours * HOURLY_AGING_RATE)

        # Stage bonus (earlier roadmap stages get a small deterministic precedence boost)
        stage_num = item.roadmap_stage or extract_roadmap_stage(item.change_name) or 99
        stage_bonus = max(0.0, (100.0 - stage_num) * 10.0)

        total_score = base_score + aging_bonus + stage_bonus
        return base_score, aging_bonus, stage_bonus, total_score

    def rank_candidates(
        self, items: list[WorkQueueItem], now: datetime | None = None
    ) -> list[WorkQueueItem]:
        """Deterministically rank queue items by priority score and tie-breaking rules."""
        current_time = now or utc_now()

        scored_items: list[WorkQueueItem] = []
        for item in items:
            _, _, _, total_score = self.compute_priority_score(item, current_time)
            updated = item.model_copy(update={"priority_score": total_score})
            scored_items.append(updated)

        # Sort order:
        # 1. Total score descending
        # 2. Roadmap stage ascending (earlier stages first)
        # 3. Discovered timestamp ascending (earlier items first)
        # 4. GitHub issue number ascending
        scored_items.sort(
            key=lambda i: (
                -i.priority_score,
                i.roadmap_stage if i.roadmap_stage is not None else 9999,
                i.discovered_at,
                i.github_issue_number if i.github_issue_number is not None else 999999,
            )
        )
        return scored_items

    def explain_item_priority(self, project_id: str, change_name: str) -> QueueExplainReport:
        """Provide detailed explainability report for an item's queue ranking and blockers."""
        item = self.uow.work_queue.get_by_project_and_change(project_id, change_name)
        if not item:
            raise ValueError(
                f"Work queue item not found for project '{project_id}' and change '{change_name}'."
            )

        all_items = self.uow.work_queue.list_all(project_id)
        ranked = self.rank_candidates(all_items)

        position = None
        for idx, r in enumerate(ranked, start=1):
            if r.change_name == change_name and r.project_id == project_id:
                position = idx
                break

        base_score, aging_bonus, stage_bonus, total_score = self.compute_priority_score(item)

        eval_result = self.evaluate_admission(project_id, change_name)
        decision = eval_result.decision
        refusal_code = eval_result.legacy_refusal_code
        reason_summary = eval_result.rationale

        blockers = list(item.unmet_readiness_reasons)
        if eval_result.block_condition:
            blockers.append(
                f"Admission Blocker: {eval_result.block_condition.value} - {reason_summary}"
            )

        rationale = (
            f"Ranked #{position}: Base score {base_score:.0f} ({item.priority.value}) + "
            f"Aging bonus {aging_bonus:.1f} + Stage bonus {stage_bonus:.1f} = {total_score:.1f}. "
            f"Status: {decision.value}"
            + (
                f" ({eval_result.block_condition.value}: {reason_summary})"
                if eval_result.block_condition
                else ""
            )
        )

        return QueueExplainReport(
            project_id=project_id,
            change_name=change_name,
            github_issue_number=item.github_issue_number,
            readiness_state=item.readiness_state,
            admission_eligible=item.admission_eligible and decision == AdmissionDecisionKind.RUN,
            priority=item.priority,
            base_score=base_score,
            aging_bonus=aging_bonus,
            roadmap_precedence_penalty=0.0,
            total_score=total_score,
            queue_position=position,
            blockers=blockers,
            refusal_code=refusal_code,
            operational_decision=decision,
            block_condition=eval_result.block_condition,
            selection_rationale=rationale,
            evaluated_at=utc_now(),
        )

    _IN_FLIGHT_JOB_STATUSES: frozenset[JobStatus] = frozenset(
        {
            JobStatus.RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.CHECKS_PASSED,
            JobStatus.REVIEW_RUNNING,
            JobStatus.WAITING_CAPACITY,
        }
    )

    def _lookup_provider_health(self, provider: str) -> ProviderHealth | None:
        """Return authoritative provider health, or None when truth is unavailable.

        Fail-closed: a lookup exception must NEVER be synthesized into AVAILABLE.
        Callers treat None (truth unavailable) as UNKNOWN capacity.

        When a tick has captured an admission-time health snapshot (before probe/
        discovery helpers may synthesize records), that snapshot is authoritative.
        """
        truth = self._admission_health_truth
        if truth is not None and provider in truth:
            return truth[provider]
        return self._safe_lookup_provider_health(provider)

    def _safe_lookup_provider_health(self, provider: str) -> ProviderHealth | None:
        try:
            return self.provider_health_service.get_existing_health(provider)
        except Exception as exc:
            logger.warning("Provider health lookup failed for '%s': %s", provider, exc)
            return None

    def _provider_has_probe_path(self, provider: str) -> bool:
        """Return True when an authorized bounded automatic recovery probe exists.

        Primary providers are probed by ``ProviderHealthService.probe_unavailable_providers``
        during each scheduler tick; generic providers have no such automatic path.
        """
        return provider in PRIMARY_PROVIDERS

    def _find_drain_continuation(
        self, project: Project, change_name: str
    ) -> tuple[OrchestrationRun | None, Job | None]:
        """Locate an active, materially-started in-flight job eligible for drain continuation."""
        active_run = self.uow.orchestration_runs.get_active_run(project.project_id, change_name)
        if not active_run or not active_run.active_job_id:
            return None, None
        job = self.uow.jobs.get_by_id(active_run.active_job_id)
        if not job:
            return None, None
        if job.status not in self._IN_FLIGHT_JOB_STATUSES:
            return None, None
        if not is_material_execution_started(job):
            return None, None
        return active_run, job

    def _evaluate_drain_eligibility(
        self, project: Project, run: OrchestrationRun, job: Job
    ) -> OpenRouterEligibilityResult:
        """Evaluate canonical OpenRouter drain fallback eligibility for an in-flight job."""
        evaluator = OpenRouterEligibilityEvaluator()
        primary_health = self.provider_health_service.list_all_health()
        policy, headroom = BudgetService(self.uow).get_headroom(project.project_id)
        model_independent = self.model_independence_policy.validate(
            getattr(project, "implementer", None),
            getattr(project, "reviewer", None),
        )[0]
        return evaluator.evaluate_10_points(
            scheduler_mode=self.mode,
            job=job,
            role="implementer",
            is_new_ready_change=False,
            primary_health_records=primary_health,
            project=project,
            policy=policy,
            headroom=headroom,
            model_identity_valid=model_independent,
        )

    def _drain_denial_result(
        self, project_id: str, change_name: str, denial_reason: str | None
    ) -> AdmissionEvaluationResult:
        """Map a canonical drain eligibility denial to an operational decision.

        DRAIN is never emitted on denial. Budget exhaustion halts in-flight drain
        with BUDGET_EXCEEDED; structural denial surfaces as NEEDS_HUMAN; anything
        else is treated as a temporary capacity block.
        """
        reason = denial_reason or "Drain fallback eligibility denied."
        lowered = reason.lower()
        if "budget" in lowered or "headroom" in lowered:
            decision = AdmissionDecisionKind.NEEDS_HUMAN
            block = AdmissionBlockCondition.BUDGET_EXCEEDED
        elif "model identity" in lowered or "independent" in lowered:
            decision = AdmissionDecisionKind.NEEDS_HUMAN
            block = AdmissionBlockCondition.REVIEWER_INDEPENDENCE_UNAVAILABLE
        elif "disabled" in lowered or "breached" in lowered:
            decision = AdmissionDecisionKind.NEEDS_HUMAN
            block = AdmissionBlockCondition.CONFIGURATION_INVALID
        else:
            decision = AdmissionDecisionKind.WAIT
            block = AdmissionBlockCondition.CAPACITY_EXHAUSTED

        return AdmissionEvaluationResult(
            decision=decision,
            project_id=project_id,
            change_name=change_name,
            safe_executable_pair_exists=False,
            block_condition=block,
            rationale=f"In-flight drain continuation denied: {reason}",
            legacy_decision=AdmissionDecision.REFUSED,
            legacy_refusal_code=AdmissionRefusalCode.PROVIDER_DRAIN,
        )

    def prepare_admission_evidence(
        self, project_id: str, change_name: str
    ) -> PreparedAdmissionEvidence:
        """Phase A: Pre-lock evidence preparation.

        Performs all slow/external/non-transactional observations required for admission
        (GitHub issue binding validation, OpenSpec CLI validation, workspace inspection,
        Git repository identity, Apply attribution gate evaluation, base SHA resolution)
        BEFORE acquiring Stage F transaction advisory locks.

        MUST NOT acquire locks, mutate persistent state, or perform DB commits.
        """
        now = utc_now()
        project = self.uow.projects.get_by_id(project_id)
        if not project or project.status != ProjectStatus.ACTIVE:
            return PreparedAdmissionEvidence(
                project_id=project_id,
                change_name=change_name,
                observed_at=now,
                project_exists=False,
            )

        change_rec = self.uow.changes.get_by_name(project_id, change_name)
        backlog_rec = self.uow.backlog_items.get_by_openspec_change_name(project_id, change_name)
        if not change_rec and not backlog_rec:
            return PreparedAdmissionEvidence(
                project_id=project_id,
                change_name=change_name,
                observed_at=now,
                change_exists=False,
            )


        binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
        if not binding or not binding.is_valid or not binding.github_issue_number:
            return PreparedAdmissionEvidence(
                project_id=project_id,
                change_name=change_name,
                observed_at=now,
                binding_valid=False,
            )

        # 1. Pure Definition of Ready (DoR) evaluation — zero DB writes, zero commits
        readiness_eval = self.readiness_service.evaluate_change_readiness_pure(
            project_id=project_id,
            change_name=change_name,
            project_root=str(self.project_root),
            github_repo=project.repository,
            github_issue=binding.github_issue_number,
        )

        # 2. Apply Attribution Gate evaluation (Git / OpenSpec subprocess check)
        from minime.services.lifecycle_gates import ApplyAttributionGate
        apply_result = ApplyAttributionGate(self.openspec_adapter).evaluate(
            project=project,
            change_name=change_name,
            project_root=self.project_root,
        )

        # 3. Base SHA resolution (Git subprocess check)
        observed_base_sha = self.orchestration_service._resolve_base_sha(
            project, self.project_root
        )

        return PreparedAdmissionEvidence(
            project_id=project_id,
            change_name=change_name,
            observed_at=now,
            github_issue_number=binding.github_issue_number,
            github_repo=project.repository,
            readiness_evaluation=readiness_eval,
            apply_attribution_result=apply_result,
            observed_base_sha=observed_base_sha,
            project_exists=True,
            change_exists=True,
            binding_valid=True,
        )

    def evaluate_admission(
        self,
        project_id: str,
        change_name: str,
        evidence: PreparedAdmissionEvidence | None = None,
    ) -> AdmissionEvaluationResult:
        """Evaluate full admission criteria and determine converged operational decision."""
        if evidence is None:
            evidence = self.prepare_admission_evidence(project_id, change_name)

        # 1. Registered project check
        project = self.uow.projects.get_by_id(project_id)
        if not project or project.status != ProjectStatus.ACTIVE or not evidence.project_exists:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.CONFIGURATION_INVALID,
                rationale=f"Project '{project_id}' not found or is not active.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.INVALID_BINDING,
            )

        change_rec = self.uow.changes.get_by_name(project_id, change_name)
        backlog_rec = self.uow.backlog_items.get_by_openspec_change_name(project_id, change_name)
        if (not change_rec and not backlog_rec) or not evidence.change_exists:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.CONFIGURATION_INVALID,
                rationale=f"Change '{change_name}' not found for project '{project_id}'.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.NOT_READY,
            )

        # Check active run uniqueness first so duplicate active runs report CHANGE_ALREADY_ACTIVE
        active_runs = self.uow.orchestration_runs.list_runs(is_active=True)
        for active_run in active_runs:
            if active_run.project_id == project_id and active_run.change_name == change_name:
                if self.mode != SchedulerMode.DRAIN:
                    return AdmissionEvaluationResult(
                        decision=AdmissionDecisionKind.WAIT,
                        project_id=project_id,
                        change_name=change_name,
                        safe_executable_pair_exists=True,
                        eligible_implementer=getattr(project, "implementer", None) or "codex",
                        eligible_reviewer=getattr(project, "reviewer", None) or "antigravity",
                        block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                        rationale=f"Active orchestration run '{active_run.run_id}' already exists for project '{project_id}' and change '{change_name}'.",
                        legacy_decision=AdmissionDecision.REFUSED,
                        legacy_refusal_code=AdmissionRefusalCode.CHANGE_ALREADY_ACTIVE,
                        refusal_details={"code": "DUPLICATE_ACTIVE_RUN", "existing_run_id": active_run.run_id},
                    )

        if change_rec and change_rec.status in (ChangeStatus.DONE, ChangeStatus.CANCELLED):
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                rationale=f"Change '{change_name}' is in terminal state '{change_rec.status.value}' and cannot be admitted.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.NOT_READY,
                refusal_details={"code": "LIFECYCLE_BLOCKED", "status": change_rec.status.value},
            )

        existing_active = self.uow.orchestration_runs.get_active_run(project_id, change_name)
        if existing_active and self.mode != SchedulerMode.DRAIN:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.WAIT,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                rationale=f"Active orchestration run '{existing_active.run_id}' already exists for change '{change_name}'.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.CHANGE_ALREADY_ACTIVE,
                refusal_details={"code": "DUPLICATE_ACTIVE_RUN", "existing_run_id": existing_active.run_id},
            )

        if backlog_rec and backlog_rec.status != WorkItemStatus.READY:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                rationale=f"BacklogItem for change '{change_name}' is in state '{backlog_rec.status.value}' (expected READY).",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.NOT_READY,
                refusal_details={"code": "LIFECYCLE_BLOCKED", "status": backlog_rec.status.value},
            )

        # 2. Durable ProjectBinding check
        binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
        if not binding or not binding.is_valid or not binding.github_issue_number or not evidence.binding_valid:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.CONFIGURATION_INVALID,
                rationale=f"Project binding for change '{change_name}' is invalid or missing GitHub issue number.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.INVALID_BINDING,
            )

        # Evidence staleness check: verify prepared evidence matches current DB identity
        if (
            evidence.github_issue_number != binding.github_issue_number
            or evidence.github_repo != project.repository
        ):

            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                rationale="Pre-lock admission evidence is stale or invalidated by current durable state.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.INVALID_BINDING,
            )

        if evidence.apply_attribution_result and evidence.apply_attribution_result.is_blocking:
            code = evidence.apply_attribution_result.reason.code
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                rationale=f"{code}: {evidence.apply_attribution_result.reason.message}",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.NOT_READY,
                refusal_details={
                    "code": code,
                    "gate": evidence.apply_attribution_result.gate_name,
                    "status": evidence.apply_attribution_result.status.value,
                    **evidence.apply_attribution_result.reason.details,
                },
            )


        # Capture canonical existing provider-health truth BEFORE readiness/capacity
        # checks can synthesize records. Absent rows must remain UNKNOWN for the
        # admission decision, never be reinterpreted as AVAILABLE.
        configured_implementer = getattr(project, "implementer", None) or "codex"
        configured_reviewer = getattr(project, "reviewer", None) or "antigravity"
        impl_health = self._lookup_provider_health(configured_implementer)
        rev_health = self._lookup_provider_health(configured_reviewer)

        # 3. Check prior execution outcomes for this change if one exists
        # In particular, EVIDENCE_INSUFFICIENT on latest attempt -> NEEDS_HUMAN, no auto-retry, no capacity wait
        change_rec = self.uow.changes.get_by_name(project_id, change_name)
        if change_rec:
            cid = getattr(change_rec, "change_id", getattr(change_rec, "id", None))
            jobs = [
                j
                for j in self.uow.jobs.list_by_project(project_id)
                if (cid and getattr(j, "change_id", None) == cid)
                or getattr(j, "change_name", None) == change_name
            ]
            if jobs:
                latest_job = jobs[-1]
                jid = getattr(latest_job, "job_id", getattr(latest_job, "id", None))
                attempts = self.uow.job_attempts.list_by_job(jid)
                if attempts:
                    latest_attempt = attempts[-1]
                    exec_outcome = getattr(
                        latest_attempt,
                        "normalized_outcome",
                        getattr(latest_attempt, "execution_outcome", None),
                    )
                    fail_reason = getattr(latest_attempt, "failure_reason", "") or str(
                        getattr(latest_attempt, "error_details", {})
                    )
                    if (
                        exec_outcome == ExecutionOutcome.EVIDENCE_INSUFFICIENT
                        or "EVIDENCE_INSUFFICIENT" in str(fail_reason)
                    ):
                        return AdmissionEvaluationResult(
                            decision=AdmissionDecisionKind.NEEDS_HUMAN,
                            project_id=project_id,
                            change_name=change_name,
                            safe_executable_pair_exists=False,
                            block_condition=AdmissionBlockCondition.EVIDENCE_INSUFFICIENT,
                            rationale="Previous execution attempt completed without verifiable repository-editing evidence (EVIDENCE_INSUFFICIENT). Human intervention required; automated retry prohibited.",
                            legacy_decision=AdmissionDecision.REFUSED,
                            legacy_refusal_code=AdmissionRefusalCode.EVALUATION_ERROR,
                        )
                    if (
                        exec_outcome
                        in (
                            ExecutionOutcome.ENVIRONMENT_UNAVAILABLE,
                            getattr(ExecutionOutcome, "HARNESS_UNAVAILABLE", None),
                        )
                        or "HARNESS_UNAVAILABLE" in str(fail_reason)
                        or "ENVIRONMENT_UNAVAILABLE" in str(fail_reason)
                    ):
                        return AdmissionEvaluationResult(
                            decision=AdmissionDecisionKind.NEEDS_HUMAN,
                            project_id=project_id,
                            change_name=change_name,
                            safe_executable_pair_exists=False,
                            block_condition=AdmissionBlockCondition.HARNESS_UNAVAILABLE,
                            rationale="Local execution harness unavailable or structural tool defect detected. Human intervention required.",
                            legacy_decision=AdmissionDecision.REFUSED,
                            legacy_refusal_code=AdmissionRefusalCode.WORKSPACE_ERROR,
                        )

        # 4. Definition of Ready (DoR) check — pure evaluation from evidence (zero DB commits)
        readiness = evidence.readiness_evaluation if evidence and evidence.readiness_evaluation else self.readiness_service.evaluate_change_readiness_pure(
            project_id=project_id,
            change_name=change_name,
            project_root=str(self.project_root),
            github_repo=project.repository,
            github_issue=binding.github_issue_number,
        )
        non_capacity_unmet = [
            r
            for r in readiness.unmet_reasons
            if "primary pair capacity shortage" not in r.lower()
            and "capacity shortage" not in r.lower()
        ]
        if non_capacity_unmet:
            reasons_str = "; ".join(non_capacity_unmet)
            if any(
                "complementary" in r.lower() or "independent" in r.lower() or "same" in r.lower()
                for r in non_capacity_unmet
            ):
                block_cond = AdmissionBlockCondition.REVIEWER_INDEPENDENCE_UNAVAILABLE
                op_decision = AdmissionDecisionKind.NEEDS_HUMAN
            elif any(
                "manual" in r.lower()
                or "human" in r.lower()
                or "approval" in r.lower()
                or "preview" in r.lower()
                for r in non_capacity_unmet
            ):
                block_cond = AdmissionBlockCondition.HUMAN_APPROVAL_REQUIRED
                op_decision = AdmissionDecisionKind.NEEDS_HUMAN
            elif any(
                "spec" in r.lower() or "schema" in r.lower() or "invalid" in r.lower()
                for r in non_capacity_unmet
            ):
                block_cond = AdmissionBlockCondition.LIFECYCLE_BLOCKED
                op_decision = AdmissionDecisionKind.NEEDS_HUMAN
            elif any(
                "predecessor" in r.lower() or "dependency" in r.lower() for r in non_capacity_unmet
            ):
                block_cond = AdmissionBlockCondition.LIFECYCLE_BLOCKED
                op_decision = AdmissionDecisionKind.WAIT
            else:
                block_cond = AdmissionBlockCondition.LIFECYCLE_BLOCKED
                op_decision = AdmissionDecisionKind.NEEDS_HUMAN

            return AdmissionEvaluationResult(
                decision=op_decision,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=block_cond,
                rationale=f"Definition of Ready unmet: {reasons_str}",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.NOT_READY,
            )

        # 5. Roadmap governance: check for incomplete predecessor roadmap stages
        stage_num = extract_roadmap_stage(change_name)
        if stage_num is not None:
            all_changes = self.uow.changes.list_by_project(project_id)
            for other_change in all_changes:
                if other_change.name == change_name:
                    continue
                other_stage = extract_roadmap_stage(other_change.name)
                if other_stage is not None and other_stage < stage_num:
                    if other_change.status not in (ChangeStatus.DONE, ChangeStatus.CANCELLED):
                        return AdmissionEvaluationResult(
                            decision=AdmissionDecisionKind.WAIT,
                            project_id=project_id,
                            change_name=change_name,
                            safe_executable_pair_exists=False,
                            block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                            rationale=f"Roadmap predecessor stage {other_stage:03d} ('{other_change.name}') is incomplete.",
                            legacy_decision=AdmissionDecision.REFUSED,
                            legacy_refusal_code=AdmissionRefusalCode.ROADMAP_PREDECESSOR_INCOMPLETE,
                        )

        # 6. Dependency check
        queue_item = self.uow.work_queue.get_by_project_and_change(project_id, change_name)
        if queue_item and queue_item.dependencies:
            for dep_name in queue_item.dependencies:
                dep_change = self.uow.changes.get_by_name(project_id, dep_name)
                dep_backlog = self.uow.backlog_items.get_by_openspec_change_name(
                    project_id, dep_name
                )
                is_complete = False
                if dep_change and dep_change.status in (
                    ChangeStatus.DONE,
                    ChangeStatus.CANCELLED,
                ):
                    is_complete = True
                elif dep_backlog and dep_backlog.status in (
                    WorkItemStatus.COMPLETED,
                    WorkItemStatus.CANCELLED,
                ):
                    is_complete = True

                if not is_complete:
                    return AdmissionEvaluationResult(
                        decision=AdmissionDecisionKind.WAIT,
                        project_id=project_id,
                        change_name=change_name,
                        safe_executable_pair_exists=False,
                        block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                        rationale=f"Declared dependency '{dep_name}' is not complete.",
                        legacy_decision=AdmissionDecision.REFUSED,
                        legacy_refusal_code=AdmissionRefusalCode.DEPENDENCY_BLOCKED,
                    )

        # 7. Project policy checks
        if not getattr(project, "auto_admit", True):
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.HUMAN_APPROVAL_REQUIRED,
                rationale=f"Project '{project_id}' policy requires manual admission ('auto_admit' is disabled).",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.MANUAL_ADMISSION_POLICY,
            )

        # 8. Scheduler mode check (RUN / DRAIN / WAIT)
        if self.mode == SchedulerMode.WAIT:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.WAIT,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.CAPACITY_EXHAUSTED,
                rationale="Scheduler is in WAIT mode: all admissions suspended.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.PROVIDER_WAIT,
            )

        # 9. Strict drain fallback policy: DRAIN is confined to active in-flight
        # continuations of already-admitted work. New READY items are NEVER admitted
        # through drain fallback.
        if self.mode == SchedulerMode.DRAIN:
            run, job = self._find_drain_continuation(project, change_name)
            if run is None or job is None:
                # New READY work, or historical materialized work without an active
                # in-flight continuation: drain fallback must not admit new work.
                return AdmissionEvaluationResult(
                    decision=AdmissionDecisionKind.WAIT,
                    project_id=project_id,
                    change_name=change_name,
                    safe_executable_pair_exists=False,
                    block_condition=AdmissionBlockCondition.CAPACITY_EXHAUSTED,
                    rationale="Scheduler is in DRAIN mode: new backlog work items may not be admitted.",
                    legacy_decision=AdmissionDecision.REFUSED,
                    legacy_refusal_code=AdmissionRefusalCode.PROVIDER_DRAIN,
                )

            eligibility = self._evaluate_drain_eligibility(project, run, job)
            if not eligibility.eligible:
                return self._drain_denial_result(project_id, change_name, eligibility.denial_reason)

            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.DRAIN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=True,
                eligible_implementer=getattr(project, "implementer", None) or "codex",
                eligible_reviewer=getattr(project, "reviewer", None) or "antigravity",
                block_condition=None,
                rationale=f"In-flight work item '{change_name}' admitted for drain continuation.",
                legacy_decision=AdmissionDecision.ADMITTED,
                legacy_refusal_code=None,
            )

        # 10. SAFE_EXECUTABLE_PAIR_EXISTS for the canonically assigned path only.
        # The scheduler answers whether the CURRENT configured implementer/reviewer
        # path is safely executable under ModelIndependencePolicy. It does NOT search
        # external_providers_allowed for an alternative implementer/reviewer pair.
        # (configured_implementer / configured_reviewer / impl_health / rev_health were
        # captured above, before readiness checks could synthesize provider records.)
        health_by_provider = {
            configured_implementer: impl_health,
            configured_reviewer: rev_health,
        }
        auth_errors: list[str] = []
        config_errors: list[str] = []
        for p, h in health_by_provider.items():
            if h is not None and h.status == ProviderHealthStatus.AUTH_REQUIRED:
                auth_errors.append(p)
            elif h is not None and h.status == ProviderHealthStatus.MISCONFIGURED:
                config_errors.append(p)

        if auth_errors:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.AUTH_REQUIRED,
                rationale=f"Provider credentials missing or invalid for: {', '.join(auth_errors)}.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.PROVIDER_UNAVAILABLE,
            )

        if config_errors:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.CONFIGURATION_INVALID,
                rationale=f"Provider configuration invalid for: {', '.join(config_errors)}.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.PROVIDER_UNAVAILABLE,
            )

        # UNKNOWN capacity must NEVER become RUN. Fail closed.
        unreachable = [
            p
            for p, h in (
                (configured_implementer, impl_health),
                (configured_reviewer, rev_health),
            )
            if h is not None and h.status == ProviderHealthStatus.UNREACHABLE
        ]
        if unreachable:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.UNKNOWN_CAPACITY,
                rationale=f"Provider capacity unprobeable or unreachable: {', '.join(unreachable)}.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.PROVIDER_UNAVAILABLE,
            )

        lookup_failed = [
            p
            for p, h in (
                (configured_implementer, impl_health),
                (configured_reviewer, rev_health),
            )
            if h is None
        ]
        if lookup_failed:
            probeable = any(self._provider_has_probe_path(p) for p in lookup_failed)
            decision = (
                AdmissionDecisionKind.WAIT if probeable else AdmissionDecisionKind.NEEDS_HUMAN
            )
            return AdmissionEvaluationResult(
                decision=decision,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.UNKNOWN_CAPACITY,
                rationale=f"Provider capacity unknown for: {', '.join(lookup_failed)}.",
                has_deterministic_eta=False,
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.PROVIDER_UNAVAILABLE,
            )

        # Structural model independence impossibility on the assigned path.
        is_independent, _ = self.model_independence_policy.validate(
            configured_implementer, configured_reviewer
        )
        if not is_independent:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.NEEDS_HUMAN,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=AdmissionBlockCondition.REVIEWER_INDEPENDENCE_UNAVAILABLE,
                rationale="Configured provider pair cannot satisfy ModelIndependencePolicy under any circumstances.",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.PROVIDER_UNAVAILABLE,
            )

        # Temporary exhaustion on the assigned implementer/reviewer path -> WAIT.
        def _capacity_eta(provider: str) -> tuple[datetime | None, bool]:
            win = self.uow.capacity_windows.get_latest_for_provider(provider)
            if win and win.capacity_reset_at:
                return win.capacity_reset_at, True
            return None, False

        if impl_health is not None and impl_health.status not in (
            ProviderHealthStatus.AVAILABLE,
            ProviderHealthStatus.DEGRADED,
        ):
            cooldown_until, has_deterministic_eta = _capacity_eta(configured_implementer)
            block_cond = (
                AdmissionBlockCondition.UNKNOWN_CAPACITY
                if impl_health.status == ProviderHealthStatus.UNKNOWN
                else AdmissionBlockCondition.CAPACITY_EXHAUSTED
            )
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.WAIT,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=block_cond,
                rationale=f"Configured implementer '{configured_implementer}' is {impl_health.status.value}.",
                cooldown_until=cooldown_until,
                has_deterministic_eta=has_deterministic_eta,
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.PROVIDER_UNAVAILABLE,
            )

        if rev_health is not None and rev_health.status not in (
            ProviderHealthStatus.AVAILABLE,
            ProviderHealthStatus.DEGRADED,
        ):
            cooldown_until, has_deterministic_eta = _capacity_eta(configured_reviewer)
            block_cond = (
                AdmissionBlockCondition.UNKNOWN_CAPACITY
                if rev_health.status == ProviderHealthStatus.UNKNOWN
                else AdmissionBlockCondition.CAPACITY_EXHAUSTED
            )
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.WAIT,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=False,
                block_condition=block_cond,
                rationale=f"Configured reviewer '{configured_reviewer}' is {rev_health.status.value}.",
                cooldown_until=cooldown_until,
                has_deterministic_eta=has_deterministic_eta,
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.PROVIDER_UNAVAILABLE,
            )

        selected_impl = configured_implementer
        selected_rev = configured_reviewer

        # 11. Concurrency checks (fresh admission only)
        active_runs = self.uow.orchestration_runs.list_runs(is_active=True)

        for active_run in active_runs:
            if active_run.project_id == project_id and active_run.change_name == change_name:
                return AdmissionEvaluationResult(
                    decision=AdmissionDecisionKind.WAIT,
                    project_id=project_id,
                    change_name=change_name,
                    safe_executable_pair_exists=True,
                    eligible_implementer=selected_impl,
                    eligible_reviewer=selected_rev,
                    block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                    rationale=f"Active orchestration run '{active_run.run_id}' already exists for project '{project_id}' and change '{change_name}'.",
                    legacy_decision=AdmissionDecision.REFUSED,
                    legacy_refusal_code=AdmissionRefusalCode.CHANGE_ALREADY_ACTIVE,
                )

        max_project_jobs = getattr(project, "max_concurrent_jobs", 1)
        project_active = [r for r in active_runs if r.project_id == project_id]
        if len(project_active) >= max_project_jobs:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.WAIT,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=True,
                eligible_implementer=selected_impl,
                eligible_reviewer=selected_rev,
                block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                rationale=f"Project '{project_id}' concurrency limit reached ({len(project_active)}/{max_project_jobs} active runs).",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.PROJECT_CONCURRENCY_LIMIT,
            )

        if len(active_runs) >= self.max_global_jobs:
            return AdmissionEvaluationResult(
                decision=AdmissionDecisionKind.WAIT,
                project_id=project_id,
                change_name=change_name,
                safe_executable_pair_exists=True,
                eligible_implementer=selected_impl,
                eligible_reviewer=selected_rev,
                block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                rationale=f"Global concurrency limit reached ({len(active_runs)}/{self.max_global_jobs} active runs).",
                legacy_decision=AdmissionDecision.REFUSED,
                legacy_refusal_code=AdmissionRefusalCode.GLOBAL_CONCURRENCY_LIMIT,
            )

        # All criteria satisfied -> RUN
        return AdmissionEvaluationResult(
            decision=AdmissionDecisionKind.RUN,
            project_id=project_id,
            change_name=change_name,
            safe_executable_pair_exists=True,
            eligible_implementer=selected_impl,
            eligible_reviewer=selected_rev,
            block_condition=None,
            rationale=f"Work item '{change_name}' is READY and admitted for execution.",
            legacy_decision=AdmissionDecision.ADMITTED,
            legacy_refusal_code=None,
        )

    def admit_work_item(
        self, project_id: str, change_name: str, drive_admitted: bool = False
    ) -> tuple[AdmissionDecision, SchedulerDecisionRecord, OrchestrationRun | None]:
        """Atomically evaluate admission and start native candidate execution if eligible under advisory lock."""
        from minime.db.concurrency import (
            derive_global_admission_lock_key,
            derive_project_admission_lock_key,
        )

        # PHASE A: Pre-lock evidence preparation (no locks, no DB commits, all external/subprocess reads)
        evidence = self.prepare_admission_evidence(project_id, change_name)

        # PHASE B: Serialized DB authority (under advisory locks, single atomic DB transaction with retry)
        from minime.db.retry import TransactionRetryWrapper

        def _phase_b_body() -> tuple[AdmissionDecision, SchedulerDecisionRecord, OrchestrationRun | None]:
            global_key = derive_global_admission_lock_key()
            project_key = derive_project_admission_lock_key(project_id)

            self.uow.acquire_advisory_lock(global_key, lock_timeout="2s")
            self.uow.acquire_advisory_lock(project_key, lock_timeout="2s")

            eval_result = self.evaluate_admission(project_id, change_name, evidence=evidence)
            decision = eval_result.decision
            refusal_code = eval_result.legacy_refusal_code
            reason_summary = eval_result.rationale
            selected_implementer = eval_result.eligible_implementer

            item = self.uow.work_queue.get_by_project_and_change(project_id, change_name)
            _, _, _, priority_score = (
                self.compute_priority_score(item) if item else (0.0, 0.0, 0.0, 0.0)
            )
            issue_number = item.github_issue_number if item else None

            active_runs = self.uow.orchestration_runs.list_runs(is_active=True)
            concurrency_snapshot = {
                "global_active": len(active_runs),
                "max_global_jobs": self.max_global_jobs,
                "project_active": len([r for r in active_runs if r.project_id == project_id]),
            }
            capacity_snapshot = {
                "mode": self.mode.value,
                "implementer": selected_implementer,
                "operational_decision": eval_result.decision.value,
            }

            if decision == AdmissionDecisionKind.RUN:
                admission_result = self.orchestration_service._admit_change_in_transaction(
                    project_id=project_id,
                    change_name=change_name,
                    project_root=self.project_root,
                    evidence=evidence,
                )
                if not admission_result.admitted or not admission_result.run:
                    refusal_code_str = (
                        admission_result.refusal_details.get("code")
                        if admission_result.refusal_details
                        else "EVALUATION_ERROR"
                    )
                    try:
                        refusal = AdmissionRefusalCode(refusal_code_str)
                    except ValueError:
                        refusal = AdmissionRefusalCode.EVALUATION_ERROR

                    decision_record = SchedulerDecisionRecord(
                        project_id=project_id,
                        change_name=change_name,
                        github_issue_number=issue_number,
                        decision=AdmissionDecision.REFUSED,
                        reason_code=refusal,
                        reason_summary=admission_result.refusal_reason
                        or "Orchestration admission failed",
                        priority_score=priority_score,
                        selected_implementer=selected_implementer,
                        operational_decision=AdmissionDecisionKind.NEEDS_HUMAN,
                        block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                        eligible_reviewer=eval_result.eligible_reviewer,
                        safe_executable_pair_exists=eval_result.safe_executable_pair_exists,
                        has_deterministic_eta=eval_result.has_deterministic_eta,
                        cooldown_until=eval_result.cooldown_until,
                        concurrency_snapshot=concurrency_snapshot,
                        capacity_snapshot=capacity_snapshot,
                        refusal_details=admission_result.refusal_details or {"code": refusal_code_str},
                        run_id=str(admission_result.existing_run_id) if admission_result and getattr(admission_result, "existing_run_id", None) is not None else None,
                        evaluated_at=utc_now(),
                    )
                    self.uow.scheduler_decisions.save(decision_record)
                    self.uow.commit()
                    return AdmissionDecision.REFUSED, decision_record, None

                run = admission_result.run

                decision_record = SchedulerDecisionRecord(
                    project_id=project_id,
                    change_name=change_name,
                    github_issue_number=issue_number,
                    decision=AdmissionDecision.ADMITTED,
                    reason_code=None,
                    reason_summary=reason_summary,
                    priority_score=priority_score,
                    selected_implementer=selected_implementer,
                    operational_decision=eval_result.decision,
                    block_condition=eval_result.block_condition,
                    eligible_reviewer=eval_result.eligible_reviewer,
                    safe_executable_pair_exists=eval_result.safe_executable_pair_exists,
                    has_deterministic_eta=eval_result.has_deterministic_eta,
                    cooldown_until=eval_result.cooldown_until,
                    concurrency_snapshot=concurrency_snapshot,
                    capacity_snapshot=capacity_snapshot,
                    run_id=str(run.run_id) if run and getattr(run, "run_id", None) is not None else None,
                    evaluated_at=utc_now(),
                )
                self.uow.scheduler_decisions.save(decision_record)

                if item:
                    updated_item = item.model_copy(
                        update={
                            "admission_eligible": False,
                            "blocked_reason": f"Admitted in active run '{run.run_id}'",
                            "last_evaluated_at": utc_now(),
                        }
                    )
                    self.uow.work_queue.save(updated_item)

                backlog_item = self.uow.backlog_items.get_by_openspec_change_name(
                    project_id, change_name
                )
                if backlog_item and backlog_item.status != WorkItemStatus.ADMITTED:
                    authority = LifecycleTransitionAuthority(self.uow)
                    authority.transition_backlog_item(
                        project_id=project_id,
                        item_key=backlog_item.item_key,
                        expected_from_state=WorkItemStatus.READY,
                        to_state=WorkItemStatus.ADMITTED,
                        run_id=run.run_id,
                        reason_code="scheduler_admission",
                        actor="scheduler",
                    )

                self.uow.commit()

                return AdmissionDecision.ADMITTED, decision_record, run

            elif decision == AdmissionDecisionKind.DRAIN:
                # Drain continuation of already-admitted in-flight work. This is NEVER a
                # fresh admission: no admit_change, no new job, no READY backlog claim.
                project = self.uow.projects.get_by_id(project_id)
                run, _ = (
                    self._find_drain_continuation(project, change_name) if project else (None, None)
                )
                if run is None:
                    # No canonical drain continuation path is available from this service.
                    decision_record = SchedulerDecisionRecord(
                        project_id=project_id,
                        change_name=change_name,
                        github_issue_number=issue_number,
                        decision=AdmissionDecision.REFUSED,
                        reason_code=AdmissionRefusalCode.EVALUATION_ERROR,
                        reason_summary=(
                            "SCOPE_CONTRACT_MISMATCH: no canonical drain continuation "
                            "path available for in-flight work."
                        ),
                        priority_score=priority_score,
                        selected_implementer=selected_implementer,
                        operational_decision=AdmissionDecisionKind.NEEDS_HUMAN,
                        block_condition=AdmissionBlockCondition.LIFECYCLE_BLOCKED,
                        eligible_reviewer=eval_result.eligible_reviewer,
                        safe_executable_pair_exists=eval_result.safe_executable_pair_exists,
                        has_deterministic_eta=eval_result.has_deterministic_eta,
                        cooldown_until=eval_result.cooldown_until,
                        concurrency_snapshot=concurrency_snapshot,
                        capacity_snapshot=capacity_snapshot,
                        evaluated_at=utc_now(),
                    )
                    self.uow.scheduler_decisions.save(decision_record)
                    self.uow.commit()
                    return AdmissionDecision.REFUSED, decision_record, None

                decision_record = SchedulerDecisionRecord(
                    project_id=project_id,
                    change_name=change_name,
                    github_issue_number=issue_number,
                    decision=AdmissionDecision.ADMITTED,
                    reason_code=None,
                    reason_summary=reason_summary,
                    priority_score=priority_score,
                    selected_implementer=selected_implementer,
                    operational_decision=AdmissionDecisionKind.DRAIN,
                    block_condition=eval_result.block_condition,
                    eligible_reviewer=eval_result.eligible_reviewer,
                    safe_executable_pair_exists=eval_result.safe_executable_pair_exists,
                    has_deterministic_eta=eval_result.has_deterministic_eta,
                    cooldown_until=eval_result.cooldown_until,
                    concurrency_snapshot=concurrency_snapshot,
                    capacity_snapshot=capacity_snapshot,
                    run_id=run.run_id,
                    evaluated_at=utc_now(),
                )
                self.uow.scheduler_decisions.save(decision_record)
                self.uow.commit()
                return AdmissionDecision.ADMITTED, decision_record, run

            else:
                if eval_result and eval_result.refusal_details and "code" in eval_result.refusal_details:
                    details = dict(eval_result.refusal_details)
                elif refusal_code == AdmissionRefusalCode.CHANGE_ALREADY_ACTIVE:
                    active_runs = self.uow.orchestration_runs.list_runs(is_active=True)
                    existing = next(
                        (r for r in active_runs if r.project_id == project_id and r.change_name == change_name),
                        None,
                    )
                    details = {
                        "code": "DUPLICATE_ACTIVE_RUN",
                        "existing_run_id": existing.run_id if existing else None,
                    }
                elif refusal_code == AdmissionRefusalCode.NOT_READY:
                    details = {"code": "NOT_READY"}
                    if "Definition of Ready unmet:" in reason_summary:
                        reasons_part = reason_summary.split("Definition of Ready unmet:", 1)[1].strip()
                        details["unmet_reasons"] = [r.strip() for r in reasons_part.split(";") if r.strip()]
                else:
                    details = {"code": refusal_code.value if refusal_code else "REFUSED"}

                decision_record = SchedulerDecisionRecord(
                    project_id=project_id,
                    change_name=change_name,
                    github_issue_number=issue_number,
                    decision=AdmissionDecision.REFUSED,
                    reason_code=refusal_code,
                    reason_summary=reason_summary,
                    priority_score=priority_score,
                    selected_implementer=selected_implementer,
                    operational_decision=eval_result.decision,
                    block_condition=eval_result.block_condition,
                    eligible_reviewer=eval_result.eligible_reviewer,
                    safe_executable_pair_exists=eval_result.safe_executable_pair_exists,
                    has_deterministic_eta=eval_result.has_deterministic_eta,
                    cooldown_until=eval_result.cooldown_until,
                    concurrency_snapshot=concurrency_snapshot,
                    capacity_snapshot=capacity_snapshot,
                    refusal_details=details,
                    run_id=str(details.get("existing_run_id")) if details.get("existing_run_id") is not None else None,
                    evaluated_at=utc_now(),
                )
                self.uow.scheduler_decisions.save(decision_record)

                if item:
                    updated_item = item.model_copy(
                        update={
                            "blocked_reason": f"{refusal_code.value if refusal_code else 'BLOCKED'}: {reason_summary}",
                            "last_evaluated_at": utc_now(),
                        }
                    )
                    self.uow.work_queue.save(updated_item)
                self.uow.commit()
                return AdmissionDecision.REFUSED, decision_record, None

        retry_wrapper = TransactionRetryWrapper(max_attempts=3, is_coordination_path=True)
        decision, decision_record, run = retry_wrapper.execute(
            command_fn=_phase_b_body,
            rollback_fn=lambda: self.uow.rollback(),
            is_coordination_path=True,
            command_identity=f"admit_work_item:{project_id}:{change_name}",
        )
        if decision == AdmissionDecision.ADMITTED and run is not None:
            if decision_record.operational_decision == AdmissionDecisionKind.DRAIN:
                run = self.orchestration_service.resume(
                    run.run_id, project_root=self.project_root, drain_mode=True
                )
            elif drive_admitted:
                run = self.orchestration_service.drive_coordinator(
                    run.run_id, project_root=self.project_root
                )
        return decision, decision_record, run

    def reconcile_waiting_runs(
        self,
        project_id: str | None = None,
        drive_resumed: bool = False,
        timeout_hours: float = 2.0,
    ) -> list[str]:
        """Re-evaluate active orchestration runs waiting for capacity or external environment via RecoveryConvergenceService."""
        decisions = self.recovery_convergence_service.reconcile_cycle(
            project_id=project_id,
            source=RecoverySource.SCHEDULER,
            drive_admitted=drive_resumed,
        )
        return [
            d.identity_id
            for d in decisions
            if d.identity_type == "RUN" and d.status == RecoveryDecisionStatus.COMPLETED
        ]

    def tick(
        self, project_id: str | None = None, drive_admitted: bool = False
    ) -> list[SchedulerDecisionRecord]:
        """Execute one complete scheduler evaluation and admission cycle."""
        # Capture authoritative existing provider-health truth BEFORE probe/discovery
        # helpers may synthesize default records, so this tick's admission decisions
        # reflect the true (possibly UNKNOWN) state rather than fabricated AVAILABLE.
        self._admission_health_truth = {
            provider: self._safe_lookup_provider_health(provider) for provider in PRIMARY_PROVIDERS
        }

        # 0.0 Proactively probe unavailable providers to detect recovery without creating Runs/Jobs
        try:
            import asyncio

            try:
                asyncio.get_running_loop()
                # If running loop exists, run probe in background task or skip blocking
            except RuntimeError:
                asyncio.run(self.provider_health_service.probe_unavailable_providers())
        except Exception as exc:
            logger.warning("Provider health probe during tick encountered error: %s", exc)

        # 0. Canonical Recovery Convergence Cycle
        try:
            self.recovery_convergence_service.reconcile_cycle(
                project_id=project_id,
                source=RecoverySource.TICK,
                drive_admitted=drive_admitted,
            )
        except Exception as exc:
            logger.warning("Recovery convergence cycle during tick encountered error: %s", exc)

        # 0.1 Autonomous intake sweep for unprepared backlog items when auto_prepare is enabled
        try:
            self.intake_service.sweep_unprepared_backlog_items(project_id=project_id)
        except Exception as exc:
            logger.warning(f"Autonomous intake sweep error during scheduler tick: {exc}")

        # 1. Discover work items
        try:
            self.discovery_service.discover_work(project_id)
        except Exception as exc:
            logger.warning(f"Work discovery error during scheduler tick: {exc}")

        # 2. Retrieve all queue items
        items = self.uow.work_queue.list_all(project_id)

        # 3. Rank candidates
        ranked_candidates = self.rank_candidates(items)

        # 4. Evaluate admission for candidates up to available concurrency
        decision_records: list[SchedulerDecisionRecord] = []
        active_runs_count = len(self.uow.orchestration_runs.list_runs(is_active=True))
        available_slots = max(0, self.max_global_jobs - active_runs_count)

        for candidate in ranked_candidates:
            try:
                eval_result = self.evaluate_admission(candidate.project_id, candidate.change_name)
                if eval_result.decision == AdmissionDecisionKind.RUN and available_slots > 0:
                    dec, record, run = self.admit_work_item(
                        candidate.project_id, candidate.change_name, drive_admitted=drive_admitted
                    )
                    decision_records.append(record)
                    if dec == AdmissionDecision.ADMITTED:
                        available_slots -= 1
                elif eval_result.decision == AdmissionDecisionKind.DRAIN:
                    dec, record, run = self.admit_work_item(
                        candidate.project_id, candidate.change_name, drive_admitted=drive_admitted
                    )
                    decision_records.append(record)
                else:
                    # WAIT / NEEDS_HUMAN -> legacy REFUSED is a derived compatibility view
                    # only; the authoritative result remains eval_result.decision.
                    reason_code = eval_result.legacy_refusal_code
                    reason_summary = eval_result.rationale
                    if eval_result.decision == AdmissionDecisionKind.RUN and available_slots <= 0:
                        reason_code = AdmissionRefusalCode.GLOBAL_CONCURRENCY_LIMIT
                        reason_summary = f"Global concurrency limit reached ({self.max_global_jobs} active runs)."

                    record = SchedulerDecisionRecord(
                        project_id=candidate.project_id,
                        change_name=candidate.change_name,
                        github_issue_number=candidate.github_issue_number,
                        decision=AdmissionDecision.REFUSED,
                        reason_code=reason_code,
                        reason_summary=reason_summary,
                        priority_score=candidate.priority_score,
                        selected_implementer=eval_result.eligible_implementer,
                        operational_decision=eval_result.decision,
                        block_condition=eval_result.block_condition,
                        eligible_reviewer=eval_result.eligible_reviewer,
                        safe_executable_pair_exists=eval_result.safe_executable_pair_exists,
                        has_deterministic_eta=eval_result.has_deterministic_eta,
                        cooldown_until=eval_result.cooldown_until,
                        concurrency_snapshot={
                            "global_active": active_runs_count,
                            "max_global_jobs": self.max_global_jobs,
                        },
                        capacity_snapshot={"mode": self.mode.value},
                        evaluated_at=utc_now(),
                    )
                    self.uow.scheduler_decisions.save(record)
                    decision_records.append(record)
            except Exception as exc:
                logger.error(
                    f"Error evaluating candidate '{candidate.change_name}': {exc}",
                    exc_info=True,
                )
                record = SchedulerDecisionRecord(
                    project_id=candidate.project_id,
                    change_name=candidate.change_name,
                    github_issue_number=candidate.github_issue_number,
                    decision=AdmissionDecision.REFUSED,
                    reason_code=AdmissionRefusalCode.EVALUATION_ERROR,
                    reason_summary=f"Evaluation error: {exc}",
                    priority_score=candidate.priority_score,
                    evaluated_at=utc_now(),
                )
                self.uow.scheduler_decisions.save(record)
                decision_records.append(record)

        self.uow.commit()
        self._admission_health_truth = None
        return decision_records

    def get_status(self, project_id: str | None = None) -> SchedulerStatusView:
        """Get operational status view of the autonomous queue and scheduler."""
        items = self.uow.work_queue.list_all(project_id)
        ranked = self.rank_candidates(items)

        ready_count = len([i for i in items if i.admission_eligible])
        blocked_count = len(items) - ready_count
        active_runs = self.uow.orchestration_runs.list_runs(is_active=True)

        next_cand = None
        for r in ranked:
            if r.admission_eligible:
                next_cand = r
                break

        recent = self.uow.scheduler_decisions.list_recent(project_id, limit=20)

        health_dict = {}
        for h in self.uow.provider_health.list_all():
            health_dict[h.provider] = h.status.value

        return SchedulerStatusView(
            mode=self.mode,
            queue_depth=len(items),
            ready_count=ready_count,
            blocked_count=blocked_count,
            active_runs_count=len(active_runs),
            max_global_jobs=self.max_global_jobs,
            next_candidate=next_cand,
            recent_decisions=recent,
            provider_health=health_dict,
            evaluated_at=utc_now(),
        )
