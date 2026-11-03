"""Unit tests for scheduler status, provider health API endpoints, and CLI commands."""

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from minime.api.app import app, get_uow
from minime.cli.main import app as cli_app
from minime.domain.enums import ProviderHealthStatus, ProviderResultClass
from minime.domain.models import NormalizedProviderResult
from minime.services.provider_health_service import ProviderHealthService

runner = CliRunner()




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




