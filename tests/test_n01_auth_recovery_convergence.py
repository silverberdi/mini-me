from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from minime.domain.enums import (
    ExecutionOutcome,
    JobStatus,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProviderHealthStatus,
    RecoveryClassification,
    RecoveryDecisionStatus,
    RecoverySource,
)
from minime.domain.models import (
    Job,
    JobAttempt,
    OperatorActionRequest,
    OrchestrationRun,
    Project,
    ProviderHealth,
    RecoveryClaimContext,
    RecoveryDecision,
    utc_now,
)
from minime.services.control_plane_service import ControlPlaneService


def _auth_waiting_n01(in_memory_uow):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)
    run = OrchestrationRun(
        run_id="run-n01-auth",
        project_id=project.project_id,
        change_name="operational-blocker-visibility",
        base_sha="base-sha-n01",
        current_stage=OrchestrationStage.IMPLEMENTING,
        resumable_stage=OrchestrationStage.IMPLEMENTING,
        current_generation=1,
        active_job_id="job-n01-auth",
        current_candidate_sha=None,
        is_active=True,
        stop_outcome=OrchestrationStopOutcome.WAITING_CAPACITY,
        stop_details={"provider": "codex"},
    )
    job = Job(
        job_id=run.active_job_id,
        project_id=project.project_id,
        change_name=run.change_name,
        status=JobStatus.WAITING_CAPACITY,
        implementer_role="codex",
        current_executor="codex",
        waiting_provider="codex",
        attempt_count=4,
    )
    health = ProviderHealth(
        health_id="ph-codex",
        provider="codex",
        status=ProviderHealthStatus.AUTH_REQUIRED,
        updated_at=utc_now(),
    )
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.jobs.save(job)
    in_memory_uow.provider_health.save(health)
    in_memory_uow.commit()
    return project, run, job, health


def test_active_waiting_auth_required_exposes_confirmation_bound_continue(in_memory_uow):
    _, run, _, health = _auth_waiting_n01(in_memory_uow)

    actions = ControlPlaneService(in_memory_uow).get_available_actions(run.run_id)
    action = next(item for item in actions if item.action == OperatorActionType.CONTINUE)

    assert action.enabled is True
    assert action.requires_confirmation is True
    assert (
        action.parameters_schema["properties"]["expected_provider_health_updated_at"]["const"]
        == health.updated_at.isoformat()
    )


def test_local_reauthentication_ack_does_not_promote_health_and_authorizes_one_dispatch(
    in_memory_uow, monkeypatch
):
    _, run, _, health = _auth_waiting_n01(in_memory_uow)
    service = ControlPlaneService(in_memory_uow)
    captured = {}

    def request_continuation(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status=RecoveryDecisionStatus.COMPLETED, reason_code=None)

    monkeypatch.setattr(
        service.recovery_convergence_service,
        "request_run_continuation",
        request_continuation,
    )
    request = OperatorActionRequest(
        action_request_id="auth-confirmed-request-1",
        project_id=run.project_id,
        change_name=run.change_name,
        run_id=run.run_id,
        action_type=OperatorActionType.CONTINUE,
        actor_identity="operator-test",
        expected_stage=OrchestrationStage.IMPLEMENTING,
        expected_generation=run.current_generation,
        parameters={
            "provider_reauthentication_confirmed": True,
            "expected_provider_health_updated_at": health.updated_at.isoformat(),
        },
    )

    result = service.execute_action(request)

    assert result.status == OperatorActionStatus.COMPLETED
    assert captured["force"] is False
    assert captured["drive_admitted"] is True
    assert captured["auth_recovery_authorization"]["action_request_id"] == request.action_request_id
    assert (
        in_memory_uow.provider_health.get_by_provider("codex").status
        == ProviderHealthStatus.AUTH_REQUIRED
    )
    assert in_memory_uow.jobs.get_by_id(run.active_job_id).attempt_count == 4


