from __future__ import annotations

import time

from minime.domain.enums import (
    JobStatus,
    OrchestrationStage,
    RecoveryDecisionStatus,
    RecoverySource,
)
from minime.domain.models import Job, OrchestrationRun
from minime.services.recovery_convergence_service import RecoveryConvergenceService


class _SlowResume:
    def __init__(self, uow):
        self.uow = uow
        self.fence_valid_after_wait = False

    def resume(self, *, run_id, drain_mode, force, claim_context, **kwargs):
        time.sleep(1.25)
        self.fence_valid_after_wait = self.uow.claims.validate_cas(
            claim_key=claim_context.claim_key,
            owner_instance_id=claim_context.owner_instance_id,
            fence_token=claim_context.fence_token,
        )


def _setup_run(uow):
    job = Job(
        job_id="job-recovery-heartbeat",
        project_id="project-recovery-heartbeat",
        change_name="heartbeat-change",
        implementer_role="codex",
        status=JobStatus.CHECKS_FAILED,
        base_sha="base-sha",
    )
    run = OrchestrationRun(
        run_id="run-recovery-heartbeat",
        project_id=job.project_id,
        change_name=job.change_name,
        base_sha=job.base_sha,
        active_job_id=job.job_id,
        current_stage=OrchestrationStage.IMPLEMENTING,
        resumable_stage=OrchestrationStage.IMPLEMENTING,
        is_active=True,
    )
    uow.jobs.save(job)
    uow.orchestration_runs.save(run)
    return run


def test_canonical_run_continuation_renews_claim_during_slow_resume(in_memory_uow):
    _setup_run(in_memory_uow)

    def renew_isolated(claim_context, lease_seconds):
        refreshed = in_memory_uow.claims.acquire_or_reacquire(
            claim_context.claim_key,
            claim_context.owner_instance_id,
            lease_seconds=lease_seconds,
        )
        return bool(refreshed and refreshed.fence_token == claim_context.fence_token)

    # Model the production UoW's isolated-session heartbeat API without
    # changing the legacy in-memory repository fixture.
    in_memory_uow.renew_claim_heartbeat_isolated = renew_isolated
    orchestration = _SlowResume(in_memory_uow)
    service = RecoveryConvergenceService(
        in_memory_uow,
        orchestration_service=orchestration,
        lease_seconds=1,
        heartbeat_seconds=0.2,
    )

    decision = service.request_run_continuation(
        "run-recovery-heartbeat",
        source=RecoverySource.CONTROL_PLANE,
        force=True,
        drive_admitted=True,
    )

    assert orchestration.fence_valid_after_wait
    assert decision.status == RecoveryDecisionStatus.COMPLETED
    claim = in_memory_uow.claims.get_by_key("run:run-recovery-heartbeat")
    assert claim is None or claim.released_at is not None


def test_continuation_persists_bounded_reason_code_for_long_exception(in_memory_uow):
    _setup_run(in_memory_uow)

    class FailingResume:
        def resume(self, **_kwargs):
            raise RuntimeError("provider text " + ("x" * 500))

    service = RecoveryConvergenceService(
        in_memory_uow,
        orchestration_service=FailingResume(),
    )
    decision = service.request_run_continuation(
        "run-recovery-heartbeat",
        source=RecoverySource.CONTROL_PLANE,
        force=True,
        drive_admitted=True,
    )

    assert decision.status == RecoveryDecisionStatus.BLOCKED
    assert decision.reason_code == "CONTINUATION_FAILED_RUNTIMEERROR"
    assert len(decision.reason_code) <= 128
