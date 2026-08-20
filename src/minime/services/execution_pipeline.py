"""Execution pipeline orchestration for Stage 1 implementation jobs."""

from __future__ import annotations

from pathlib import Path

from minime.domain.enums import EventType, JobStatus, ReadinessState
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import Event, Job, JobLog, MetricFact, Project, utc_now
from minime.services.checks_runner import ChecksRunner
from minime.services.implementer_runner import ImplementerRunnerInterface, runner_for_implementer
from minime.services.openspec_tasks import OpenSpecTaskTracker
from minime.services.worktree_manager import WorktreeManager

EVENT_BY_STATUS = {
    JobStatus.RUNNING: EventType.JOB_RUNNING,
    JobStatus.CHECKS_RUNNING: EventType.JOB_CHECKS_RUNNING,
    JobStatus.CHECKS_PASSED: EventType.JOB_CHECKS_PASSED,
    JobStatus.CHECKS_FAILED: EventType.JOB_CHECKS_FAILED,
    JobStatus.FAILED: EventType.JOB_FAILED,
    JobStatus.CANCELLED: EventType.JOB_CANCELLED,
}


class ExecutionPipelineService:
    """Coordinates job state, isolated workspace, implementer execution and checks."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path,
        implementer_runner: ImplementerRunnerInterface | None = None,
        worktree_manager: WorktreeManager | None = None,
        checks_runner: ChecksRunner | None = None,
        task_tracker: OpenSpecTaskTracker | None = None,
        implementer_timeout_seconds: int = 3600,
    ):
        self.uow = uow
        self.project_root = Path(project_root)
        self.implementer_runner = implementer_runner
        self.worktree_manager = worktree_manager or WorktreeManager(self.project_root)
        self.checks_runner = checks_runner or ChecksRunner()
        self.task_tracker = task_tracker or OpenSpecTaskTracker(self.project_root)
        self.implementer_timeout_seconds = implementer_timeout_seconds

    def queue_job(self, project_id: str, change_name: str) -> Job:
        project = self._require_project(project_id)
        change = self.uow.changes.get_by_name(project_id, change_name)
        if not change or change.last_readiness_status != ReadinessState.READY:
            raise ValueError(f"Change '{change_name}' for project '{project_id}' is not READY.")
        job = Job(project_id=project_id, change_name=change_name, implementer_role=project.implementer)
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
        phase_started = utc_now()
        checks_started = None
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
            if result.timed_out:
                self._save_event(EventType.JOB_TIMEOUT, job, {"timeout_seconds": self.implementer_timeout_seconds})
                raise RuntimeError("Implementer execution timed out.")
            if result.exit_code != 0:
                raise RuntimeError(f"Implementer exited with code {result.exit_code}.")

            job.candidate_sha = await self.worktree_manager.current_sha(worktree.path)
            self.uow.jobs.save(job)

            incomplete = worktree_task_tracker.incomplete_tasks(project.openspec_path, job.change_name)
            if incomplete:
                self._save_event(
                    EventType.INCOMPLETE_TASKS,
                    job,
                    {"remaining_task_ids": [task.task_id for task in incomplete]},
                )
                raise RuntimeError("OpenSpec tasks remain incomplete.")

            checks_started = utc_now()
            job = self._transition(job, JobStatus.CHECKS_RUNNING)
            check_run = await self.checks_runner.run(job.job_id, project.checks, worktree.path)
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
            self._transition(
                job, JobStatus.CHECKS_PASSED if check_run.passed else JobStatus.CHECKS_FAILED
            )
        except Exception as exc:
            latest = self._require_job(job.job_id)
            if latest.status not in {
                JobStatus.CHECKS_FAILED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.CHECKS_PASSED,
            }:
                self._transition(latest, JobStatus.FAILED, str(exc))
        finally:
            if worktree_created:
                await self.worktree_manager.cleanup_worktree(job.job_id)
            latest = self._require_job(job.job_id)
            if latest.status in {
                JobStatus.CHECKS_PASSED,
                JobStatus.CHECKS_FAILED,
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
                        details={"job_id": latest.job_id, "status": latest.status.value},
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
