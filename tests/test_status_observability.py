"""Tests for status observability, FastAPI endpoints, and CLI interface."""

import platform
import sys
from datetime import timedelta

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from conftest import create_isolated_openspec_change
from minime.api.app import app, get_uow
from minime.cli.main import app as cli_app
from minime.domain.enums import (
    AuditRiskLevel,
    AuditStatus,
    ExternalActionStatus,
    ExternalActionType,
    JobStatus,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.models import (
    AuditRecord,
    Change,
    CheckResult,
    Job,
    JobLog,
    OperatorActionRecord,
    OrchestrationExternalAction,
    OrchestrationRun,
    Project,
    Review,
    utc_now,
)
from minime.services.status_service import StatusService

runner = CliRunner()


def test_runtime_environment_diagnostic_reports_standalone_runtime(in_memory_uow, monkeypatch):
    monkeypatch.setattr("minime.services.status_service.os.path.exists", lambda path: False)

    diagnostic = StatusService(in_memory_uow).get_runtime_environment_diagnostic()

    assert diagnostic == {
        "platform": sys.platform,
        "python_version": platform.python_version(),
        "runtime_mode": "standalone",
        "database_engine": "PostgreSQL",
    }


def test_runtime_environment_diagnostic_reports_server_runtime(in_memory_uow, monkeypatch):
    checked_paths = []
    monkeypatch.setattr(
        "minime.services.status_service.os.path.exists",
        lambda path: checked_paths.append(path) or True,
    )

    diagnostic = StatusService(in_memory_uow).get_runtime_environment_diagnostic()

    assert diagnostic["runtime_mode"] == "server"
    assert checked_paths == ["/etc/minime"]


def test_system_status_includes_runtime_environment(in_memory_uow, monkeypatch):
    service = StatusService(in_memory_uow)
    expected = {
        "platform": "test-platform",
        "python_version": "3.14.5",
        "runtime_mode": "server",
        "database_engine": "PostgreSQL",
    }
    monkeypatch.setattr(service, "get_runtime_environment_diagnostic", lambda: expected)

    assert service.get_system_status()["runtime_environment"] == expected


def test_status_service(in_memory_uow):
    service = StatusService(in_memory_uow)

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        change_id="c-001",
        project_id="mini-me",
        name="synthetic-change",
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    status_data = service.get_system_status()
    assert status_data["projects_count"] == 1
    assert status_data["projects"][0]["project_id"] == "mini-me"
    assert status_data["projects"][0]["changes"][0]["name"] == "synthetic-change"
    assert status_data["projects"][0]["changes"][0]["readiness"] == "READY"


def test_pipeline_diagnostic_returns_run_snapshot(in_memory_uow):
    run = OrchestrationRun(
        run_id="run-1",
        project_id="mini-me",
        change_name="diagnostic-change",
        base_sha="base-sha",
        current_stage=OrchestrationStage.PR_PREPARED,
        active_job_id="job-1",
        current_candidate_sha="candidate-sha",
    )
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.jobs.save(
        Job(
            job_id="job-1",
            project_id="mini-me",
            change_name="diagnostic-change",
            implementer_role="codex",
            candidate_sha="candidate-sha",
        )
    )
    in_memory_uow.reviews.save(
        Review(
            job_id="job-1",
            project_id="mini-me",
            change_name="diagnostic-change",
            reviewer_role="antigravity",
            candidate_sha="candidate-sha",
            base_sha="base-sha",
            status=ReviewStatus.REVIEW_COMPLETED,
            verdict=ReviewVerdict.READY_TO_MERGE,
        )
    )
    in_memory_uow.audits.save(
        AuditRecord(
            job_id="job-1",
            project_id="mini-me",
            change_name="diagnostic-change",
            candidate_sha="candidate-sha",
            base_sha="base-sha",
            status=AuditStatus.AUDIT_COMPLETED,
            risk=AuditRiskLevel.LOW,
        )
    )
    in_memory_uow.orchestration_external_actions.reserve(
        OrchestrationExternalAction(
            run_id="run-1",
            action_key="pr-create-1",
            action_type=ExternalActionType.PR_CREATE,
            target_identity="silverberdi/mini-me",
            request_fingerprint="fingerprint",
            candidate_sha="candidate-sha",
            generation=1,
            status=ExternalActionStatus.COMPLETED,
            result_payload={"pr_url": "https://github.com/silverberdi/mini-me/pull/1"},
        )
    )

    diagnostic = StatusService(in_memory_uow).get_pipeline_diagnostic("run-1")

    assert diagnostic == {
        "run_id": "run-1",
        "project_id": "mini-me",
        "change_name": "diagnostic-change",
        "stage": "PR_PREPARED",
        "candidate_sha": "candidate-sha",
        "pr_url": "https://github.com/silverberdi/mini-me/pull/1",
        "review_verdict": "READY_TO_MERGE",
        "audit_risk": "low",
    }


def test_pipeline_diagnostic_returns_none_for_unknown_run(in_memory_uow):
    assert StatusService(in_memory_uow).get_pipeline_diagnostic("unknown-run-id") is None


def test_fastapi_endpoints(in_memory_uow, tmp_path):
    create_isolated_openspec_change(tmp_path, "synthetic-change")

    # Override get_uow dependency with in_memory_uow
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    # Health
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["version"] == "0.1.0"

    # Register project
    payload = {
        "project_id": "test-api-proj",
        "display_name": "API Test Project",
        "repository": "https://github.com/org/api-test.git",
        "base_branch": "main",
        "implementer": "codex",
        "reviewer": "antigravity",
    }
    res = client.post("/projects", json=payload)
    assert res.status_code == 410
    assert res.json()["detail"]["code"] == "operation_unavailable"
    assert in_memory_uow.projects.get_by_id("test-api-proj") is None

    in_memory_uow.projects.save(
        Project(
            project_id="test-api-proj",
            display_name="API Test Project",
            repository="org/api-test",
        )
    )

    # List projects
    res = client.get("/projects")
    assert res.status_code == 200
    assert len(res.json()) >= 1

    # Get project by ID
    res = client.get("/projects/test-api-proj")
    assert res.status_code == 200
    assert res.json()["display_name"] == "API Test Project"

    # Discover changes
    res = client.post(f"/projects/test-api-proj/discover?project_root={tmp_path}")
    assert res.status_code == 410
    assert res.json()["code"] == "operation_unavailable"

    # Clean up dependency override
    app.dependency_overrides.clear()


def test_fastapi_job_observability_endpoints(in_memory_uow):
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    job = Job(
        job_id="job-1",
        project_id="mini-me",
        change_name="synthetic-job-change",
        implementer_role="codex",
        candidate_sha="abc123",
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.job_logs.save(JobLog(job_id="job-1", stream="stdout", message="ok"))
    in_memory_uow.check_results.save(
        CheckResult(
            job_id="job-1",
            check_name="pytest",
            command="pytest",
            exit_code=0,
            duration_ms=12,
            output_snippet="passed",
        )
    )

    res = client.get("/projects/mini-me/jobs")
    assert res.status_code == 410
    assert res.json()["code"] == "operation_unavailable"

    res = client.get("/jobs/job-1")
    assert res.status_code == 410
    assert res.json()["code"] == "operation_unavailable"

    res = client.get("/jobs/job-1/logs")
    assert res.status_code == 410
    assert res.json()["code"] == "operation_unavailable"

    app.dependency_overrides.clear()


def test_job_projection_separates_current_check_batch_from_history(in_memory_uow):
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)
    project = Project(
        project_id="checks-projection-project",
        display_name="Checks projection",
        repository="org/checks-projection",
        checks=[{"name": "pytest", "command": "pytest -q"}],
    )
    job = Job(
        job_id="checks-projection-job",
        project_id=project.project_id,
        change_name="checks-projection-change",
        implementer_role="codex",
        status=JobStatus.CHECKS_PASSED,
        candidate_sha="candidate-sha",
    )
    run = OrchestrationRun(
        run_id="checks-projection-run",
        project_id=project.project_id,
        change_name=job.change_name,
        base_sha="base-sha",
        active_job_id=job.job_id,
        current_generation=2,
        current_candidate_sha=job.candidate_sha,
        stop_details={"code": "CODE_REVIEW_COMPLETED_REQUIRES_SEPARATE_AUTHORIZED_CONTINUATION"},
    )
    now = utc_now()
    old_failed = CheckResult(
        job_id=job.job_id,
        check_name="pytest",
        command="pytest -q",
        exit_code=1,
        duration_ms=5,
        output_snippet="historical failure",
        candidate_sha=job.candidate_sha,
        candidate_generation=2,
        created_at=now - timedelta(minutes=1),
    )
    latest_passed = CheckResult(
        job_id=job.job_id,
        check_name="pytest",
        command="pytest -q",
        exit_code=0,
        duration_ms=5,
        output_snippet="passed",
        candidate_sha=job.candidate_sha,
        candidate_generation=2,
        created_at=now,
    )
    review_id = "checks-projection-review"
    authorization_id = "checks-projection-authorization"
    review = Review(
        review_id=review_id,
        job_id=job.job_id,
        project_id=project.project_id,
        change_name=job.change_name,
        reviewer_role="deepseek",
        reviewer_model="deepseek-flash",
        review_stage="CODE_REVIEW",
        provider="deepseek",
        account_fingerprint="account-fingerprint",
        budget_authorization_id=authorization_id,
        orchestration_run_id=run.run_id,
        candidate_generation=2,
        candidate_sha=job.candidate_sha,
        base_sha=run.base_sha,
        manifest_id="manifest-id",
        manifest_hash="manifest-hash",
        status=ReviewStatus.REVIEW_COMPLETED,
        verdict=ReviewVerdict.READY_TO_MERGE,
    )
    authorization = OperatorActionRecord(
        action_request_id=authorization_id,
        project_id=project.project_id,
        change_name=job.change_name,
        run_id=run.run_id,
        job_id=job.job_id,
        action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_CODE_REVIEW,
        status=OperatorActionStatus.COMPLETED,
    )
    dispatch_key = f"deepseek-code-review:{authorization_id}"
    dispatch = OrchestrationExternalAction(
        run_id=run.run_id,
        action_key=dispatch_key,
        action_type=ExternalActionType.DEEPSEEK_CODE_REVIEW_DISPATCH,
        target_identity="deepseek:account-fingerprint:deepseek-flash:REVIEW",
        request_fingerprint="dispatch-fingerprint",
        candidate_sha=job.candidate_sha,
        generation=2,
        status=ExternalActionStatus.COMPLETED,
        remote_identifier=review_id,
        last_dispatch_intent_id="durable-dispatch-intent",
    )
    in_memory_uow.projects.save(project)
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.check_results.save(old_failed)
    in_memory_uow.check_results.save(latest_passed)
    in_memory_uow.reviews.save(review)
    in_memory_uow.operator_actions.save(authorization)
    in_memory_uow.orchestration_external_actions.reserve(dispatch)

    response = client.get(f"/jobs/{job.job_id}")
    assert response.status_code == 410
    assert response.json()["code"] == "operation_unavailable"
    app.dependency_overrides.clear()


def test_cli_help():
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    assert "mini me" in result.stdout
    assert "status" in result.stdout
    assert "project" in result.stdout
    assert "serve" in result.stdout
