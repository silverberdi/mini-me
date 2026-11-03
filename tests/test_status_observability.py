"""Tests for status observability, FastAPI endpoints, and CLI interface."""

import platform
import sys
from datetime import timedelta

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from conftest import create_isolated_openspec_change
from minime.api.app import app, get_current_operator, get_uow
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








def test_cli_help():
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    assert "mini me" in result.stdout
    assert "status" in result.stdout
    assert "project" in result.stdout
    assert "serve" in result.stdout
