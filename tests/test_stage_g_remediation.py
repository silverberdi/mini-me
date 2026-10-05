"""Focused regressions for the final Stage G recovery remediation."""

import time

from conftest import InMemoryPersistenceUnitOfWork
from minime.domain.enums import (
    ExternalActionType,
    ExternalOutcome,
    ExternalReasonCode,
    JobStatus,
    OrchestrationStage,
    RecoverySource,
)
from minime.domain.models import (
    ExternalActionResult,
    Job,
    OrchestrationExternalAction,
    OrchestrationRun,
    Project,
    ProjectBinding,
    RecoveryClaimContext,
    utc_now,
)
from minime.services.recovery_convergence_service import (
    ActionObservationOutcome,
    OperationalHeartbeat,
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


def test_issue_observers_fail_closed_except_for_authoritative_not_found():
    uow = InMemoryPersistenceUnitOfWork()
    uow.projects.save(Project(project_id="p", display_name="p", repository="owner/repo"))
    uow.bindings.save(
        ProjectBinding(
            project_id="p", repository="owner/repo", openspec_change_name="change", github_issue_number=7
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(run_id="run", project_id="p", change_name="change", base_sha="base")
    )
    action = OrchestrationExternalAction(
        action_key="issue", action_type=ExternalActionType.ISSUE_CREATE, target_identity="change",
        request_fingerprint="fp", run_id="run",
    )

    class Adapter:
        result: ExternalActionResult[dict]

        def get_issue(self, repository, issue_number):
            return self.result

    adapter = Adapter()
    adapter.result = ExternalActionResult(
        outcome=ExternalOutcome.FAILURE, source_adapter="test", reason_code=ExternalReasonCode.TIMEOUT
    )
    service = RecoveryConvergenceService(uow, github_adapter=adapter)
    assert service._observe_by_action_type(action) == ActionObservationOutcome.UNOBSERVABLE
    adapter.result = ExternalActionResult(
        outcome=ExternalOutcome.FAILURE, source_adapter="test", reason_code=ExternalReasonCode.NOT_FOUND
    )
    assert service._observe_by_action_type(action) == ActionObservationOutcome.OBSERVED_ABSENT


def test_issue_close_without_remote_issue_identity_is_unobservable():
    uow = InMemoryPersistenceUnitOfWork()
    uow.projects.save(Project(project_id="p", display_name="p", repository="owner/repo"))
    uow.bindings.save(ProjectBinding(project_id="p", repository="owner/repo", openspec_change_name="change"))
    uow.orchestration_runs.save(OrchestrationRun(run_id="run", project_id="p", change_name="change", base_sha="base"))
    action = OrchestrationExternalAction(
        action_key="close", action_type=ExternalActionType.ISSUE_CLOSE, target_identity="change",
        request_fingerprint="fp", run_id="run",
    )
    assert RecoveryConvergenceService(uow)._observe_by_action_type(action) == ActionObservationOutcome.UNOBSERVABLE


def test_heartbeat_exception_marks_worker_stale():
    context = RecoveryClaimContext(
        claim_key="run:heartbeat", owner_instance_id="owner", fence_token=1,
        lease_expires_at=utc_now(),
    )

    def fail_renewal(context, lease):
        raise RuntimeError("database unavailable")

    heartbeat = OperationalHeartbeat(claim_context=context, interval_seconds=0.01, renew_claim=fail_renewal)
    with heartbeat:
        time.sleep(0.03)
    assert heartbeat.heartbeat_failed is True
