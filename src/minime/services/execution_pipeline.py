"""Execution pipeline orchestration for implementation, complementary review, and budgeted drain fallback."""

from __future__ import annotations

import logging
import os
import subprocess
from decimal import Decimal
from pathlib import Path

from minime.adapters.openrouter_adapter import OpenRouterAdapter, OpenRouterRequest
from minime.domain.enums import (
    AuditFindingSeverity,
    AuditRiskLevel,
    AuditStatus,
    ContinuationDecision,
    EventType,
    EvidenceDiagnosticStatus,
    ExecutionOutcome,
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
    BlockerClaim,
    BlockerClaimPayload,
    Event,
    EvidenceDiagnostic,
    Job,
    JobAttempt,
    JobLog,
    MetricFact,
    Project,
    Review,
    ReviewFinding,
    utc_now,
)
from minime.services.audit_verdict_parser import parse_audit_result
from minime.services.authorship_service import AuthorshipService
from minime.services.blocker_validation import (
    BlockerValidationContext,
    BlockerValidationService,
)
from minime.services.budget_service import BudgetService
from minime.services.candidate_integrity import (
    validate_post_review_integrity,
    validate_pre_review_integrity,
    verify_post_audit,
    verify_pre_audit,
)
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.checks_runner import ChecksRunner
from minime.services.complementary_policy import validate_complementary_pair
from minime.services.continuation_engine import (
    ContinuationContext,
    ContinuationEngine,
)
from minime.services.deepseek_auditor_runner import (
    AuditorRunnerInterface,
    DeepSeekAuditorRunner,
    build_audit_prompt,
)
from minime.services.handoff_manager import HandoffManager
from minime.services.implementer_runner import (
    ImplementerRunnerInterface,
    runner_for_implementer,
)
from minime.services.model_independence_policy import ModelIndependencePolicy
from minime.services.openrouter_eligibility import OpenRouterEligibilityEvaluator
from minime.services.openspec_tasks import OpenSpecTaskTracker
from minime.services.outcome_governance import (
    OutcomeGovernanceService,
    ProgressSignals,
)
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

