from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from minime.adapters import provider_adapter
from minime.adapters.provider_adapter import DeepSeekProviderAdapter
from minime.api import app as api_module
from minime.config import AppConfig, ProviderConfig
from minime.db.models import ProviderModelRegistryModel
from minime.db.repository import PostgresPersistenceUnitOfWork


@pytest.fixture
def provider_http_server():
    state = {
        "status": 200,
        "body": {"message": "provider-body-secret"},
        "delay": 0.0,
        "requests": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"].append(
                {
                    "method": self.command,
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                }
            )
            if state["delay"]:
                time.sleep(state["delay"])
            body = json.dumps(state["body"]).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


@pytest.fixture
def diagnostic_api(provider_http_server, monkeypatch, tmp_path):
    base_url, provider_state = provider_http_server
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'provider-diagnostic.db'}",
        connect_args={"check_same_thread": False},
    )
    ProviderModelRegistryModel.__table__.create(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add_all(
            [
                ProviderModelRegistryModel(
                    id=provider_id,
                    provider_id=provider_id,
                    harness_id="direct",
                    canonical_model_id=f"{provider_id}-model",
                    origin="static",
                    capabilities={"workflow": True},
                    discovery_status="available",
                    diagnostic_code="before-test",
                    diagnostic_summary="unchanged prior observation",
                    is_enabled=True,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                for provider_id in ("openrouter", "unsupported", "unconfigured")
            ]
        )
        session.commit()

    config = AppConfig(
        providers={
            "openrouter": ProviderConfig(
                type="openai-compatible",
                enabled=True,
                base_url=base_url,
                api_key_env="OPENROUTER_TEST_API_KEY",
            ),
            "unsupported": ProviderConfig(type="unknown-provider", enabled=True),
        }
    )

    def override_uow():
        session = Session(engine)
        try:
            yield PostgresPersistenceUnitOfWork(session)
        finally:
            session.close()

    prior_adapters = dict(provider_adapter._ADAPTER_REGISTRY)
    provider_adapter._ADAPTER_REGISTRY.clear()
    api_module.app.dependency_overrides[api_module.get_uow] = override_uow
    api_module.app.dependency_overrides[api_module.get_current_operator] = lambda: object()
    monkeypatch.setattr(api_module, "load_config", lambda: config)
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "false")
    monkeypatch.setenv("OPENROUTER_TEST_API_KEY", "diagnostic-test-token")
    with TestClient(api_module.app) as client:
        yield SimpleNamespace(
            client=client,
            engine=engine,
            state=provider_state,
            config=config,
        )
    api_module.app.dependency_overrides.pop(api_module.get_uow, None)
    api_module.app.dependency_overrides.pop(api_module.get_current_operator, None)
    provider_adapter._ADAPTER_REGISTRY.clear()
    provider_adapter._ADAPTER_REGISTRY.update(prior_adapters)
    engine.dispose()


def test_authenticated_provider_diagnostic_e2e_over_local_http_fixture(
    diagnostic_api,
):
    before = _registry_snapshot(diagnostic_api.engine)

    response = diagnostic_api.client.post("/api/v1/admin/providers/openrouter/test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openrouter"
    assert payload["status"] == "success"
    assert payload["code"] == "credentials_accepted"
    assert payload["latency_ms"] >= 0
    assert "diagnostic-test-token" not in response.text
    assert "provider-body-secret" not in response.text
    assert diagnostic_api.state["requests"] == [
        {
            "method": "GET",
            "path": "/models",
            "authorization": "Bearer diagnostic-test-token",
        }
    ]
    assert _registry_snapshot(diagnostic_api.engine) == before


def test_provider_rejection_is_sanitized_and_does_not_read_or_return_body(
    diagnostic_api,
):
    diagnostic_api.state["status"] = 401
    diagnostic_api.state["body"] = {
        "error": "invalid credential diagnostic-test-token provider-body-secret"
    }

    response = diagnostic_api.client.post("/api/v1/admin/providers/openrouter/test")

    assert response.status_code == 200
    assert response.json()["status"] == "failure"
    assert response.json()["code"] == "credentials_rejected"
    assert response.json()["detail"] == "The provider rejected the configured credentials."
    assert "diagnostic-test-token" not in response.text
    assert "provider-body-secret" not in response.text


def test_provider_timeout_is_reported_with_safe_diagnostic_code(
    diagnostic_api, monkeypatch
):
    diagnostic_api.state["delay"] = 0.2
    monkeypatch.setattr(provider_adapter, "PROVIDER_DIAGNOSTIC_TIMEOUT_SECONDS", 0.02)

    response = diagnostic_api.client.post("/api/v1/admin/providers/openrouter/test")

    assert response.status_code == 200
    assert response.json()["status"] == "failure"
    assert response.json()["code"] == "provider_timeout"
    assert "diagnostic-test-token" not in response.text


def test_transport_failure_is_reported_without_exception_text(diagnostic_api):
    diagnostic_api.config.providers["openrouter"].base_url = "http://127.0.0.1:1"

    response = diagnostic_api.client.post("/api/v1/admin/providers/openrouter/test")

    assert response.status_code == 200
    assert response.json()["status"] == "failure"
    assert response.json()["code"] == "provider_unreachable"
    assert "diagnostic-test-token" not in response.text


def test_missing_credentials_are_unavailable_without_provider_io(
    diagnostic_api, monkeypatch
):
    monkeypatch.delenv("OPENROUTER_TEST_API_KEY")

    response = diagnostic_api.client.post("/api/v1/admin/providers/openrouter/test")

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["code"] == "credentials_not_configured"
    assert diagnostic_api.state["requests"] == []


def test_provider_without_supported_adapter_reports_unavailable_without_io(
    diagnostic_api,
):
    response = diagnostic_api.client.post("/api/v1/admin/providers/unsupported/test")

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["code"] == "diagnostic_unsupported"
    assert response.json()["latency_ms"] is None
    assert diagnostic_api.state["requests"] == []


@pytest.mark.parametrize("provider", ["missing", "unconfigured"])
def test_unknown_or_unconfigured_provider_is_rejected_without_io(
    diagnostic_api, provider
):
    response = diagnostic_api.client.post(f"/api/v1/admin/providers/{provider}/test")

    assert response.status_code == 404
    assert diagnostic_api.state["requests"] == []


def test_connection_diagnostic_requires_an_authorized_operator(diagnostic_api):
    api_module.app.dependency_overrides.pop(api_module.get_current_operator, None)
    try:
        response = diagnostic_api.client.post("/api/v1/admin/providers/openrouter/test")
    finally:
        api_module.app.dependency_overrides[api_module.get_current_operator] = lambda: object()

    assert response.status_code == 401
    assert diagnostic_api.state["requests"] == []


@pytest.mark.asyncio
async def test_deepseek_diagnostic_uses_only_models_endpoint_and_never_returns_body(
    monkeypatch,
):
    requests = []
    transport = httpx.MockTransport(
        lambda request: requests.append(request)
        or httpx.Response(200, json={"secret": "body-secret"})
    )
    real_async_client = httpx.AsyncClient

    def test_client(**kwargs):
        return real_async_client(transport=transport, **kwargs)

    monkeypatch.setattr(provider_adapter.httpx, "AsyncClient", test_client)
    monkeypatch.setenv("DEEPSEEK_DIAGNOSTIC_TEST_KEY", "deepseek-test-token")
    diagnostic = await DeepSeekProviderAdapter(
        api_key_env="DEEPSEEK_DIAGNOSTIC_TEST_KEY"
    ).diagnose_connection()

    assert diagnostic.status == "success"
    assert diagnostic.code == "credentials_accepted"
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/models"
    assert requests[0].headers["Authorization"] == "Bearer deepseek-test-token"
    assert "body-secret" not in diagnostic.detail


def _registry_snapshot(engine):
    with Session(engine) as session:
        rows = session.scalars(
            select(ProviderModelRegistryModel).order_by(ProviderModelRegistryModel.id)
        ).all()
        return [
            (
                row.id,
                row.provider_id,
                row.discovery_status,
                row.diagnostic_code,
                row.diagnostic_summary,
                row.is_enabled,
                row.version,
            )
            for row in rows
        ]
