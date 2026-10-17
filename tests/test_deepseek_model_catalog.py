"""Contract tests for the documented, non-inferential DeepSeek model catalog."""

from __future__ import annotations

import json

import httpx
import pytest

from minime.adapters import provider_adapter
from minime.adapters.provider_adapter import DeepSeekProviderAdapter
from minime.services.contract_review_service import DeepSeekContractReviewRunner


def _install_models_response(monkeypatch, handler):
    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def mocked_client(*, base_url, timeout):
        return real_async_client(base_url=base_url, timeout=timeout, transport=transport)

    monkeypatch.setattr(provider_adapter.httpx, "AsyncClient", mocked_client)


@pytest.mark.asyncio
async def test_deepseek_adapter_accepts_effort_from_official_models_schema(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-account-key")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {
                        "id": "deepseek-flash",
                        "object": "model",
                        "owned_by": "deepseek",
                        "context_window": 128000,
                        "max_output_tokens": 8192,
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                        "effort": {
                            "supported_levels": ["low", "high", "max"],
                            "default_level": "high",
                        },
                    }
                ],
            },
            request=request,
        )

    _install_models_response(monkeypatch, handler)
    adapter = DeepSeekProviderAdapter()

    assert await adapter.check_model_supported("deepseek-flash", effort="low") == (True, None)
    assert await adapter.check_model_supported("deepseek-flash", effort="medium") == (
        False,
        "Effort 'medium' is not supported by DeepSeek model 'deepseek-flash'.",
    )
    assert await adapter.check_model_supported("deepseek-chat", effort="low") == (
        False,
        "Model 'deepseek-chat' is absent from the authenticated DeepSeek account catalog.",
    )
    assert len(calls) == 3
    assert all(request.method == "GET" and request.url.path == "/models" for request in calls)
    assert all(request.headers["Authorization"] == "Bearer test-account-key" for request in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload",
    [
        (401, {"error": {"message": "unauthorized"}}),
        (200, {"object": "list", "data": {"id": "deepseek-flash"}}),
        (200, {"object": "list", "data": [{"id": "deepseek-flash", "effort": {}}]}),
    ],
)
async def test_deepseek_adapter_rejects_catalog_errors_or_missing_effort(
    monkeypatch, status, payload
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-account-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, request=request)

    _install_models_response(monkeypatch, handler)
    adapter = DeepSeekProviderAdapter()

    supported, reason = await adapter.check_model_supported("deepseek-flash", effort="low")

    assert supported is False
    assert reason


@pytest.mark.asyncio
async def test_contract_review_runner_sends_documented_reasoning_effort_without_inference():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/chat/completions"
        assert request.read()
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-flash"
        assert payload["reasoning_effort"] == "low"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"verdict":"CONTRACT_ACCEPTED"}'}}],
                "model": "deepseek-flash",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        runner = DeepSeekContractReviewRunner(
            api_key="test-account-key",
            model="deepseek-flash",
            effort="low",
            client=client,
        )
        result = await runner.review('{"stage":"CONTRACT_REVIEW"}', timeout_seconds=5)
    finally:
        await client.aclose()

    assert result.exit_code == 0
    assert result.model == "deepseek-flash"
    assert len(requests) == 1