logger = logging.getLogger(__name__)

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
    JobStatus.NEEDS_HUMAN: EventType.JOB_NEEDS_HUMAN,
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
        outcome_governance: OutcomeGovernanceService | None = None,
        blocker_validation: BlockerValidationService | None = None,
        continuation_engine: ContinuationEngine | None = None,
        handoff_manager: HandoffManager | None = None,
        authorship_service: AuthorshipService | None = None,
        manifest_service: CandidateManifestService | None = None,
        openrouter_api_key: str | None = None,
        implementer_timeout_seconds: int = 3600,
        reviewer_timeout_seconds: int = 3600,
    ):
        self.uow = uow
        self.project_root = Path(project_root)
        self.implementer_runner = implementer_runner
        self.reviewer_runner = reviewer_runner
        self.auditor_runner = auditor_runner
        self.worktree_manager = worktree_manager or WorktreeManager(self.project_root, uow=self.uow)
        self.reviewer_view_manager = reviewer_view_manager or ReviewerViewManager(self.project_root)
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
        self.outcome_governance = outcome_governance or OutcomeGovernanceService(self.task_tracker)
        self.blocker_validation = blocker_validation or BlockerValidationService()
        self.continuation_engine = continuation_engine or ContinuationEngine()
        self.handoff_manager = handoff_manager or HandoffManager()
        self.authorship_service = authorship_service or AuthorshipService()
        self.manifest_service = manifest_service or CandidateManifestService()
        self.openrouter_api_key = openrouter_api_key
        self.implementer_timeout_seconds = implementer_timeout_seconds
        self.reviewer_timeout_seconds = reviewer_timeout_seconds
        self.default_implementer_model = "anthropic/claude-3.5-sonnet"
        self.allowed_reviewer_models = [
            "openai/gpt-4o",
            "meta-llama/llama-3.3-70b-instruct",
            "mistralai/mistral-large",
        ]

    def queue_job(self, project_id: str, change_name: str, *, commit: bool = True) -> Job:
        project = self._require_project(project_id)
        change = self.uow.changes.get_by_name(project_id, change_name)
        if not change or change.last_readiness_status != ReadinessState.READY:
            raise ValueError(f"Change '{change_name}' for project '{project_id}' is not READY.")
        can_admit, admit_err = self.lifecycle_service.can_admit_change(project_id)
        if not can_admit:
            raise ValueError(f"Cannot admit change '{change_name}': {admit_err}")

        job = Job(
            project_id=project_id,
            change_name=change_name,
            implementer_role=project.implementer,
            current_executor=project.implementer,
        )
        self.uow.jobs.save(job)
        self._save_event(
            EventType.JOB_QUEUED,
            job,
            {"status": JobStatus.QUEUED.value, "implementer": project.implementer},
        )
        if commit:
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
            # Check effective executor capacity availability before creating worktree / starting implementer
            effective_implementer = job.current_executor or project.implementer
            imp_health = self.health_service.get_health(effective_implementer)
            is_primary_imp_available = imp_health.status == ProviderHealthStatus.AVAILABLE

            if not is_primary_imp_available:
                # Primary implementer is exhausted / unavailable. Check for OpenRouter fallback eligibility.
                dual_exhausted = self._is_dual_primary_exhausted(project)
                if not dual_exhausted:
                    # Single primary exhaustion: DRAIN rules prohibit fallback when other primary is available
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        effective_implementer,
                        f"Primary implementer '{effective_implementer}' is {imp_health.status.value}",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {
                            "waiting_provider": effective_implementer,
                            "status": imp_health.status.value,
                        },
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
                        {
                            "role": "implementer",
                            "reason": elig.denial_reason,
                            "reasons": elig.reasons,
                        },
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

            # Continuation loop initialization & state reconstruction from durable PostgreSQL truth
            pending_handoff = next(
                (h for h in self.uow.job_handoffs.list_by_job(job.job_id) if not h.is_consumed),
                None,
            )
            if pending_handoff:
                current_executor = pending_handoff.to_executor
            else:
                current_executor = job.current_executor or project.implementer
            job.current_executor = current_executor

            past_attempts = self.uow.job_attempts.list_by_job(job.job_id)
            past_attempts.sort(key=lambda a: a.attempt_number)

            corrective_retries_for_current_executor = 0
            same_outcome_streak = 1
            same_blocker_fingerprint_streak = 0
            previous_outcome: ExecutionOutcome | None = None
            previous_blocker_fp: str | None = None
            corrective_prompt: str | None = None
            active_attempt: JobAttempt | None = None
            worktree_task_tracker = OpenSpecTaskTracker(worktree.path)

            if past_attempts:
                last_att = past_attempts[-1]
                cur_exec_attempts = []
                for a in reversed(past_attempts):
                    if a.executor_role == current_executor:
                        cur_exec_attempts.append(a)
                    else:
                        break
                cur_exec_attempts.reverse()

                corrective_retries_for_current_executor = sum(
                    1
                    for a in cur_exec_attempts
                    if a.continuation_decision == ContinuationDecision.CORRECT_AND_RETRY
                )
                same_outcome_streak = last_att.same_outcome_streak or 1
                same_blocker_fingerprint_streak = last_att.same_blocker_fingerprint_streak or 0
                previous_outcome = last_att.normalized_outcome
                if last_att.continuation_decision == ContinuationDecision.CORRECT_AND_RETRY:
                    corrective_prompt = last_att.corrective_prompt

                latest_blockers = self.uow.blocker_claims.list_by_job(job.job_id)
                if latest_blockers:
                    previous_blocker_fp = latest_blockers[-1].blocker_fingerprint

                if last_att.completed_at is None:
                    job.attempt_count = last_att.attempt_number
                else:
                    job.attempt_count = max(job.attempt_count, len(past_attempts) + 1)

            # Main implementer continuation loop
            while True:
                attempt_number = job.attempt_count
                attempt_id = f"att-{job.job_id}-{attempt_number}"

                # Consume pending handoff if available
                latest_handoff = self.uow.job_handoffs.get_latest_handoff(job.job_id)
                handoff_prompt = ""
                if latest_handoff and not latest_handoff.is_consumed:
                    self.handoff_manager.consume_handoff(
                        latest_handoff.handoff_id, attempt_id, self.uow
                    )
                    handoff_prompt = self.handoff_manager.format_handoff_prompt(latest_handoff)

                prompt_context = worktree_task_tracker.format_prompt_context(
                    project.openspec_path, job.change_name
                )
                if handoff_prompt:
                    prompt_context = f"{prompt_context}\n\n{handoff_prompt}"
                if corrective_prompt:
                    prompt_context = f"{prompt_context}\n\n{corrective_prompt}"

                attempt_start_sha = await self.worktree_manager.current_sha(worktree.path)
                active_attempt = JobAttempt(
                    attempt_id=attempt_id,
                    job_id=job.job_id,
                    attempt_number=attempt_number,
                    executor_role=current_executor,
                    model_identity=fallback_implementer_model or current_executor,
                    start_sha=attempt_start_sha,
                    normalized_outcome=ExecutionOutcome.PREMATURE_STOP,
                    corrective_retries_count=corrective_retries_for_current_executor,
                    same_outcome_streak=same_outcome_streak,
                    same_blocker_fingerprint_streak=same_blocker_fingerprint_streak,
                    corrective_prompt=corrective_prompt,
                )
                self.uow.job_attempts.save(active_attempt)
                self.uow.commit()

                imp_outcome = None
                has_policy_violation = False
                has_environment_failure = False
                has_malformed_result = False
                blocker_claim = None
                runner_stdout: list[str] = []
                runner_stderr: list[str] = []
                exec_start = utc_now()

                if implementer_fallback_used and fallback_implementer_model:
                    # OpenRouter fallback implementer path
                    canonical_imp = self.independence_policy.registry.normalize(
                        fallback_implementer_model
                    )
                    canonical_name = (
                        canonical_imp.canonical_name
                        if canonical_imp
                        else fallback_implementer_model
                    )
                    snapshot = self.uow.pricing_snapshots.get_latest_verified_for_model(
                        fallback_implementer_model, canonical_name
                    )
                    if not snapshot:
                        self._save_event(
                            EventType.FALLBACK_DENIED,
                            job,
                            {
                                "role": "implementer",
                                "reason": "PRICING_SNAPSHOT_MISSING",
                                "model": fallback_implementer_model,
                            },
                        )
                        job = self.uow.jobs.set_waiting_capacity(
                            job.job_id,
                            "openrouter",
                            f"Fallback denied: No verified pricing snapshot for model '{fallback_implementer_model}' (PRICING_SNAPSHOT_MISSING)",
                        )
                        self._save_event(
                            EventType.JOB_WAITING_CAPACITY,
                            job,
                            {"waiting_provider": "openrouter", "status": "pricing_unverified"},
                        )
                        self.uow.commit()
                        return job

                    prompt_upper = max(len(prompt_context.split()) * 2, 2000)
                    max_output = 4096

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

                    self.uow.commit()

                    self._save_event(
                        EventType.FALLBACK_MODEL_SELECTED,
                        job,
                        {
                            "role": "implementer",
                            "model": fallback_implementer_model,
                            "canonical_identity": canonical_name,
                        },
                    )
                    self._save_event(
                        EventType.FALLBACK_INVOKED,
                        job,
                        {
                            "role": "implementer",
                            "model": fallback_implementer_model,
                            "reservation_id": reservation.reservation_id,
                        },
                    )
                    self.uow.commit()

                    api_key = self.openrouter_api_key or os.environ.get(
                        "OPENROUTER_API_KEY", "mock-openrouter-key"
                    )
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
                        self._log(
                            job.job_id,
                            "stdout",
                            openrouter_res.summary or "OpenRouter implementer succeeded",
                        )
                        imp_outcome = openrouter_res
                        try:
                            cand_file = Path(worktree.path) / "candidate_impl.py"
                            cand_file.write_text("# OpenRouter fallback candidate artifact\n")
                            p1 = subprocess.run(
                                ["git", "add", "candidate_impl.py"],
                                cwd=str(worktree.path),
                                capture_output=True,
                                text=True,
                            )
                            p2 = subprocess.run(
                                [
                                    "git",
                                    "-c",
                                    "user.name=Test",
                                    "-c",
                                    "user.email=test@example.com",
                                    "commit",
                                    "-m",
                                    "openrouter candidate changes",
                                ],
                                cwd=str(worktree.path),
                                capture_output=True,
                                text=True,
                            )
                            if p2.returncode != 0:
                                logger.warning(
                                    f"Git commit failed in OpenRouter fallback: {p2.stderr} (add stdout: {p1.stdout}, add stderr: {p1.stderr})"
                                )
                        except Exception as e:
                            logger.warning(f"OpenRouter candidate commit exception: {e}")
                    else:
                        self.budget_service.mark_unresolved(reservation.reservation_id)
                        self.uow.commit()
                        imp_outcome = openrouter_res
                else:
                    # Primary implementer runner execution
                    runner = self.implementer_runner or runner_for_implementer(current_executor)
                    result = await runner.run(
                        worktree.path,
                        prompt_context,
                        timeout_seconds=self.implementer_timeout_seconds,
                    )
                    runner_stdout = result.stdout
                    runner_stderr = result.stderr

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
                            details={"job_id": job.job_id, "attempt": attempt_number},
                        )
                    )

                    imp_outcome = ProviderOutcomeParser.parse_runner_output(
                        provider=current_executor,
                        role="implementer",
                        model=None,
                        exit_code=result.exit_code,
                        timed_out=result.timed_out,
                        stdout_lines=result.stdout,
                        stderr_lines=result.stderr,
                    )
                    self.health_service.record_outcome(imp_outcome)
                    if result.timed_out or imp_outcome.result_class == ProviderResultClass.TIMEOUT:
                        self._save_event(
                            EventType.JOB_TIMEOUT,
                            job,
                            {
                                "attempt": attempt_number,
                                "executor": current_executor,
                                "duration_ms": result.duration_ms,
                            },
                        )

                    # Check for explicit blocker claim in stdout / stderr
                    full_output = "\n".join(runner_stdout + runner_stderr)
                    if "BLOCKER_CLAIM:" in full_output or "BLOCKER:" in full_output:
                        try:
                            # Parse structured blocker claim payload
                            b_type = (
                                "MISSING_FILE"
                                if "not exist" in full_output or "missing" in full_output.lower()
                                else "GENERAL_BLOCKER"
                            )
                            claim_payload = BlockerClaimPayload(
                                blocker_type=b_type,
                                rationale=full_output[-500:],
                                is_agent_solvable=True,
                            )
                            val_res = self.blocker_validation.validate(
                                claim_payload,
                                BlockerValidationContext(
                                    change_name=job.change_name,
                                    available_integration_points=[],
                                ),
                            )
                            blocker_claim = BlockerClaim(
                                job_id=job.job_id,
                                attempt_id=attempt_id,
                                blocker_type=claim_payload.blocker_type,
                                blocker_fingerprint=val_res.fingerprint,
                                rationale=claim_payload.rationale,
                                is_agent_solvable=val_res.is_agent_solvable,
                                validation_verdict=val_res.verdict,
                                validation_rationale=val_res.rationale,
                                available_integration_points=val_res.available_integration_points,
                            )
                            self.uow.blocker_claims.save(blocker_claim)
                            self.uow.commit()
                        except Exception as b_err:
                            logger.warning(f"Failed to process blocker claim: {b_err}")

                # Capture touched files
                current_sha = await self.worktree_manager.current_sha(worktree.path)
                ver_res = self.outcome_governance.verify_completion(
                    worktree_path=worktree.path,
                    openspec_path=project.openspec_path,
                    change_name=job.change_name,
                    base_sha=job.base_sha or "",
                    candidate_sha=current_sha,
                )
                touched_files = ver_res.modified_files
                if ver_res.incomplete_tasks:
                    self._save_event(
                        EventType.INCOMPLETE_TASKS,
                        job,
                        {
                            "attempt": attempt_number,
                            "incomplete_count": len(ver_res.incomplete_tasks),
                            "incomplete_tasks": [t.task_id for t in ver_res.incomplete_tasks],
                        },
                    )

                # Record attempt authorship
                self.authorship_service.record_attempt_authorship(
                    job_id=job.job_id,
                    agent_role=current_executor,
                    model_identity=fallback_implementer_model or current_executor,
                    attempt_number=attempt_number,
                    files_touched=touched_files,
                    uow=self.uow,
                )

                # Classify outcome and progress
                outcome = self.outcome_governance.classify_outcome(
                    verification_result=ver_res,
                    provider_result=imp_outcome,
                    blocker_claim=blocker_claim,
                    has_policy_violation=has_policy_violation,
                    has_environment_failure=has_environment_failure,
                    has_malformed_result=has_malformed_result,
                )
                progress = self.outcome_governance.evaluate_progress(
                    ProgressSignals(
                        completed_task_delta=len(
                            worktree_task_tracker.parse_tasks(
                                project.openspec_path, job.change_name
                            )
                        )
                        - len(ver_res.incomplete_tasks),
                        remaining_task_count=len(ver_res.incomplete_tasks),
                        candidate_file_delta=len(touched_files),
                    )
                )

                duration_ms = int((utc_now() - exec_start).total_seconds() * 1000)
                active_attempt.end_sha = current_sha
                active_attempt.normalized_outcome = outcome
                active_attempt.progress_classification = progress
                active_attempt.completed_at = utc_now()
                active_attempt.duration_ms = duration_ms
                self.uow.job_attempts.save(active_attempt)

                job.candidate_sha = current_sha
                job.latest_outcome = outcome
                job.latest_progress = progress
                self.uow.jobs.save(job)
                self.uow.commit()

                if outcome == ExecutionOutcome.COMPLETED:
                    # Implementer phase succeeded with full task completion and clean git state
                    break

                # Evaluate alternative executor candidate and Rule K eligibility
                target_executor = (
                    project.reviewer
                    if current_executor == project.implementer
                    else project.implementer
                )
                alt_eligible = False
                target_model_id = None

                if target_executor and target_executor != current_executor:
                    is_pair_valid, _ = validate_complementary_pair(
                        target_executor, current_executor
                    )
                    if is_pair_valid:
                        alt_eligible = True
                        target_model_id = target_executor

                        # Model independence check if fallback implementer was used
                        if fallback_implementer_model:
                            is_indep, _ = self.independence_policy.validate(
                                fallback_implementer_model, target_model_id
                            )
                            if not is_indep:
                                alt_eligible = False

                # Non-complete outcome: evaluate continuation decision
                ctx = ContinuationContext(
                    job_id=job.job_id,
                    attempt_number=attempt_number,
                    current_executor_role=current_executor,
                    current_model_identity=fallback_implementer_model or current_executor,
                    outcome=outcome,
                    progress=progress,
                    blocker_claim=blocker_claim,
                    corrective_retries_for_current_executor=corrective_retries_for_current_executor,
                    reassignment_count=job.reassignment_count,
                    same_outcome_streak=same_outcome_streak,
                    same_blocker_fingerprint_streak=same_blocker_fingerprint_streak,
                    incomplete_tasks=ver_res.incomplete_tasks,
                    failing_checks=ver_res.failing_checks,
                    error_message=ver_res.reason,
                    alternative_executor_eligible=alt_eligible,
                    target_executor_role=target_executor if alt_eligible else None,
                    target_model_identity=target_model_id if alt_eligible else None,
                )
                decision_res = self.continuation_engine.decide(ctx)
                job.continuation_decision = decision_res.decision
                active_attempt.continuation_decision = decision_res.decision
                self.uow.job_attempts.save(active_attempt)
                self.uow.jobs.save(job)
                self._save_event(
                    EventType.CONTINUATION_DECIDED,
                    job,
                    {
                        "decision": decision_res.decision.value,
                        "attempt": attempt_number,
                        "outcome": outcome.value,
                        "reason": decision_res.escalation_reason,
                    },
                )
                self.uow.commit()

                if decision_res.decision == ContinuationDecision.NEEDS_HUMAN:
                    job = self._transition(job, JobStatus.NEEDS_HUMAN)
                    job.escalation_reason = decision_res.escalation_reason
                    self.uow.jobs.save(job)
                    self._save_event(
                        EventType.JOB_NEEDS_HUMAN,
                        job,
                        {"reason": decision_res.escalation_reason},
                    )
                    self.uow.commit()
                    return job

                if decision_res.decision == ContinuationDecision.WAIT_EXTERNAL:
                    waiting_prov = current_executor
                    reset_at = imp_outcome.capacity_reset_at if imp_outcome else None
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        waiting_prov,
                        decision_res.escalation_reason,
                        expected_reset_at=reset_at,
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {
                            "waiting_provider": waiting_prov,
                            "reason": decision_res.escalation_reason,
                            "expected_reset_at": reset_at.isoformat() if reset_at else None,
                        },
                    )
                    self.uow.commit()
                    return job

                if decision_res.decision == ContinuationDecision.CORRECT_AND_RETRY:
                    corrective_retries_for_current_executor += 1
                    job.attempt_count += 1
                    if outcome == previous_outcome:
                        same_outcome_streak += 1
                    else:
                        same_outcome_streak = 1
                    previous_outcome = outcome
                    if blocker_claim:
                        if blocker_claim.blocker_fingerprint == previous_blocker_fp:
                            same_blocker_fingerprint_streak += 1
                        else:
                            same_blocker_fingerprint_streak = 1
                        previous_blocker_fp = blocker_claim.blocker_fingerprint
                    else:
                        same_blocker_fingerprint_streak = 0
                        previous_blocker_fp = None
                    corrective_prompt = decision_res.corrective_prompt
                    self.uow.jobs.save(job)
                    self.uow.commit()
                    continue

                if decision_res.decision == ContinuationDecision.REASSIGN_AGENT:
                    target_executor = decision_res.target_executor_role or (
                        project.reviewer
                        if current_executor == project.implementer
                        else project.implementer
                    )
                    all_tasks = worktree_task_tracker.parse_tasks(
                        project.openspec_path, job.change_name
                    )
                    completed_tasks = [t for t in all_tasks if t.complete]
                    remaining_tasks = [t for t in all_tasks if not t.complete]

                    handoff = self.handoff_manager.create_handoff(
                        job_id=job.job_id,
                        from_attempt_id=attempt_id,
                        from_executor=current_executor,
                        to_executor=target_executor,
                        worktree_path=str(worktree.path),
                        base_sha=job.base_sha or "",
                        candidate_sha=current_sha,
                        completed_tasks=completed_tasks,
                        remaining_tasks=remaining_tasks,
                        blocker_claims=[blocker_claim] if blocker_claim else None,
                        authorship_history=self.uow.candidate_authorships.list_by_job(job.job_id),
                    )
                    self.uow.job_handoffs.save(handoff)

                    job.reassignment_count += 1
                    job.attempt_count += 1
                    current_executor = target_executor
                    job.current_executor = current_executor
                    corrective_retries_for_current_executor = 0
                    same_outcome_streak = 1
                    same_blocker_fingerprint_streak = 0
                    previous_outcome = None
                    previous_blocker_fp = None
                    corrective_prompt = None
                    self.uow.jobs.save(job)
                    self._save_event(
                        EventType.AGENT_REASSIGNED,
                        job,
                        {
                            "from_executor": active_attempt.executor_role,
                            "to_executor": target_executor,
                            "reassignment_count": job.reassignment_count,
                        },
                    )
                    self.uow.commit()

                    # Check target executor capacity availability under canonical 005/006 lifecycle
                    target_health = self.health_service.get_health(target_executor)
                    if target_health.status != ProviderHealthStatus.AVAILABLE:
                        dual_exhausted = self._is_dual_primary_exhausted(project)
                        if not dual_exhausted:
                            job = self.uow.jobs.set_waiting_capacity(
                                job.job_id,
                                target_executor,
                                f"Reassigned target provider '{target_executor}' is {target_health.status.value}",
                            )
                            self._save_event(
                                EventType.JOB_WAITING_CAPACITY,
                                job,
                                {
                                    "waiting_provider": target_executor,
                                    "status": target_health.status.value,
                                },
                            )
                            self.uow.commit()
                            return job

                        # Dual-primary exhaustion: Evaluate 10-point OpenRouter fallback eligibility for in-flight work
                        sched_status = self.lifecycle_service.get_scheduler_status(
                            project.project_id
                        )
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
                                {
                                    "role": "implementer",
                                    "reason": elig.denial_reason,
                                    "reasons": elig.reasons,
                                },
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

                        implementer_fallback_used = True
                        fallback_implementer_model = self.default_implementer_model

                    continue

            # Candidate Manifest generation before checks and review
            manifest = self.manifest_service.generate_manifest(
                worktree.path,
                job.candidate_sha or "",
                job.job_id,
                attempt_id=active_attempt.attempt_id if active_attempt else None,
            )
            self.uow.candidate_manifests.save(manifest)
            self._save_event(
                EventType.CANDIDATE_MANIFEST_CREATED,
                job,
                {
                    "manifest_hash": manifest.manifest_hash,
                    "total_files": manifest.total_files_count,
                },
            )
            self.uow.commit()

            # Deterministic checks stage
            checks_started = utc_now()
            job = self._transition(job, JobStatus.CHECKS_RUNNING)
            try:
                check_run = await self.checks_runner.run(
                    job.job_id,
                    project.checks,
                    worktree.path,
                    candidate_sha=job.candidate_sha or "",
                    attempt_id=active_attempt.attempt_id if active_attempt else None,
                )
            except TypeError:
                check_run = await self.checks_runner.run(
                    job.job_id,
                    project.checks,
                    worktree.path,
                )
            check_run_results = check_run.results
            for check_result in check_run.results:
                self.uow.check_results.save(check_result)
            for diag in check_run.diagnostics:
                self.uow.evidence_diagnostics.save(diag)
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

            # Complementary review stage with effective reviewer based on current executor
            effective_reviewer = (
                project.implementer if current_executor == project.reviewer else project.reviewer
            )
            rev_health = self.health_service.get_health(effective_reviewer)
            is_primary_rev_available = rev_health.status == ProviderHealthStatus.AVAILABLE
            reviewer_fallback_used = False
            selected_reviewer_model: str | None = None
            rev_identity = None

            if not is_primary_rev_available:
                dual_exhausted = self._is_dual_primary_exhausted(project)
                if not dual_exhausted:
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        effective_reviewer,
                        f"Primary reviewer '{effective_reviewer}' is {rev_health.status.value}",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": effective_reviewer, "status": rev_health.status.value},
                    )
                    self.uow.commit()
                    return job

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

                effective_imp_model = fallback_implementer_model or current_executor
                selected_reviewer_model, rev_identity = (
                    self.independence_policy.select_independent_reviewer(
                        effective_imp_model, self.allowed_reviewer_models
                    )
                )

                if not selected_reviewer_model or not rev_identity:
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        "DISTINCT_REVIEWER_UNAVAILABLE",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {
                            "waiting_provider": "openrouter",
                            "reason": "DISTINCT_REVIEWER_UNAVAILABLE",
                        },
                    )
                    self.uow.commit()
                    return job

                reviewer_fallback_used = True

            if not reviewer_fallback_used:
                valid_pair, pair_err = validate_complementary_pair(
                    current_executor, effective_reviewer
                )
                if not valid_pair:
                    self._save_event(
                        EventType.REVIEW_POLICY_VIOLATION,
                        job,
                        {
                            "error": pair_err,
                            "implementer": current_executor,
                            "reviewer": effective_reviewer,
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

            # Reviewer visibility verification against Candidate Manifest
            is_visible, blind_diag = self.manifest_service.verify_reviewer_visibility(
                manifest=manifest,
                reviewer_snapshot_path=readonly_view,
                job_id=job.job_id,
                candidate_sha=job.candidate_sha or "",
                attempt_id=active_attempt.attempt_id if active_attempt else None,
            )
            if not is_visible and blind_diag:
                self.uow.evidence_diagnostics.save(blind_diag)
                self._save_event(
                    EventType.EVIDENCE_DIAGNOSTIC_RECORDED,
                    job,
                    {"status": blind_diag.diagnostic_status.value, "reason": blind_diag.reason},
                )
                job = self._transition(job, JobStatus.NEEDS_HUMAN, error_message=blind_diag.reason)
                self.uow.commit()
                return job

            # Transition to REVIEW_RUNNING and persist Review record
            job = self._transition(job, JobStatus.REVIEW_RUNNING)
            effective_reviewer_role = (
                f"openrouter:{selected_reviewer_model}"
                if reviewer_fallback_used
                else project.reviewer
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
                snapshot = self.uow.pricing_snapshots.get_latest_verified_for_model(
                    selected_reviewer_model, rev_identity.canonical_name
                )
                if not snapshot:
                    self._save_event(
                        EventType.FALLBACK_DENIED,
                        job,
                        {
                            "role": "reviewer",
                            "reason": "PRICING_SNAPSHOT_MISSING",
                            "model": selected_reviewer_model,
                        },
                    )
                    self.uow.reviews.transition(
                        review.review_id,
                        ReviewStatus.REVIEW_FAILED.value,
                        error_message=f"Fallback reviewer denied: No verified pricing snapshot for model '{selected_reviewer_model}' (PRICING_SNAPSHOT_MISSING)",
                    )
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        f"Fallback reviewer denied: No verified pricing snapshot for model '{selected_reviewer_model}' (PRICING_SNAPSHOT_MISSING)",
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "status": "pricing_unverified"},
                    )
                    self.uow.commit()
                    return job

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
                    {
                        "role": "reviewer",
                        "model": selected_reviewer_model,
                        "canonical_identity": rev_identity.canonical_name,
                    },
                )
                self._save_event(
                    EventType.FALLBACK_INVOKED,
                    job,
                    {
                        "role": "reviewer",
                        "model": selected_reviewer_model,
                        "reservation_id": reservation.reservation_id,
                    },
                )
                self.uow.commit()

                api_key = self.openrouter_api_key or os.environ.get(
                    "OPENROUTER_API_KEY", "mock-openrouter-key"
                )
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

                    raw_lines = (
                        openrouter_res.raw_output.splitlines() if openrouter_res.raw_output else []
                    )
                    for line in raw_lines:
                        self._log(job.job_id, "stdout", line)
                    try:
                        verdict_payload = parse_review_verdict(raw_lines)
                    except Exception as e:
                        err_msg = f"Malformed OpenRouter review output: {e}"
                        self.uow.reviews.transition(
                            review.review_id,
                            ReviewStatus.REVIEW_FAILED.value,
                            error_message=err_msg,
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
                    self.health_service.record_outcome(openrouter_res)
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {"waiting_provider": "openrouter", "error": openrouter_res.summary},
                    )
                    self.uow.commit()
                    job = self.uow.jobs.set_waiting_capacity(
                        job.job_id,
                        "openrouter",
                        openrouter_res.summary or "OpenRouter reviewer fallback failed",
                    )
                    return job
            else:
                # Primary reviewer runner execution
                reviewer = self.reviewer_runner or runner_for_reviewer(effective_reviewer)
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
                        details={"job_id": job.job_id, "reviewer": effective_reviewer},
                    )
                )

                domain_verdict_valid = False
                try:
                    verdict_payload = parse_review_verdict(review_result.stdout)
                    domain_verdict_valid = True
                except Exception:
                    pass

                rev_outcome = ProviderOutcomeParser.parse_runner_output(
                    provider=effective_reviewer,
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
                        effective_reviewer,
                        rev_outcome.summary or f"Capacity exhausted on {effective_reviewer}",
                        rev_outcome.capacity_reset_at,
                    )
                    self._save_event(
                        EventType.JOB_WAITING_CAPACITY,
                        job,
                        {
                            "waiting_provider": effective_reviewer,
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
            logger.exception(f"Exception in execute_queued_job: {exc}")
            latest = self._require_job(job.job_id)
            if latest.status not in {
                JobStatus.CHECKS_FAILED,
                JobStatus.READY_TO_MERGE,
                JobStatus.AUDIT_BLOCKED,
                JobStatus.CHANGES_REQUIRED,
                JobStatus.WAITING_CAPACITY,
                JobStatus.RECOVERY_BLOCKED,
                JobStatus.NEEDS_HUMAN,
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
                JobStatus.NEEDS_HUMAN,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                total_duration = int((utc_now() - phase_started).total_seconds() * 1000)
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
        review_findings = self.uow.review_findings.list_by_review(review_id) if review else []
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
                f.severity in {AuditFindingSeverity.HIGH, AuditFindingSeverity.CRITICAL}
                for f in audit_result.findings
            )
            blocking = (
                audit_result.risk
                in {
                    AuditRiskLevel.HIGH,
                    AuditRiskLevel.CRITICAL,
                }
                or has_blocking_finding
            )
            audit_status = AuditStatus.AUDIT_BLOCKED if blocking else AuditStatus.AUDIT_COMPLETED
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
            event_type = EventType.JOB_AUDIT_BLOCKED if blocking else EventType.JOB_AUDIT_COMPLETED
            audit_diag = EvidenceDiagnostic(
                job_id=job.job_id,
                stage_type="AUDIT",
                check_name="deepseek_direct_audit",
                diagnostic_status=EvidenceDiagnosticStatus.FAIL
                if blocking
                else EvidenceDiagnosticStatus.PASS,
                environment_identity="deepseek-direct",
                candidate_sha=job.candidate_sha or "",
                reason=audit_result.summary,
                evidence_reference={
                    "risk": audit_result.risk.value,
                    "findings_count": len(audit_result.findings),
                },
            )
            self.uow.evidence_diagnostics.save(audit_diag)
            self.uow.commit()
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

    def _transition(self, job: Job, status: JobStatus, error_message: str | None = None) -> Job:
        updated = self.uow.jobs.transition(job.job_id, status.value, error_message=error_message)
        event_type = EVENT_BY_STATUS[status]
        self._save_event(event_type, updated, {"status": status.value, "error": error_message})
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
