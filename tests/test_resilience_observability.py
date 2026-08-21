"""Unit tests for scheduler status, provider health API endpoints, and CLI commands."""

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from minime.api.app import app, get_uow
from minime.cli.main import app as cli_app
from minime.domain.enums import JobStatus, ProviderHealthStatus, ProviderResultClass, SchedulerMode
from minime.domain.models import Job, NormalizedProviderResult, Project, utc_now
from minime.services.provider_health_service import ProviderHealthService

runner = CliRunner()


def test_scheduler_status_api_endpoint(in_memory_uow):
    """Verify GET /scheduler/status returns current scheduler status."""
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    res = client.get("/scheduler/status")
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == SchedulerMode.RUN.value
    assert data["admission_allowed"] is True
    assert data["primary_capacity_available"] is True


def test_providers_health_api_endpoint(in_memory_uow):
    """Verify GET /providers/health returns health for Codex and Antigravity."""
    health_service = ProviderHealthService(in_memory_uow)
    health_service.record_outcome(
        NormalizedProviderResult(
            result_class=ProviderResultClass.QUOTA_LIMIT,
            provider="codex",
            role="implementer",
            summary="Quota exceeded",
        )
    )

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    res = client.get("/providers/health")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2

    codex_data = next(d for d in data if d["provider"] == "codex")
    assert codex_data["status"] == ProviderHealthStatus.EXHAUSTED.value
    assert codex_data["consecutive_failures"] >= 1

    agy_data = next(d for d in data if d["provider"] == "antigravity")
    assert agy_data["status"] == ProviderHealthStatus.AVAILABLE.value


def test_get_job_includes_resilience_fields(in_memory_uow):
    """Verify GET /jobs/{job_id} includes waiting_provider, capacity/recovery reasons and expected_reset_at."""
    reset_time = utc_now()
    job = Job(
        job_id="job-resilience-1",
        project_id="mini-me",
        change_name="005-feature",
        implementer_role="codex",
        status=JobStatus.WAITING_CAPACITY,
        waiting_provider="codex",
        capacity_block_reason="Quota limit exhausted",
        expected_reset_at=reset_time,
    )
    in_memory_uow.jobs.save(job)

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    res = client.get(f"/jobs/{job.job_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == JobStatus.WAITING_CAPACITY.value
    assert data["waiting_provider"] == "codex"
    assert data["capacity_block_reason"] == "Quota limit exhausted"
    assert data["expected_reset_at"] == reset_time.isoformat()


def test_cli_scheduler_and_providers_help():
    """Verify CLI scheduler and providers help subcommands are reachable."""
    res_sched = runner.invoke(cli_app, ["scheduler", "--help"])
    assert res_sched.exit_code == 0
    assert "status" in res_sched.output

    res_prov = runner.invoke(cli_app, ["providers", "--help"])
    assert res_prov.exit_code == 0
    assert "health" in res_prov.output
