"""Autonomous Change Orchestration coordinator service for single READY changes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from minime.adapters.github import GitHubAdapter
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import (
    AuditFindingSeverity,
    AuditStatus,
    ContinuationDecision,
    EventType,
    ExecutionOutcome,
    ExternalActionStatus,
    ExternalActionType,
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProviderHealthStatus,
    PullRequestLookupState,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.interfaces import GitHubAdapterInterface, PersistenceUnitOfWork
from minime.domain.models import (
    AdmissionResult,
    Event,
    Job,
    OrchestrationCandidate,
    OrchestrationExternalAction,
    OrchestrationRun,
    OrchestrationStageEvent,
    OrchestrationStatusView,
    Project,
    ProjectBinding,
    generate_uuid,
    utc_now,
)
from minime.logging import redact_secrets
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.project_service import ProjectService
from minime.services.readiness_service import ReadinessService

logger = logging.getLogger(__name__)

ALLOWED_STAGE_TRANSITIONS: dict[OrchestrationStage, set[OrchestrationStage]] = {
    OrchestrationStage.ADMITTED: {OrchestrationStage.PREPARING_EXECUTION},
    OrchestrationStage.PREPARING_EXECUTION: {OrchestrationStage.IMPLEMENTING},
    OrchestrationStage.IMPLEMENTING: {OrchestrationStage.EVALUATING_ATTEMPT},
    OrchestrationStage.EVALUATING_ATTEMPT: {
        OrchestrationStage.RUNNING_CHECKS,
        OrchestrationStage.IMPLEMENTING,
    },
    OrchestrationStage.RUNNING_CHECKS: {
        OrchestrationStage.FREEZING_CANDIDATE,
        OrchestrationStage.IMPLEMENTING,
    },
    OrchestrationStage.FREEZING_CANDIDATE: {OrchestrationStage.COMPLEMENTARY_REVIEW},
    OrchestrationStage.COMPLEMENTARY_REVIEW: {
        OrchestrationStage.INDEPENDENT_AUDIT,
        OrchestrationStage.REVIEW_REMEDIATION,
    },
    OrchestrationStage.REVIEW_REMEDIATION: {OrchestrationStage.IMPLEMENTING},
    OrchestrationStage.INDEPENDENT_AUDIT: {
        OrchestrationStage.PREPARING_PR,
        OrchestrationStage.AUDIT_REMEDIATION,
    },
    OrchestrationStage.AUDIT_REMEDIATION: {OrchestrationStage.IMPLEMENTING},
    OrchestrationStage.PREPARING_PR: {
        OrchestrationStage.PR_PREPARED,
        OrchestrationStage.INDEPENDENT_AUDIT,
    },
}


class OrchestrationService:
    """Coordinates one already-READY OpenSpec change across 001-007 authorities."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        pipeline: ExecutionPipelineService | None = None,
        github_adapter: GitHubAdapterInterface | None = None,
        openspec_adapter: OpenSpecAdapter | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.pipeline = pipeline or ExecutionPipelineService(
            uow=self.uow,
            project_root=self.project_root,
        )
        self.github_adapter = github_adapter or GitHubAdapter()
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()
        self.project_service = ProjectService(self.uow)
        self.readiness_service = ReadinessService(self.uow)

    def admit_change(
        self,
        project_id: str,
        change_name: str,
        project_root: str | Path | None = None,
    ) -> AdmissionResult:
        """Admit one project/change pair into orchestration after re-verifying all requirements."""
        root = Path(project_root).resolve() if project_root else self.project_root

        # 1. Project existence check
        project = self.uow.projects.get_by_id(project_id)
        if not project:
            return AdmissionResult(
                admitted=False,
                refusal_reason=f"Project '{project_id}' not found.",
                refusal_details={"code": "PROJECT_NOT_FOUND", "project_id": project_id},
            )

        # 2. Change existence check
        change = self.uow.changes.get_by_name(project_id, change_name)
        if not change:
            return AdmissionResult(
                admitted=False,
                refusal_reason=f"Change '{change_name}' not found for project '{project_id}'.",
                refusal_details={"code": "CHANGE_NOT_FOUND", "change_name": change_name},
            )

        # 3. Durable ProjectBinding validation
        binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
        if not binding or not binding.is_valid:
            reasons = binding.mismatch_reasons if binding else ["Binding does not exist"]
            return AdmissionResult(
                admitted=False,
                refusal_reason=f"Project binding for change '{change_name}' is invalid or missing: {'; '.join(reasons)}",
                refusal_details={"code": "INVALID_BINDING", "reasons": reasons},
            )

        if not binding.github_issue_number or binding.github_issue_number <= 0:
            return AdmissionResult(
                admitted=False,
                refusal_reason=f"Missing or invalid GitHub Issue binding for change '{change_name}'.",
                refusal_details={"code": "MISSING_GITHUB_ISSUE"},
            )

        # 4. Re-evaluate change Definition of Ready (DoR)
        eval_result = self.readiness_service.evaluate_change_readiness(
            project_id=project_id,
            change_name=change_name,
            project_root=str(root),
        )
        if not eval_result.is_ready or eval_result.status != ReadinessState.READY:
            return AdmissionResult(
                admitted=False,
                refusal_reason=f"Change '{change_name}' is not READY: {'; '.join(eval_result.unmet_reasons)}",
                refusal_details={
                    "code": "NOT_READY",
                    "status": eval_result.status.value,
                    "unmet_reasons": eval_result.unmet_reasons,
                },
            )

        # 5. Worktree / workspace preflight
        if not root.exists():
            return AdmissionResult(
                admitted=False,
                refusal_reason=f"Project root workspace does not exist: '{root}'",
                refusal_details={"code": "WORKSPACE_PREFLIGHT_FAILED", "path": str(root)},
            )

        # 6. Active run uniqueness guard
        existing_active = self.uow.orchestration_runs.get_active_run(project_id, change_name)
        if existing_active:
            return AdmissionResult(
                admitted=False,
                refusal_reason=f"Active orchestration run '{existing_active.run_id}' already exists for project '{project_id}' and change '{change_name}'.",
                refusal_details={
                    "code": "DUPLICATE_ACTIVE_RUN",
                    "existing_run_id": existing_active.run_id,
                },
                existing_run_id=existing_active.run_id,
            )

        # Determine registered base SHA from repo or project
        base_sha = self._resolve_base_sha(project, root)

        run = OrchestrationRun(
            run_id=generate_uuid(),
            project_id=project_id,
            change_name=change_name,
            base_sha=base_sha,
            current_stage=OrchestrationStage.ADMITTED,
            resumable_stage=OrchestrationStage.ADMITTED,
            human_gate=None,
            is_active=True,
            current_generation=1,
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        self.uow.orchestration_runs.save(run)
        self.uow.orchestration_stage_events.save(
            OrchestrationStageEvent(
                run_id=run.run_id,
                from_stage=None,
                to_stage=OrchestrationStage.ADMITTED,
                event_type=EventType.ORCHESTRATION_STARTED.value,
                transition_key=f"{run.run_id}:START:{run.current_generation}",
                evidence_references={"base_sha": base_sha, "change_name": change_name},
                actor="system",
                created_at=utc_now(),
            )
        )
        self.uow.events.save(
            Event(
                event_type=EventType.ORCHESTRATION_STARTED,
                project_id=project_id,
                change_id=change_name,
                operation_id=run.run_id,
                payload={
                    "run_id": run.run_id,
                    "stage": OrchestrationStage.ADMITTED.value,
                    "base_sha": base_sha,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        return AdmissionResult(admitted=True, run=run)

    def start(
        self,
        project_id: str,
        change_name: str,
        project_root: str | Path | None = None,
    ) -> OrchestrationRun:
        """Admit and run single-change orchestration automatically to a legitimate stop."""
        admission = self.admit_change(project_id, change_name, project_root)
        if not admission.admitted or not admission.run:
            raise ValueError(admission.refusal_reason or "Admission failed")

        return self.drive_coordinator(admission.run.run_id, project_root=project_root)

    def resume(
        self,
        run_id: str,
        project_root: str | Path | None = None,
    ) -> OrchestrationRun:
        """Resume an orchestration run from its persisted resumable checkpoint."""
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if not run:
            raise ValueError(f"Orchestration run '{run_id}' not found.")

        # Check if already in terminal state
        if run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE:
            return run

        # Revalidate / clear transient waiting states when resuming
        if run.stop_outcome == OrchestrationStopOutcome.WAITING_CAPACITY:
            project = self.uow.projects.get_by_id(run.project_id)
            if project:
                health = self.pipeline.health_service.get_health(project.implementer)
                if health.status == ProviderHealthStatus.AVAILABLE:
                    run.stop_outcome = None
                    run.human_gate = None
                    run.is_active = True
                    run.stop_reason = None
                    run.stop_details = {}
                    self.uow.orchestration_runs.save(run)
                    self.uow.commit()
                else:
                    logger.info(
                        f"Resume for run '{run_id}' skipped: provider '{project.implementer}' still {health.status.value}."
                    )
                    return run

        elif run.stop_outcome == OrchestrationStopOutcome.WAITING_EXTERNAL:
            run.stop_outcome = None
            run.human_gate = None
            run.is_active = True
            run.stop_reason = None
            run.stop_details = {}
            self.uow.orchestration_runs.save(run)
            self.uow.commit()

        elif run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN:
            # Escalated runs require explicit human resolution before resuming
            return run

        self.uow.orchestration_stage_events.save(
            OrchestrationStageEvent(
                run_id=run.run_id,
                from_stage=run.current_stage,
                to_stage=run.resumable_stage,
                event_type=EventType.ORCHESTRATION_RESUMED.value,
                transition_key=f"{run.run_id}:RESUME:{utc_now().isoformat()}",
                evidence_references={"resumed_from": run.resumable_stage.value},
                actor="system",
                created_at=utc_now(),
            )
        )
        self.uow.commit()

        return self.drive_coordinator(run.run_id, project_root=project_root)

    def drive_coordinator(
        self,
        run_id: str,
        project_root: str | Path | None = None,
    ) -> OrchestrationRun:
        """Drive the deterministic stage state machine until a legitimate stop outcome."""
        root = Path(project_root).resolve() if project_root else self.project_root

        while True:
            run = self.uow.orchestration_runs.get_by_id(run_id)
            if not run or not run.is_active or run.stop_outcome is not None:
                break

            stage = run.current_stage
            logger.info(f"COORDINATOR STAGE: {stage.value}")

            if stage == OrchestrationStage.ADMITTED:
                self._advance_stage(run, OrchestrationStage.PREPARING_EXECUTION)

            elif stage == OrchestrationStage.PREPARING_EXECUTION:
                project = self.uow.projects.get_by_id(run.project_id)
                if not project:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason=f"Project '{run.project_id}' missing during execution prep.",
                        stop_details={"code": "PROJECT_NOT_FOUND"},
                    )
                    break

                # 1. Check provider capacity before execution
                effective_executor = project.implementer
                health = self.pipeline.health_service.get_health(effective_executor)
                if health.status != ProviderHealthStatus.AVAILABLE:
                    # Capacity shortage -> WAITING_CAPACITY (not a human gate)
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.WAITING_CAPACITY,
                        human_gate=None,
                        stop_reason=f"Primary implementer '{effective_executor}' is {health.status.value}.",
                        stop_details={
                            "provider": effective_executor,
                            "status": health.status.value,
                        },
                    )
                    break

                # 2. Attach or queue Job
                if not run.active_job_id:
                    existing_jobs = self.uow.jobs.list_by_project(run.project_id)
                    matching = [j for j in existing_jobs if j.change_name == run.change_name]
                    job = matching[0] if matching else None
                    if not job:
                        try:
                            job = self.pipeline.queue_job(run.project_id, run.change_name)
                        except ValueError as exc:
                            if (
                                "waiting for capacity recovery" in str(exc).lower()
                                or "scheduler is in wait mode" in str(exc).lower()
                            ):
                                self._stop_run(
                                    run,
                                    stop_outcome=OrchestrationStopOutcome.WAITING_CAPACITY,
                                    human_gate=None,
                                    stop_reason=str(exc),
                                    stop_details={"provider": effective_executor},
                                )
                                break
                            raise
                    run.active_job_id = job.job_id
                    self.uow.orchestration_runs.update_active_job(run.run_id, job.job_id)
                    self.uow.commit()

                self._advance_stage(run, OrchestrationStage.IMPLEMENTING)

            elif stage == OrchestrationStage.IMPLEMENTING:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                if not job:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason=f"Active job '{run.active_job_id}' not found.",
                        stop_details={"code": "JOB_NOT_FOUND"},
                    )
                    break

                # Execute attempt via pipeline
                import asyncio

                try:
                    job = asyncio.run(self.pipeline.execute_queued_job(job.job_id))
                except Exception as exc:
                    logger.error(f"Error executing job attempt for run '{run.run_id}': {exc}")
                    job = self.uow.jobs.get_by_id(run.active_job_id)

                if not job:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason="Job execution aborted unexpectedly.",
                    )
                    break

                if job.status == JobStatus.WAITING_CAPACITY:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.WAITING_CAPACITY,
                        human_gate=None,
                        stop_reason=job.capacity_block_reason
                        or f"Waiting capacity for provider '{job.waiting_provider}'",
                        stop_details={"provider": job.waiting_provider},
                    )
                    break

                self._advance_stage(run, OrchestrationStage.EVALUATING_ATTEMPT)

            elif stage == OrchestrationStage.EVALUATING_ATTEMPT:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                if not job:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason="Active job missing during evaluation.",
                    )
                    break

                attempts = self.uow.job_attempts.list_by_job(job.job_id)
                attempts.sort(key=lambda a: a.attempt_number)
                latest_att = attempts[-1] if attempts else None

                if job.status in {
                    JobStatus.READY_TO_MERGE,
                    JobStatus.CHECKS_PASSED,
                    JobStatus.CHANGES_REQUIRED,
                    JobStatus.AUDIT_BLOCKED,
                } or (latest_att and latest_att.normalized_outcome == ExecutionOutcome.COMPLETED):
                    # Ready for checks / freeze / review / audit stages
                    self._advance_stage(run, OrchestrationStage.RUNNING_CHECKS)
                else:
                    decision = (
                        latest_att.continuation_decision
                        if latest_att
                        else job.continuation_decision
                    )
                    outcome = latest_att.normalized_outcome if latest_att else job.latest_outcome

                    if decision in {
                        ContinuationDecision.CONTINUE_SAME_AGENT,
                        ContinuationDecision.CORRECT_AND_RETRY,
                        ContinuationDecision.REASSIGN_AGENT,
                    }:
                        self._advance_stage(run, OrchestrationStage.IMPLEMENTING)
                    elif decision == ContinuationDecision.WAIT_EXTERNAL:
                        self._stop_run(
                            run,
                            stop_outcome=OrchestrationStopOutcome.WAITING_EXTERNAL,
                            human_gate=None,
                            stop_reason=job.escalation_reason or "Waiting on external dependency.",
                            stop_details={"code": "WAIT_EXTERNAL"},
                        )
                        break
                    elif (
                        decision == ContinuationDecision.NEEDS_HUMAN
                        or job.status == JobStatus.NEEDS_HUMAN
                    ):
                        self._stop_run(
                            run,
                            stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                            human_gate=HumanGate.NEEDS_HUMAN,
                            stop_reason=job.escalation_reason
                            or "Escalated by continuation governance.",
                            stop_details={
                                "code": "NEEDS_HUMAN",
                                "outcome": outcome.value if outcome else None,
                            },
                        )
                        break
                    else:
                        # Verified complete or ready for checks
                        self._advance_stage(run, OrchestrationStage.RUNNING_CHECKS)

            elif stage == OrchestrationStage.RUNNING_CHECKS:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                project = self.uow.projects.get_by_id(run.project_id)
                if not job or not job.candidate_sha:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason="Execution pipeline did not persist a verified candidate SHA.",
                        stop_details={"code": "MISSING_AUTHORITATIVE_CANDIDATE"},
                    )
                    break

                # ExecutionPipelineService owns deterministic check execution.  It persists
                # those results before cleaning up its worktree, so orchestration must consume
                # that authority rather than rerun checks against a path that no longer exists.
                checks_to_run = project.checks if project and project.checks else []
                persisted_checks = self.uow.check_results.list_by_job(job.job_id)
                checks_by_name = {result.check_name: result for result in persisted_checks}
                missing_checks = [
                    check.get("name")
                    for check in checks_to_run
                    if check.get("name") not in checks_by_name
                ]
                if missing_checks:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason="Execution pipeline did not persist results for every configured check.",
                        stop_details={
                            "code": "INCOMPLETE_AUTHORITATIVE_CHECKS",
                            "missing_checks": missing_checks,
                        },
                    )
                    break

                all_passed = all(
                    checks_by_name[check.get("name")].exit_code == 0 for check in checks_to_run
                )
                if not all_passed:
                    if job.status not in {JobStatus.CHECKS_FAILED, JobStatus.FAILED}:
                        self.uow.jobs.transition(
                            job.job_id,
                            JobStatus.CHECKS_FAILED.value,
                            error_message="Deterministic checks failed.",
                        )
                    self._advance_stage(run, OrchestrationStage.EVALUATING_ATTEMPT)
                else:
                    if job.status in {JobStatus.RUNNING, JobStatus.CHECKS_RUNNING}:
                        self.uow.jobs.transition(job.job_id, JobStatus.CHECKS_PASSED.value)
                    self._advance_stage(run, OrchestrationStage.FREEZING_CANDIDATE)

            elif stage == OrchestrationStage.FREEZING_CANDIDATE:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                if not job or not job.candidate_sha or job.base_sha != run.base_sha:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason="Candidate identity is incomplete or does not match the admitted base.",
                        stop_details={"code": "CANDIDATE_IDENTITY_MISMATCH"},
                    )
                    break

                # The execution pipeline generated and persisted the manifest while the
                # managed worktree existed.  Reuse that exact immutable evidence; never
                # regenerate it from the finalized (and cleaned) worktree path.
                manifest = self.uow.candidate_manifests.get_by_candidate_sha(
                    job.job_id, job.candidate_sha
                )
                if not manifest or not manifest.manifest_hash or manifest.total_files_count <= 0:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason="Execution pipeline did not persist a non-empty candidate manifest.",
                        stop_details={
                            "code": "MISSING_AUTHORITATIVE_MANIFEST",
                            "candidate_sha": job.candidate_sha,
                        },
                    )
                    break
                head_sha = job.candidate_sha
                authorships = self.uow.candidate_authorships.list_by_job(job.job_id)

                latest_candidate = self.uow.orchestration_candidates.get_latest_for_run(run.run_id)
                if not latest_candidate:
                    # Generation 1
                    cand = OrchestrationCandidate(
                        run_id=run.run_id,
                        generation=1,
                        base_sha=run.base_sha,
                        candidate_sha=head_sha,
                        manifest_id=manifest.manifest_id,
                        manifest_hash=manifest.manifest_hash,
                        authorship_summary={"authorships_count": len(authorships)},
                        is_frozen=True,
                    )
                    self.uow.orchestration_candidates.save(cand)
                    run.current_generation = 1
                    run.current_candidate_sha = head_sha
                    self.uow.orchestration_runs.update_candidate_binding(run.run_id, 1, head_sha)
                else:
                    if (
                        latest_candidate.candidate_sha != head_sha
                        or latest_candidate.manifest_hash != manifest.manifest_hash
                    ):
                        # Material remediation -> increment generation
                        next_gen = latest_candidate.generation + 1
                        new_cand = OrchestrationCandidate(
                            run_id=run.run_id,
                            generation=next_gen,
                            base_sha=run.base_sha,
                            candidate_sha=head_sha,
                            manifest_id=manifest.manifest_id,
                            manifest_hash=manifest.manifest_hash,
                            authorship_summary={"authorships_count": len(authorships)},
                            is_frozen=True,
                        )
                        self.uow.orchestration_candidates.save(new_cand)
                        self.uow.orchestration_candidates.supersede(
                            latest_candidate.candidate_id, new_cand.candidate_id
                        )
                        run.current_generation = next_gen
                        run.current_candidate_sha = head_sha
                        self.uow.orchestration_runs.update_candidate_binding(
                            run.run_id, next_gen, head_sha
                        )

                current_candidate = self.uow.orchestration_candidates.get_latest_for_run(run.run_id)
                if current_candidate:
                    self._bind_current_authority_records(run, job, current_candidate)

                self._advance_stage(run, OrchestrationStage.COMPLEMENTARY_REVIEW)

            elif stage == OrchestrationStage.COMPLEMENTARY_REVIEW:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                current_cand = self.uow.orchestration_candidates.get_latest_for_run(run.run_id)
                if not current_cand:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason="No frozen candidate found for complementary review.",
                    )
                    break

                valid, verdict, reason = self._validate_review_authority(run, job, current_cand)
                if valid and verdict == ReviewVerdict.READY_TO_MERGE:
                    self._advance_stage(run, OrchestrationStage.INDEPENDENT_AUDIT)
                else:
                    # Changes required or invalid/missing review authority -> route to review remediation
                    self._advance_stage(run, OrchestrationStage.REVIEW_REMEDIATION)

            elif stage == OrchestrationStage.REVIEW_REMEDIATION:
                # Review changes required -> route to continuation remediation attempt
                self._advance_stage(run, OrchestrationStage.IMPLEMENTING)

            elif stage == OrchestrationStage.INDEPENDENT_AUDIT:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                current_cand = self.uow.orchestration_candidates.get_latest_for_run(run.run_id)
                if not current_cand:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason="No frozen candidate found for independent audit.",
                    )
                    break

                valid, is_passing, reason = self._validate_audit_authority(run, job, current_cand)
                if valid and is_passing:
                    self._advance_stage(run, OrchestrationStage.PREPARING_PR)
                else:
                    # Audit failed or missing/invalid audit authority -> route to audit remediation
                    self._advance_stage(run, OrchestrationStage.AUDIT_REMEDIATION)

            elif stage == OrchestrationStage.AUDIT_REMEDIATION:
                # Audit failed -> feed to continuation governance for corrective remediation
                self._advance_stage(run, OrchestrationStage.IMPLEMENTING)

            elif stage == OrchestrationStage.PREPARING_PR:
                job = self.uow.jobs.get_by_id(run.active_job_id)
                project = self.uow.projects.get_by_id(run.project_id)
                binding = self.uow.bindings.get_by_project_and_change(
                    run.project_id, run.change_name
                )
                current_cand = self.uow.orchestration_candidates.get_latest_for_run(run.run_id)
                if not current_cand:
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                        human_gate=HumanGate.NEEDS_HUMAN,
                        stop_reason="No frozen candidate found for PR preparation.",
                    )
                    break

                # STRICT AUDIT GATE: PR preparation requires an actual CURRENT authoritative DeepSeek Direct audit
                audit_valid, audit_passing, audit_reason = self._validate_audit_authority(
                    run=run, job=job, cand=current_cand
                )
                if not audit_valid or not audit_passing:
                    logger.warning(
                        f"PR preparation blocked: no valid passing audit for candidate '{current_cand.candidate_sha}'. Reason: {audit_reason}"
                    )
                    # Cannot prepare PR without authoritative audit -> stay in INDEPENDENT_AUDIT
                    self._advance_stage(run, OrchestrationStage.INDEPENDENT_AUDIT)
                    continue

                cand_sha = current_cand.candidate_sha
                gen = current_cand.generation
                branch_name = f"minime/{run.change_name}"

                # 1. Mutating Git Action: Branch Push
                push_key = f"push:{run.run_id}:gen{gen}:{cand_sha}"
                push_action = self.uow.orchestration_external_actions.get_by_action_key(push_key)
                if not push_action:
                    push_action = OrchestrationExternalAction(
                        run_id=run.run_id,
                        action_key=push_key,
                        action_type=ExternalActionType.BRANCH_PUSH,
                        target_identity=f"{project.repository}:{branch_name}",
                        request_fingerprint=f"push:{cand_sha}",
                        candidate_sha=cand_sha,
                        generation=gen,
                        status=ExternalActionStatus.RESERVED,
                    )
                    self.uow.orchestration_external_actions.reserve(push_action)
                    self.uow.commit()

                # Reconcile remote branch head before any push attempt
                try:
                    remote_sha = self.github_adapter.get_remote_branch_head(
                        repository=str(root),
                        branch=branch_name,
                        remote="origin",
                    )
                except Exception as exc:
                    logger.warning(f"Could not observe remote branch '{branch_name}': {exc}")
                    self._stop_run(
                        run,
                        stop_outcome=OrchestrationStopOutcome.WAITING_EXTERNAL,
                        human_gate=None,
                        stop_reason=f"Cannot observe remote branch state: {exc}",
                        stop_details={"action_key": push_key},
                    )
                    break

                if remote_sha is not None:
                    if remote_sha == cand_sha:
                        # Remote already matches exact audited candidate SHA -> mark COMPLETED, ZERO second push
                        if push_action.status != ExternalActionStatus.COMPLETED:
                            self.uow.orchestration_external_actions.update_status(
                                push_key,
                                ExternalActionStatus.COMPLETED,
                                remote_identifier=f"refs/heads/{branch_name}",
                            )
                            self.uow.commit()
                    else:
                        # Remote branch exists with different SHA -> contradiction fail closed NEEDS_HUMAN, ZERO push
                        self.uow.orchestration_external_actions.update_status(
                            push_key,
                            ExternalActionStatus.FAILED,
                            error_message=f"Remote branch head '{remote_sha}' differs from candidate '{cand_sha}'.",
                        )
                        self._stop_run(
                            run,
                            stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                            human_gate=HumanGate.NEEDS_HUMAN,
                            stop_reason=f"Remote branch '{branch_name}' already exists with SHA '{remote_sha}' (differs from audited '{cand_sha}').",
                            stop_details={
                                "code": "REMOTE_BRANCH_MISMATCH",
                                "remote_sha": remote_sha,
                                "expected": cand_sha,
                            },
                        )
                        break
                else:
                    # Remote branch does not exist yet -> execute push once
                    if push_action.status != ExternalActionStatus.COMPLETED:
                        repository_context, context_error = self._validated_repository_context(
                            root, project, binding, cand_sha
                        )
                        if context_error:
                            self.uow.orchestration_external_actions.update_status(
                                push_key,
                                ExternalActionStatus.FAILED,
                                error_message=context_error,
                            )
                            self._stop_run(
                                run,
                                stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                                human_gate=HumanGate.NEEDS_HUMAN,
                                stop_reason=context_error,
                                stop_details={"code": "INVALID_PUSH_REPOSITORY_CONTEXT"},
                            )
                            break
                        try:
                            self.github_adapter.push_branch(
                                worktree_path=str(repository_context),
                                remote="origin",
                                branch=branch_name,
                                candidate_sha=cand_sha,
                            )
                            self.uow.orchestration_external_actions.update_status(
                                push_key,
                                ExternalActionStatus.COMPLETED,
                                remote_identifier=f"refs/heads/{branch_name}",
                            )
                            self.uow.commit()
                        except Exception as exc:
                            logger.warning(
                                f"Branch push transient failure for run '{run.run_id}': {exc}"
                            )
                            self.uow.orchestration_external_actions.update_status(
                                push_key,
                                ExternalActionStatus.FAILED,
                                error_message=str(exc),
                            )
                            self._stop_run(
                                run,
                                stop_outcome=OrchestrationStopOutcome.WAITING_EXTERNAL,
                                human_gate=None,
                                stop_reason=f"Branch push temporarily failed: {exc}",
                                stop_details={"action_key": push_key},
                            )
                            break

                # 2. Mutating GitHub Action: PR Create / Reconcile
                pr_key = f"pr:{run.run_id}:gen{gen}:{cand_sha}"
                pr_action = self.uow.orchestration_external_actions.get_by_action_key(pr_key)
                if not pr_action:
                    pr_action = OrchestrationExternalAction(
                        run_id=run.run_id,
                        action_key=pr_key,
                        action_type=ExternalActionType.PR_CREATE,
                        target_identity=f"{project.repository}:{branch_name}",
                        request_fingerprint=f"pr:{cand_sha}",
                        candidate_sha=cand_sha,
                        generation=gen,
                        status=ExternalActionStatus.RESERVED,
                    )
                    self.uow.orchestration_external_actions.reserve(pr_action)
                    self.uow.commit()

                if pr_action.status != ExternalActionStatus.COMPLETED:
                    try:
                        # Check if PR already exists on GitHub
                        lookup = self.github_adapter.get_pull_request(
                            repository=project.repository,
                            branch=branch_name,
                            base=project.base_branch,
                        )
                        lookup_state = getattr(lookup, "state", None)
                        if lookup_state is not None:
                            if lookup_state == PullRequestLookupState.UNOBSERVABLE:
                                self._stop_run(
                                    run,
                                    stop_outcome=OrchestrationStopOutcome.WAITING_EXTERNAL,
                                    human_gate=None,
                                    stop_reason=lookup.detail or "Cannot observe remote PR state.",
                                    stop_details={"action_key": pr_key, "code": lookup_state.value},
                                )
                                break
                            if lookup_state == PullRequestLookupState.AMBIGUOUS:
                                self._stop_run(
                                    run,
                                    stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                                    human_gate=HumanGate.NEEDS_HUMAN,
                                    stop_reason=lookup.detail or "Remote PR state is ambiguous.",
                                    stop_details={"action_key": pr_key, "code": lookup_state.value},
                                )
                                break
                            existing_pr = lookup.pull_request
                        else:
                            # Existing deterministic test doubles return the legacy shape.  A
                            # real GitHubAdapter always returns PullRequestLookupResult.
                            existing_pr = lookup
                        if existing_pr:
                            valid_adoption, reason, details = self._verify_pr_adoption_identity(
                                existing_pr=existing_pr,
                                project=project,
                                binding=binding,
                                run=run,
                                expected_branch=branch_name,
                                cand_sha=cand_sha,
                            )
                            if valid_adoption:
                                # Adopt existing matching PR
                                self.uow.orchestration_external_actions.update_status(
                                    pr_key,
                                    ExternalActionStatus.COMPLETED,
                                    remote_identifier=existing_pr.get("url"),
                                    result_payload=existing_pr,
                                )
                                binding.github_pr_number = existing_pr["number"]
                                binding.github_pr_url = existing_pr.get("url")
                                self.uow.bindings.save(binding)
                                self.uow.commit()
                            else:
                                # Contradictory identity / head mismatch -> fail closed NEEDS_HUMAN
                                self.uow.orchestration_external_actions.update_status(
                                    pr_key,
                                    ExternalActionStatus.FAILED,
                                    remote_identifier=existing_pr.get("url"),
                                    error_message=reason,
                                )
                                self._stop_run(
                                    run,
                                    stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                                    human_gate=HumanGate.NEEDS_HUMAN,
                                    stop_reason=reason,
                                    stop_details=details,
                                )
                                break
                        else:
                            # Create new PR
                            new_pr = self.github_adapter.create_pull_request(
                                repository=project.repository,
                                branch=branch_name,
                                base=project.base_branch,
                                title=f"{run.change_name}: Autonomous Orchestration",
                                body=(
                                    f"Autonomous candidate for `{run.change_name}`\n"
                                    f"Closes #{binding.github_issue_number}\n"
                                    f"Audited SHA: `{cand_sha}`"
                                ),
                                head_sha=cand_sha,
                            )
                            remote_head = new_pr.get("head_sha")
                            if remote_head and remote_head != cand_sha:
                                error_msg = f"Created PR head '{remote_head}' differs from audited candidate '{cand_sha}'."
                                self.uow.orchestration_external_actions.update_status(
                                    pr_key,
                                    ExternalActionStatus.FAILED,
                                    remote_identifier=new_pr.get("url"),
                                    error_message=error_msg,
                                )
                                self._stop_run(
                                    run,
                                    stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                                    human_gate=HumanGate.NEEDS_HUMAN,
                                    stop_reason=error_msg,
                                    stop_details={"code": "PR_HEAD_MISMATCH"},
                                )
                                break

                            self.uow.orchestration_external_actions.update_status(
                                pr_key,
                                ExternalActionStatus.COMPLETED,
                                remote_identifier=new_pr.get("url"),
                                result_payload=new_pr,
                            )
                            binding.github_pr_number = new_pr["number"]
                            binding.github_pr_url = new_pr.get("url")
                            self.uow.bindings.save(binding)
                            self.uow.commit()
                    except Exception as exc:
                        logger.warning(
                            f"GitHub PR interaction failure for run '{run.run_id}': {exc}"
                        )
                        self.uow.orchestration_external_actions.update_status(
                            pr_key,
                            ExternalActionStatus.FAILED,
                            error_message=str(exc),
                        )
                        self._stop_run(
                            run,
                            stop_outcome=OrchestrationStopOutcome.WAITING_EXTERNAL,
                            human_gate=None,
                            stop_reason=f"GitHub PR interaction temporarily failed: {exc}",
                            stop_details={"action_key": pr_key},
                        )
                        break

                # 3. Advance to PR_PREPARED
                self._advance_stage(run, OrchestrationStage.PR_PREPARED)

            elif stage == OrchestrationStage.PR_PREPARED:
                # Final terminal checkpoint: set human gate to READY_FOR_HUMAN_MERGE and STOP
                self._stop_run(
                    run,
                    stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
                    human_gate=HumanGate.READY_FOR_HUMAN_MERGE,
                    stop_reason="Audited candidate successfully prepared on GitHub PR. Ready for human merge.",
                    stop_details={"code": "READY_FOR_HUMAN_MERGE"},
                )
                break

        return self.uow.orchestration_runs.get_by_id(run_id) or run

    def get_status(self, run_id: str) -> OrchestrationStatusView:
        """Return truthful, secret-redacted operational status for an orchestration run."""
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if not run:
            raise ValueError(f"Orchestration run '{run_id}' not found.")

        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        current_cand = self.uow.orchestration_candidates.get_latest_for_run(run.run_id)
        events = self.uow.orchestration_stage_events.list_by_run(run.run_id)
        last_event = events[-1] if events else None

        review = self.uow.reviews.get_by_job_id(job.job_id) if job else None
        audit = self.uow.audits.get_by_job_id(job.job_id) if job else None
        checks = self.uow.check_results.list_by_job(job.job_id) if job else []
        pending_handoff = None
        if job:
            handoffs = self.uow.job_handoffs.list_by_job(job.job_id)
            pending = next((h for h in handoffs if not h.is_consumed), None)
            if pending:
                pending_handoff = {
                    "handoff_id": pending.handoff_id,
                    "from_executor": pending.from_executor,
                    "to_executor": pending.to_executor,
                }

        # PR action info
        pr_action = None
        actions = self.uow.orchestration_external_actions.list_by_run(run.run_id)
        for a in reversed(actions):
            if (
                a.action_type == ExternalActionType.PR_CREATE
                and a.status == ExternalActionStatus.COMPLETED
            ):
                pr_action = a
                break

        pr_num = None
        pr_url = None
        pr_head = None
        if pr_action:
            pr_num = pr_action.result_payload.get("number")
            pr_url = pr_action.remote_identifier or pr_action.result_payload.get("url")
            pr_head = pr_action.candidate_sha

        # Candidate review & audit bindings
        review_binding = None
        if review:
            review_binding = {
                "candidate_sha": review.candidate_sha,
                "base_sha": review.base_sha,
                "orchestration_run_id": review.orchestration_run_id,
                "candidate_generation": review.candidate_generation,
                "manifest_id": review.manifest_id,
                "manifest_hash": review.manifest_hash,
                "is_current": bool(
                    current_cand
                    and review.orchestration_run_id == run.run_id
                    and review.candidate_generation == current_cand.generation
                    and review.candidate_sha == current_cand.candidate_sha
                    and review.manifest_id == current_cand.manifest_id
                    and review.manifest_hash == current_cand.manifest_hash
                ),
            }

        audit_binding = None
        if audit:
            audit_binding = {
                "candidate_sha": audit.candidate_sha,
                "base_sha": audit.base_sha,
                "orchestration_run_id": audit.orchestration_run_id,
                "candidate_generation": audit.candidate_generation,
                "manifest_id": audit.manifest_id,
                "manifest_hash": audit.manifest_hash,
                "is_full_candidate": audit.is_full_candidate,
                "is_current": bool(
                    current_cand
                    and audit.orchestration_run_id == run.run_id
                    and audit.candidate_generation == current_cand.generation
                    and audit.candidate_sha == current_cand.candidate_sha
                    and audit.manifest_id == current_cand.manifest_id
                    and audit.manifest_hash == current_cand.manifest_hash
                ),
            }

        checks_status = None
        if checks:
            checks_status = "PASSED" if all(c.exit_code == 0 for c in checks) else "FAILED"

        return OrchestrationStatusView(
            run_id=run.run_id,
            project_id=run.project_id,
            change_name=run.change_name,
            current_stage=run.current_stage,
            resumable_stage=run.resumable_stage,
            is_active=run.is_active,
            active_job_id=run.active_job_id,
            current_executor=job.current_executor if job else None,
            current_generation=run.current_generation,
            base_sha=run.base_sha,
            candidate_sha=run.current_candidate_sha
            or (current_cand.candidate_sha if current_cand else None),
            manifest_hash=current_cand.manifest_hash if current_cand else None,
            checks_status=checks_status,
            review_verdict=review.verdict.value if review and review.verdict else None,
            review_candidate_binding=review_binding,
            audit_status=audit.status.value if audit else None,
            audit_risk=audit.risk.value if audit and audit.risk else None,
            audit_candidate_binding=audit_binding,
            provider_capacity_state={
                "waiting_provider": job.waiting_provider if job else None,
                "capacity_block_reason": job.capacity_block_reason if job else None,
            },
            retry_count=job.attempt_count if job else 0,
            reassignment_count=job.reassignment_count if job else 0,
            pending_handoff=pending_handoff,
            pr_number=pr_num,
            pr_url=pr_url,
            pr_head_sha=pr_head,
            stop_outcome=run.stop_outcome,
            human_gate=run.human_gate,
            stop_reason=redact_secrets(run.stop_reason or "") if run.stop_reason else None,
            stop_details=run.stop_details or {},
            last_transition={
                "from_stage": last_event.from_stage.value
                if last_event and last_event.from_stage
                else None,
                "to_stage": last_event.to_stage.value if last_event else None,
                "event_type": last_event.event_type if last_event else None,
                "timestamp": last_event.created_at.isoformat() if last_event else None,
            }
            if last_event
            else None,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    def _validate_review_authority(
        self,
        run: OrchestrationRun,
        job: Job,
        cand: OrchestrationCandidate,
    ) -> tuple[bool, ReviewVerdict | None, str | None]:
        """
        Deterministically validate review authority against current candidate.
        Requires:
        - candidate exists with candidate_sha
        - review record exists for job
        - status == REVIEW_COMPLETED
        - exact candidate_sha == cand.candidate_sha
        - exact base_sha == run.base_sha
        - manifest_id/manifest_hash match when set
        - structured verdict exists
        Fail closed on any missing field, mismatched identity, or wrong generation.
        """
        if not cand or not cand.candidate_sha:
            return False, None, "No active candidate recorded."

        existing_review = self.uow.reviews.get_by_job_id(job.job_id)
        if not existing_review:
            return False, None, f"No review record exists for job '{job.job_id}'."

        if existing_review.status != ReviewStatus.REVIEW_COMPLETED:
            return (
                False,
                None,
                f"Review status '{existing_review.status.value}' is not REVIEW_COMPLETED.",
            )

        required_review_binding = {
            "orchestration_run_id": (existing_review.orchestration_run_id, run.run_id),
            "candidate_generation": (existing_review.candidate_generation, cand.generation),
            "manifest_id": (existing_review.manifest_id, cand.manifest_id),
            "manifest_hash": (existing_review.manifest_hash, cand.manifest_hash),
        }
        for field, (actual, expected) in required_review_binding.items():
            if actual is None or actual == "":
                return False, None, f"Review binding field '{field}' is missing."
            if expected is None or actual != expected:
                return (
                    False,
                    None,
                    f"Review binding field '{field}' does not match current candidate.",
                )

        project = self.uow.projects.get_by_id(run.project_id)
        if not project or existing_review.reviewer_role != project.reviewer:
            return False, None, "Review reviewer identity does not match the assigned reviewer."

        if not existing_review.candidate_sha or existing_review.candidate_sha != cand.candidate_sha:
            return (
                False,
                None,
                f"Review candidate SHA '{existing_review.candidate_sha}' does not match current candidate '{cand.candidate_sha}'.",
            )

        if not existing_review.base_sha or existing_review.base_sha != run.base_sha:
            return (
                False,
                None,
                f"Review base SHA '{existing_review.base_sha}' does not match run base '{run.base_sha}'.",
            )

        if existing_review.verdict is None:
            return False, None, "Review has no structured verdict."

        return True, existing_review.verdict, None

    def _validate_audit_authority(
        self,
        run: OrchestrationRun,
        job: Job,
        cand: OrchestrationCandidate,
    ) -> tuple[bool, bool, str | None]:
        """
        Deterministically validate DeepSeek Direct audit authority against current candidate.
        Requires:
        - candidate exists with candidate_sha
        - audit record exists for job
        - status == AUDIT_COMPLETED
        - provider == 'deepseek'
        - is_full_candidate == True
        - exact candidate_sha == cand.candidate_sha
        - exact base_sha == run.base_sha
        - 0 CRITICAL, 0 HIGH, 0 MEDIUM findings
        Fail closed on any missing field or mismatch.
        Returns: (is_valid, is_passing, reason)
        """
        if not cand or not cand.candidate_sha:
            return False, False, "No active candidate recorded."

        existing_audit = self.uow.audits.get_by_job_id(job.job_id)
        if not existing_audit:
            return False, False, f"No audit record exists for job '{job.job_id}'."

        if existing_audit.status != AuditStatus.AUDIT_COMPLETED:
            return (
                False,
                False,
                f"Audit status '{existing_audit.status.value}' is not AUDIT_COMPLETED.",
            )

        if existing_audit.provider not in {"deepseek_direct", "deepseek"}:
            return (
                False,
                False,
                f"Audit provider '{existing_audit.provider}' is not DeepSeek Direct.",
            )

        if existing_audit.is_full_candidate is not True:
            return (
                False,
                False,
                "Audit was not performed over full candidate explicitly (is_full_candidate must be true).",
            )

        required_audit_binding = {
            "orchestration_run_id": (existing_audit.orchestration_run_id, run.run_id),
            "candidate_generation": (existing_audit.candidate_generation, cand.generation),
            "manifest_id": (existing_audit.manifest_id, cand.manifest_id),
            "manifest_hash": (existing_audit.manifest_hash, cand.manifest_hash),
        }
        for field, (actual, expected) in required_audit_binding.items():
            if actual is None or actual == "":
                return False, False, f"Audit binding field '{field}' is missing."
            if expected is None or actual != expected:
                return (
                    False,
                    False,
                    f"Audit binding field '{field}' does not match current candidate.",
                )

        if not existing_audit.candidate_sha or existing_audit.candidate_sha != cand.candidate_sha:
            return (
                False,
                False,
                f"Audit candidate SHA '{existing_audit.candidate_sha}' does not match current candidate '{cand.candidate_sha}'.",
            )

        if not existing_audit.base_sha or existing_audit.base_sha != run.base_sha:
            return (
                False,
                False,
                f"Audit base SHA '{existing_audit.base_sha}' does not match run base '{run.base_sha}'.",
            )

        has_blocking = False
        for f in existing_audit.findings:
            if f.severity in {
                AuditFindingSeverity.CRITICAL,
                AuditFindingSeverity.HIGH,
                AuditFindingSeverity.MEDIUM,
            }:
                has_blocking = True
                break

        if has_blocking:
            return True, False, "Audit contains blocking findings (CRITICAL/HIGH/MEDIUM)."

        return True, True, None

    def _advance_stage(
        self,
        run: OrchestrationRun,
        to_stage: OrchestrationStage,
        correlation_id: str | None = None,
    ) -> None:
        """Advance run to next stage with finite graph validation and deterministic transition events."""
        from_stage = run.current_stage
        allowed = ALLOWED_STAGE_TRANSITIONS.get(from_stage, set())
        if to_stage not in allowed:
            error_msg = f"Illegal stage transition from '{from_stage.value}' to '{to_stage.value}'."
            logger.error(error_msg)
            self._stop_run(
                run,
                stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                human_gate=HumanGate.NEEDS_HUMAN,
                stop_reason=error_msg,
                stop_details={"from_stage": from_stage.value, "to_stage": to_stage.value},
            )
            raise ValueError(error_msg)

        evidence_error = self._stage_evidence_error(run, to_stage)
        if evidence_error:
            self._stop_run(
                run,
                stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                human_gate=HumanGate.NEEDS_HUMAN,
                stop_reason=evidence_error,
                stop_details={"from_stage": from_stage.value, "to_stage": to_stage.value},
            )
            raise ValueError(evidence_error)

        candidate_key = run.current_candidate_sha or "none"
        transition_key = f"{run.run_id}:{from_stage.value}->{to_stage.value}:gen{run.current_generation}:cand{candidate_key}:{correlation_id or 'default'}"
        existing_event = self.uow.orchestration_stage_events.get_by_transition_key(transition_key)

        requested_evidence = {
            "generation": run.current_generation,
            "candidate_sha": run.current_candidate_sha,
        }
        if existing_event:
            existing_evidence = existing_event.evidence_references or {}
            if (
                existing_event.run_id != run.run_id
                or existing_event.from_stage != from_stage
                or existing_event.to_stage != to_stage
                or existing_evidence != requested_evidence
            ):
                conflict = f"Conflicting orchestration transition event for key '{transition_key}'."
                self._stop_run(
                    run,
                    stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                    human_gate=HumanGate.NEEDS_HUMAN,
                    stop_reason=conflict,
                    stop_details={"transition_key": transition_key},
                )
                raise ValueError(conflict)

        run.current_stage = to_stage
        run.resumable_stage = to_stage
        run.updated_at = utc_now()
        self.uow.orchestration_runs.save(run)

        if not existing_event:
            self.uow.orchestration_stage_events.save(
                OrchestrationStageEvent(
                    run_id=run.run_id,
                    from_stage=from_stage,
                    to_stage=to_stage,
                    event_type=EventType.ORCHESTRATION_STAGE_TRANSITIONED.value,
                    transition_key=transition_key,
                    evidence_references=requested_evidence,
                    actor="system",
                    created_at=utc_now(),
                )
            )
        self.uow.commit()

    def _stage_evidence_error(
        self, run: OrchestrationRun, to_stage: OrchestrationStage
    ) -> str | None:
        """Return a fail-closed reason when the target stage lacks authority evidence."""
        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        candidate = self.uow.orchestration_candidates.get_latest_for_run(run.run_id)

        if to_stage == OrchestrationStage.FREEZING_CANDIDATE:
            if not job:
                return "Cannot freeze candidate without an active job."
            checks = self.uow.check_results.list_by_job(job.job_id)
            project = self.uow.projects.get_by_id(run.project_id)
            if (
                project
                and project.checks
                and (not checks or any(result.exit_code != 0 for result in checks))
            ):
                return "Cannot freeze candidate without authoritative passing checks."
        elif to_stage == OrchestrationStage.COMPLEMENTARY_REVIEW:
            if (
                not candidate
                or not candidate.is_frozen
                or not candidate.manifest_id
                or not candidate.manifest_hash
            ):
                return "Cannot enter complementary review without a frozen candidate manifest."
        elif to_stage == OrchestrationStage.INDEPENDENT_AUDIT:
            if not job or not candidate:
                return "Cannot enter independent audit without current job and candidate evidence."
            valid, verdict, reason = self._validate_review_authority(run, job, candidate)
            if not valid or verdict != ReviewVerdict.READY_TO_MERGE:
                return (
                    reason
                    or "Cannot enter independent audit without current passing review authority."
                )
        elif to_stage == OrchestrationStage.PREPARING_PR:
            if not job or not candidate:
                return "Cannot prepare PR without current job and candidate evidence."
            valid, passing, reason = self._validate_audit_authority(run, job, candidate)
            if not valid or not passing:
                return reason or "Cannot prepare PR without current passing audit authority."
        elif to_stage == OrchestrationStage.PR_PREPARED:
            if not candidate:
                return "Cannot prepare human merge gate without a current candidate."
            actions = self.uow.orchestration_external_actions.list_by_run(run.run_id)
            completed = {
                action.action_type: action
                for action in actions
                if action.status == ExternalActionStatus.COMPLETED
            }
            push = completed.get(ExternalActionType.BRANCH_PUSH)
            pr = completed.get(ExternalActionType.PR_CREATE)
            if (
                not push
                or not pr
                or (pr.result_payload or {}).get("head_sha") != candidate.candidate_sha
            ):
                return "Cannot prepare human merge gate without reconciled push and exact PR head evidence."
        return None

    def _bind_current_authority_records(
        self, run: OrchestrationRun, job: Job, candidate: OrchestrationCandidate
    ) -> None:
        """Attach pipeline-produced evidence to this immutable candidate generation."""
        review = self.uow.reviews.get_by_job_id(job.job_id)
        if review and review.candidate_sha == candidate.candidate_sha:
            review.orchestration_run_id = run.run_id
            review.candidate_generation = candidate.generation
            review.manifest_id = candidate.manifest_id
            review.manifest_hash = candidate.manifest_hash
            self.uow.reviews.save(review)

        audit = self.uow.audits.get_by_job_id(job.job_id)
        if audit and audit.candidate_sha == candidate.candidate_sha:
            audit.orchestration_run_id = run.run_id
            audit.candidate_generation = candidate.generation
            audit.manifest_id = candidate.manifest_id
            audit.manifest_hash = candidate.manifest_hash
            if audit.status == AuditStatus.AUDIT_COMPLETED:
                audit.is_full_candidate = True
            self.uow.audits.save(audit)
        self.uow.commit()

    def _stop_run(
        self,
        run: OrchestrationRun,
        stop_outcome: OrchestrationStopOutcome,
        human_gate: HumanGate | None = None,
        stop_reason: str | None = None,
        stop_details: dict[str, Any] | None = None,
    ) -> None:
        """Stop run at a legitimate stop outcome, with optional human gate."""
        run.stop_outcome = stop_outcome
        run.human_gate = human_gate
        run.stop_reason = stop_reason
        run.stop_details = stop_details or {}
        run.is_active = stop_outcome in {
            OrchestrationStopOutcome.WAITING_CAPACITY,
            OrchestrationStopOutcome.WAITING_EXTERNAL,
        }
        run.updated_at = utc_now()
        self.uow.orchestration_runs.save(run)

        event_type = (
            EventType.READY_FOR_HUMAN_MERGE.value
            if stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
            else EventType.ORCHESTRATION_STOPPED.value
        )
        transition_key = f"{run.run_id}:STOP:{stop_outcome.value}:gen{run.current_generation}"
        existing_event = self.uow.orchestration_stage_events.get_by_transition_key(transition_key)
        if not existing_event:
            self.uow.orchestration_stage_events.save(
                OrchestrationStageEvent(
                    run_id=run.run_id,
                    from_stage=run.current_stage,
                    to_stage=run.current_stage,
                    event_type=event_type,
                    transition_key=transition_key,
                    evidence_references={
                        "stop_outcome": stop_outcome.value,
                        "human_gate": human_gate.value if human_gate else None,
                        "reason": stop_reason,
                    },
                    actor="system",
                    created_at=utc_now(),
                )
            )
        self.uow.events.save(
            Event(
                event_type=EventType.ORCHESTRATION_STOPPED,
                project_id=run.project_id,
                change_id=run.change_name,
                operation_id=run.run_id,
                payload={
                    "run_id": run.run_id,
                    "stage": run.current_stage.value,
                    "stop_outcome": stop_outcome.value,
                    "human_gate": human_gate.value if human_gate else None,
                    "stop_reason": stop_reason,
                },
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

    def _resolve_base_sha(self, project: Project, root: Path) -> str:
        """Resolve base SHA from repository git HEAD or fallback."""
        import subprocess

        try:
            cmd = ["git", "rev-parse", f"origin/{project.base_branch}"]
            res = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()

            cmd_local = ["git", "rev-parse", project.base_branch]
            res_local = subprocess.run(
                cmd_local, cwd=str(root), capture_output=True, text=True, timeout=5
            )
            if res_local.returncode == 0 and res_local.stdout.strip():
                return res_local.stdout.strip()
        except Exception:
            pass
        return "0000000000000000000000000000000000000000"

    def _resolve_head_sha(self, worktree_path: Path) -> str | None:
        """Resolve HEAD SHA of a worktree directory."""
        import subprocess

        if not worktree_path.exists():
            return None
        try:
            cmd = ["git", "rev-parse", "HEAD"]
            res = subprocess.run(
                cmd, cwd=str(worktree_path), capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return None

    def _validated_repository_context(
        self,
        root: Path,
        project: Project,
        binding: ProjectBinding | None,
        candidate_sha: str,
    ) -> tuple[Path, str | None]:
        """Validate the registered repository root and exact audited candidate for push."""
        import subprocess

        if not binding or not binding.is_valid or binding.repository != project.repository:
            return root, "Project repository binding is invalid for branch push."
        try:
            top = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root.resolve():
                return root, f"Registered repository root is not a valid Git repository: {root}"
            candidate = subprocess.run(
                ["git", "rev-parse", "--verify", f"{candidate_sha}^{{commit}}"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if candidate.returncode != 0 or candidate.stdout.strip() != candidate_sha:
                return (
                    root,
                    f"Audited candidate SHA '{candidate_sha}' is not resolvable from {root}.",
                )
        except OSError as exc:
            return root, f"Cannot validate registered repository root '{root}': {exc}"
        return root, None

    def _verify_pr_adoption_identity(
        self,
        existing_pr: dict[str, Any],
        project: Project,
        binding: ProjectBinding | None,
        run: OrchestrationRun,
        expected_branch: str,
        cand_sha: str,
    ) -> tuple[bool, str | None, dict[str, Any]]:
        """Deterministically verify PR identity before adoption without fallbacks. Fail closed on mismatch."""
        # 1. Registered repository identity
        pr_repo = existing_pr.get("repository")
        if not pr_repo or pr_repo != project.repository:
            return (
                False,
                f"PR repository '{pr_repo}' does not match registered repository '{project.repository}'.",
                {
                    "code": "PR_REPOSITORY_MISMATCH",
                    "pr_repo": pr_repo,
                    "expected": project.repository,
                },
            )

        # 2. Durable project/change binding
        if (
            not binding
            or not binding.is_valid
            or not binding.github_issue_number
            or binding.openspec_change_name != run.change_name
        ):
            return (
                False,
                f"Durable binding invalid or mismatched for change '{run.change_name}'.",
                {"code": "INVALID_BINDING"},
            )

        # 3. Expected head branch
        pr_head_branch = existing_pr.get("head_branch") or existing_pr.get("head_ref")
        if not pr_head_branch or pr_head_branch != expected_branch:
            return (
                False,
                f"PR head branch '{pr_head_branch}' does not match expected '{expected_branch}'.",
                {
                    "code": "PR_BRANCH_MISMATCH",
                    "pr_head_branch": pr_head_branch,
                    "expected": expected_branch,
                },
            )

        # 4. Expected base branch
        pr_base_branch = existing_pr.get("base_branch") or existing_pr.get("base_ref")
        if not pr_base_branch or pr_base_branch != project.base_branch:
            return (
                False,
                f"PR base branch '{pr_base_branch}' does not match project base '{project.base_branch}'.",
                {
                    "code": "PR_BASE_MISMATCH",
                    "pr_base_branch": pr_base_branch,
                    "expected": project.base_branch,
                },
            )

        # 5. Exact current independently audited candidate SHA
        remote_head = existing_pr.get("head_sha")
        if not remote_head or remote_head != cand_sha:
            return (
                False,
                f"Remote PR head '{remote_head}' does not match audited candidate SHA '{cand_sha}'.",
                {"code": "PR_HEAD_MISMATCH", "remote_head": remote_head, "expected": cand_sha},
            )

        # 6. PR identifier presence
        pr_number = existing_pr.get("number")
        if not pr_number:
            return (
                False,
                "PR record missing number identifier.",
                {"code": "PR_NUMBER_MISSING"},
            )

        issue_number = binding.github_issue_number
        linkage_text = " ".join(str(existing_pr.get(field) or "") for field in ("title", "body"))
        if (
            not issue_number
            or run.change_name not in linkage_text
            or f"#{issue_number}" not in linkage_text
        ):
            return (
                False,
                "PR does not explicitly link the bound GitHub issue and OpenSpec change.",
                {"code": "PR_LINKAGE_UNPROVEN", "issue_number": issue_number},
            )

        if binding.github_pr_number is not None and pr_number != binding.github_pr_number:
            return (
                False,
                f"Existing durable binding PR #{binding.github_pr_number} differs from discovered PR #{pr_number}.",
                {"code": "PR_NUMBER_MISMATCH"},
            )

        return True, None, {}
