"""Unit tests for OpenRouterAdapter outcome normalization, routing, snapshot binding, and secret redaction."""

import json
from decimal import Decimal

import httpx
import pytest

from minime.adapters.openrouter_adapter import (
    MockOpenRouterAdapter,
    OpenRouterAdapter,
    OpenRouterRequest,
)
from minime.domain.enums import ProviderResultClass
from minime.domain.models import OpenRouterPricingSnapshot


def _valid_snapshot() -> OpenRouterPricingSnapshot:
    return OpenRouterPricingSnapshot(
        snapshot_id="snap-1",
        canonical_model_identity="anthropic:claude-3.5-sonnet",
        routed_model_identity="anthropic/claude-3.5-sonnet",
        prompt_price_per_token=Decimal("0.000003"),
        output_price_per_token=Decimal("0.000015"),
        additional_cost_per_request=Decimal("0.0"),
    )


@pytest.mark.asyncio
async def test_exact_authorized_route_allows_dispatch():
    snapshot = _valid_snapshot()
    response_payload = {
        "choices": [{"message": {"role": "assistant", "content": "OK"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": "0.000105"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["model"] == "anthropic/claude-3.5-sonnet"
        return httpx.Response(200, json=response_payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterAdapter()
        req = OpenRouterRequest(
            model="anthropic/claude-3.5-sonnet",
            canonical_model_identity="anthropic:claude-3.5-sonnet",
            prompt="hello",
            max_output_tokens=100,
            authorized_max_output_tokens=100,
            api_key="sk-or-test-key-12345",
            pricing_snapshot=snapshot,
            pricing_snapshot_id=snapshot.snapshot_id,
        )
        result, meta = await adapter.execute(req, client=client)

    assert result.result_class == ProviderResultClass.SUCCESS
    assert meta["actual_cost_usd"] == Decimal("0.000105")


@pytest.mark.asyncio
async def test_canonical_model_mismatch_prevents_http_dispatch():
    snapshot = _valid_snapshot()
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterAdapter()
        req = OpenRouterRequest(
            model="anthropic/claude-3.5-sonnet",
            canonical_model_identity="openai:gpt-4o",  # MISMATCH with snapshot
            prompt="hello",
            max_output_tokens=100,
            authorized_max_output_tokens=100,
            api_key="sk-or-test-key-12345",
            pricing_snapshot=snapshot,
            pricing_snapshot_id=snapshot.snapshot_id,
        )
        result, _ = await adapter.execute(req, client=client)

    assert called is False
    assert result.result_class == ProviderResultClass.POLICY_DENIED
    assert "Canonical model identity" in result.summary


@pytest.mark.asyncio
async def test_routed_model_mismatch_prevents_http_dispatch():
    snapshot = _valid_snapshot()
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterAdapter()
        req = OpenRouterRequest(
            model="openai/gpt-4o",  # MISMATCH with snapshot routed_model_identity
            canonical_model_identity="anthropic:claude-3.5-sonnet",
            prompt="hello",
            max_output_tokens=100,
            authorized_max_output_tokens=100,
            api_key="sk-or-test-key-12345",
            pricing_snapshot=snapshot,
            pricing_snapshot_id=snapshot.snapshot_id,
        )
        result, _ = await adapter.execute(req, client=client)

    assert called is False
    assert result.result_class == ProviderResultClass.POLICY_DENIED
    assert "Dispatched model" in result.summary


@pytest.mark.asyncio
async def test_auto_routing_rejected_before_dispatch():
    snapshot = OpenRouterPricingSnapshot(
        snapshot_id="snap-auto",
        canonical_model_identity="openrouter:auto",
        routed_model_identity="openrouter/auto",
        prompt_price_per_token=Decimal("0.000001"),
        output_price_per_token=Decimal("0.000002"),
    )
    adapter = OpenRouterAdapter()
    req = OpenRouterRequest(
        model="openrouter/auto",
        canonical_model_identity="openrouter:auto",
        prompt="hello",
        max_output_tokens=100,
        authorized_max_output_tokens=100,
        api_key="sk-or-test-key-12345",
        pricing_snapshot=snapshot,
        pricing_snapshot_id=snapshot.snapshot_id,
    )
    result, _ = await adapter.execute(req)
    assert result.result_class == ProviderResultClass.POLICY_DENIED
    assert "Auto-routing" in result.summary


@pytest.mark.asyncio
async def test_max_output_tokens_above_authorized_bound_rejected():
    snapshot = _valid_snapshot()
    adapter = OpenRouterAdapter()
    req = OpenRouterRequest(
        model="anthropic/claude-3.5-sonnet",
        canonical_model_identity="anthropic:claude-3.5-sonnet",
        prompt="hello",
        max_output_tokens=2000,  # Exceeds authorized bound 1000
        authorized_max_output_tokens=1000,
        api_key="sk-or-test-key-12345",
        pricing_snapshot=snapshot,
        pricing_snapshot_id=snapshot.snapshot_id,
    )
    result, _ = await adapter.execute(req)
    assert result.result_class == ProviderResultClass.POLICY_DENIED
    assert "exceeds authorized reservation bound" in result.summary


@pytest.mark.asyncio
async def test_missing_pricing_snapshot_binding_rejected():
    adapter = OpenRouterAdapter()
    req = OpenRouterRequest(
        model="anthropic/claude-3.5-sonnet",
        canonical_model_identity="anthropic:claude-3.5-sonnet",
        prompt="hello",
        max_output_tokens=100,
        authorized_max_output_tokens=100,
        api_key="sk-or-test-key-12345",
        pricing_snapshot=None,
    )
    result, _ = await adapter.execute(req)
    assert result.result_class == ProviderResultClass.POLICY_DENIED
    assert "Missing or invalid pricing snapshot" in result.summary


@pytest.mark.asyncio
async def test_caller_route_substitution_attempt_fails_closed():
    snapshot = _valid_snapshot()
    # Caller reserved snapshot for claude-3.5-sonnet but attempts to substitute deepseek/deepseek-chat
    adapter = OpenRouterAdapter()
    req = OpenRouterRequest(
        model="deepseek/deepseek-chat",
        canonical_model_identity="deepseek:deepseek-chat",
        prompt="hello",
        max_output_tokens=500,
        authorized_max_output_tokens=500,
        api_key="sk-or-test-key-12345",
        pricing_snapshot=snapshot,
        pricing_snapshot_id=snapshot.snapshot_id,
    )
    result, _ = await adapter.execute(req)
    assert result.result_class == ProviderResultClass.POLICY_DENIED
    assert "does not match authorized" in result.summary


@pytest.mark.asyncio
async def test_missing_api_key_rejected():
    snapshot = _valid_snapshot()
    adapter = OpenRouterAdapter()
    req = OpenRouterRequest(
        model="anthropic/claude-3.5-sonnet",
        canonical_model_identity="anthropic:claude-3.5-sonnet",
        prompt="hello",
        max_output_tokens=100,
        authorized_max_output_tokens=100,
        api_key="",
        pricing_snapshot=snapshot,
        pricing_snapshot_id=snapshot.snapshot_id,
    )
    result, _ = await adapter.execute(req)
    assert result.result_class == ProviderResultClass.POLICY_DENIED
    assert "Missing OPENROUTER_API_KEY" in result.summary


@pytest.mark.asyncio
async def test_successful_response_normalization():
    snapshot = _valid_snapshot()
    response_payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "READY_TO_MERGE\nSummary: Changes look clean.",
                }
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "total_tokens": 165,
            "cost": 0.0012,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == "Bearer sk-or-test-key-12345"
        assert json.loads(request.content)["model"] == "anthropic/claude-3.5-sonnet"
        return httpx.Response(200, json=response_payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterAdapter()
        req = OpenRouterRequest(
            model="anthropic/claude-3.5-sonnet",
            canonical_model_identity="anthropic:claude-3.5-sonnet",
            prompt="review prompt",
            max_output_tokens=1000,
            authorized_max_output_tokens=1000,
            api_key="sk-or-test-key-12345",
            pricing_snapshot=snapshot,
            pricing_snapshot_id=snapshot.snapshot_id,
        )
        result, meta = await adapter.execute(req, client=client)

    assert result.result_class == ProviderResultClass.SUCCESS
    assert result.raw_output == "READY_TO_MERGE\nSummary: Changes look clean."
    assert meta["prompt_tokens"] == 120
    assert meta["completion_tokens"] == 45
    assert meta["total_tokens"] == 165
    assert meta["actual_cost_usd"] == Decimal("0.0012")


@pytest.mark.asyncio
async def test_rate_limit_normalization():
    snapshot = _valid_snapshot()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "30"}, text="Rate limit exceeded")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterAdapter()
        req = OpenRouterRequest(
            model="anthropic/claude-3.5-sonnet",
            canonical_model_identity="anthropic:claude-3.5-sonnet",
            prompt="prompt",
            max_output_tokens=500,
            authorized_max_output_tokens=500,
            api_key="sk-or-test-key-12345",
            pricing_snapshot=snapshot,
            pricing_snapshot_id=snapshot.snapshot_id,
        )
        result, _ = await adapter.execute(req, client=client)

    assert result.result_class == ProviderResultClass.RATE_LIMIT
    assert result.retry_after == "30"


@pytest.mark.asyncio
async def test_auth_error_normalization_and_redaction():
    snapshot = _valid_snapshot()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized API key sk-or-test-key-12345")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterAdapter()
        req = OpenRouterRequest(
            model="anthropic/claude-3.5-sonnet",
            canonical_model_identity="anthropic:claude-3.5-sonnet",
            prompt="prompt",
            max_output_tokens=500,
            authorized_max_output_tokens=500,
            api_key="sk-or-test-key-12345",
            pricing_snapshot=snapshot,
            pricing_snapshot_id=snapshot.snapshot_id,
        )
        result, _ = await adapter.execute(req, client=client)

    assert result.result_class == ProviderResultClass.AUTH_ERROR
    # Secret must be redacted in summary
    assert "sk-or-test-key-12345" not in result.summary


@pytest.mark.asyncio
async def test_mock_adapter():
    snapshot = _valid_snapshot()
    mock_adapter = MockOpenRouterAdapter()
    req = OpenRouterRequest(
        model="anthropic/claude-3.5-sonnet",
        canonical_model_identity="anthropic:claude-3.5-sonnet",
        prompt="test prompt",
        max_output_tokens=100,
        authorized_max_output_tokens=100,
        api_key="mock-key",
        pricing_snapshot=snapshot,
        pricing_snapshot_id=snapshot.snapshot_id,
    )
    result, meta = await mock_adapter.execute(req)
    assert len(mock_adapter.calls) == 1
    assert result.result_class == ProviderResultClass.SUCCESS
