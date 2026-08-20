"""Execution pipeline orchestration for implementation and complementary review jobs."""

from __future__ import annotations

from pathlib import Path

from minime.domain.enums import (
    EventType,
    JobStatus,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    Job,
    JobLog,
    MetricFact,
    Project,
    Review,
    ReviewFinding,
    utc_now,
)
from minime.services.candidate_integrity import (
    validate_post_review_integrity,
    validate_pre_review_integrity,
)
from minime.services.checks_runner import ChecksRunner
from minime.services.complementary_policy import validate_complementary_pair
from minime.services.implementer_runner import (
    ImplementerRunnerInterface,
    runner_for_implementer,
)
from minime.services.openspec_tasks import OpenSpecTaskTracker
from minime.services.review_verdict_parser import parse_review_verdict
from minime.services.reviewer_contract import build_reviewer_prompt
from minime.services.reviewer_runner import (
    ReviewerRunnerInterface,
    runner_for_reviewer,
)
from minime.services.reviewer_view import ReviewerViewManager
from minime.services.worktree_manager import WorktreeManager

EVENT_BY_STATUS = {
    JobStatus.RUNNING: EventType.JOB_RUNNING,
    JobStatus.CHECKS_RUNNING: EventType.JOB_CHECKS_RUNNING,
    JobStatus.CHECKS_PASSED: EventType.JOB_CHECKS_PASSED,
    JobStatus.CHECKS_FAILED: EventType.JOB_CHECKS_FAILED,
    JobStatus.REVIEW_RUNNING: EventType.JOB_REVIEW_RUNNING,
    JobStatus.READY_TO_MERGE: EventType.JOB_READY_TO_MERGE,
    JobStatus.CHANGES_REQUIRED: EventType.JOB_CHANGES_REQUIRED,
    JobStatus.FAILED: EventType.JOB_FAILED,
    JobStatus.CANCELLED: EventType.JOB_CANCELLED,
}


class ExecutionPipelineService:
    """Coordinates job state, isolated workspace, implementer execution, checks, and complementary review."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path,
        implementer_runner: ImplementerRunnerInterface | None = None,
        reviewer_runner: ReviewerRunnerInterface | None = None,
        worktree_manager: WorktreeManager | None = None,
        reviewer_view_manager: ReviewerViewManager | None = None,
        checks_runner: ChecksRunner | None = None,
        task_tracker: OpenSpecTaskTracker | None = None,
        implementer_timeout_seconds: int = 3600,
        reviewer_timeout_seconds: int = 3600,
    ):
        self.uow = uow
        self.project_root = Path(project_root)
        self.implementer_runner = implementer_runner
        self.reviewer_runner = reviewer_runner
        self.worktree_manager = worktree_manager or WorktreeManager(self.project_root)
        self.reviewer_view_manager = (
            reviewer_view_manager or ReviewerViewManager(self.project_root)
        )
        self.checks_runner = checks_runner or ChecksRunner()
        self.task_tracker = task_tracker or OpenSpecTaskTracker(self.project_root)
        self.implementer_timeout_seconds = implementer_timeout_seconds
        self.reviewer_timeout_seconds = reviewer_timeout_seconds

    def queue_job(self, project_id: str, change_name: str) -> Job:
        project = self._require_project(project_id)
        change = self.uow.changes.get_by_name(project_id, change_name)
        if not change or change.last_readiness_status != ReadinessState.READY:
            raise ValueError(
                f"Change '{change_name}' for project '{project_id}' is not READY."
            )
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
        try:
            job = self._transition(job, JobStatus.RUNNING)
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
            runner = self.implementer_runner or runner_for_implementer(
                project.implementer
            )
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
            # 1. Policy validation
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

            # 2. Pre-review candidate integrity and base SHA validation
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

            # 3. Create isolated read-only reviewer workspace snapshot
            readonly_view = self.reviewer_view_manager.create_readonly_view(
                worktree.path, job.job_id
            )
            readonly_view_created = True

            # 4. Transition to REVIEW_RUNNING and persist Review record
            job = self._transition(job, JobStatus.REVIEW_RUNNING)
            review = Review(
                job_id=job.job_id,
                project_id=job.project_id,
                change_name=job.change_name,
                reviewer_role=project.reviewer,
                candidate_sha=job.candidate_sha or "",
                base_sha=job.base_sha or "",
                status=ReviewStatus.REVIEW_RUNNING,
            )
            self.uow.reviews.save(review)
            self.uow.commit()

            # 5. Build prompt and execute reviewer runner inside read-only view
            review_prompt = build_reviewer_prompt(
                project=project,
                change_name=job.change_name,
                job_id=job.job_id,
                candidate_sha=job.candidate_sha or "",
                base_sha=job.base_sha or "",
                candidate_worktree_path=readonly_view,
                checks_results=check_run_results,
            )
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

            # 6. Post-review non-mutation integrity validation on original worktree
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

            # 7. Parse structured review verdict strictly
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

            # 8. Apply verdict transition
            if verdict_payload.verdict == ReviewVerdict.READY_TO_MERGE:
                self.uow.reviews.transition(
                    review.review_id,
                    ReviewStatus.REVIEW_COMPLETED.value,
                    verdict=ReviewVerdict.READY_TO_MERGE.value,
                    summary=verdict_payload.summary,
                )
                self.uow.commit()
                self._transition(job, JobStatus.READY_TO_MERGE)
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
                JobStatus.CHANGES_REQUIRED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                self._transition(latest, JobStatus.FAILED, str(exc))
        finally:
            if readonly_view_created:
                self.reviewer_view_manager.cleanup_readonly_view(job.job_id)
            if worktree_created:
                await self.worktree_manager.cleanup_worktree(job.job_id)
            latest = self._require_job(job.job_id)
            if latest.status in {
                JobStatus.READY_TO_MERGE,
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
