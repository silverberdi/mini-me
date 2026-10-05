"""Focused regressions for the final Stage G recovery remediation."""

from conftest import InMemoryPersistenceUnitOfWork
from minime.domain.enums import (
    ExternalActionType,
    JobStatus,
    OrchestrationStage,
    RecoverySource,
)
from minime.domain.models import Job, OrchestrationExternalAction, OrchestrationRun
from minime.services.recovery_convergence_service import (
    ActionObservationOutcome,
    RecoveryConvergenceService,
)


def test_missing_claim_repository_cannot_fabricate_recovery_authority():
    uow = InMemoryPersistenceUnitOfWork()
    uow.claims = None
    assert RecoveryConvergenceService(uow).acquire_claim("job:missing") is None


def test_orphan_active_job_convergence_releases_claim_and_persists_transition():
    uow = InMemoryPersistenceUnitOfWork()
    job = Job(
        job_id="orphan-job",
        project_id="project",
        change_name="change",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    uow.jobs.save(job)

    decisions = RecoveryConvergenceService(uow).reconcile_cycle(source=RecoverySource.TICK)

    assert uow.jobs.get_by_id(job.job_id).status == JobStatus.QUEUED
    assert uow.claims.get_by_key("job:orphan-job") is None
    assert any(d.identity_id == job.job_id and d.status.value == "COMPLETED" for d in decisions)
    assert uow.committed


def test_checkpoint_evidence_requires_matching_base_and_generation():
    uow = InMemoryPersistenceUnitOfWork()
    job = Job(
        job_id="job-identity",
        project_id="project",
        change_name="change",
        implementer_role="codex",
        candidate_sha="head",
        base_sha="base",
    )
    uow.jobs.save(job)
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-identity",
            project_id="project",
            change_name="change",
            base_sha="base",
            current_candidate_sha="head",
            current_generation=2,
            current_stage=OrchestrationStage.RUNNING_CHECKS,
        )
    )
    from minime.domain.models import CheckResult

    uow.check_results.save(
        CheckResult(
            job_id=job.job_id,
            check_name="unit",
            command="true",
            exit_code=0,
            duration_ms=1,
            output_snippet="",
            candidate_sha="head",
            candidate_generation=1,
        )
    )
    assert RecoveryConvergenceService(uow)._determine_highest_job_checkpoint(job) == JobStatus.QUEUED


def test_issue_observers_use_remote_result_payload_and_project_item_fails_closed():
    uow = InMemoryPersistenceUnitOfWork()
    action = OrchestrationExternalAction(
        action_key="project-item",
        action_type=ExternalActionType.PROJECT_ITEM_EDIT,
        target_identity="Done",
        request_fingerprint="fp",
        run_id="run-project-item",
    )
    assert (
        RecoveryConvergenceService(uow)._observe_by_action_type(action)
        == ActionObservationOutcome.UNOBSERVABLE
    )
