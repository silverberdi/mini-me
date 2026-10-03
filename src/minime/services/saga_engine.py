"""Durable Saga Engine for mini me intake and closure processes."""

from __future__ import annotations

import logging
from typing import Any, Callable

from minime.db.savepoint import execute_with_savepoint_recovery
from minime.domain.enums import (
    EventType,
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    SagaStatus,
    SagaType,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    DurableSaga,
    Event,
    FencedDispatchResult,
    OrchestrationExternalAction,
    RecoveryClaimContext,
)

logger = logging.getLogger(__name__)


class SagaEngine:
    """Manages lifecycle phase transitions, checkpoints, and external action reservations for DurableSagas."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def get_saga(self, saga_id: str) -> DurableSaga | None:
        return self.uow.durable_sagas.get_by_id(saga_id)

    def get_for_update(self, saga_id: str) -> DurableSaga | None:
        return self.uow.durable_sagas.get_for_update(saga_id)

    def get_active_saga(
        self,
        project_id: str,
        work_item_key: str,
        saga_type: SagaType | str,
    ) -> DurableSaga | None:
        return self.uow.durable_sagas.get_active_saga(project_id, work_item_key, saga_type)

    def start_saga(
        self,
        saga_type: SagaType | str,
        project_id: str,
        work_item_key: str,
        change_name: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        initial_phase: str = "STARTED",
    ) -> DurableSaga:
        """Start a new saga or return existing active saga for (project_id, work_item_key, saga_type)."""
        st_enum = SagaType(saga_type) if isinstance(saga_type, str) else saga_type
        existing = self.uow.durable_sagas.get_active_saga(project_id, work_item_key, st_enum)
        if existing:
            logger.info(
                "Active saga '%s' of type '%s' already exists for item '%s'.",
                existing.id,
                st_enum.value,
                work_item_key,
            )
            return existing

        saga = DurableSaga(
            saga_type=st_enum,
            project_id=project_id,
            work_item_key=work_item_key,
            change_name=change_name,
            run_id=run_id,
            job_id=job_id,
            generation=1,
            current_phase=initial_phase,
            status=SagaStatus.IN_PROGRESS,
            evidence_references={},
        )

        constraint_name = (
            "uq_active_intake_saga" if st_enum == SagaType.INTAKE else "uq_active_closure_saga"
        )

        def _recovery_saga() -> DurableSaga:
            winner = self.uow.durable_sagas.get_active_saga(project_id, work_item_key, st_enum)
            if winner:
                return winner
            raise RuntimeError(f"Failed to recover active saga for {work_item_key}")

        from minime.db.savepoint import execute_with_savepoint_recovery
        session = getattr(self.uow, "session", None)
        if session is not None and hasattr(session, "begin_nested"):
            saved, recovery_res = execute_with_savepoint_recovery(
                session=session,
                save_fn=lambda: self.uow.durable_sagas.save(saga),
                constraint_name=constraint_name,
                recovery_fn=_recovery_saga,
            )
            if not saved and recovery_res is not None:
                return recovery_res
        else:
            self.uow.durable_sagas.save(saga)

        event = Event(
            project_id=project_id,
            change_id=change_name or work_item_key,
            event_type=EventType.DURABLE_SAGA_STARTED.value,
            payload={
                "saga_id": saga.id,
                "saga_type": st_enum.value,
                "work_item_key": work_item_key,
                "change_name": change_name,
                "initial_phase": initial_phase,
            },
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.info(
            "Started DurableSaga '%s' (%s) at phase '%s'", saga.id, st_enum.value, initial_phase
        )
        return saga

    def advance_phase(
        self,
        saga: DurableSaga,
        next_phase: str,
        evidence_references: dict[str, Any] | None = None,
        last_observed_outcome: ExternalOutcome | str | None = None,
    ) -> DurableSaga:
        """Advance saga checkpoint to next phase with durable evidence persistence."""
        updated = self.uow.durable_sagas.update_phase(
            saga_id=saga.id,
            current_phase=next_phase,
            evidence_references=evidence_references,
            last_observed_outcome=last_observed_outcome,
        )

        event = Event(
            project_id=saga.project_id,
            change_id=saga.change_name or saga.work_item_key,
            event_type=EventType.DURABLE_SAGA_PHASE_ADVANCED.value,
            payload={
                "saga_id": saga.id,
                "saga_type": saga.saga_type.value,
                "previous_phase": saga.current_phase,
                "next_phase": next_phase,
                "evidence_references": evidence_references or {},
            },
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.info(
            "Saga '%s' (%s) advanced phase: %s -> %s",
            saga.id,
            saga.saga_type.value,
            saga.current_phase,
            next_phase,
        )
        return updated

    def block_saga(
        self,
        saga: DurableSaga,
        blocking_reason: str,
        last_observed_outcome: ExternalOutcome | str | None = None,
    ) -> DurableSaga:
        """Transition saga to BLOCKED status with explicit blocking reason."""
        updated = self.uow.durable_sagas.update_status(
            saga_id=saga.id,
            status=SagaStatus.BLOCKED,
            blocking_reason=blocking_reason,
            last_observed_outcome=last_observed_outcome,
        )

        event = Event(
            project_id=saga.project_id,
            change_id=saga.change_name or saga.work_item_key,
            event_type=EventType.DURABLE_SAGA_BLOCKED.value,
            payload={
                "saga_id": saga.id,
                "saga_type": saga.saga_type.value,
                "phase": saga.current_phase,
                "blocking_reason": blocking_reason,
            },
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.warning(
            "Saga '%s' blocked at phase '%s': %s", saga.id, saga.current_phase, blocking_reason
        )
        return updated

    def complete_saga(
        self,
        saga: DurableSaga,
        evidence_references: dict[str, Any] | None = None,
    ) -> DurableSaga:
        """Mark saga as COMPLETED after all phases are proven complete."""
        if evidence_references:
            self.uow.durable_sagas.update_phase(
                saga_id=saga.id,
                current_phase=saga.current_phase,
                evidence_references=evidence_references,
            )

        updated = self.uow.durable_sagas.update_status(
            saga_id=saga.id,
            status=SagaStatus.COMPLETED,
            last_observed_outcome=ExternalOutcome.SUCCESS,
        )

        event = Event(
            project_id=saga.project_id,
            change_id=saga.change_name or saga.work_item_key,
            event_type=EventType.DURABLE_SAGA_COMPLETED.value,
            payload={
                "saga_id": saga.id,
                "saga_type": saga.saga_type.value,
                "final_phase": saga.current_phase,
            },
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.info("Saga '%s' (%s) COMPLETED cleanly.", saga.id, saga.saga_type.value)
        return updated

    def fail_saga(
        self,
        saga: DurableSaga,
        failure_reason: str,
    ) -> DurableSaga:
        """Mark saga as FAILED."""
        updated = self.uow.durable_sagas.update_status(
            saga_id=saga.id,
            status=SagaStatus.FAILED,
            blocking_reason=failure_reason,
            last_observed_outcome=ExternalOutcome.FAILURE,
        )

        event = Event(
            project_id=saga.project_id,
            change_id=saga.change_name or saga.work_item_key,
            event_type=EventType.DURABLE_SAGA_FAILED.value,
            payload={
                "saga_id": saga.id,
                "saga_type": saga.saga_type.value,
                "phase": saga.current_phase,
                "failure_reason": failure_reason,
            },
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.error(
            "Saga '%s' (%s) FAILED at phase '%s': %s",
            saga.id,
            saga.saga_type.value,
            saga.current_phase,
            failure_reason,
        )
        return updated

    def reserve_action(
        self,
        action_key: str,
        action_type: ExternalActionType | str,
        target_identity: str,
        request_fingerprint: str,
        run_id: str | None = None,
        saga_id: str | None = None,
        candidate_sha: str | None = None,
        generation: int = 1,
    ) -> OrchestrationExternalAction:
        """Reserve an external mutating action in DB BEFORE external network execution."""
        at_enum = ExternalActionType(action_type) if isinstance(action_type, str) else action_type

        existing = self.uow.orchestration_external_actions.get_by_action_key(action_key)
        if existing:
            logger.info(
                "Action reservation for '%s' already exists (status=%s).",
                action_key,
                existing.status.value,
            )
            return existing

        action = OrchestrationExternalAction(
            run_id=run_id,
            saga_id=saga_id,
            action_key=action_key,
            action_type=at_enum,
            target_identity=target_identity,
            request_fingerprint=request_fingerprint,
            candidate_sha=candidate_sha,
            generation=generation,
            status=ExternalActionStatus.RESERVED,
        )

        def _recovery_action() -> OrchestrationExternalAction:
            res = self.uow.orchestration_external_actions.get_by_action_key(action_key)
            if res:
                return res
            raise RuntimeError(f"Failed to recover action for {action_key}")

        session = getattr(self.uow, "session", None)
        if session is not None and hasattr(session, "begin_nested"):
            saved, recovery_res = execute_with_savepoint_recovery(
                session=session,
                save_fn=lambda: self.uow.orchestration_external_actions.reserve(action),
                constraint_name="action_key",
                recovery_fn=_recovery_action,
            )
            if not saved and recovery_res is not None:
                return recovery_res
        else:
            self.uow.orchestration_external_actions.reserve(action)


        event = Event(
            project_id="system",
            change_id=action_key,
            event_type=EventType.DURABLE_SAGA_ACTION_RESERVED.value,
            payload={
                "action_key": action_key,
                "action_type": at_enum.value,
                "target_identity": target_identity,
                "saga_id": saga_id,
                "run_id": run_id,
            },
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.info(
            "Reserved action '%s' (%s) in PostgreSQL BEFORE execution.", action_key, at_enum.value
        )
        return action

    def execute_fenced_external_action(
        self,
        claim_context: RecoveryClaimContext,
        action_key: str,
        action_type: ExternalActionType | str,
        target_identity: str,
        request_fingerprint: str,
        mutation_fn: Callable[[], Any],
        saga_id: str | None = None,
        run_id: str | None = None,
        candidate_sha: str | None = None,
        observation_fn: Callable[[], Any | None] | None = None,
        is_original_request: bool = True,
    ) -> FencedDispatchResult:
        """Execute a recoverable external mutation under canonical Stage G atomic fenced dispatch intent."""
        from minime.domain.enums import (
            ExternalActionObservation,
            ExternalActionStatus,
            ExternalOutcome,
        )
        from minime.domain.models import (
            FencedDispatchResult,
            evaluate_dispatch_authorization,
            validate_claim_context_authoritative,
        )

        validate_claim_context_authoritative(self.uow, claim_context)

        def _check_fence_valid() -> bool:
            if claim_context is None:
                return True
            if hasattr(self.uow, "claims") and self.uow.claims is not None:
                return self.uow.claims.validate_cas(
                    claim_key=claim_context.claim_key,
                    owner_instance_id=claim_context.owner_instance_id,
                    fence_token=claim_context.fence_token,
                )
            return claim_context.is_valid()

        # 1. Reserve action identity
        action = self.reserve_action(
            action_key=action_key,
            action_type=action_type,
            target_identity=target_identity,
            request_fingerprint=request_fingerprint,
            run_id=run_id,
            saga_id=saga_id,
            candidate_sha=candidate_sha,
        )

        if action.status == ExternalActionStatus.COMPLETED:
            logger.info("Action '%s' is already COMPLETED; skipping remote mutation.", action_key)
            is_valid = _check_fence_valid()
            return FencedDispatchResult(
                action_key=action_key,
                result=action.result_payload,
                outcome=ExternalOutcome.SUCCESS,
                result_application_authorized=is_valid,
                fence_token=claim_context.fence_token if claim_context else 1,
                is_stale=not is_valid,
                remote_identifier=action.remote_identifier,
                result_payload=action.result_payload,
            )

        # 2. Observation classification & remote check
        attempts = (
            self.uow.external_action_attempts.list_by_action_key(action_key)
            if hasattr(self.uow, "external_action_attempts") and self.uow.external_action_attempts is not None
            else []
        )
        if action.last_dispatch_intent_id or action.remote_identifier or attempts:
            obs = ExternalActionObservation.POSSIBLY_DISPATCHED
        else:
            obs = ExternalActionObservation.PROVEN_NEVER_DISPATCHED

        observation_proven_absent = False
        if observation_fn is not None:
            obs_res = observation_fn()
            if obs_res is not None and getattr(obs_res, "outcome", None) == ExternalOutcome.SUCCESS:
                remote_id = getattr(obs_res, "external_id", None) or str(getattr(obs_res, "data", ""))
                self.record_action_result(
                    action_key=action_key,
                    status=ExternalActionStatus.COMPLETED,
                    remote_identifier=remote_id,
                    result_payload=getattr(obs_res, "data", None) if isinstance(getattr(obs_res, "data", None), dict) else None,
                )
                is_valid = _check_fence_valid()
                return FencedDispatchResult(
                    action_key=action_key,
                    result=obs_res,
                    outcome=ExternalOutcome.SUCCESS,
                    result_application_authorized=is_valid,
                    fence_token=claim_context.fence_token if claim_context else 1,
                    is_stale=not is_valid,
                    remote_identifier=remote_id,
                    result_payload=getattr(obs_res, "data", None) if isinstance(getattr(obs_res, "data", None), dict) else None,
                )
            elif obs_res is not None and getattr(obs_res, "outcome", None) in (
                ExternalOutcome.FAILURE,
                ExternalOutcome.UNKNOWN,
                ExternalOutcome.AMBIGUOUS,
            ):
                from minime.domain.enums import ExternalReasonCode

                obs_outcome = getattr(obs_res, "outcome", ExternalOutcome.FAILURE)
                if obs_outcome == ExternalOutcome.FAILURE and getattr(obs_res, "reason_code", None) == ExternalReasonCode.NOT_FOUND:
                    observation_proven_absent = True
                else:
                    err_msg = getattr(obs_res, "error_message", None) or f"Observation outcome: {obs_outcome.value}"
                    status_enum = (
                        ExternalActionStatus.AMBIGUOUS
                        if obs_outcome == ExternalOutcome.AMBIGUOUS
                        else ExternalActionStatus.FAILED
                    )
                    self.record_action_result(
                        action_key=action_key,
                        status=status_enum,
                        error_message=err_msg,
                    )
                    is_valid = _check_fence_valid()
                    return FencedDispatchResult(
                        action_key=action_key,
                        result=obs_res,
                        outcome=obs_outcome,
                        result_application_authorized=is_valid,
                        fence_token=claim_context.fence_token if claim_context else 1,
                        is_stale=not is_valid,
                        error_message=err_msg,
                    )
            elif obs_res is None:
                observation_proven_absent = True

        # 3. Stage B/D Authorization evaluation
        auth = evaluate_dispatch_authorization(
            action=action,
            observation=obs,
            is_original_request=is_original_request,
            observation_proven_absent=observation_proven_absent,
        )
        if not auth.is_authorized:
            raise ValueError(
                f"Stage B/D dispatch authorization denied for '{action_key}': {auth.authorization_reason}"
            )

        # 4. Atomic Commit Fenced Dispatch Intent (SHORT DB TRANSACTION BEFORE I/O)
        if claim_context is not None and hasattr(self.uow, "claims") and self.uow.claims is not None:
            attempt_number = len(attempts) + 1
            self.uow.claims.commit_fenced_dispatch_intent(
                claim_key=claim_context.claim_key,
                owner_instance_id=claim_context.owner_instance_id,
                fence_token=claim_context.fence_token,
                action_key=action_key,
                attempt_number=attempt_number,
                authorization=auth,
            )

        # 5. Execute slow external mutation (NO DB LOCK HELD)
        res = mutation_fn()

        # 6. Record truthful remote action result (monotonically persisted in DB)
        outcome = getattr(res, "outcome", None)
        remote_id = getattr(res, "external_id", None)
        res_data = getattr(res, "data", None)
        err_msg = getattr(res, "error_message", None)

        if outcome == ExternalOutcome.SUCCESS or res is True:
            self.record_action_result(
                action_key=action_key,
                status=ExternalActionStatus.COMPLETED,
                remote_identifier=remote_id,
                result_payload=res_data if isinstance(res_data, dict) else None,
            )
        elif outcome == ExternalOutcome.FAILURE:
            err_msg = err_msg or "Mutation failed."
            self.record_action_result(
                action_key=action_key,
                status=ExternalActionStatus.FAILED,
                error_message=err_msg,
            )
        else:
            err_msg = err_msg or "Mutation outcome ambiguous."
            self.record_action_result(
                action_key=action_key,
                status=ExternalActionStatus.AMBIGUOUS,
                error_message=err_msg,
            )

        # 7. Post-I/O Fence CAS check to authorize lifecycle application
        is_valid = _check_fence_valid()
        final_outcome = outcome or (ExternalOutcome.SUCCESS if res is True else ExternalOutcome.FAILURE)

        return FencedDispatchResult(
            action_key=action_key,
            result=res,
            outcome=final_outcome,
            result_application_authorized=is_valid,
            fence_token=claim_context.fence_token if claim_context else 1,
            is_stale=not is_valid,
            remote_identifier=remote_id,
            result_payload=res_data if isinstance(res_data, dict) else None,
            error_message=err_msg if final_outcome != ExternalOutcome.SUCCESS else None,
        )

    def record_action_result(
        self,
        action_key: str,
        status: ExternalActionStatus | str,
        remote_identifier: str | None = None,
        result_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> OrchestrationExternalAction:
        """Record external action execution outcome. Valid status MUST be canonical ExternalActionStatus."""
        st_enum = ExternalActionStatus(status) if isinstance(status, str) else status
        if st_enum not in {
            ExternalActionStatus.COMPLETED,
            ExternalActionStatus.FAILED,
            ExternalActionStatus.AMBIGUOUS,
            ExternalActionStatus.UNKNOWN,
            ExternalActionStatus.EXECUTING,
            ExternalActionStatus.RESERVED,
        }:
            raise ValueError(
                f"Invalid external action status '{st_enum}'. Cannot persist arbitrary status."
            )

        updated = self.uow.orchestration_external_actions.update_status(
            action_key=action_key,
            status=st_enum,
            remote_identifier=remote_identifier,
            result_payload=result_payload,
            error_message=error_message,
        )

        event = Event(
            project_id="system",
            change_id=action_key,
            event_type=EventType.DURABLE_SAGA_ACTION_RECONCILED.value,
            payload={
                "action_key": action_key,
                "status": st_enum.value,
                "remote_identifier": remote_identifier,
                "error_message": error_message,
            },
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.info("Recorded action result for '%s': status=%s", action_key, st_enum.value)
        return updated

    def cancel_saga(
        self,
        saga: DurableSaga,
        cancellation_reason: str,
    ) -> DurableSaga:
        """Mark saga as CANCELLED."""
        updated = self.uow.durable_sagas.update_status(
            saga_id=saga.id,
            status=SagaStatus.CANCELLED,
            blocking_reason=cancellation_reason,
            last_observed_outcome=ExternalOutcome.FAILURE,
        )

        event = Event(
            project_id=saga.project_id,
            change_id=saga.change_name or saga.work_item_key,
            event_type=EventType.DURABLE_SAGA_FAILED.value,
            payload={
                "saga_id": saga.id,
                "saga_type": saga.saga_type.value,
                "phase": saga.current_phase,
                "cancellation_reason": cancellation_reason,
            },
        )
        self.uow.events.save(event)
        self.uow.commit()

        logger.info(
            "Saga '%s' (%s) CANCELLED: %s", saga.id, saga.saga_type.value, cancellation_reason
        )
        return updated

    def resume_saga(
        self,
        saga_id: str,
        intake_service: Any = None,
        post_merge_service: Any = None,
        claim_context: RecoveryClaimContext | None = None,
    ) -> DurableSaga:
        from minime.domain.models import validate_claim_context_authoritative

        validate_claim_context_authoritative(self.uow, claim_context)

        saga = self.get_for_update(saga_id) or self.get_saga(saga_id)
        if not saga:
            raise ValueError(f"Saga '{saga_id}' not found.")

        if saga.status in {SagaStatus.COMPLETED, SagaStatus.FAILED}:
            logger.info(
                "Saga '%s' is in terminal state '%s'; resume skipped.", saga.id, saga.status.value
            )
            return saga

        logger.info(
            "Resuming saga '%s' (%s) at phase '%s' (status=%s)",
            saga.id,
            saga.saga_type.value,
            saga.current_phase,
            saga.status.value,
        )

        if saga.status == SagaStatus.BLOCKED:
            saga = self.uow.durable_sagas.update_status(
                saga.id, status=SagaStatus.IN_PROGRESS, blocking_reason=None
            )

        if saga.saga_type == SagaType.INTAKE:
            if intake_service is not None:
                intake_service.prepare_work_item(saga.project_id, saga.work_item_key, claim_context=claim_context)
        elif saga.saga_type == SagaType.CLOSURE:
            if post_merge_service is not None:
                post_merge_service.reconcile_post_merge(
                    project_id=saga.project_id,
                    change_name=saga.change_name or saga.work_item_key,
                    run_id=saga.run_id,
                    claim_context=claim_context,
                )

        updated = self.get_saga(saga_id) or saga
        return updated
