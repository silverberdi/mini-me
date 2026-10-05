"""Canonical Stage G Recovery Convergence Service."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from minime.domain.enums import (
    AuditFindingSeverity,
    AuditStatus,
    ChangeStatus,
    EventType,
    ExternalActionObservation,
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    ExternalReasonCode,
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProviderHealthStatus,
    PullRequestLookupState,
    RecoveryClassification,
    RecoveryDecisionStatus,
    RecoverySource,
    ReviewStatus,
    ReviewVerdict,
    SagaStatus,
    SagaType,
    WorkItemStatus,
)
from minime.domain.exceptions import StaleClaimError
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    ExternalActionAttempt,
    Job,
    OrchestrationExternalAction,
    RecoveryClaimContext,
    RecoveryDecision,
    generate_uuid,
    utc_now,
)
from minime.services.provider_health_service import ProviderHealthService


class ActionObservationOutcome(str, Enum):
    OBSERVED_PRESENT = "OBSERVED_PRESENT"
    OBSERVED_ABSENT = "OBSERVED_ABSENT"
    UNOBSERVABLE = "UNOBSERVABLE"
    CONTRADICTORY = "CONTRADICTORY"

logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 60
DEFAULT_HEARTBEAT_SECONDS = 15


class OperationalHeartbeat:
    """Async/sync operational heartbeat for long-running claimed tasks."""

    def __init__(
        self,
        recovery_service: RecoveryConvergenceService | Any = None,
        claim_context: RecoveryClaimContext | None = None,
        interval_seconds: int = 15,
        uow: Any = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        renew_claim: Any | None = None,
    ):
        self.recovery_service = recovery_service
        self.uow = uow
        self.claim_context = claim_context
        self.interval_seconds = interval_seconds
        self.lease_seconds = lease_seconds
        self.renew_claim = renew_claim
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.heartbeat_failed = False

    def start(self) -> OperationalHeartbeat:
        def _run():
            while not self._stop_event.wait(self.interval_seconds):
                try:
                    if not self.claim_context:
                        break
                    if self.renew_claim is not None:
                        success = self.renew_claim(self.claim_context, self.lease_seconds)
                    elif self.recovery_service is not None:
                        success = self.recovery_service.heartbeat(self.claim_context)
                    elif self.uow is not None and hasattr(self.uow, "claims") and self.uow.claims is not None:
                        success = self.uow.claims.renew_heartbeat(
                            claim_key=self.claim_context.claim_key,
                            owner_instance_id=self.claim_context.owner_instance_id,
                            fence_token=self.claim_context.fence_token,
                            lease_seconds=self.lease_seconds,
                        )
                    else:
                        success = True
                    if not success:
                        self.heartbeat_failed = True
                        logger.warning(
                            "Heartbeat renewal failed for claim '%s'; worker is now stale.",
                            self.claim_context.claim_key,
                        )
                        break
                except Exception as exc:
                    self.heartbeat_failed = True
                    logger.warning("Heartbeat error for claim '%s': %s", getattr(self.claim_context, "claim_key", "unknown"), exc)
                    break

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def __enter__(self) -> OperationalHeartbeat:
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()


class RecoveryConvergenceService:
    """Canonical recovery and continuation authority across startup, ticks, API, CLI, and Control Plane."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        owner_instance_id: str | None = None,
        health_service: ProviderHealthService | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        heartbeat_seconds: int = DEFAULT_HEARTBEAT_SECONDS,
        post_merge_service: Any | None = None,
        github_adapter: Any | None = None,
    ):
        if heartbeat_seconds >= lease_seconds / 3:
            raise ValueError(
                f"Heartbeat interval ({heartbeat_seconds}s) must be strictly less than 1/3 of lease duration ({lease_seconds}s)."
            )
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.owner_instance_id = owner_instance_id or f"instance-{os.getpid()}"
        self.health_service = health_service or ProviderHealthService(uow)
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.post_merge_service = post_merge_service
        self.github_adapter = github_adapter

    def reconcile_cycle(
        self,
        project_id: str | None = None,
        source: RecoverySource = RecoverySource.TICK,
        drive_admitted: bool = False,
        timeout_hours: float = 2.0,
    ) -> list[RecoveryDecision]:
        """Run a canonical recovery convergence cycle across all active runs, jobs, and sagas."""
        cycle_id = generate_uuid()

        # 1. Record event
        active_jobs = self.uow.jobs.list_active_jobs()
        event_type = EventType.DAEMON_RESTARTED if source == RecoverySource.STARTUP else EventType.STATUS_CHECKED
        payload = {
            "cycle_id": cycle_id,
            "source": source.value,
            "project_id": project_id,
        }
        if source == RecoverySource.STARTUP:
            payload["active_jobs_count"] = len(active_jobs)
            payload["interrupted_jobs_count"] = len(active_jobs)

        self.uow.events.save(
            Event(
                event_type=event_type,
                payload=payload,
                timestamp=utc_now(),
            )
        )
        self.uow.commit()

        decisions: list[RecoveryDecision] = []

        # 2. Gather active targets
        active_runs = self.uow.orchestration_runs.list_runs(is_active=True)
        if project_id:
            active_runs = [r for r in active_runs if r.project_id == project_id]

        active_sagas = self.uow.durable_sagas.list_active()
        if project_id:
            active_sagas = [s for s in active_sagas if s.project_id == project_id]

        # 3. Converge Runs
        for run in active_runs:
            try:
                claim_key = f"run:{run.run_id}"
                decision = self._converge_run_identity(
                    run_id=run.run_id,
                    cycle_id=cycle_id,
                    claim_key=claim_key,
                    source=source,
                    drive_admitted=drive_admitted,
                    timeout_hours=timeout_hours,
                )
                decisions.append(decision)
            except Exception as exc:
                logger.error("Run convergence failed for '%s': %s", run.run_id, exc)
                decision = RecoveryDecision(
                    cycle_id=cycle_id,
                    claim_key=f"run:{run.run_id}",
                    identity_type="RUN",
                    identity_id=run.run_id,
                    project_id=run.project_id,
                    change_name=run.change_name,
                    source=source,
                    classification=RecoveryClassification.TERMINAL_EXECUTION_BLOCKED,
                    planned_action="NO_ACTION",
                    status=RecoveryDecisionStatus.BLOCKED,
                    reason_code=str(exc),
                )
                self._create_decision(decision)
                self.uow.commit()
                decisions.append(decision)

        # 4. Converge Active Sagas
        for saga in active_sagas:
            try:
                if saga.saga_type == SagaType.INTAKE:
                    claim_key = f"intake:{saga.project_id}:{saga.work_item_key}"
                else:
                    claim_key = f"run:{saga.run_id}" if saga.run_id else f"closure:{saga.id}"

                if any(d.claim_key == claim_key for d in decisions):
                    continue

                decision = self._converge_saga_identity(
                    saga_id=saga.id, cycle_id=cycle_id, claim_key=claim_key, source=source
                )
                decisions.append(decision)
            except Exception as exc:
                logger.error("Saga convergence failed for '%s': %s", saga.id, exc)
                decision = RecoveryDecision(
                    cycle_id=cycle_id,
                    claim_key=(
                        f"intake:{saga.project_id}:{saga.work_item_key}"
                        if saga.saga_type == SagaType.INTAKE
                        else (f"run:{saga.run_id}" if saga.run_id else f"closure:{saga.id}")
                    ),
                    identity_type="SAGA",
                    identity_id=saga.id,
                    project_id=saga.project_id,
                    change_name=saga.change_name,
                    source=source,
                    classification=RecoveryClassification.TERMINAL_EXECUTION_BLOCKED,
                    planned_action="NO_ACTION",
                    status=RecoveryDecisionStatus.BLOCKED,
                    reason_code=str(exc),
                )
                self._create_decision(decision)
                self.uow.commit()
                decisions.append(decision)

        # 5. Converge Active Jobs
        active_jobs = self.uow.jobs.list_active_jobs()
        if project_id:
            active_jobs = [j for j in active_jobs if j.project_id == project_id]
        for job in active_jobs:
            run = self.uow.orchestration_runs.get_active_run(job.project_id, job.change_name) if hasattr(self.uow.orchestration_runs, "get_active_run") else None
            # A run owns its active Job's lifecycle. It was already converged above
            # under run:<run_id>; never compete with a second job claim.
            if run:
                continue
            context: RecoveryClaimContext | None = None
            decision: RecoveryDecision | None = None
            try:
                claim_key = f"job:{job.job_id}"
                claim = self.acquire_claim(claim_key, lease_seconds=self.lease_seconds)
                if not claim:
                    decision = RecoveryDecision(
                        cycle_id=cycle_id,
                        claim_key=claim_key,
                        identity_type="JOB",
                        identity_id=job.job_id,
                        project_id=job.project_id,
                        change_name=job.change_name,
                        source=source,
                        classification=RecoveryClassification.CLAIMED_ELSEWHERE,
                        planned_action="NO_ACTION",
                        status=RecoveryDecisionStatus.NO_ACTION,
                        reason_code="CLAIM_UNAVAILABLE",
                    )
                    self._create_decision(decision)
                    self.uow.commit()
                    decisions.append(decision)
                    continue
                context = RecoveryClaimContext(
                    claim_key=claim.claim_key,
                    owner_instance_id=claim.owner_instance_id,
                    fence_token=claim.fence_token,
                    lease_expires_at=claim.lease_expires_at,
                )
                self.uow.commit()
                decision = RecoveryDecision(
                    cycle_id=cycle_id,
                    claim_key=claim_key,
                    identity_type="JOB",
                    identity_id=job.job_id,
                    project_id=job.project_id,
                    change_name=job.change_name,
                    source=source,
                    fence_token=context.fence_token,
                    classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
                    planned_action="CONVERGE_JOB",
                    status=RecoveryDecisionStatus.EXECUTING,
                )
                self._create_decision(decision)
                self.uow.commit()
                self._converge_job_state(job, cycle_id, claim_context=context)
                decision.status = RecoveryDecisionStatus.COMPLETED
                self._update_decision(decision)
                self.uow.commit()
                decisions.append(decision)
            except Exception as exc:
                logger.error("Job state convergence failed for '%s': %s", job.job_id, exc)
                if decision is None:
                    decision = RecoveryDecision(
                        cycle_id=cycle_id,
                        claim_key=f"job:{job.job_id}",
                        identity_type="JOB",
                        identity_id=job.job_id,
                        project_id=job.project_id,
                        change_name=job.change_name,
                        source=source,
                        classification=RecoveryClassification.TERMINAL_EXECUTION_BLOCKED,
                        planned_action="NO_ACTION",
                        status=RecoveryDecisionStatus.BLOCKED,
                        reason_code=str(exc),
                    )
                    self._create_decision(decision)
                else:
                    decision.status = RecoveryDecisionStatus.BLOCKED
                    decision.reason_code = str(exc)
                    self._update_decision(decision)
                self.uow.commit()
                decisions.append(decision)
            finally:
                if context is not None:
                    self.release_claim(context)

        return decisions

    def _determine_highest_job_checkpoint(self, job: Job) -> JobStatus:
        """Evaluate durable candidate-bound evidence to select the highest proven checkpoint stage."""
        if not job.candidate_sha:
            return JobStatus.QUEUED

        # A positive checkpoint must bind to the current durable candidate identity.
        # A Job does not carry a generation itself, so recovery cannot safely adopt
        # evidence when its owning run (and therefore generation/base identity) is
        # unavailable.
        run = (
            self.uow.orchestration_runs.get_active_run(job.project_id, job.change_name)
            if hasattr(self.uow.orchestration_runs, "get_active_run")
            else None
        )
        if (
            run is None
            or not run.base_sha
            or not run.current_candidate_sha
            or run.current_candidate_sha != job.candidate_sha
            or not job.base_sha
            or job.base_sha != run.base_sha
        ):
            return JobStatus.QUEUED
        candidate_generation = run.current_generation
        candidate_base_sha = run.base_sha

        # 1. Checks: candidate-bound passing checks evidence
        check_results = (
            self.uow.check_results.list_by_job(job.job_id)
            if hasattr(self.uow, "check_results") and self.uow.check_results is not None
            else []
        )
        checks_passed = len(check_results) > 0 and all(
            getattr(c, "candidate_sha", None) == job.candidate_sha
            and getattr(c, "candidate_generation", None) == candidate_generation
            and c.exit_code == 0
            for c in check_results
        )
        if not checks_passed:
            return JobStatus.QUEUED

        # 2. Review: candidate-bound completed review evidence matching candidate_sha & base_sha with READY_TO_MERGE verdict
        if hasattr(self.uow, "reviews") and self.uow.reviews is not None:
            if hasattr(self.uow.reviews, "list_by_job"):
                reviews = self.uow.reviews.list_by_job(job.job_id)
            elif hasattr(self.uow.reviews, "get_by_job_id"):
                r = self.uow.reviews.get_by_job_id(job.job_id)
                reviews = [r] if r else []
            else:
                reviews = []
        else:
            reviews = []

        review_passed = any(
            getattr(r, "candidate_sha", None) == job.candidate_sha
            and getattr(r, "base_sha", None) == candidate_base_sha
            and getattr(r, "candidate_generation", None) == candidate_generation
            and r.status == ReviewStatus.REVIEW_COMPLETED
            and r.verdict == ReviewVerdict.READY_TO_MERGE
            for r in reviews
        )

        # 3. Audit: candidate-bound completed audit evidence matching candidate_sha & base_sha with no critical/high/blocker findings
        if hasattr(self.uow, "audits") and self.uow.audits is not None:
            if hasattr(self.uow.audits, "list_by_job"):
                audits = self.uow.audits.list_by_job(job.job_id)
            elif hasattr(self.uow.audits, "get_by_job_id"):
                a = self.uow.audits.get_by_job_id(job.job_id)
                audits = [a] if a else []
            else:
                audits = []
        else:
            audits = []
        audit_passed = review_passed and any(
            getattr(a, "candidate_sha", None) == job.candidate_sha
            and getattr(a, "base_sha", None) == candidate_base_sha
            and getattr(a, "candidate_generation", None) == candidate_generation
            and a.status == AuditStatus.AUDIT_COMPLETED
            and not any(
                f.severity in (AuditFindingSeverity.CRITICAL, AuditFindingSeverity.HIGH, AuditFindingSeverity.BLOCKER)
                for f in getattr(a, "findings", [])
            )
            for a in audits
        )

        if audit_passed:
            return JobStatus.READY_TO_MERGE
        if review_passed:
            return JobStatus.AUDIT_RUNNING
        return JobStatus.CHECKS_PASSED

    def _converge_job_state(
        self,
        job: Job,
        cycle_id: str,
        claim_context: RecoveryClaimContext | None = None,
    ) -> None:
        """Converge active job lifecycle state and emit JOB_RECOVERED event if transitioned."""
        change = self.uow.changes.get_by_name(job.project_id, job.change_name)
        if change and change.status in {ChangeStatus.DONE, ChangeStatus.CANCELLED}:
            if job.status not in {JobStatus.CANCELLED, JobStatus.COMPLETED}:
                self.uow.jobs.transition(
                    job.job_id,
                    JobStatus.CANCELLED.value,
                    error_message=f"Change is already in terminal state {change.status.value}.",
                    claim_context=claim_context,
                )
            return

        if job.status in {
            JobStatus.NEEDS_HUMAN,
            JobStatus.RECOVERY_BLOCKED,
            JobStatus.WAITING_CAPACITY,
            JobStatus.QUEUED,
            JobStatus.CANCELLED,
            JobStatus.COMPLETED,
        }:
            return

        # Handle pending unconsumed handoff
        if hasattr(self.uow, "job_handoffs") and self.uow.job_handoffs is not None:
            pending_handoff = next(
                (h for h in self.uow.job_handoffs.list_by_job(job.job_id) if not h.is_consumed),
                None,
            )
            if pending_handoff:
                self.uow.jobs.update_executor_fenced(
                    job.job_id,
                    pending_handoff.to_executor,
                    claim_context=claim_context,
                )

        # Handle RECOVERY_BLOCKED evidence recorded during lock inspection
        if hasattr(self.uow, "events") and self.uow.events is not None:
            if hasattr(self.uow.events, "list_by_project"):
                events = self.uow.events.list_by_project(job.project_id)
            elif hasattr(self.uow.events, "list_events"):
                events = self.uow.events.list_events(project_id=job.project_id)
            else:
                events = []
            blocked_event = next(
                (
                    e
                    for e in events
                    if e.event_type == EventType.RECOVERY_BLOCKED and e.operation_id == job.job_id
                ),
                None,
            )
            if blocked_event:
                reason = blocked_event.payload.get("reason", "Unsafe Git lock condition")
                self.uow.jobs.set_recovery_blocked(
                    job_id=job.job_id,
                    reason=reason,
                    claim_context=claim_context,
                )
                return

        if job.status in {
            JobStatus.RUNNING,
            JobStatus.CHECKS_RUNNING,
            JobStatus.REVIEW_RUNNING,
            JobStatus.AUDIT_RUNNING,
        }:
            stage_map = {
                JobStatus.RUNNING: "implementer",
                JobStatus.CHECKS_RUNNING: "checks",
                JobStatus.REVIEW_RUNNING: "reviewer",
                JobStatus.AUDIT_RUNNING: "auditor",
            }
            interrupted_stage = stage_map.get(job.status, "unknown")
            target_status = self._determine_highest_job_checkpoint(job)
            if target_status == JobStatus.QUEUED:
                updated = self.uow.jobs.transition(
                    job.job_id,
                    JobStatus.QUEUED.value,
                    error_message="Recovered on daemon restart; re-queued for execution.",
                    claim_context=claim_context,
                )
            else:
                updated = self.uow.jobs.transition(
                    job.job_id,
                    target_status.value,
                    error_message=f"Recovered on daemon restart; preserved completed checkpoint ({target_status.value}).",
                    claim_context=claim_context,
                )
            self.uow.events.save(
                Event(
                    event_type=EventType.JOB_INTERRUPTED if False else EventType.JOB_RECOVERED,
                    project_id=job.project_id,
                    change_id=job.change_name,
                    operation_id=job.job_id,
                    payload={
                        "job_id": job.job_id,
                        "new_status": updated.status.value,
                        "recovered_status": updated.status.value,
                        "interrupted_stage": interrupted_stage,
                        "recovery_cycle_id": cycle_id,
                    },
                    timestamp=utc_now(),
                )
            )

    def request_run_continuation(
        self,
        run_id: str,
        source: RecoverySource,
        requested_action: str | None = None,
        drain_mode: bool = False,
        force: bool = False,
    ) -> RecoveryDecision:
        """Drive direct run continuation through canonical claim acquisition and classification."""
        cycle_id = generate_uuid()
        claim_key = f"run:{run_id}"
        return self._converge_run_identity(
            run_id=run_id,
            cycle_id=cycle_id,
            claim_key=claim_key,
            source=source,
            requested_action=requested_action,
            drain_mode=drain_mode,
            force=force,
        )

    def reconcile_saga(self, saga_id: str, source: RecoverySource) -> RecoveryDecision:
        """Drive direct saga recovery through canonical claim acquisition."""
        cycle_id = generate_uuid()
        saga = self.uow.durable_sagas.get_by_id(saga_id)
        if not saga:
            raise ValueError(f"Saga '{saga_id}' not found.")
        claim_key = (
            f"run:{saga.run_id}"
            if saga.run_id
            else (
                f"intake:{saga.project_id}:{saga.work_item_key}"
                if saga.saga_type == SagaType.INTAKE
                else f"closure:{saga.id}"
            )
        )
        return self._converge_saga_identity(
            saga_id=saga.id, cycle_id=cycle_id, claim_key=claim_key, source=source
        )

    def reconcile_action(self, action_key: str, source: RecoverySource) -> RecoveryDecision:
        """Reconcile nonterminal external action under canonical claim and Stage B/D observation matrix."""
        action = self.uow.orchestration_external_actions.get_by_action_key(action_key)
        if not action:
            raise ValueError(f"External action '{action_key}' not found.")
        if action.run_id:
            claim_key = f"run:{action.run_id}"
        elif action.saga_id:
            saga = self.uow.durable_sagas.get_by_id(action.saga_id)
            if saga and saga.run_id:
                claim_key = f"run:{saga.run_id}"
            elif saga and saga.saga_type == SagaType.INTAKE:
                claim_key = f"intake:{saga.project_id}:{saga.work_item_key}"
            elif saga:
                claim_key = f"closure:{saga.id}"
            else:
                claim_key = f"closure:{action.saga_id}"
        else:
            raise ValueError(f"Action '{action_key}' lacks parent run_id and saga_id for claim derivation.")

        cycle_id = generate_uuid()
        return self._converge_action_identity(
            action_key=action_key, cycle_id=cycle_id, claim_key=claim_key, source=source
        )

    def _create_decision(self, decision: RecoveryDecision) -> None:
        if hasattr(self.uow, "recovery_decisions") and self.uow.recovery_decisions is not None:
            self.uow.recovery_decisions.create_decision(decision)

    def _update_decision(self, decision: RecoveryDecision) -> None:
        if hasattr(self.uow, "recovery_decisions") and self.uow.recovery_decisions is not None:
            self.uow.recovery_decisions.update_decision(decision)

    def acquire_claim(self, claim_key: str, lease_seconds: int = 60) -> RecoveryClaimContext | None:
        """Acquire or re-acquire a claim for this owner instance."""
        if not hasattr(self.uow, "claims") or self.uow.claims is None:
            logger.error("Durable recovery claims are unavailable; refusing continuation for '%s'.", claim_key)
            return None
        try:
            claim = self.uow.claims.acquire_or_reacquire(
                claim_key=claim_key,
                owner_instance_id=self.owner_instance_id,
                lease_seconds=lease_seconds,
            )
            if not claim:
                return None
            self.uow.commit()
        except Exception:
            self.uow.rollback()
            return None
        if isinstance(claim, RecoveryClaimContext):
            return claim
        claim_key_val = claim.claim_key if isinstance(getattr(claim, "claim_key", None), str) else claim_key
        owner_id_val = claim.owner_instance_id if isinstance(getattr(claim, "owner_instance_id", None), str) else self.owner_instance_id
        fence_token_val = claim.fence_token if isinstance(getattr(claim, "fence_token", None), int) else 1
        lease_expires_val = (
            claim.lease_expires_at
            if isinstance(getattr(claim, "lease_expires_at", None), datetime)
            else datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        )
        return RecoveryClaimContext(
            claim_key=claim_key_val,
            owner_instance_id=owner_id_val,
            fence_token=fence_token_val,
            lease_expires_at=lease_expires_val,
        )

    def heartbeat(self, context: RecoveryClaimContext) -> bool:
        """Atomic fenced heartbeat renewal."""
        if not hasattr(self.uow, "claims") or self.uow.claims is None:
            return True
        res = self.uow.claims.renew_heartbeat(
            claim_key=context.claim_key,
            owner_instance_id=context.owner_instance_id,
            fence_token=context.fence_token,
            lease_seconds=self.lease_seconds,
        )
        if res:
            self.uow.commit()
            context.lease_expires_at = utc_now() + timedelta(seconds=self.lease_seconds)
        return res

    def release_claim(self, context: RecoveryClaimContext) -> bool:
        """Atomic fenced claim release."""
        if not hasattr(self.uow, "claims") or self.uow.claims is None:
            return True
        res = self.uow.claims.release(
            claim_key=context.claim_key,
            owner_instance_id=context.owner_instance_id,
            fence_token=context.fence_token,
        )
        if res:
            self.uow.commit()
        return res

    def validate_claim(self, context: RecoveryClaimContext) -> bool:
        """Validate that current claim is still active and owned with matching fence."""
        if not hasattr(self.uow, "claims") or self.uow.claims is None:
            return context.is_valid()
        return self.uow.claims.validate_cas(
            claim_key=context.claim_key,
            owner_instance_id=context.owner_instance_id,
            fence_token=context.fence_token,
        )

    def atomic_commit_dispatch_intent(
        self,
        context: RecoveryClaimContext,
        action_key: str,
        attempt_number: int = 1,
    ) -> ExternalActionAttempt:
        """Immediately before slow external mutation: validate fence, verify auth, persist unique dispatch intent, and commit in one short atomic DB transaction."""
        return self.uow.claims.commit_fenced_dispatch_intent(
            claim_key=context.claim_key,
            owner_instance_id=context.owner_instance_id,
            fence_token=context.fence_token,
            action_key=action_key,
            attempt_number=attempt_number,
        )

    def apply_lifecycle_result(
        self,
        context: RecoveryClaimContext,
        apply_fn: Any,
    ) -> Any:
        """Atomic fenced CAS result application: validates claim fence atomically during execution."""
        if hasattr(self.uow, "claims") and self.uow.claims is not None:
            if not self.uow.claims.validate_cas(
                claim_key=context.claim_key,
                owner_instance_id=context.owner_instance_id,
                fence_token=context.fence_token,
            ):
                raise StaleClaimError(
                    f"Stale worker with fence {context.fence_token} cannot advance lifecycle."
                )
        result = apply_fn()
        if hasattr(self.uow, "claims") and self.uow.claims is not None:
            if not self.uow.claims.validate_cas(
                claim_key=context.claim_key,
                owner_instance_id=context.owner_instance_id,
                fence_token=context.fence_token,
            ):
                self.uow.rollback()
                raise StaleClaimError(
                    f"Stale worker with fence {context.fence_token} cannot advance lifecycle."
                )
        self.uow.commit()
        return result

    def classify_external_action_observation(
        self, action: OrchestrationExternalAction
    ) -> ExternalActionObservation:
        """Classify nonterminal RESERVED action as PROVEN_NEVER_DISPATCHED vs POSSIBLY_DISPATCHED."""
        if action.last_dispatch_intent_id or action.remote_identifier:
            return ExternalActionObservation.POSSIBLY_DISPATCHED
        attempts = self.uow.external_action_attempts.list_by_action_key(action.action_key)
        if attempts:
            return ExternalActionObservation.POSSIBLY_DISPATCHED
        return ExternalActionObservation.PROVEN_NEVER_DISPATCHED

    def observe_external_action(
        self, action: OrchestrationExternalAction
    ) -> ActionObservationOutcome:
        """Canonical action observer dispatch keyed by ExternalActionType."""
        if action.status == ExternalActionStatus.COMPLETED:
            return ActionObservationOutcome.OBSERVED_PRESENT

        obs = self.classify_external_action_observation(action)
        if obs == ExternalActionObservation.PROVEN_NEVER_DISPATCHED and action.status == ExternalActionStatus.RESERVED:
            return ActionObservationOutcome.OBSERVED_ABSENT

        try:
            outcome = self._observe_by_action_type(action)
        except Exception as exc:
            logger.warning("Observer failed for action '%s': %s", action.action_key, exc)
            outcome = ActionObservationOutcome.UNOBSERVABLE

        if outcome == ActionObservationOutcome.OBSERVED_PRESENT:
            if action.status != ExternalActionStatus.COMPLETED:
                self.uow.orchestration_external_actions.update_status(
                    action.action_key, ExternalActionStatus.COMPLETED
                )
                self.uow.commit()
        elif outcome == ActionObservationOutcome.CONTRADICTORY:
            if action.status != ExternalActionStatus.AMBIGUOUS:
                self.uow.orchestration_external_actions.update_status(
                    action.action_key, ExternalActionStatus.AMBIGUOUS
                )
                self.uow.commit()

        return outcome

    def _observe_by_action_type(
        self, action: OrchestrationExternalAction
    ) -> ActionObservationOutcome:
        atype = action.action_type

        if atype == ExternalActionType.BRANCH_PUSH:
            target_ref = action.target_identity or (f"refs/heads/candidate-{action.candidate_sha[:8]}" if action.candidate_sha else None)
            if not target_ref or not action.candidate_sha:
                return ActionObservationOutcome.UNOBSERVABLE
            try:
                res = subprocess.run(
                    ["git", "ls-remote", "origin", target_ref],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )
                if res.returncode == 0:
                    lines = res.stdout.strip().splitlines()
                    if lines:
                        remote_sha = lines[0].split()[0]
                        if remote_sha == action.candidate_sha:
                            return ActionObservationOutcome.OBSERVED_PRESENT
                        else:
                            return ActionObservationOutcome.CONTRADICTORY
                    else:
                        return ActionObservationOutcome.OBSERVED_ABSENT
                return ActionObservationOutcome.UNOBSERVABLE
            except Exception:
                return ActionObservationOutcome.UNOBSERVABLE

        elif atype == ExternalActionType.PR_CREATE:
            from minime.services.status_service import PullRequestLookupService
            pr_svc = PullRequestLookupService(self.uow, self.project_root)
            run = self.uow.orchestration_runs.get_by_id(action.run_id) if action.run_id else None
            if run:
                lookup = pr_svc.lookup_pr(run.project_id, run.change_name)
                if lookup.state == PullRequestLookupState.FOUND_EXACT:
                    return ActionObservationOutcome.OBSERVED_PRESENT
                elif lookup.state == PullRequestLookupState.NOT_FOUND:
                    return ActionObservationOutcome.OBSERVED_ABSENT
                elif lookup.state == PullRequestLookupState.AMBIGUOUS:
                    return ActionObservationOutcome.CONTRADICTORY
                else:
                    return ActionObservationOutcome.UNOBSERVABLE
            return ActionObservationOutcome.UNOBSERVABLE

        elif atype == ExternalActionType.ISSUE_CREATE:
            project_id = None
            change_name = None
            if action.run_id:
                run = self.uow.orchestration_runs.get_by_id(action.run_id)
                if run:
                    project_id = run.project_id
                    change_name = run.change_name
            elif action.saga_id:
                saga = self.uow.durable_sagas.get_by_id(action.saga_id)
                if saga:
                    project_id = saga.project_id
                    change_name = saga.change_name or saga.work_item_key

            if project_id and change_name:
                binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
                if binding and binding.github_issue_number:
                    project = self.uow.projects.get_by_id(project_id)
                    if project and project.repository and getattr(self, "github_adapter", None) and hasattr(self.github_adapter, "get_issue"):
                        try:
                            issue_result = self.github_adapter.get_issue(project.repository, binding.github_issue_number)
                            issue = getattr(issue_result, "data", None)
                            if (
                                getattr(issue_result, "outcome", None) == ExternalOutcome.SUCCESS
                                and isinstance(issue, dict)
                                and issue.get("number") == binding.github_issue_number
                            ):
                                return ActionObservationOutcome.OBSERVED_PRESENT
                            if (
                                getattr(issue_result, "outcome", None) == ExternalOutcome.FAILURE
                                and getattr(issue_result, "reason_code", None) == ExternalReasonCode.NOT_FOUND
                            ):
                                return ActionObservationOutcome.OBSERVED_ABSENT
                            return ActionObservationOutcome.UNOBSERVABLE
                        except Exception:
                            return ActionObservationOutcome.UNOBSERVABLE
                    return ActionObservationOutcome.UNOBSERVABLE
                elif binding and not binding.github_issue_number:
                    return ActionObservationOutcome.UNOBSERVABLE
            return ActionObservationOutcome.UNOBSERVABLE

        elif atype == ExternalActionType.ISSUE_CLOSE:
            project_id = None
            change_name = None
            if action.run_id:
                run = self.uow.orchestration_runs.get_by_id(action.run_id)
                if run:
                    project_id = run.project_id
                    change_name = run.change_name
            elif action.saga_id:
                saga = self.uow.durable_sagas.get_by_id(action.saga_id)
                if saga:
                    project_id = saga.project_id
                    change_name = saga.change_name or saga.work_item_key

            if project_id and change_name:
                binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
                if binding and binding.github_issue_number:
                    try:
                        project = self.uow.projects.get_by_id(project_id)
                        if project and project.repository and getattr(self, "github_adapter", None) and hasattr(self.github_adapter, "get_issue"):
                            issue_result = self.github_adapter.get_issue(project.repository, binding.github_issue_number)
                            issue = getattr(issue_result, "data", None)
                            if (
                                getattr(issue_result, "outcome", None) == ExternalOutcome.SUCCESS
                                and isinstance(issue, dict)
                                and issue.get("number") == binding.github_issue_number
                                and issue.get("state") == "closed"
                            ):
                                return ActionObservationOutcome.OBSERVED_PRESENT
                            elif (
                                getattr(issue_result, "outcome", None) == ExternalOutcome.SUCCESS
                                and isinstance(issue, dict)
                                and issue.get("number") == binding.github_issue_number
                                and issue.get("state") == "open"
                            ):
                                return ActionObservationOutcome.OBSERVED_ABSENT
                    except Exception:
                        return ActionObservationOutcome.UNOBSERVABLE
                elif binding and not binding.github_issue_number:
                    return ActionObservationOutcome.UNOBSERVABLE
            return ActionObservationOutcome.UNOBSERVABLE

        elif atype == ExternalActionType.PROJECT_ITEM_ADD:
            project_id = None
            change_name = None
            if action.run_id:
                run = self.uow.orchestration_runs.get_by_id(action.run_id)
                if run:
                    project_id = run.project_id
                    change_name = run.change_name
            elif action.saga_id:
                saga = self.uow.durable_sagas.get_by_id(action.saga_id)
                if saga:
                    project_id = saga.project_id
                    change_name = saga.change_name or saga.work_item_key

            if project_id and change_name:
                binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
                if binding and binding.github_project_item_id:
                    return ActionObservationOutcome.UNOBSERVABLE
                elif binding and not binding.github_project_item_id:
                    return ActionObservationOutcome.OBSERVED_ABSENT
            return ActionObservationOutcome.UNOBSERVABLE

        elif atype == ExternalActionType.PROJECT_ITEM_EDIT:
            project_id = None
            change_name = None
            if action.run_id:
                run = self.uow.orchestration_runs.get_by_id(action.run_id)
                if run:
                    project_id = run.project_id
                    change_name = run.change_name
            elif action.saga_id:
                saga = self.uow.durable_sagas.get_by_id(action.saga_id)
                if saga:
                    project_id = saga.project_id
                    change_name = saga.change_name or saga.work_item_key

            if project_id and change_name:
                binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
                if binding and binding.github_project_item_id:
                    return ActionObservationOutcome.UNOBSERVABLE
                elif binding and not binding.github_project_item_id:
                    return ActionObservationOutcome.OBSERVED_ABSENT
            return ActionObservationOutcome.UNOBSERVABLE

        elif atype == ExternalActionType.BRANCH_DELETE:
            branch_name = action.target_identity or (f"minime/{action.request_fingerprint}" if action.request_fingerprint else None)
            if branch_name:
                try:
                    loc_res = subprocess.run(
                        ["git", "rev-parse", "--verify", branch_name],
                        cwd=self.project_root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    local_absent = loc_res.returncode != 0
                    rem_res = subprocess.run(
                        ["git", "ls-remote", "origin", f"refs/heads/{branch_name}"],
                        cwd=self.project_root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    remote_absent = rem_res.returncode == 0 and not rem_res.stdout.strip()
                    if local_absent and remote_absent:
                        return ActionObservationOutcome.OBSERVED_PRESENT
                    return ActionObservationOutcome.OBSERVED_ABSENT
                except Exception:
                    return ActionObservationOutcome.UNOBSERVABLE
            return ActionObservationOutcome.UNOBSERVABLE

        elif atype == ExternalActionType.WORKTREE_DELETE:
            if action.target_identity:
                path = Path(action.target_identity)
                dir_absent = not path.exists()
                try:
                    res = subprocess.run(
                        ["git", "worktree", "list"],
                        cwd=self.project_root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    worktree_reg_absent = str(path) not in res.stdout
                except Exception:
                    worktree_reg_absent = dir_absent
                if dir_absent and worktree_reg_absent:
                    return ActionObservationOutcome.OBSERVED_PRESENT
                return ActionObservationOutcome.OBSERVED_ABSENT
            return ActionObservationOutcome.UNOBSERVABLE

        elif atype in (ExternalActionType.OPENSPEC_SYNC, ExternalActionType.OPENSPEC_ARCHIVE):
            if action.target_identity:
                from minime.adapters.openspec import OpenSpecAdapter
                adapter = OpenSpecAdapter()
                res = adapter.get_change_status(self.project_root, action.target_identity)
                if atype == ExternalActionType.OPENSPEC_ARCHIVE:
                    if not res.exists or res.is_archived:
                        return ActionObservationOutcome.OBSERVED_PRESENT
                    return ActionObservationOutcome.OBSERVED_ABSENT
                elif atype == ExternalActionType.OPENSPEC_SYNC:
                    if res.is_synced:
                        return ActionObservationOutcome.OBSERVED_PRESENT
                    return ActionObservationOutcome.OBSERVED_ABSENT
            return ActionObservationOutcome.UNOBSERVABLE

        elif atype in (ExternalActionType.DEPLOY_EXECUTE, ExternalActionType.SERVICE_RESTART):
            return ActionObservationOutcome.UNOBSERVABLE

        if action.last_dispatch_intent_id:
            return ActionObservationOutcome.UNOBSERVABLE
        return ActionObservationOutcome.OBSERVED_ABSENT

    def _converge_run_identity(
        self,
        run_id: str,
        cycle_id: str,
        claim_key: str,
        source: RecoverySource,
        requested_action: str | None = None,
        drain_mode: bool = False,
        force: bool = False,
        drive_admitted: bool = False,
        timeout_hours: float = 2.0,
    ) -> RecoveryDecision:
        claim = self.acquire_claim(claim_key=claim_key, lease_seconds=self.lease_seconds)
        if not claim:
            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="RUN",
                identity_id=run_id,
                source=source,
                classification=RecoveryClassification.CLAIMED_ELSEWHERE,
                planned_action="NO_ACTION",
                status=RecoveryDecisionStatus.NO_ACTION,
                reason_code="CLAIMED_ELSEWHERE",
            )
            self._create_decision(decision)
            self.uow.commit()
            return decision

        context = RecoveryClaimContext(
            claim_key=claim.claim_key,
            owner_instance_id=claim.owner_instance_id,
            fence_token=claim.fence_token,
            lease_expires_at=claim.lease_expires_at,
        )

        run = self.uow.orchestration_runs.get_by_id(run_id)
        if not run:
            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="RUN",
                identity_id=run_id,
                source=source,
                fence_token=context.fence_token,
                classification=RecoveryClassification.NO_ACTION,
                planned_action="NO_ACTION",
                status=RecoveryDecisionStatus.NO_ACTION,
                reason_code="RUN_NOT_FOUND",
            )
            self._create_decision(decision)
            self.uow.commit()
            self.release_claim(context)
            return decision
        if run.active_job_id:
            job = self.uow.jobs.get_by_id(run.active_job_id)
            if job:
                change = (
                    self.uow.changes.get_by_name(job.project_id, job.change_name)
                    if hasattr(self.uow, "changes") and self.uow.changes is not None
                    else None
                )
                if change and change.status in {ChangeStatus.DONE, ChangeStatus.CANCELLED}:
                    if job.status not in {JobStatus.CANCELLED, JobStatus.COMPLETED}:
                        self.uow.jobs.transition(
                            job.job_id,
                            JobStatus.CANCELLED.value,
                            error_message=f"Change is already in terminal state {change.status.value}.",
                            claim_context=context,
                        )
                elif job.status in {
                    JobStatus.RUNNING,
                    JobStatus.CHECKS_RUNNING,
                    JobStatus.REVIEW_RUNNING,
                    JobStatus.AUDIT_RUNNING,
                }:
                    target_status = self._determine_highest_job_checkpoint(job)
                    if target_status == JobStatus.QUEUED:
                        self.uow.jobs.transition(
                            job.job_id,
                            JobStatus.QUEUED.value,
                            error_message="Recovered on daemon restart; re-queued for execution.",
                            claim_context=context,
                        )
                    else:
                        self.uow.jobs.transition(
                            job.job_id,
                            target_status.value,
                            error_message=f"Recovered on daemon restart; preserved completed checkpoint ({target_status.value}).",
                            claim_context=context,
                        )

        if (
            not run.is_active
            or run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
            or run.current_stage in (OrchestrationStage.PR_PREPARED, OrchestrationStage.POST_MERGE_RECONCILING)
        ):
            from minime.services.post_merge_service import PostMergeReconciliationService
            from minime.services.saga_engine import SagaEngine

            closure_sagas = [
                s
                for s in self.uow.durable_sagas.list_active()
                if s.run_id == run.run_id and s.saga_type == SagaType.CLOSURE
            ]
            if closure_sagas or run.current_stage in (OrchestrationStage.PR_PREPARED, OrchestrationStage.POST_MERGE_RECONCILING) or run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE:
                decision = RecoveryDecision(
                    cycle_id=cycle_id,
                    claim_key=claim_key,
                    identity_type="RUN",
                    identity_id=run_id,
                    project_id=run.project_id,
                    change_name=run.change_name,
                    source=source,
                    fence_token=context.fence_token,
                    classification=RecoveryClassification.CLOSURE_ONLY_CONTINUATION,
                    planned_action="RECONCILE_POST_MERGE",
                    status=RecoveryDecisionStatus.PLANNED,
                )
                self._create_decision(decision)
                self.uow.commit()

                try:
                    post_merge_svc = self.post_merge_service or PostMergeReconciliationService(
                        self.uow,
                        project_root=self.project_root,
                        github_adapter=self.github_adapter,
                        saga_engine=SagaEngine(
                            self.uow,
                            heartbeat_interval_seconds=self.heartbeat_seconds,
                            lease_seconds=self.lease_seconds,
                        ),
                    )
                    if closure_sagas:
                        engine = SagaEngine(
                            self.uow,
                            heartbeat_interval_seconds=self.heartbeat_seconds,
                            lease_seconds=self.lease_seconds,
                        )
                        engine.resume_saga(
                            closure_sagas[0].id,
                            post_merge_service=post_merge_svc,
                            claim_context=context,
                        )
                    else:
                        post_merge_svc.reconcile_post_merge(
                            project_id=run.project_id,
                            change_name=run.change_name,
                            run_id=run.run_id,
                            claim_context=context,
                        )
                    decision.status = RecoveryDecisionStatus.COMPLETED
                except Exception as exc:
                    decision.status = RecoveryDecisionStatus.BLOCKED
                    decision.reason_code = str(exc)
                self._update_decision(decision)
                self.release_claim(context)
                return decision

            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="RUN",
                identity_id=run_id,
                project_id=run.project_id,
                change_name=run.change_name,
                source=source,
                fence_token=context.fence_token,
                classification=RecoveryClassification.TERMINAL_EXECUTION_BLOCKED,
                planned_action="NO_ACTION",
                status=RecoveryDecisionStatus.NO_ACTION,
                reason_code="TERMINAL_RUN",
            )
            self._create_decision(decision)
            self.release_claim(context)
            return decision

        if run.stop_outcome in (OrchestrationStopOutcome.WAITING_CAPACITY, OrchestrationStopOutcome.WAITING_EXTERNAL):
            waiting_since_str = (run.stop_details or {}).get("waiting_since")
            if waiting_since_str:
                try:
                    from datetime import datetime, timezone
                    ws = datetime.fromisoformat(waiting_since_str)
                    if ws.tzinfo is None:
                        ws = ws.replace(tzinfo=timezone.utc)
                    elapsed_hours = (utc_now() - ws).total_seconds() / 3600.0
                    if elapsed_hours >= timeout_hours:
                        reason = f"Waiting capacity timeout exceeded ({elapsed_hours:.1f}h > {timeout_hours:.1f}h)"
                        self.uow.orchestration_runs.update_stop_outcome(
                            run_id=run.run_id,
                            stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                            human_gate=HumanGate.NEEDS_HUMAN,
                            stop_reason=reason,
                            is_active=False,
                            claim_context=context,
                        )
                        if run.active_job_id:
                            self.uow.jobs.transition(
                                job_id=run.active_job_id,
                                new_status=JobStatus.NEEDS_HUMAN.value,
                                error_message=reason,
                                claim_context=context,
                            )
                        self.uow.commit()

                        decision = RecoveryDecision(
                            cycle_id=cycle_id,
                            claim_key=claim_key,
                            identity_type="RUN",
                            identity_id=run_id,
                            project_id=run.project_id,
                            change_name=run.change_name,
                            source=source,
                            fence_token=context.fence_token,
                            classification=RecoveryClassification.NEEDS_HUMAN,
                            planned_action="ESCALATE_NEEDS_HUMAN",
                            status=RecoveryDecisionStatus.COMPLETED,
                            reason_code="WAITING_TIMEOUT_EXCEEDED",
                        )
                        self._create_decision(decision)
                        self.uow.commit()
                        self.release_claim(context)
                        return decision
                except Exception as exc:
                    logger.warning(f"Failed to evaluate waiting_since for run '{run_id}': {exc}")

        if run.stop_outcome == OrchestrationStopOutcome.WAITING_CAPACITY:
            project = self.uow.projects.get_by_id(run.project_id)
            provider = (
                (run.stop_details.get("provider") if run.stop_details else None)
                or (project.implementer if project else "codex")
            )
            health = self.health_service.get_health(provider)
            if (
                health.status not in (ProviderHealthStatus.AVAILABLE, ProviderHealthStatus.DEGRADED)
                and not force
                and not drain_mode
            ):
                decision = RecoveryDecision(
                    cycle_id=cycle_id,
                    claim_key=claim_key,
                    identity_type="RUN",
                    identity_id=run_id,
                    project_id=run.project_id,
                    change_name=run.change_name,
                    source=source,
                    fence_token=context.fence_token,
                    classification=RecoveryClassification.WAITING_CAPACITY,
                    planned_action="NO_ACTION",
                    status=RecoveryDecisionStatus.NO_ACTION,
                    reason_code=f"PROVIDER_UNAVAILABLE_{provider}",
                )
                self._create_decision(decision)
                self.release_claim(context)
                return decision
            else:
                self.uow.orchestration_runs.update_stop_outcome(
                    run_id=run.run_id,
                    stop_outcome=None,
                    stop_reason=None,
                    is_active=True,
                    claim_context=context,
                )
                self.uow.commit()

                if not drive_admitted:
                    decision = RecoveryDecision(
                        cycle_id=cycle_id,
                        claim_key=claim_key,
                        identity_type="RUN",
                        identity_id=run_id,
                        project_id=run.project_id,
                        change_name=run.change_name,
                        source=source,
                        fence_token=context.fence_token,
                        classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
                        planned_action="RECONCILE_WAITING_CAPACITY",
                        status=RecoveryDecisionStatus.COMPLETED,
                        reason_code="CAPACITY_RECOVERED",
                    )
                    self._create_decision(decision)
                    self.uow.commit()
                    self.release_claim(context)
                    return decision

        actions = self.uow.orchestration_external_actions.list_by_run(run.run_id)
        has_ambiguous = False
        has_adoptable = False
        has_unobservable = False
        for action in actions:
            if action.status in (
                ExternalActionStatus.EXECUTING,
                ExternalActionStatus.UNKNOWN,
                ExternalActionStatus.AMBIGUOUS,
                ExternalActionStatus.RESERVED,
                ExternalActionStatus.FAILED,
            ):
                outcome = self.observe_external_action(action)
                if outcome == ActionObservationOutcome.OBSERVED_PRESENT or action.status == ExternalActionStatus.COMPLETED:
                    has_adoptable = True
                elif outcome == ActionObservationOutcome.OBSERVED_ABSENT:
                    continue
                elif outcome == ActionObservationOutcome.CONTRADICTORY or action.status == ExternalActionStatus.AMBIGUOUS:
                    has_ambiguous = True
                elif outcome == ActionObservationOutcome.UNOBSERVABLE:
                    has_unobservable = True

        if has_ambiguous:
            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="RUN",
                identity_id=run_id,
                project_id=run.project_id,
                change_name=run.change_name,
                source=source,
                fence_token=context.fence_token,
                classification=RecoveryClassification.NEEDS_HUMAN,
                planned_action="ESCALATE_NEEDS_HUMAN",
                status=RecoveryDecisionStatus.PLANNED,
                reason_code="CONTRADICTORY_EXTERNAL_EVIDENCE",
            )
            self._create_decision(decision)
            self.uow.commit()
            self.release_claim(context)
            return decision

        if has_unobservable:
            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="RUN",
                identity_id=run_id,
                project_id=run.project_id,
                change_name=run.change_name,
                source=source,
                fence_token=context.fence_token,
                classification=RecoveryClassification.WAITING_EXTERNAL,
                planned_action="OBSERVE_EXTERNAL",
                status=RecoveryDecisionStatus.PLANNED,
                reason_code="EXTERNAL_ACTION_UNOBSERVABLE",
            )
            self._create_decision(decision)
            self.uow.commit()
            self.release_claim(context)
            return decision

        if has_adoptable:
            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="RUN",
                identity_id=run_id,
                project_id=run.project_id,
                change_name=run.change_name,
                source=source,
                fence_token=context.fence_token,
                classification=RecoveryClassification.ADOPT_OBSERVED_EFFECT,
                planned_action="ADOPT_COMPLETED",
                status=RecoveryDecisionStatus.COMPLETED,
            )
            self._create_decision(decision)
            self.uow.commit()
            self.release_claim(context)
            return decision

        if (
            source == RecoverySource.TICK
            and run.stop_outcome is None
            and requested_action is None
            and not force
            and not drain_mode
        ):
            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="RUN",
                identity_id=run_id,
                project_id=run.project_id,
                change_name=run.change_name,
                source=source,
                fence_token=context.fence_token,
                classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
                planned_action="NO_ACTION",
                status=RecoveryDecisionStatus.NO_ACTION,
                reason_code="HEALTHY_ACTIVE_RUN",
            )
            self._create_decision(decision)
            self.release_claim(context)
            return decision

        decision = RecoveryDecision(
            cycle_id=cycle_id,
            claim_key=claim_key,
            identity_type="RUN",
            identity_id=run_id,
            project_id=run.project_id,
            change_name=run.change_name,
            source=source,
            fence_token=context.fence_token,
            classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
            planned_action="DRIVE_CONTINUATION",
            status=RecoveryDecisionStatus.EXECUTING,
        )
        self._create_decision(decision)
        if source == RecoverySource.STARTUP:
            self.uow.events.save(
                Event(
                    event_type=EventType.ORCHESTRATION_RECOVERED,
                    project_id=run.project_id,
                    change_id=run.change_name,
                    operation_id=run.run_id,
                    payload={
                        "run_id": run.run_id,
                        "stage": run.current_stage.value,
                        "resumable_stage": run.resumable_stage.value if run.resumable_stage else None,
                        "recovery_cycle_id": cycle_id,
                    },
                    timestamp=utc_now(),
                )
            )
        self.uow.commit()

        from minime.services.orchestration_service import OrchestrationService

        orchestration_svc = OrchestrationService(self.uow, project_root=self.project_root)
        try:
            orchestration_svc.resume(
                run_id=run.run_id, drain_mode=drain_mode, force=force, claim_context=context
            )
            decision.status = RecoveryDecisionStatus.COMPLETED
        except Exception as exc:
            logger.error("Run continuation failed for '%s': %s", run.run_id, exc)
            decision.status = RecoveryDecisionStatus.BLOCKED
            decision.reason_code = str(exc)

        self._update_decision(decision)
        self.release_claim(context)
        return decision

    def _converge_saga_identity(
        self,
        saga_id: str,
        cycle_id: str,
        claim_key: str,
        source: RecoverySource,
    ) -> RecoveryDecision:
        claim = self.acquire_claim(claim_key=claim_key, lease_seconds=self.lease_seconds)
        if not claim:
            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="SAGA",
                identity_id=saga_id,
                source=source,
                classification=RecoveryClassification.CLAIMED_ELSEWHERE,
                planned_action="NO_ACTION",
                status=RecoveryDecisionStatus.NO_ACTION,
                reason_code="CLAIMED_ELSEWHERE",
            )
            self._create_decision(decision)
            self.uow.commit()
            return decision

        context = RecoveryClaimContext(
            claim_key=claim.claim_key,
            owner_instance_id=claim.owner_instance_id,
            fence_token=claim.fence_token,
            lease_expires_at=claim.lease_expires_at,
        )

        saga = self.uow.durable_sagas.get_by_id(saga_id)
        if not saga or saga.status in (SagaStatus.COMPLETED, SagaStatus.FAILED):
            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="SAGA",
                identity_id=saga_id,
                source=source,
                fence_token=context.fence_token,
                classification=RecoveryClassification.TERMINAL_EXECUTION_BLOCKED,
                planned_action="NO_ACTION",
                status=RecoveryDecisionStatus.NO_ACTION,
            )
            self._create_decision(decision)
            self.release_claim(context)
            return decision

        item = self.uow.backlog_items.get_by_project_and_key(
            saga.project_id, saga.work_item_key
        )
        change = self.uow.changes.get_by_name(
            saga.project_id, saga.change_name or saga.work_item_key
        )
        is_terminal = (
            item and item.status in (WorkItemStatus.COMPLETED, WorkItemStatus.CANCELLED)
        ) or (change and change.status in (ChangeStatus.DONE, ChangeStatus.CANCELLED))

        from minime.services.intake_service import IntakeService
        from minime.services.post_merge_service import PostMergeReconciliationService
        from minime.services.saga_engine import SagaEngine

        saga_engine = SagaEngine(
            self.uow,
            heartbeat_interval_seconds=self.heartbeat_seconds,
            lease_seconds=self.lease_seconds,
        )
        intake_svc = IntakeService(self.uow, project_root=self.project_root, github_adapter=self.github_adapter)
        post_merge_svc = self.post_merge_service or PostMergeReconciliationService(
            self.uow,
            project_root=self.project_root,
            github_adapter=self.github_adapter,
            saga_engine=SagaEngine(
                self.uow,
                heartbeat_interval_seconds=self.heartbeat_seconds,
                lease_seconds=self.lease_seconds,
            ),
        )

        if is_terminal and saga.saga_type == SagaType.INTAKE:
            saga_engine.cancel_saga(
                saga, cancellation_reason="Parent backlog item or change is terminal.", claim_context=context
            )
            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="SAGA",
                identity_id=saga_id,
                project_id=saga.project_id,
                change_name=saga.change_name,
                source=source,
                fence_token=context.fence_token,
                classification=RecoveryClassification.TERMINAL_EXECUTION_BLOCKED,
                planned_action="CANCEL_INTAKE_SAGA",
                status=RecoveryDecisionStatus.COMPLETED,
            )
            self._create_decision(decision)
            self.release_claim(context)
            return decision

        decision = RecoveryDecision(
            cycle_id=cycle_id,
            claim_key=claim_key,
            identity_type="SAGA",
            identity_id=saga_id,
            project_id=saga.project_id,
            change_name=saga.change_name,
            source=source,
            fence_token=context.fence_token,
            classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
            planned_action="RESUME_SAGA",
            status=RecoveryDecisionStatus.EXECUTING,
        )
        self._create_decision(decision)
        self.uow.commit()

        try:
            saga_engine.resume_saga(
                saga.id,
                intake_service=intake_svc,
                post_merge_service=post_merge_svc,
                claim_context=context,
            )
            decision.status = RecoveryDecisionStatus.COMPLETED
        except Exception as exc:
            decision.status = RecoveryDecisionStatus.BLOCKED
            decision.reason_code = str(exc)

        self._update_decision(decision)
        self.release_claim(context)
        return decision

    def _converge_action_identity(
        self,
        action_key: str,
        cycle_id: str,
        claim_key: str,
        source: RecoverySource,
    ) -> RecoveryDecision:
        action = self.uow.orchestration_external_actions.get_by_action_key(action_key)
        if not action:
            raise ValueError(f"Action '{action_key}' not found.")

        claim = self.uow.claims.acquire_or_reacquire(
            claim_key=claim_key,
            owner_instance_id=self.owner_instance_id,
            lease_seconds=self.lease_seconds,
        )
        if not claim:
            decision = RecoveryDecision(
                cycle_id=cycle_id,
                claim_key=claim_key,
                identity_type="ACTION",
                identity_id=action_key,
                source=source,
                classification=RecoveryClassification.CLAIMED_ELSEWHERE,
                planned_action="NO_ACTION",
                status=RecoveryDecisionStatus.NO_ACTION,
            )
            self._create_decision(decision)
            self.uow.commit()
            return decision

        context = RecoveryClaimContext(
            claim_key=claim.claim_key,
            owner_instance_id=claim.owner_instance_id,
            fence_token=claim.fence_token,
            lease_expires_at=claim.lease_expires_at,
        )

        outcome = self.observe_external_action(action)

        if outcome == ActionObservationOutcome.OBSERVED_PRESENT or action.status == ExternalActionStatus.COMPLETED:
            classification = RecoveryClassification.ADOPT_OBSERVED_EFFECT
            planned_action = "ADOPT_COMPLETED"
        elif outcome == ActionObservationOutcome.OBSERVED_ABSENT:
            is_authorized = (
                action.result_payload.get("retry_safety") == "SAFE"
                or action.result_payload.get("is_retry_authorized") is True
            )
            if is_authorized:
                classification = RecoveryClassification.RESUME_SAFE_CHECKPOINT
                planned_action = "DISPATCH_AUTHORIZED"
            else:
                classification = RecoveryClassification.WAITING_EXTERNAL
                planned_action = "OBSERVE_BEFORE_REPEAT"
        elif outcome == ActionObservationOutcome.CONTRADICTORY or action.status == ExternalActionStatus.AMBIGUOUS:
            classification = RecoveryClassification.NEEDS_HUMAN
            planned_action = "ESCALATE_NEEDS_HUMAN"
        else:
            classification = RecoveryClassification.WAITING_EXTERNAL
            planned_action = "OBSERVE_BEFORE_REPEAT"

        decision = RecoveryDecision(
            cycle_id=cycle_id,
            claim_key=claim_key,
            identity_type="ACTION",
            identity_id=action_key,
            source=source,
            fence_token=context.fence_token,
            classification=classification,
            planned_action=planned_action,
            status=RecoveryDecisionStatus.COMPLETED,
        )
        self._create_decision(decision)
        self.release_claim(context)
        return decision