def test_auth_recovery_rejects_missing_or_stale_confirmation(in_memory_uow):
    _, run, _, health = _auth_waiting_n01(in_memory_uow)
    service = ControlPlaneService(in_memory_uow)
    missing = OperatorActionRequest(
        action_request_id="auth-confirmation-missing",
        project_id=run.project_id,
        change_name=run.change_name,
        run_id=run.run_id,
        action_type=OperatorActionType.CONTINUE,
        parameters={"force": True},
    )
    stale = OperatorActionRequest(
        action_request_id="auth-confirmation-stale",
        project_id=run.project_id,
        change_name=run.change_name,
        run_id=run.run_id,
        action_type=OperatorActionType.CONTINUE,
        parameters={
            "provider_reauthentication_confirmed": True,
            "expected_provider_health_updated_at": "2026-01-01T00:00:00+00:00",
        },
    )
    forced = OperatorActionRequest(
        action_request_id="auth-confirmation-generic-force",
        project_id=run.project_id,
        change_name=run.change_name,
        run_id=run.run_id,
        action_type=OperatorActionType.CONTINUE,
        expected_stage=run.current_stage,
        expected_generation=run.current_generation,
        parameters={
            "provider_reauthentication_confirmed": True,
            "expected_provider_health_updated_at": health.updated_at.isoformat(),
            "force": True,
        },
    )

    assert service.execute_action(missing).status == OperatorActionStatus.REJECTED
    assert service.execute_action(stale).status == OperatorActionStatus.REJECTED
    assert service.execute_action(forced).status == OperatorActionStatus.REJECTED
    assert health.status == ProviderHealthStatus.AUTH_REQUIRED
    assert (
        in_memory_uow.orchestration_runs.get_by_id(run.run_id).stop_outcome
        == OrchestrationStopOutcome.WAITING_CAPACITY
    )
    assert in_memory_uow.jobs.get_by_id(run.active_job_id).attempt_count == 4


def test_auth_recovery_requires_matching_waiting_job_and_no_candidate(in_memory_uow):
    _, run, job, health = _auth_waiting_n01(in_memory_uow)
    job.waiting_provider = "antigravity"
    in_memory_uow.jobs.save(job)

    assert (
        ControlPlaneService(in_memory_uow)._auth_recovery_state(
            run, in_memory_uow.projects.get_by_id(run.project_id)
        )
        is None
    )

    job.waiting_provider = "codex"
    job.candidate_sha = "unexpected-candidate"
    in_memory_uow.jobs.save(job)
    assert (
        ControlPlaneService(in_memory_uow)._auth_recovery_state(
            run, in_memory_uow.projects.get_by_id(run.project_id)
        )
        is None
    )
    assert health.status == ProviderHealthStatus.AUTH_REQUIRED


def test_auth_recovery_accepts_existing_drain_ineligible_capacity_projection(in_memory_uow):
    _, run, job, _ = _auth_waiting_n01(in_memory_uow)
    job.waiting_provider = "openrouter"
    job.capacity_block_reason = "OpenRouter fallback ineligible: Scheduler is not in DRAIN mode."
    in_memory_uow.jobs.save(job)

    state = ControlPlaneService(in_memory_uow)._auth_recovery_state(
        run, in_memory_uow.projects.get_by_id(run.project_id)
    )
    assert state == {
        "provider": "codex",
        "health_updated_at": in_memory_uow.provider_health.get_by_provider(
            "codex"
        ).updated_at.isoformat(),
    }


def test_fenced_recovery_authorization_is_bound_and_single_use(in_memory_uow):
    project, run, job, health = _auth_waiting_n01(in_memory_uow)
    from minime.services.recovery_convergence_service import RecoveryConvergenceService

    authorization = {
        "action_request_id": "auth-single-use-1",
        "action_type": "CONTINUE",
        "reauthentication_confirmed": True,
        "provider": "codex",
        "expected_health_updated_at": health.updated_at.isoformat(),
        "project_id": project.project_id,
        "change_name": run.change_name,
        "run_id": run.run_id,
        "job_id": job.job_id,
        "generation": run.current_generation,
    }
    claim = RecoveryClaimContext(
        claim_key=f"run:{run.run_id}",
        owner_instance_id="test-owner",
        fence_token=7,
        lease_expires_at=utc_now() + timedelta(minutes=1),
    )
    service = RecoveryConvergenceService(in_memory_uow)

    assert (
        service._validate_auth_recovery_authorization(
            run, RecoverySource.CONTROL_PLANE, claim, authorization
        )
        is True
    )

    prior = RecoveryDecision(
        cycle_id="prior-auth-cycle",
        claim_key=claim.claim_key,
        identity_type="RUN",
        identity_id=run.run_id,
        project_id=run.project_id,
        change_name=run.change_name,
        source=RecoverySource.CONTROL_PLANE,
        fence_token=claim.fence_token,
        classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
        planned_action="DRIVE_CONTINUATION",
        status=RecoveryDecisionStatus.COMPLETED,
        observation_refs={"provider_auth_recovery": authorization},
    )
    in_memory_uow.recovery_decisions.create_decision(prior)
    assert (
        service._validate_auth_recovery_authorization(
            run, RecoverySource.CONTROL_PLANE, claim, authorization
        )
        is False
    )


