"""Execution pipeline orchestration for implementation, complementary review, and budgeted drain fallback."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from minime.adapters.openrouter_adapter import OpenRouterAdapter, OpenRouterRequest
from minime.domain.enums import (
    AuditFindingSeverity,
    AuditRiskLevel,
    AuditStatus,
    EventType,
    JobStatus,
    ProviderHealthStatus,
    ProviderResultClass,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    AuditFinding,
    AuditRecord,
    Event,
    Job,
    JobLog,
    MetricFact,
    OpenRouterPricingSnapshot,
    Project,
    Review,
    ReviewFinding,
    utc_now,
)
from minime.services.audit_verdict_parser import parse_audit_result
from minime.services.budget_service import BudgetService
from minime.services.candidate_integrity import (
    validate_post_review_integrity,
    validate_pre_review_integrity,
    verify_post_audit,
    verify_pre_audit,
)
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.checks_runner import ChecksRunner
from minime.services.complementary_policy import validate_complementary_pair
from minime.services.deepseek_auditor_runner import (
    AuditorRunnerInterface,
    DeepSeekAuditorRunner,
    build_audit_prompt,
)
from minime.services.implementer_runner import (
    ImplementerRunnerInterface,
    runner_for_implementer,
)
from minime.services.model_independence_policy import ModelIndependencePolicy
from minime.services.openrouter_eligibility import OpenRouterEligibilityEvaluator
from minime.services.openspec_tasks import OpenSpecTaskTracker
from minime.services.provider_health_service import ProviderHealthService
from minime.services.provider_outcome_parser import ProviderOutcomeParser
from minime.services.review_verdict_parser import parse_review_verdict
from minime.services.reviewer_contract import build_reviewer_prompt
from minime.services.reviewer_runner import (
    ReviewerRunnerInterface,
    runner_for_reviewer,
)
from minime.services.reviewer_view import ReviewerViewManager
from minime.services.worktree_manager import WorktreeManager

EVENT_BY_STATUS = {
    JobStatus.QUEUED: EventType.JOB_QUEUED,
    JobStatus.RUNNING: EventType.JOB_RUNNING,
    JobStatus.CHECKS_RUNNING: EventType.JOB_CHECKS_RUNNING,
    JobStatus.CHECKS_PASSED: EventType.JOB_CHECKS_PASSED,
    JobStatus.CHECKS_FAILED: EventType.JOB_CHECKS_FAILED,
    JobStatus.REVIEW_RUNNING: EventType.JOB_REVIEW_RUNNING,
    JobStatus.AUDIT_RUNNING: EventType.JOB_AUDIT_RUNNING,
    JobStatus.READY_TO_MERGE: EventType.JOB_READY_TO_MERGE,
    JobStatus.AUDIT_BLOCKED: EventType.JOB_AUDIT_BLOCKED,
    JobStatus.CHANGES_REQUIRED: EventType.JOB_CHANGES_REQUIRED,
    JobStatus.WAITING_CAPACITY: EventType.JOB_WAITING_CAPACITY,
    JobStatus.RECOVERY_BLOCKED: EventType.RECOVERY_BLOCKED,
    JobStatus.FAILED: EventType.JOB_FAILED,
    JobStatus.CANCELLED: EventType.JOB_CANCELLED,
}


class ExecutionPipelineService:
    """Coordinates job state, isolated workspace, implementer execution, checks, complementary review, and fallback."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path,
        implementer_runner: ImplementerRunnerInterface | None = None,
        reviewer_runner: ReviewerRunnerInterface | None = None,
        auditor_runner: AuditorRunnerInterface | None = None,
        worktree_manager: WorktreeManager | None = None,
        reviewer_view_manager: ReviewerViewManager | None = None,
        checks_runner: ChecksRunner | None = None,
        task_tracker: OpenSpecTaskTracker | None = None,
        health_service: ProviderHealthService | None = None,
        lifecycle_service: CapacityLifecycleService | None = None,
        budget_service: BudgetService | None = None,
        openrouter_adapter: OpenRouterAdapter | None = None,
        independence_policy: ModelIndependencePolicy | None = None,
        eligibility_evaluator: OpenRouterEligibilityEvaluator | None = None,
        openrouter_api_key: str | None = None,
        implementer_timeout_seconds: int = 3600,
        reviewer_timeout_seconds: int = 3600,
    ):
        self.uow = uow
        self.project_root = Path(project_root)
        self.implementer_runner = implementer_runner
        self.reviewer_runner = reviewer_runner
        self.auditor_runner = auditor_runner
        self.worktree_manager = worktree_manager or WorktreeManager(
            self.project_root, uow=self.uow
        )
        self.reviewer_view_manager = (
            reviewer_view_manager or ReviewerViewManager(self.project_root)
        )
        self.checks_runner = checks_runner or ChecksRunner()
        self.task_tracker = task_tracker or OpenSpecTaskTracker(self.project_root)
        self.health_service = health_service or ProviderHealthService(self.uow)
        self.lifecycle_service = lifecycle_service or CapacityLifecycleService(
            self.uow, health_service=self.health_service
        )
        self.budget_service = budget_service or BudgetService(self.uow)
        self.openrouter_adapter = openrouter_adapter or OpenRouterAdapter()
        self.independence_policy = independence_policy or ModelIndependencePolicy()
        self.eligibility_evaluator = eligibility_evaluator or OpenRouterEligibilityEvaluator()
        self.openrouter_api_key = openrouter_api_key
        self.implementer_timeout_seconds = implementer_timeout_seconds
        self.reviewer_timeout_seconds = reviewer_timeout_seconds
        self.default_implementer_model = "anthropic/claude-3.5-sonnet"
        self.allowed_reviewer_models = [
            "openai/gpt-4o",
            "meta-llama/llama-3.3-70b-instruct",
            "mistralai/mistral-large",
        ]

    def queue_job(self, project_id: str, change_name: str) -> Job:
        project = self._require_project(project_id)
        change = self.uow.changes.get_by_name(project_id, change_name)
        if not change or change.last_readiness_status != ReadinessState.READY:
            raise ValueError(
                f"Change '{change_name}' for project '{project_id}' is not READY."
            )
        can_admit, admit_err = self.lifecycle_service.can_admit_change(project_id)
        if not can_admit:
            raise ValueError(f"Cannot admit change '{change_name}': {admit_err}")

        job = Job(
            project_id=project_id,
            change_name=change_name,
            implementer_role=project.implementer,
        )
        self.uow.jobs.save(job)
        self._save_event(
            EventType.JOB_QUEUED,
            job,
            {"status": JobStatus.QUEUED.value, "implementer": project.implementer},
        )
        self.uow.commit()
        return job

    async def run_job(self, project_id: str, change_name: str) -> Job:
        job = self.queue_job(project_id, change_name)
        return await self.execute_queued_job(job.job_id)

    async def execute_queued_job(self, job_id: str) -> Job:
        job = self._require_job(job_id)
        project = self._require_project(job.project_id)
        worktree_created = False
        readonly_view_created = False
        phase_started = utc_now()
        check_run_results = []
        implementer_fallback_used = False
        fallback_implementer_model: str | None = None

        try:
            # Check implementer capacity availability before creating worktree / starting implementer
            imp_health = self.health_service.get_health(project.implementer)
            is_primary_imp_available = imp_health.status == ProviderHealthStatus.AVAILABLE

            if not is_primary_imp_available:
                # Primary implementer is exhausted / unavailable. Check for OpenRouter fallback eligibility.
                dual_exhausted = self._is_dual_primary_exhausted(project)
                if not dual_exhausted:
                    # Single primary exhaustion: DRAIN rules prohibit fallback when other primary is available
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        project.implementer,
                        f"Primary implementer '{project.implementer}' is {imp_health.status.value}",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": project.implementer, "status": imp_health.status.value},
                    )
                    self.uow.commit()
                    return job

                # Dual-primary exhaustion: Evaluate 10-point OpenRouter fallback eligibility
                sched_status = self.lifecycle_service.get_scheduler_status(project.project_id)
                policy, headroom = self.budget_service.get_headroom(project.project_id)
                primary_health_records = self.health_service.list_all_health()

                elig = self.eligibility_evaluator.evaluate_10_points(
                    scheduler_mode=sched_status.mode,
                    job=job,
                    role="implementer",
                    is_new_ready_change=False,
                    primary_health_records=primary_health_records,
                    project=project,
                    policy=policy,
                    headroom=headroom,
                    model_identity_valid=True,
                    candidate_integrity_valid=True,
                    pipeline_invariants_valid=True,
                )

                if not elig.eligible:
                    self._save_event(
                        EventType.FALLBACK_DENIED,
                        job,
                        {"role": "implementer", "reason": elig.denial_reason, "reasons": elig.reasons},
                    )
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        f"OpenRouter fallback ineligible: {elig.denial_reason}",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "status": "fallback_ineligible"},
                    )
                    self.uow.commit()
                    return job

                # Fallback is eligible for implementer!
                implementer_fallback_used = True
                fallback_implementer_model = self.default_implementer_model

            # Transition to RUNNING if not already in RUNNING status
            if job.status != JobStatus.RUNNING:
                job = self._transition(job, JobStatus.RUNNING)
            try:
                worktree = await self.worktree_manager.create_worktree(
                    job.job_id,
                    job.change_name,
                    project.base_branch,
                    project_id=project.project_id,
                )
            except TypeError:
                worktree = await self.worktree_manager.create_worktree(
                    job.job_id, job.change_name, project.base_branch
                )
            worktree_created = True
            job.base_sha = worktree.base_sha
            self.uow.jobs.save(job)
            self._log(job.job_id, "system", f"Created worktree {worktree.path}")
            self.uow.commit()

            worktree_task_tracker = OpenSpecTaskTracker(worktree.path)
            prompt_context = worktree_task_tracker.format_prompt_context(
                project.openspec_path, job.change_name
            )

            if implementer_fallback_used and fallback_implementer_model:
                # OpenRouter fallback implementer path
                canonical_imp = self.independence_policy.registry.normalize(fallback_implementer_model)
                canonical_name = canonical_imp.canonical_name if canonical_imp else fallback_implementer_model
                snapshot = self._ensure_pricing_snapshot(fallback_implementer_model, canonical_name)

                prompt_upper = max(len(prompt_context.split()) * 2, 2000)
                max_output = 4096

                # Atomic reservation on PostgreSQL policy before HTTP dispatch
                reservation, denial_reason, headroom = self.budget_service.reserve_budget(
                    project_id=project.project_id,
                    job_id=job.job_id,
                    change_id=job.change_name,
                    role="implementer",
                    canonical_model_identity=canonical_name,
                    pricing_snapshot=snapshot,
                    prompt_token_upper_bound=prompt_upper,
                    max_output_tokens=max_output,
                )
                if not reservation:
                    self._save_event(
                        EventType.FALLBACK_DENIED,
                        job,
                        {"role": "implementer", "reason": denial_reason},
                    )
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        f"Fallback budget reservation denied: {denial_reason}",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "status": "budget_denied"},
                    )
                    self.uow.commit()
                    return job

                # COMMIT reservation before external HTTP call
                self.uow.commit()

                self._save_event(
                    EventType.FALLBACK_MODEL_SELECTED,
                    job,
                    {"role": "implementer", "model": fallback_implementer_model, "canonical_identity": canonical_name},
                )
                self._save_event(
                    EventType.FALLBACK_INVOKED,
                    job,
                    {"role": "implementer", "model": fallback_implementer_model, "reservation_id": reservation.reservation_id},
                )
                self.uow.commit()

                api_key = self.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "mock-openrouter-key")
                openrouter_res, meta = await self.openrouter_adapter.execute(
                    OpenRouterRequest(
                        model=fallback_implementer_model,
                        canonical_model_identity=canonical_name,
                        prompt=prompt_context,
                        max_output_tokens=max_output,
                        authorized_max_output_tokens=max_output,
                        api_key=api_key,
                        pricing_snapshot=snapshot,
                        pricing_snapshot_id=snapshot.snapshot_id,
                        timeout_seconds=self.implementer_timeout_seconds,
                    )
                )

                if openrouter_res.result_class == ProviderResultClass.SUCCESS:
                    prompt_tok = meta.get("prompt_tokens") or (prompt_upper // 2)
                    comp_tok = meta.get("completion_tokens") or 500
                    tot_tok = meta.get("total_tokens") or (prompt_tok + comp_tok)
                    actual_cost = meta.get("actual_cost_usd")
                    if actual_cost is None:
                        actual_cost = (
                            Decimal(prompt_tok) * snapshot.prompt_price_per_token
                            + Decimal(comp_tok) * snapshot.output_price_per_token
                            + snapshot.additional_cost_per_request
                        )
                    self.budget_service.settle_reservation(
                        reservation_id=reservation.reservation_id,
                        actual_cost_usd=actual_cost,
                        prompt_tokens=prompt_tok,
                        completion_tokens=comp_tok,
                        total_tokens=tot_tok,
                    )
                    self.uow.commit()
                    self._log(job.job_id, "stdout", openrouter_res.summary or "OpenRouter implementer succeeded")
                else:
                    # Mark unresolved and fail-closed
                    self.budget_service.mark_unresolved(reservation.reservation_id)
                    self.uow.commit()
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        openrouter_res.summary or "OpenRouter implementer fallback failed",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "error": openrouter_res.summary},
                    )
                    self.uow.commit()
                    return job
            else:
                # Primary implementer runner execution
                runner = self.implementer_runner or runner_for_implementer(project.implementer)
                result = await runner.run(
                    worktree.path,
                    prompt_context,
                    timeout_seconds=self.implementer_timeout_seconds,
                )
                for line in result.stdout:
                    self._log(job.job_id, "stdout", line)
                for line in result.stderr:
                    self._log(job.job_id, "stderr", line)
                self.uow.metrics.save(
                    MetricFact(
                        metric_name="implementer_duration_ms",
                        project_id=job.project_id,
                        change_id=job.change_name,
                        duration_ms=result.duration_ms,
                        details={"job_id": job.job_id},
                    )
                )

                # Record implementer outcome for primary provider
                imp_outcome = ProviderOutcomeParser.parse_runner_output(
                    provider=project.implementer,
                    role="implementer",
                    model=None,
                    exit_code=result.exit_code,
                    timed_out=result.timed_out,
                    stdout_lines=result.stdout,
                    stderr_lines=result.stderr,
                )
                self.health_service.record_outcome(imp_outcome)

                if imp_outcome.result_class in {
                    ProviderResultClass.QUOTA_LIMIT,
                    ProviderResultClass.RATE_LIMIT,
                }:
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        project.implementer,
                        imp_outcome.summary or f"Capacity exhausted on {project.implementer}",
                        imp_outcome.capacity_reset_at,
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {
                            "waiting_provider": project.implementer,
                            "reset_at": imp_outcome.capacity_reset_at.isoformat()
                            if imp_outcome.capacity_reset_at
                            else None,
                        },
                    )
                    self.uow.commit()
                    return job

                if result.timed_out:
                    self._save_event(
                        EventType.JOB_TIMEOUT,
                        job,
                        {"timeout_seconds": self.implementer_timeout_seconds},
                    )
                    raise RuntimeError("Implementer execution timed out.")
                if result.exit_code != 0:
                    raise RuntimeError(f"Implementer exited with code {result.exit_code}.")

            job.candidate_sha = await self.worktree_manager.current_sha(worktree.path)
            self.uow.jobs.save(job)

            incomplete = worktree_task_tracker.incomplete_tasks(
                project.openspec_path, job.change_name
            )
            if incomplete:
                self._save_event(
                    EventType.INCOMPLETE_TASKS,
                    job,
                    {"remaining_task_ids": [task.task_id for task in incomplete]},
                )
                raise RuntimeError("OpenSpec tasks remain incomplete.")

            # Deterministic checks stage
            checks_started = utc_now()
            job = self._transition(job, JobStatus.CHECKS_RUNNING)
            check_run = await self.checks_runner.run(
                job.job_id, project.checks, worktree.path
            )
            check_run_results = check_run.results
            for check_result in check_run.results:
                self.uow.check_results.save(check_result)
            checks_duration = int((utc_now() - checks_started).total_seconds() * 1000)
            self.uow.metrics.save(
                MetricFact(
                    metric_name="checks_duration_ms",
                    project_id=job.project_id,
                    change_id=job.change_name,
                    duration_ms=checks_duration,
                    details={"job_id": job.job_id},
                )
            )
            self.uow.commit()

            if not check_run.passed:
                self._transition(job, JobStatus.CHECKS_FAILED)
                return self._require_job(job.job_id)

            job = self._transition(job, JobStatus.CHECKS_PASSED)

            # Complementary review stage
            rev_health = self.health_service.get_health(project.reviewer)
            is_primary_rev_available = rev_health.status == ProviderHealthStatus.AVAILABLE
            reviewer_fallback_used = False
            selected_reviewer_model: str | None = None
            rev_identity = None

            if not is_primary_rev_available:
                # Primary reviewer is unavailable. Check dual-primary exhaustion.
                dual_exhausted = self._is_dual_primary_exhausted(project)
                if not dual_exhausted:
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        project.reviewer,
                        f"Primary reviewer '{project.reviewer}' is {rev_health.status.value}",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": project.reviewer, "status": rev_health.status.value},
                    )
                    self.uow.commit()
                    return job

                # Dual exhaustion: evaluate 10-point OpenRouter fallback eligibility for reviewer
                sched_status = self.lifecycle_service.get_scheduler_status(project.project_id)
                policy, headroom = self.budget_service.get_headroom(project.project_id)
                primary_health_records = self.health_service.list_all_health()

                elig = self.eligibility_evaluator.evaluate_10_points(
                    scheduler_mode=sched_status.mode,
                    job=job,
                    role="reviewer",
                    is_new_ready_change=False,
                    primary_health_records=primary_health_records,
                    project=project,
                    policy=policy,
                    headroom=headroom,
                    model_identity_valid=True,
                    candidate_integrity_valid=True,
                    pipeline_invariants_valid=True,
                )

                if not elig.eligible:
                    self._save_event(
                        EventType.FALLBACK_DENIED,
                        job,
                        {"role": "reviewer", "reason": elig.denial_reason, "reasons": elig.reasons},
                    )
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        f"OpenRouter fallback ineligible: {elig.denial_reason}",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "status": "fallback_ineligible"},
                    )
                    self.uow.commit()
                    return job

                # Canonical Model Independence Check
                effective_imp_model = fallback_implementer_model or project.implementer
                selected_reviewer_model, rev_identity = self.independence_policy.select_independent_reviewer(
                    effective_imp_model, self.allowed_reviewer_models
                )

                if not selected_reviewer_model or not rev_identity:
                    # Model collision / unprovable distinct identity: FAIL CLOSED
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        "DISTINCT_REVIEWER_UNAVAILABLE",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "reason": "DISTINCT_REVIEWER_UNAVAILABLE"},
                    )
                    self.uow.commit()
                    return job

                reviewer_fallback_used = True

            if not reviewer_fallback_used:
                # Primary complementary pair policy validation
                valid_pair, pair_err = validate_complementary_pair(
                    project.implementer, project.reviewer
                )
                if not valid_pair:
                    self._save_event(
                        EventType.REVIEW_POLICY_VIOLATION,
                        job,
                        {
                            "error": pair_err,
                            "implementer": project.implementer,
                            "reviewer": project.reviewer,
                        },
                    )
                    raise RuntimeError(pair_err or "Invalid complementary pair.")

            # Pre-review candidate integrity validation
            valid_pre, pre_err = validate_pre_review_integrity(
                worktree.path,
                job.candidate_sha,
                job.base_sha,
                base_branch=project.base_branch,
                repo_root_path=self.project_root,
                checks_passed=True,
            )
            if not valid_pre:
                self._save_event(
                    EventType.CANDIDATE_SHA_MISMATCH,
                    job,
                    {"error": pre_err},
                )
                raise RuntimeError(pre_err or "Pre-review candidate integrity failure.")

            # Create isolated read-only reviewer workspace snapshot
            readonly_view = self.reviewer_view_manager.create_readonly_view(
                worktree.path, job.job_id
            )
            readonly_view_created = True

            # Transition to REVIEW_RUNNING and persist Review record
            job = self._transition(job, JobStatus.REVIEW_RUNNING)
            effective_reviewer_role = (
                f"openrouter:{selected_reviewer_model}" if reviewer_fallback_used else project.reviewer
            )
            review = Review(
                job_id=job.job_id,
                project_id=job.project_id,
                change_name=job.change_name,
                reviewer_role=effective_reviewer_role,
                candidate_sha=job.candidate_sha or "",
                base_sha=job.base_sha or "",
                status=ReviewStatus.REVIEW_RUNNING,
            )
            self.uow.reviews.save(review)
            self.uow.commit()

            review_prompt = build_reviewer_prompt(
                project=project,
                change_name=job.change_name,
                job_id=job.job_id,
                candidate_sha=job.candidate_sha or "",
                base_sha=job.base_sha or "",
                candidate_worktree_path=readonly_view,
                checks_results=check_run_results,
            )

            verdict_payload = None

            if reviewer_fallback_used and selected_reviewer_model and rev_identity:
                # OpenRouter fallback reviewer execution
                snapshot = self._ensure_pricing_snapshot(selected_reviewer_model, rev_identity.canonical_name)
                prompt_upper = max(len(review_prompt.split()) * 2, 2000)
                max_output = 4096

                # Atomic reservation on PostgreSQL policy before HTTP dispatch
                reservation, denial_reason, headroom = self.budget_service.reserve_budget(
                    project_id=project.project_id,
                    job_id=job.job_id,
                    change_id=job.change_name,
                    role="reviewer",
                    canonical_model_identity=rev_identity.canonical_name,
                    pricing_snapshot=snapshot,
                    prompt_token_upper_bound=prompt_upper,
                    max_output_tokens=max_output,
                )
                if not reservation:
                    self._save_event(
                        EventType.FALLBACK_DENIED,
                        job,
                        {"role": "reviewer", "reason": denial_reason},
                    )
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=f"Budget reservation denied: {denial_reason}",
                    )
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        f"Fallback budget reservation denied: {denial_reason}",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "status": "budget_denied"},
                    )
                    self.uow.commit()
                    return job

                # COMMIT reservation before external HTTP call
                self.uow.commit()

                self._save_event(
                    EventType.FALLBACK_MODEL_SELECTED,
                    job,
                    {"role": "reviewer", "model": selected_reviewer_model, "canonical_identity": rev_identity.canonical_name},
                )
                self._save_event(
                    EventType.FALLBACK_INVOKED,
                    job,
                    {"role": "reviewer", "model": selected_reviewer_model, "reservation_id": reservation.reservation_id},
                )
                self.uow.commit()

                api_key = self.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "mock-openrouter-key")
                openrouter_res, meta = await self.openrouter_adapter.execute(
                    OpenRouterRequest(
                        model=selected_reviewer_model,
                        canonical_model_identity=rev_identity.canonical_name,
                        prompt=review_prompt,
                        max_output_tokens=max_output,
                        authorized_max_output_tokens=max_output,
                        api_key=api_key,
                        pricing_snapshot=snapshot,
                        pricing_snapshot_id=snapshot.snapshot_id,
                        timeout_seconds=self.reviewer_timeout_seconds,
                    )
                )

                if openrouter_res.result_class == ProviderResultClass.SUCCESS:
                    prompt_tok = meta.get("prompt_tokens") or (prompt_upper // 2)
                    comp_tok = meta.get("completion_tokens") or 500
                    tot_tok = meta.get("total_tokens") or (prompt_tok + comp_tok)
                    actual_cost = meta.get("actual_cost_usd")
                    if actual_cost is None:
                        actual_cost = (
                            Decimal(prompt_tok) * snapshot.prompt_price_per_token
                            + Decimal(comp_tok) * snapshot.output_price_per_token
                            + snapshot.additional_cost_per_request
                        )
                    self.budget_service.settle_reservation(
                        reservation_id=reservation.reservation_id,
                        actual_cost_usd=actual_cost,
                        prompt_tokens=prompt_tok,
                        completion_tokens=comp_tok,
                        total_tokens=tot_tok,
                    )
                    self.uow.commit()

                    raw_lines = openrouter_res.raw_output.splitlines() if openrouter_res.raw_output else []
                    for line in raw_lines:
                        self._log(job.job_id, "stdout", line)
                    try:
                        verdict_payload = parse_review_verdict(raw_lines)
                    except Exception as e:
                        err_msg = f"Malformed OpenRouter review output: {e}"
                        self.uow.reviews.transition(
                            review.review_id, ReviewStatus.REVIEW_FAILED.value, error_message=err_msg
                        )
                        self._save_event(EventType.MALFORMED_REVIEW_OUTPUT, job, {"error": err_msg})
                        self.uow.commit()
                        raise RuntimeError(err_msg) from e
                else:
                    # Mark unresolved and pause job
                    self.budget_service.mark_unresolved(reservation.reservation_id)
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=openrouter_res.summary,
                    )
                    self.uow.commit()
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        openrouter_res.summary or "OpenRouter reviewer fallback failed",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "error": openrouter_res.summary},
                    )
                    self.uow.commit()
                    return job
            else:
                # Primary reviewer runner execution
                reviewer = self.reviewer_runner or runner_for_reviewer(project.reviewer)
                review_result = await reviewer.run(
                    readonly_view,
                    review_prompt,
                    timeout_seconds=self.reviewer_timeout_seconds,
                )

                for line in review_result.stdout:
                    self._log(job.job_id, "stdout", line)
                for line in review_result.stderr:
                    self._log(job.job_id, "stderr", line)

                self.uow.metrics.save(
                    MetricFact(
                        metric_name="review_duration_ms",
                        project_id=job.project_id,
                        change_id=job.change_name,
                        duration_ms=review_result.duration_ms,
                        details={"job_id": job.job_id, "reviewer": project.reviewer},
                    )
                )

                domain_verdict_valid = False
                try:
                    verdict_payload = parse_review_verdict(review_result.stdout)
                    domain_verdict_valid = True
                except Exception:
                    pass

                rev_outcome = ProviderOutcomeParser.parse_runner_output(
                    provider=project.reviewer,
                    role="reviewer",
                    model=None,
                    exit_code=review_result.exit_code,
                    timed_out=review_result.timed_out,
                    stdout_lines=review_result.stdout,
                    stderr_lines=review_result.stderr,
                    domain_verdict_valid=domain_verdict_valid,
                )
                self.health_service.record_outcome(rev_outcome)

                if rev_outcome.result_class in {
                    ProviderResultClass.QUOTA_LIMIT,
                    ProviderResultClass.RATE_LIMIT,
                }:
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        project.reviewer,
                        rev_outcome.summary or f"Capacity exhausted on {project.reviewer}",
                        rev_outcome.capacity_reset_at,
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {
                            "waiting_provider": project.reviewer,
                            "reset_at": rev_outcome.capacity_reset_at.isoformat()
                            if rev_outcome.capacity_reset_at
                            else None,
                        },
                    )
                    self.uow.commit()
                    return job

                if review_result.timed_out:
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_TIMED_OUT.value,
                        error_message=f"Reviewer execution timed out after {self.reviewer_timeout_seconds} seconds.",
                    )
                    self._save_event(
                        EventType.REVIEW_TIMEOUT,
                        job,
                        {"timeout_seconds": self.reviewer_timeout_seconds},
                    )
                    self.uow.commit()
                    raise RuntimeError("Reviewer execution timed out.")

                if review_result.exit_code != 0:
                    err_msg = f"Reviewer process exited with code {review_result.exit_code}."
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=err_msg,
                    )
                    self.uow.commit()
                    raise RuntimeError(err_msg)

            # Post-review non-mutation integrity validation on original worktree
            valid_post, post_err = validate_post_review_integrity(
                worktree.path, job.candidate_sha or ""
            )
            if not valid_post:
                self.uow.reviews.transition(
                    review.review_id,
                    ReviewStatus.REVIEW_FAILED.value,
                    error_message=post_err,
                )
                self._save_event(
                    EventType.UNAUTHORIZED_REVIEWER_MUTATION,
                    job,
                    {"error": post_err},
                )
                self.uow.commit()
                raise RuntimeError(post_err or "Post-review mutation detected.")

            # Parse structured review verdict strictly if not already parsed
            if not verdict_payload:
                try:
                    verdict_payload = parse_review_verdict(review_result.stdout)
                except Exception as parse_exc:
                    parse_err = f"Malformed review output: {parse_exc}"
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=parse_err,
                    )
                    self._save_event(
                        EventType.MALFORMED_REVIEW_OUTPUT,
                        job,
                        {"error": parse_err},
                    )
                    self.uow.commit()
                    raise RuntimeError(parse_err) from parse_exc

            # Apply review verdict transition
            if verdict_payload.verdict == ReviewVerdict.READY_TO_MERGE:
                self.uow.reviews.transition(
                    review.review_id,
                    ReviewStatus.REVIEW_COMPLETED.value,
                    verdict=ReviewVerdict.READY_TO_MERGE.value,
                    summary=verdict_payload.summary,
                )
                self.uow.commit()
                job = await self._run_audit_stage(
                    job=job,
                    project=project,
                    worktree_path=worktree.path,
                    check_run_results=check_run_results,
                    review_id=review.review_id,
                )
            elif verdict_payload.verdict == ReviewVerdict.CHANGES_REQUIRED:
                self.uow.reviews.transition(
                    review.review_id,
                    ReviewStatus.REVIEW_COMPLETED.value,
                    verdict=ReviewVerdict.CHANGES_REQUIRED.value,
                    summary=verdict_payload.summary,
                )
                for item in verdict_payload.findings:
                    finding = ReviewFinding(
                        review_id=review.review_id,
                        severity=item.severity,
                        location=item.location,
                        violated_requirement=item.violated_requirement,
                        expected_correction=item.expected_correction,
                    )
                    self.uow.review_findings.save(finding)
                self.uow.commit()
                self._transition(job, JobStatus.CHANGES_REQUIRED)

        except Exception as exc:
            latest = self._require_job(job.job_id)
            if latest.status not in {
                JobStatus.CHECKS_FAILED,
                JobStatus.READY_TO_MERGE,
                JobStatus.AUDIT_BLOCKED,
                JobStatus.CHANGES_REQUIRED,
                JobStatus.WAITING_CAPACITY,
                JobStatus.RECOVERY_BLOCKED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                self._transition(latest, JobStatus.FAILED, str(exc))
        finally:
            if readonly_view_created:
                self.reviewer_view_manager.cleanup_readonly_view(job.job_id)
            if worktree_created:
                try:
                    await self.worktree_manager.cleanup_worktree(
                        job.job_id, project_id=job.project_id
                    )
                except TypeError:
                    await self.worktree_manager.cleanup_worktree(job.job_id)
            latest = self._require_job(job.job_id)
            if latest.status in {
                JobStatus.READY_TO_MERGE,
                JobStatus.AUDIT_BLOCKED,
                JobStatus.CHANGES_REQUIRED,
                JobStatus.CHECKS_FAILED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                total_duration = int(
                    (utc_now() - phase_started).total_seconds() * 1000
                )
                self.uow.metrics.save(
                    MetricFact(
                        metric_name="total_duration_ms",
                        project_id=latest.project_id,
                        change_id=latest.change_name,
                        duration_ms=total_duration,
                        details={
                            "job_id": latest.job_id,
                            "status": latest.status.value,
                        },
                    )
                )
                self.uow.commit()
        return self._require_job(job.job_id)

    async def _run_audit_stage(
        self,
        job: Job,
        project: Project,
        worktree_path: Path,
        check_run_results: list,
        review_id: str,
    ) -> Job:
        """Execute DeepSeek Direct audit. OpenRouter is never used for audit."""
        review = self.uow.reviews.get_by_id(review_id)
        review_findings = (
            self.uow.review_findings.list_by_review(review_id) if review else []
        )
        pre_ok, pre_err = verify_pre_audit(
            worktree_path=worktree_path,
            job=job,
            review=review,
            checks_results=check_run_results,
            base_branch=project.base_branch,
            repo_root_path=self.project_root,
        )
        if not pre_ok:
            self._save_event(EventType.CANDIDATE_SHA_MISMATCH, job, {"error": pre_err})
            raise RuntimeError(pre_err or "Pre-audit integrity failure.")

        job = self._transition(job, JobStatus.AUDIT_RUNNING)
        audit = AuditRecord(
            job_id=job.job_id,
            project_id=job.project_id,
            change_name=job.change_name,
            candidate_sha=job.candidate_sha or "",
            base_sha=job.base_sha or "",
            review_id=review.review_id if review else None,
            review_verdict=review.verdict if review else None,
            status=AuditStatus.AUDIT_RUNNING,
        )
        self.uow.audits.save(audit)
        self.uow.commit()

        audit_view_created = False
        try:
            audit_view = self.reviewer_view_manager.create_readonly_view(
                worktree_path, f"audit-{job.job_id}"
            )
            audit_view_created = True
            prompt = build_audit_prompt(
                project=project,
                change_name=job.change_name,
                job_id=job.job_id,
                audit_id=audit.audit_id,
                candidate_sha=job.candidate_sha or "",
                base_sha=job.base_sha or "",
                audit_view_path=audit_view,
                checks_results=check_run_results,
                review=review,
                review_findings=review_findings,
            )
            runner = self.auditor_runner or DeepSeekAuditorRunner()
            result = await runner.run(
                audit_view,
                prompt,
                timeout_seconds=self.reviewer_timeout_seconds,
            )
            for line in result.output:
                self._log(job.job_id, "audit", line)
            self.uow.metrics.save(
                MetricFact(
                    metric_name="audit_duration_ms",
                    project_id=job.project_id,
                    change_id=job.change_name,
                    duration_ms=result.duration_ms,
                    details={
                        "job_id": job.job_id,
                        "audit_id": audit.audit_id,
                        "provider": result.provider,
                        "model": result.model,
                    },
                )
            )

            if result.timed_out:
                self.uow.audits.transition(
                    audit.audit_id,
                    AuditStatus.AUDIT_TIMED_OUT.value,
                    error_message=result.error_message
                    or f"DeepSeek audit timed out after {self.reviewer_timeout_seconds} seconds.",
                )
                self._save_event(
                    EventType.AUDIT_TIMEOUT,
                    job,
                    {"audit_id": audit.audit_id, "provider": "deepseek"},
                )
                self.uow.commit()
                raise RuntimeError("DeepSeek audit timed out.")

            if result.exit_code != 0:
                err = result.error_message or f"DeepSeek audit failed with code {result.exit_code}."
                self.uow.audits.transition(
                    audit.audit_id,
                    AuditStatus.AUDIT_FAILED.value,
                    error_message=err,
                )
                self._save_event(
                    EventType.JOB_AUDIT_FAILED,
                    job,
                    {"audit_id": audit.audit_id, "error": err},
                )
                self.uow.commit()
                raise RuntimeError(err)

            post_ok, post_err = verify_post_audit(worktree_path, job.candidate_sha or "")
            if not post_ok:
                self.uow.audits.transition(
                    audit.audit_id,
                    AuditStatus.AUDIT_FAILED.value,
                    error_message=post_err,
                )
                self._save_event(
                    EventType.UNAUTHORIZED_AUDITOR_MUTATION,
                    job,
                    {"audit_id": audit.audit_id, "error": post_err},
                )
                self.uow.commit()
                raise RuntimeError(post_err or "Post-audit mutation detected.")

            try:
                audit_result = parse_audit_result(result.output)
            except Exception as exc:
                err = f"Malformed audit output: {exc}"
                self.uow.audits.transition(
                    audit.audit_id,
                    AuditStatus.AUDIT_FAILED.value,
                    error_message=err,
                )
                self._save_event(
                    EventType.AUDIT_MALFORMED_OUTPUT,
                    job,
                    {"audit_id": audit.audit_id, "error": err},
                )
                self.uow.commit()
                raise RuntimeError(err) from exc

            has_blocking_finding = any(
                f.severity
                in {AuditFindingSeverity.HIGH, AuditFindingSeverity.CRITICAL}
                for f in audit_result.findings
            )
            blocking = audit_result.risk in {
                AuditRiskLevel.HIGH,
                AuditRiskLevel.CRITICAL,
            } or has_blocking_finding
            audit_status = (
                AuditStatus.AUDIT_BLOCKED if blocking else AuditStatus.AUDIT_COMPLETED
            )
            self.uow.audits.transition(
                audit.audit_id,
                audit_status.value,
                risk=audit_result.risk.value,
                summary=audit_result.summary,
            )
            for item in audit_result.findings:
                self.uow.audit_findings.save(
                    AuditFinding(
                        audit_id=audit.audit_id,
                        severity=item.severity,
                        category=item.category,
                        message=item.message,
                        file=item.file,
                        location=item.location,
                    )
                )
            event_type = (
                EventType.JOB_AUDIT_BLOCKED
                if blocking
                else EventType.JOB_AUDIT_COMPLETED
            )
            self._save_event(
                event_type,
                job,
                {
                    "audit_id": audit.audit_id,
                    "risk": audit_result.risk.value,
                    "findings": len(audit_result.findings),
                },
            )
            self.uow.commit()
            return self._transition(
                job, JobStatus.AUDIT_BLOCKED if blocking else JobStatus.READY_TO_MERGE
            )
        except Exception as exc:
            latest_audit = self.uow.audits.get_by_id(audit.audit_id)
            if latest_audit and latest_audit.status not in {
                AuditStatus.AUDIT_COMPLETED,
                AuditStatus.AUDIT_BLOCKED,
                AuditStatus.AUDIT_FAILED,
                AuditStatus.AUDIT_TIMED_OUT,
            }:
                err = str(exc)
                self.uow.audits.transition(
                    audit.audit_id,
                    AuditStatus.AUDIT_FAILED.value,
                    error_message=err,
                )
                self._save_event(
                    EventType.JOB_AUDIT_FAILED,
                    job,
                    {"audit_id": audit.audit_id, "error": err},
                )
                self.uow.commit()
            raise
        finally:
            if audit_view_created:
                self.reviewer_view_manager.cleanup_readonly_view(f"audit-{job.job_id}")

    def _is_dual_primary_exhausted(self, project: Project) -> bool:
        """Check if both primary providers (Codex and Antigravity) are exhausted / unavailable."""
        all_health = self.health_service.list_all_health()
        codex_h = next((h for h in all_health if h.provider == "codex"), None)
        agy_h = next((h for h in all_health if h.provider == "antigravity"), None)
        codex_unavail = codex_h is not None and codex_h.status != ProviderHealthStatus.AVAILABLE
        agy_unavail = agy_h is not None and agy_h.status != ProviderHealthStatus.AVAILABLE
        return codex_unavail and agy_unavail

    def _ensure_pricing_snapshot(self, model: str, canonical_name: str) -> OpenRouterPricingSnapshot:
        """Retrieve existing or create pinned default pricing snapshot for model."""
        snapshot_id = f"openrouter:{model}:pinned"
        existing = self.uow.pricing_snapshots.get_by_id(snapshot_id)
        if existing:
            return existing

        # Default standard token prices if not already persisted
        if "claude" in model:
            prompt_price = 0.000003  # $3/M
            output_price = 0.000015  # $15/M
        elif "gpt-4o" in model:
            prompt_price = 0.0000025  # $2.50/M
            output_price = 0.000010  # $10/M
        else:
            prompt_price = 0.0000005  # $0.50/M
            output_price = 0.0000015  # $1.50/M

        snapshot = OpenRouterPricingSnapshot(
            id=snapshot_id,
            canonical_model_identity=canonical_name,
            routed_model_identity=model,
            prompt_price_per_token=prompt_price,
            output_price_per_token=output_price,
            additional_cost_per_request=0.0,
            currency="USD",
            source="pinned_default",
            observed_at=utc_now(),
            created_at=utc_now(),
        )
        self.uow.pricing_snapshots.save(snapshot)
        return snapshot

    def _require_project(self, project_id: str) -> Project:
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")
        return project

    def _require_job(self, job_id: str) -> Job:
        job = self.uow.jobs.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found.")
        return job

    def _transition(
        self, job: Job, status: JobStatus, error_message: str | None = None
    ) -> Job:
        updated = self.uow.jobs.transition(
            job.job_id, status.value, error_message=error_message
        )
        event_type = EVENT_BY_STATUS[status]
        self._save_event(
            event_type, updated, {"status": status.value, "error": error_message}
        )
        self.uow.commit()
        return updated

    def _save_event(self, event_type: EventType, job: Job, payload: dict) -> None:
        self.uow.events.save(
            Event(
                event_type=event_type,
                project_id=job.project_id,
                change_id=job.change_name,
                operation_id=job.job_id,
                payload={"job_id": job.job_id, **payload},
            )
        )

    def _log(self, job_id: str, stream: str, message: str) -> None:
        self.uow.job_logs.save(JobLog(job_id=job_id, stream=stream, message=message))
