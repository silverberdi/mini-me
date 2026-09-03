"""Tests for status observability, FastAPI endpoints, and CLI interface."""

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
    OrchestrationExternalAction,
    OrchestrationRun,
    Project,
    Review,
)
from minime.services.status_service import StatusService

runner = CliRunner()


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
    assert res.status_code == 201
    assert res.json()["project_id"] == "test-api-proj"
    assert res.json()["repository"] == "org/api-test"

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
    assert res.status_code == 200

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
    assert res.status_code == 200
    assert res.json()[0]["job_id"] == "job-1"
    assert res.json()[0]["checks"][0]["check_name"] == "pytest"

    res = client.get("/jobs/job-1")
    assert res.status_code == 200
    assert res.json()["candidate_sha"] == "abc123"

    res = client.get("/jobs/job-1/logs")
    assert res.status_code == 200
    assert res.json()[0]["message"] == "ok"

    app.dependency_overrides.clear()


def test_cli_help():
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    assert "mini me" in result.stdout
    assert "status" in result.stdout
    assert "project" in result.stdout
    assert "discover" in result.stdout
    assert "readiness" in result.stdout
    assert "run" in result.stdout
    assert "jobs" in result.stdout