def test_active_waiting_capacity_reconciles_under_claim_without_force(in_memory_uow, monkeypatch):
    project, run, job, health = _auth_waiting_n01(in_memory_uow)
    from minime.services.recovery_convergence_service import RecoveryConvergenceService

    authorization = {
        "action_request_id": "auth-recovery-claimed-request",
        "action_type": "CONTINUE",
        "reauthentication_confirmed": True,
        "provider": "codex",
        "expected_health_updated_at": health.updated_at.isoformat(),
        "project_id": project.project_id,
        "change_name": run.change_name,
        "run_id": run.run_id,
        "job_id": job.job_id,
        "generation": run.current_generation,
    }
    captured = {}

    class ResumeHarness:
        def __init__(self, uow, project_root):
            del uow, project_root

        def resume(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("minime.services.orchestration_service.OrchestrationService", ResumeHarness)
    decision = RecoveryConvergenceService(in_memory_uow).request_run_continuation(
        run.run_id,
        source=RecoverySource.CONTROL_PLANE,
        force=False,
        auth_recovery_authorization=authorization,
        drive_admitted=True,
    )

    assert decision.status == RecoveryDecisionStatus.BLOCKED
    assert decision.reason_code == "AUTH_RECOVERY_FAILED_BEFORE_DISPATCH"
    assert decision.observation_refs["provider_auth_recovery"] == authorization
    assert captured["force"] is False
    assert captured["auth_recovery_decision_id"] == decision.decision_id
    assert in_memory_uow.orchestration_runs.get_by_id(run.run_id).is_active is True
    assert (
        in_memory_uow.orchestration_runs.get_by_id(run.run_id).stop_outcome
        == OrchestrationStopOutcome.WAITING_CAPACITY
    )
    assert in_memory_uow.jobs.get_by_id(job.job_id).status == JobStatus.WAITING_CAPACITY
    assert in_memory_uow.job_attempts.list_by_job(job.job_id) == []
    assert (
        in_memory_uow.provider_health.get_by_provider("codex").status
        == ProviderHealthStatus.AUTH_REQUIRED
    )


def test_execution_dispatch_validates_durable_decision_and_consumes_action_id(in_memory_uow):
    from minime.services.execution_pipeline import ExecutionPipelineService

    project, run, job, health = _auth_waiting_n01(in_memory_uow)
    run.stop_outcome = None
    in_memory_uow.orchestration_runs.save(run)
    refs = {
        "action_request_id": "auth-single-use-pipeline",
        "action_type": "CONTINUE",
        "reauthentication_confirmed": True,
        "provider": "codex",
        "expected_health_updated_at": health.updated_at.isoformat(),
        "project_id": project.project_id,
        "change_name": run.change_name,
        "run_id": run.run_id,
        "job_id": job.job_id,
        "generation": run.current_generation,
    }
    claim = RecoveryClaimContext(
        claim_key=f"run:{run.run_id}",
        owner_instance_id="pipeline-owner",
        fence_token=9,
        lease_expires_at=utc_now() + timedelta(minutes=1),
    )
    decision = RecoveryDecision(
        cycle_id="auth-pipeline-cycle",
        claim_key=claim.claim_key,
        identity_type="RUN",
        identity_id=run.run_id,
        project_id=run.project_id,
        change_name=run.change_name,
        source=RecoverySource.CONTROL_PLANE,
        fence_token=claim.fence_token,
        classification=RecoveryClassification.RESUME_SAFE_CHECKPOINT,
        planned_action="DRIVE_AUTH_RECOVERY_CONTINUATION",
        status=RecoveryDecisionStatus.EXECUTING,
        observation_refs={"provider_auth_recovery": refs},
    )
    in_memory_uow.recovery_decisions.create_decision(decision)
    service = object.__new__(ExecutionPipelineService)
    service.uow = in_memory_uow
    service.health_service = ControlPlaneService(in_memory_uow).provider_health_service

    assert (
        service._validate_auth_recovery_dispatch(
            decision_id=decision.decision_id,
            run=run,
            job=job,
            project=project,
            current_executor="codex",
            claim_context=claim,
            attempts=[],
        )
        == refs
    )

    consumed = JobAttempt(
        job_id=job.job_id,
        attempt_number=5,
        executor_role="codex",
        model_identity="codex",
        normalized_outcome=ExecutionOutcome.AUTH_REQUIRED,
        error_details={"provider_auth_recovery": refs},
    )
    with pytest.raises(RuntimeError, match="already consumed"):
        service._validate_auth_recovery_dispatch(
            decision_id=decision.decision_id,
            run=run,
            job=job,
            project=project,
            current_executor="codex",
            claim_context=claim,
            attempts=[consumed],
        )
