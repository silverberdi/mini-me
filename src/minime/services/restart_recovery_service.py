"""Daemon restart reconciliation service and safe Git lock recovery with concrete ownership proof."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from minime.domain.enums import (
    EventType,
    ExternalActionStatus,
    GitOperationStatus,
    HumanGate,
    JobStatus,
    LockSafetyStatus,
    OrchestrationStopOutcome,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    Job,
    LockInspectionResult,
    OrchestrationRun,
    generate_uuid,
    utc_now,
)
from minime.services.provider_health_service import ProviderHealthService

logger = logging.getLogger(__name__)


def is_pid_alive(pid: int) -> bool:
    """Check whether a process with given PID is currently alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class RestartRecoveryService:
    """Reconciles non-terminal jobs on daemon startup and safely recovers abandoned Git locks with ownership proof."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path,
        health_service: ProviderHealthService | None = None,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.managed_worktrees_root = (self.project_root / ".minime" / "worktrees").resolve()
        self.health_service = health_service or ProviderHealthService(uow)

    def reconcile_on_startup(self, orchestration_service: Any = None) -> list[Job]:
        """Reconcile all in-flight / non-terminal jobs and active orchestration runs on daemon startup with full audit evidence."""
        recovery_cycle_id = generate_uuid()
        active_jobs = self.uow.jobs.list_active_jobs()
        active_runs = self.uow.orchestration_runs.list_runs(is_active=True)

        interrupted_jobs = [
            j
            for j in active_jobs
            if j.status
            in {
                JobStatus.RUNNING,
                JobStatus.CHECKS_RUNNING,
                JobStatus.REVIEW_RUNNING,
                JobStatus.AUDIT_RUNNING,
            }
        ]
        waiting_jobs = [j for j in active_jobs if j.status == JobStatus.WAITING_CAPACITY]
        blocked_jobs = [j for j in active_jobs if j.status == JobStatus.RECOVERY_BLOCKED]
        queued_jobs = [j for j in active_jobs if j.status == JobStatus.QUEUED]

        # 1. Persist durable DAEMON_RESTARTED event for this startup recovery cycle
        self.uow.events.save(
            Event(
                event_type=EventType.DAEMON_RESTARTED,
                payload={
                    "recovery_cycle_id": recovery_cycle_id,
                    "active_jobs_count": len(active_jobs),
                    "interrupted_jobs_count": len(interrupted_jobs),
                    "waiting_jobs_count": len(waiting_jobs),
                    "blocked_jobs_count": len(blocked_jobs),
                    "queued_jobs_count": len(queued_jobs),
                    "active_orchestration_runs_count": len(active_runs),
                },
                timestamp=utc_now(),
            )
        )

        reconciled = []
        for job in active_jobs:
            rec_job = self._reconcile_job(job, recovery_cycle_id)
            reconciled.append(rec_job)

        self.reconcile_orchestration_runs(
            orchestration_service=orchestration_service,
            recovery_cycle_id=recovery_cycle_id,
        )

        self.uow.commit()
        return reconciled

    def reconcile_orchestration_runs(
        self,
        orchestration_service: Any = None,
        recovery_cycle_id: str | None = None,
    ) -> list[OrchestrationRun]:
        """Reconcile active orchestration runs on daemon startup."""
        cycle_id = recovery_cycle_id or generate_uuid()
        active_runs = self.uow.orchestration_runs.list_runs(is_active=True)
        reconciled_runs = []

        for run in active_runs:
            rec_run = self._reconcile_orchestration_run(run, orchestration_service, cycle_id)
            reconciled_runs.append(rec_run)

        self.uow.commit()
        return reconciled_runs

    def _reconcile_orchestration_run(
        self,
        run: OrchestrationRun,
        orchestration_service: Any = None,
        recovery_cycle_id: str | None = None,
    ) -> OrchestrationRun:
        """Reconcile a single active orchestration run without duplicate actions."""
        # 1. Check associated active job if any
        if run.active_job_id:
            job = self.uow.jobs.get_by_id(run.active_job_id)
            if job and job.status in {JobStatus.RECOVERY_BLOCKED, JobStatus.NEEDS_HUMAN}:
                run.is_active = False
                run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
                run.human_gate = HumanGate.NEEDS_HUMAN
                run.stop_reason = f"Active job '{job.job_id}' is in {job.status.value}."
                self.uow.orchestration_runs.save(run)
                return run

        # 2. Inspect candidate and external actions
        actions = self.uow.orchestration_external_actions.list_by_run(run.run_id)
        current_cand = self.uow.orchestration_candidates.get_latest_for_run(run.run_id)

        ambiguous_actions = [
            action for action in actions if action.status == ExternalActionStatus.AMBIGUOUS
        ]
        if ambiguous_actions:
            action_keys = [action.action_key for action in ambiguous_actions]
            run.is_active = False
            run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
            run.human_gate = HumanGate.NEEDS_HUMAN
            run.stop_reason = "Restart found ambiguous external action state."
            run.stop_details = {"action_keys": action_keys}
            self.uow.orchestration_runs.save(run)
            self.uow.events.save(
                Event(
                    event_type=EventType.RECOVERY_BLOCKED,
                    project_id=run.project_id,
                    change_id=run.change_name,
                    operation_id=run.run_id,
                    payload={"reason": run.stop_reason, "action_keys": action_keys},
                    timestamp=utc_now(),
                )
            )
            return run

        # 3. Log recovery event
        self.uow.events.save(
            Event(
                event_type="ORCHESTRATION_RECOVERED",
                project_id=run.project_id,
                change_id=run.change_name,
                payload={
                    "run_id": run.run_id,
                    "stage": run.current_stage.value,
                    "resumable_stage": run.resumable_stage.value,
                    "candidate_generation": run.current_generation,
                    "candidate_sha": current_cand.candidate_sha if current_cand else None,
                    "actions_count": len(actions),
                    "recovery_cycle_id": recovery_cycle_id,
                },
                timestamp=utc_now(),
            )
        )

        # 4. If orchestration_service provided, resume the run safely
        if orchestration_service is not None and run.is_active:
            try:
                orchestration_service.resume(run.run_id)
            except Exception as exc:
                logger.warning(
                    f"Failed to auto-resume run '{run.run_id}' during restart recovery: {exc}"
                )

        return run

    def _reconcile_job(self, job: Job, recovery_cycle_id: str) -> Job:
        """Reconcile a single non-terminal job."""
        # 1. Check for unconsumed pending handoff to preserve executor continuity across restart
        pending_handoff = next(
            (h for h in self.uow.job_handoffs.list_by_job(job.job_id) if not h.is_consumed),
            None,
        )
        if pending_handoff:
            job.current_executor = pending_handoff.to_executor
            self.uow.jobs.save(job)

        if job.status == JobStatus.NEEDS_HUMAN:
            logger.info(f"Job '{job.job_id}' is NEEDS_HUMAN; retaining state for human review.")
            return job

        if job.status == JobStatus.RECOVERY_BLOCKED:
            logger.info(
                f"Job '{job.job_id}' is RECOVERY_BLOCKED; retaining state for human inspection."
            )
            return job

        if job.status == JobStatus.WAITING_CAPACITY:
            logger.info(f"Job '{job.job_id}' is WAITING_CAPACITY; retaining state.")
            return job

        if job.status == JobStatus.QUEUED:
            return job

        # 2. For jobs in active execution phase, persist durable JOB_INTERRUPTED evidence BEFORE transition
        stage_map = {
            JobStatus.RUNNING: "implementer",
            JobStatus.CHECKS_RUNNING: "checks",
            JobStatus.REVIEW_RUNNING: "reviewer",
            JobStatus.AUDIT_RUNNING: "auditor",
        }
        interrupted_stage = stage_map.get(job.status, "unknown")

        self.uow.events.save(
            Event(
                event_type=EventType.JOB_INTERRUPTED,
                project_id=job.project_id,
                change_id=job.change_name,
                operation_id=job.job_id,
                payload={
                    "job_id": job.job_id,
                    "project_id": job.project_id,
                    "change_id": job.change_name,
                    "previous_status": job.status.value,
                    "interrupted_stage": interrupted_stage,
                    "candidate_sha": job.candidate_sha,
                    "base_sha": job.base_sha,
                    "implementer_role": job.implementer_role,
                    "recovery_cycle_id": recovery_cycle_id,
                },
                timestamp=utc_now(),
            )
        )

        # 3. Inspect and recover Git locks fail-closed with concrete ownership proof
        worktree_path = self.managed_worktrees_root / job.job_id
        lock_results = self.inspect_git_locks(worktree_path, job)

        unsafe_results = [r for r in lock_results if r.verdict != LockSafetyStatus.SAFE_ORPHANED]
        if unsafe_results:
            reasons = "; ".join([r.reason for r in unsafe_results])
            logger.warning(
                f"Job '{job.job_id}' encountered unsafe Git lock condition: {reasons}. Marking RECOVERY_BLOCKED."
            )
            blocked_job = self.uow.jobs.set_recovery_blocked(
                job_id=job.job_id,
                reason=reasons,
            )
            self.uow.events.save(
                Event(
                    event_type=EventType.RECOVERY_BLOCKED,
                    project_id=job.project_id,
                    change_id=job.change_name,
                    operation_id=job.job_id,
                    payload={
                        "job_id": job.job_id,
                        "reason": reasons,
                        "recovery_cycle_id": recovery_cycle_id,
                        "lock_inspections": [r.model_dump() for r in lock_results],
                    },
                    timestamp=utc_now(),
                )
            )
            return blocked_job

        # Safely remove conclusively proven SAFE_ORPHANED locks and update ownership records
        for safe_res in lock_results:
            if safe_res.verdict == LockSafetyStatus.SAFE_ORPHANED:
                lock_file_path = Path(safe_res.lock_path)
                lock_file_path.unlink(missing_ok=True)
                logger.info(f"Safely removed orphaned mini me Git lock: {safe_res.lock_path}")

                # Update in-flight GitOperation records to RECOVERED
                matching_ops = self.uow.git_operations.list_by_job(job.job_id)
                for op in matching_ops:
                    if op.status in {GitOperationStatus.RUNNING, GitOperationStatus.INTERRUPTED}:
                        self.uow.git_operations.update_status(
                            op.operation_id,
                            GitOperationStatus.RECOVERED,
                            completed_at=utc_now(),
                        )

                self.uow.events.save(
                    Event(
                        event_type=EventType.WORKTREE_LOCK_RECOVERED,
                        project_id=job.project_id,
                        change_id=job.change_name,
                        operation_id=job.job_id,
                        payload={
                            "job_id": job.job_id,
                            "lock_path": safe_res.lock_path,
                            "operation_id": safe_res.operation_id,
                            "owning_pid": safe_res.owning_pid,
                            "reason": safe_res.reason,
                            "recovery_cycle_id": recovery_cycle_id,
                        },
                        timestamp=utc_now(),
                    )
                )

        # 4. Checkpoint preservation & reconciliation
        check_results = self.uow.check_results.list_by_job(job.job_id)
        checks_passed = len(check_results) > 0 and all(c.exit_code == 0 for c in check_results)

        if job.candidate_sha and (checks_passed or job.status == JobStatus.CHECKS_PASSED):
            # Preserved checkpoint: candidate SHA produced and checks passed.
            # Reset stage to CHECKS_PASSED so review stage can resume without re-running implementer/checks.
            target_status = JobStatus.CHECKS_PASSED
            updated = self.uow.jobs.transition(
                job.job_id,
                target_status.value,
                error_message="Recovered on daemon restart; preserved completed implementation and checks.",
            )
            self.uow.events.save(
                Event(
                    event_type=EventType.JOB_RECOVERED,
                    project_id=job.project_id,
                    change_id=job.change_name,
                    operation_id=job.job_id,
                    payload={
                        "job_id": job.job_id,
                        "previous_status": job.status.value,
                        "new_status": target_status.value,
                        "candidate_sha": job.candidate_sha,
                        "checks_passed": True,
                        "recovery_cycle_id": recovery_cycle_id,
                    },
                    timestamp=utc_now(),
                )
            )
            return updated
        else:
            # Did not complete candidate SHA or checks before restart; reset to QUEUED. Never infer success.
            target_status = JobStatus.QUEUED
            updated = self.uow.jobs.transition(
                job.job_id,
                target_status.value,
                error_message="Recovered on daemon restart; re-queued for execution.",
            )
            self.uow.events.save(
                Event(
                    event_type=EventType.JOB_RECOVERED,
                    project_id=job.project_id,
                    change_id=job.change_name,
                    operation_id=job.job_id,
                    payload={
                        "job_id": job.job_id,
                        "previous_status": job.status.value,
                        "new_status": target_status.value,
                        "recovery_cycle_id": recovery_cycle_id,
                    },
                    timestamp=utc_now(),
                )
            )
            return updated

    def inspect_git_locks(self, worktree_path: Path, job: Job) -> list[LockInspectionResult]:
        """Inspect all Git lock files in worktree context fail-closed with concrete ownership proof."""
        if not worktree_path.exists():
            return []

        resolved_worktree = worktree_path.resolve()
        lock_files: list[Path] = []

        # Find direct index.lock files
        lock_files.extend(worktree_path.glob("**/.git/**/index.lock"))
        lock_files.extend(worktree_path.glob(".git/index.lock"))
        lock_files.extend(worktree_path.glob("**/index.lock"))

        if (worktree_path / ".git").is_file():
            # Git worktree file containing `gitdir: <path>`
            try:
                gitdir_content = (worktree_path / ".git").read_text(encoding="utf-8").strip()
                if gitdir_content.startswith("gitdir:"):
                    gitdir_raw = gitdir_content.split("gitdir:", 1)[1].strip()
                    gitdir_path = Path(gitdir_raw)
                    if not gitdir_path.is_absolute():
                        gitdir_path = (worktree_path / gitdir_path).resolve()
                    git_lock = gitdir_path / "index.lock"
                    if git_lock.exists() and git_lock not in lock_files:
                        lock_files.append(git_lock)
            except Exception as e:
                logger.warning(f"Error reading .git file in worktree {worktree_path}: {e}")

        # Deduplicate
        unique_locks = list(dict.fromkeys(lock_files))
        results: list[LockInspectionResult] = []

        for lock_file in unique_locks:
            res = self._inspect_single_lock(lock_file, resolved_worktree, job)
            results.append(res)

        return results

    def _inspect_single_lock(
        self, lock_file: Path, resolved_worktree: Path, job: Job
    ) -> LockInspectionResult:
        """Inspect a single Git lock file against strict fail-closed criteria and concrete ownership evidence."""
        # 1. Symlink inspection
        if lock_file.is_symlink():
            try:
                link_target = lock_file.readlink()
                resolved_target = lock_file.resolve()
                if not (
                    resolved_target.is_relative_to(resolved_worktree)
                    or resolved_target.is_relative_to(self.managed_worktrees_root)
                ):
                    return LockInspectionResult(
                        verdict=LockSafetyStatus.EXTERNAL_OR_INVALID,
                        lock_path=str(lock_file),
                        reason=f"Git lock symlink '{lock_file}' points outside managed worktree context to '{link_target}'",
                    )
            except Exception as e:
                return LockInspectionResult(
                    verdict=LockSafetyStatus.EXTERNAL_OR_INVALID,
                    lock_path=str(lock_file),
                    reason=f"Failed to inspect Git lock symlink '{lock_file}': {e}",
                )

        # 2. Boundary resolution check
        try:
            resolved_lock = lock_file.resolve()
        except Exception as e:
            return LockInspectionResult(
                verdict=LockSafetyStatus.EXTERNAL_OR_INVALID,
                lock_path=str(lock_file),
                reason=f"Failed to resolve lock path '{lock_file}': {e}",
            )

        if not (
            resolved_lock.is_relative_to(self.managed_worktrees_root)
            or resolved_lock.is_relative_to(self.project_root / ".git" / "worktrees")
        ):
            return LockInspectionResult(
                verdict=LockSafetyStatus.EXTERNAL_OR_INVALID,
                lock_path=str(resolved_lock),
                reason=f"Git lock path '{resolved_lock}' is outside mini me-managed worktree context",
            )

        if resolved_lock == (self.project_root / ".git" / "index.lock").resolve():
            return LockInspectionResult(
                verdict=LockSafetyStatus.EXTERNAL_OR_INVALID,
                lock_path=str(resolved_lock),
                reason="Git lock belongs to main project repository root, not a managed worktree",
            )

        if not resolved_lock.exists():
            return LockInspectionResult(
                verdict=LockSafetyStatus.UNCERTAIN,
                lock_path=str(resolved_lock),
                reason=f"Git lock '{resolved_lock}' disappeared or is inaccessible",
            )

        # 3. Mini me Git Operation Ownership Verification (DURABLE EVIDENCE)
        job_ops = [
            op
            for op in self.uow.git_operations.list_by_job(job.job_id)
            if Path(op.worktree_path).resolve() == resolved_worktree
            and op.job_id == job.job_id
            and op.project_id == job.project_id
        ]
        if not job_ops:
            return LockInspectionResult(
                verdict=LockSafetyStatus.UNCERTAIN,
                lock_path=str(resolved_lock),
                reason=f"Git lock '{resolved_lock}' has no matching mini me Git-operation ownership record for job '{job.job_id}' (project '{job.project_id}')",
            )

        # Check conflicting active operations from other jobs on this worktree
        all_worktree_ops = self.uow.git_operations.list_by_worktree(str(resolved_worktree))
        conflicting_ops = [
            op
            for op in all_worktree_ops
            if op.job_id != job.job_id
            and (op.status == GitOperationStatus.RUNNING or (op.pid and is_pid_alive(op.pid)))
        ]
        if conflicting_ops:
            return LockInspectionResult(
                verdict=LockSafetyStatus.UNCERTAIN,
                lock_path=str(resolved_lock),
                reason=f"Conflicting active Git operation '{conflicting_ops[0].operation_id}' from job '{conflicting_ops[0].job_id}' exists on worktree",
            )

        # 4. Content and PID validation
        try:
            stat_info = resolved_lock.stat()
            if stat_info.st_size == 0:
                return LockInspectionResult(
                    verdict=LockSafetyStatus.UNCERTAIN,
                    lock_path=str(resolved_lock),
                    reason=f"Git lock '{resolved_lock}' is empty (0 bytes); ownership cannot be verified",
                )

            raw_content = resolved_lock.read_text(encoding="utf-8", errors="replace").strip()
        except Exception as e:
            return LockInspectionResult(
                verdict=LockSafetyStatus.UNCERTAIN,
                lock_path=str(resolved_lock),
                reason=f"Failed to read Git lock content '{resolved_lock}': {e}",
            )

        # Content must be a valid positive decimal integer PID
        if not raw_content.isdigit() or int(raw_content) <= 0:
            return LockInspectionResult(
                verdict=LockSafetyStatus.UNCERTAIN,
                lock_path=str(resolved_lock),
                reason=f"Git lock '{resolved_lock}' does not contain a valid PID (content: '{raw_content[:50]}'); ownership cannot be verified",
            )

        lock_pid = int(raw_content)

        # 5. Check active process ownership
        if is_pid_alive(lock_pid):
            return LockInspectionResult(
                verdict=LockSafetyStatus.ACTIVE_OWNER,
                lock_path=str(resolved_lock),
                reason=f"Git lock '{resolved_lock}' is owned by active process PID {lock_pid}",
                owning_pid=lock_pid,
            )

        # 6. Verify in-flight / interrupted mini me operation match
        in_flight_ops = [
            op
            for op in job_ops
            if op.status in {GitOperationStatus.RUNNING, GitOperationStatus.INTERRUPTED}
        ]
        if not in_flight_ops:
            return LockInspectionResult(
                verdict=LockSafetyStatus.UNCERTAIN,
                lock_path=str(resolved_lock),
                reason=f"Git lock '{resolved_lock}' has no in-flight/interrupted mini me Git-operation record (all recorded operations are completed or failed)",
                owning_pid=lock_pid,
            )

        matching_op = in_flight_ops[0]

        # CANONICAL PID RULE: Recorded mini me operation PID MUST be non-null and EXACTLY match lock_pid
        if matching_op.pid is None:
            return LockInspectionResult(
                verdict=LockSafetyStatus.UNCERTAIN,
                lock_path=str(resolved_lock),
                reason=f"Git lock '{resolved_lock}' has matching operation '{matching_op.operation_id}' with unrecorded PID (pid=None); ownership cannot be conclusively proven",
                owning_pid=lock_pid,
            )

        if matching_op.pid != lock_pid:
            return LockInspectionResult(
                verdict=LockSafetyStatus.UNCERTAIN,
                lock_path=str(resolved_lock),
                reason=f"Git lock PID {lock_pid} does not match recorded mini me operation PID {matching_op.pid}",
                owning_pid=lock_pid,
            )

        # Check if any associated process is still alive
        if any(op.pid and is_pid_alive(op.pid) for op in in_flight_ops):
            active_op = next(op for op in in_flight_ops if op.pid and is_pid_alive(op.pid))
            return LockInspectionResult(
                verdict=LockSafetyStatus.ACTIVE_OWNER,
                lock_path=str(resolved_lock),
                reason=f"Matching mini me Git-operation '{active_op.operation_id}' has active process PID {active_op.pid}",
                owning_pid=active_op.pid,
            )

        # Conclusively proven orphaned mini me-owned lock!
        return LockInspectionResult(
            verdict=LockSafetyStatus.SAFE_ORPHANED,
            lock_path=str(resolved_lock),
            reason=f"Git lock '{resolved_lock}' belongs to mini me Git-operation '{matching_op.operation_id}' ({matching_op.operation_type}) for job '{job.job_id}' and owning process PID {lock_pid} is terminated/dead",
            owning_pid=lock_pid,
            operation_id=matching_op.operation_id,
        )
