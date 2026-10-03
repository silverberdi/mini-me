"""Canonical Stage G Recovery Convergence Service."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from minime.domain.enums import (
    ChangeStatus,
    EventType,
    ExternalActionObservation,
    ExternalActionStatus,
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProviderHealthStatus,
    RecoveryClassification,
    RecoveryDecisionStatus,
    RecoverySource,
    SagaStatus,
    SagaType,
    WorkItemStatus,
)
from minime.domain.exceptions import StaleClaimError
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Event,
    ExternalActionAttempt,
    OrchestrationExternalAction,
    RecoveryClaimContext,
    RecoveryDecision,
    generate_uuid,
    utc_now,
)
from minime.services.provider_health_service import ProviderHealthService

logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 60
DEFAULT_HEARTBEAT_SECONDS = 15


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
    ):
        if heartbeat_seconds >= lease_seconds / 3:
            raise ValueError(
                f"Heartbeat interval ({heartbeat_seconds}s) must be strictly less than 1/3 of lease duration ({lease_seconds}s)."
            )
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.owner_instance_id = owner_instance_id or f"instance-{os.getpid()}-{generate_uuid()[:8]}"
        self.health_service = health_service or ProviderHealthService(uow)
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds

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

        # 4. Converge Active Sagas
        for saga in active_sagas:
            if saga.saga_type == SagaType.INTAKE:
                claim_key = f"intake:{saga.project_id}:{saga.work_item_key}"
            else:
                claim_key = f"run:{saga.run_id}" if saga.run_id else f"closure:{saga.id}"

            # Check if decision for this claim_key already exists in this cycle
            if any(d.claim_key == claim_key for d in decisions):
                continue

            decision = self._converge_saga_identity(
                saga_id=saga.id, cycle_id=cycle_id, claim_key=claim_key, source=source
            )
            decisions.append(decision)

        return decisions

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
        claim_key = f"run:{action.run_id}" if action.run_id else f"closure:{action.saga_id}"
        cycle_id = generate_uuid()
        return self._converge_action_identity(
            action_key=action_key, cycle_id=cycle_id, claim_key=claim_key, source=source
        )

    def acquire_claim(self, claim_key: str, lease_seconds: int = 60) -> RecoveryClaimContext | None:
        """Acquire or re-acquire a claim for this owner instance."""
        claim = self.uow.claims.acquire_or_reacquire(
            claim_key=claim_key,
            owner_instance_id=self.owner_instance_id,
            lease_seconds=lease_seconds,
        )
        if not claim:
            return None
        self.uow.commit()
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
        """Fenced CAS result application: validates fence before updating lifecycle state."""
        if not self.validate_claim(context):
            raise StaleClaimError(
                f"Stale worker with fence {context.fence_token} cannot advance lifecycle."
            )
        result = apply_fn()
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
        claim = self.uow.claims.acquire_or_reacquire(
            claim_key=claim_key,
            owner_instance_id=self.owner_instance_id,
            lease_seconds=self.lease_seconds,
        )
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
            self.uow.recovery_decisions.create_decision(decision)
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
            self.uow.recovery_decisions.create_decision(decision)
            self.release_claim(context)
            return decision

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
                self.uow.recovery_decisions.create_decision(decision)
                self.uow.commit()

                try:
                    if closure_sagas:
                        engine = SagaEngine(self.uow)
                        engine.resume_saga(closure_sagas[0].id, claim_context=context)
                    else:
                        post_merge_svc = PostMergeReconciliationService(self.uow, project_root=self.project_root)
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
                self.uow.recovery_decisions.update_decision(decision)
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
            self.uow.recovery_decisions.create_decision(decision)
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
                        run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
                        run.human_gate = HumanGate.NEEDS_HUMAN
                        run.is_active = False
                        run.stop_reason = reason
                        if run.active_job_id:
                            job = self.uow.jobs.get_by_id(run.active_job_id)
                            if job:
                                job.status = JobStatus.NEEDS_HUMAN
                                job.escalation_reason = reason
                                self.uow.jobs.save(job)
                        self.uow.orchestration_runs.save(run)
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
                        self.uow.recovery_decisions.create_decision(decision)
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
                self.uow.recovery_decisions.create_decision(decision)
                self.release_claim(context)
                return decision
            else:
                run.stop_outcome = None
                run.stop_reason = None
                self.uow.orchestration_runs.save(run)
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
                    self.uow.recovery_decisions.create_decision(decision)
                    self.uow.commit()
                    self.release_claim(context)
                    return decision

        actions = self.uow.orchestration_external_actions.list_by_run(run.run_id)
        has_ambiguous = False
        has_adoptable = False
        for action in actions:
            if action.status in (
                ExternalActionStatus.EXECUTING,
                ExternalActionStatus.UNKNOWN,
                ExternalActionStatus.AMBIGUOUS,
                ExternalActionStatus.RESERVED,
            ):
                obs = self.classify_external_action_observation(action)
                if action.status == ExternalActionStatus.COMPLETED:
                    has_adoptable = True
                elif obs == ExternalActionObservation.PROVEN_NEVER_DISPATCHED:
                    continue
                elif action.status == ExternalActionStatus.AMBIGUOUS or obs == ExternalActionObservation.POSSIBLY_DISPATCHED:
                    has_ambiguous = True

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
                classification=RecoveryClassification.WAITING_EXTERNAL,
                planned_action="OBSERVE_EXTERNAL",
                status=RecoveryDecisionStatus.PLANNED,
            )
            self.uow.recovery_decisions.create_decision(decision)
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
            self.uow.recovery_decisions.create_decision(decision)
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
            self.uow.recovery_decisions.create_decision(decision)
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
        self.uow.recovery_decisions.create_decision(decision)
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

        self.uow.recovery_decisions.update_decision(decision)
        self.release_claim(context)
        return decision

    def _converge_saga_identity(
        self,
        saga_id: str,
        cycle_id: str,
        claim_key: str,
        source: RecoverySource,
    ) -> RecoveryDecision:
        claim = self.uow.claims.acquire_or_reacquire(
            claim_key=claim_key,
            owner_instance_id=self.owner_instance_id,
            lease_seconds=self.lease_seconds,
        )
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
            self.uow.recovery_decisions.create_decision(decision)
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
            self.uow.recovery_decisions.create_decision(decision)
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

        from minime.services.saga_engine import SagaEngine

        saga_engine = SagaEngine(self.uow)

        if is_terminal and saga.saga_type == SagaType.INTAKE:
            saga_engine.cancel_saga(
                saga, cancellation_reason="Parent backlog item or change is terminal."
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
            self.uow.recovery_decisions.create_decision(decision)
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
        self.uow.recovery_decisions.create_decision(decision)
        self.uow.commit()

        try:
            saga_engine.resume_saga(saga.id, claim_context=context)
            decision.status = RecoveryDecisionStatus.COMPLETED
        except Exception as exc:
            decision.status = RecoveryDecisionStatus.BLOCKED
            decision.reason_code = str(exc)

        self.uow.recovery_decisions.update_decision(decision)
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
            self.uow.recovery_decisions.create_decision(decision)
            self.uow.commit()
            return decision

        context = RecoveryClaimContext(
            claim_key=claim.claim_key,
            owner_instance_id=claim.owner_instance_id,
            fence_token=claim.fence_token,
            lease_expires_at=claim.lease_expires_at,
        )

        obs = self.classify_external_action_observation(action)

        if action.status == ExternalActionStatus.COMPLETED:
            classification = RecoveryClassification.ADOPT_OBSERVED_EFFECT
            planned_action = "ADOPT_COMPLETED"
        elif (
            action.status == ExternalActionStatus.RESERVED
            and obs == ExternalActionObservation.PROVEN_NEVER_DISPATCHED
        ):
            classification = RecoveryClassification.RESUME_SAFE_CHECKPOINT
            planned_action = "DISPATCH_AUTHORIZED"
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
        self.uow.recovery_decisions.create_decision(decision)
        self.release_claim(context)
        return decision
