"""Tests for resilient HTTP/SSE transport, error classification, and retry backoff."""

from __future__ import annotations

import httpx
import pytest

from minime.adapters.resilient_transport import (
    PostSendAmbiguousError,
    ResilientTransport,
    is_non_retriable_status_code,
    is_retriable_status_code,
    is_retriable_transport_exception,
    parse_retry_after,
)


def test_error_classification():
    assert is_retriable_transport_exception(ConnectionResetError("reset"))
    assert is_retriable_transport_exception(httpx.ConnectError("cannot connect"))
    assert is_retriable_transport_exception(httpx.ReadTimeout("read timeout"))
    assert not is_retriable_transport_exception(ValueError("invalid payload"))

    assert is_retriable_status_code(429)
    assert is_retriable_status_code(502)
    assert is_retriable_status_code(503)
    assert is_retriable_status_code(504)
    assert not is_retriable_status_code(400)
    assert not is_retriable_status_code(401)
    assert not is_retriable_status_code(403)

    assert is_non_retriable_status_code(400)
    assert is_non_retriable_status_code(401)
    assert is_non_retriable_status_code(403)
    assert not is_non_retriable_status_code(429)
    assert not is_non_retriable_status_code(503)


def test_parse_retry_after():
    assert parse_retry_after("5", default_delay=1.0) == 5.0
    assert parse_retry_after("2.5", default_delay=1.0) == 2.5
    assert parse_retry_after(None, default_delay=1.5) == 1.5
    assert parse_retry_after("invalid", default_delay=3.0) == 3.0


@pytest.mark.asyncio
async def test_transient_connection_reset_recovers_automatically():
    transport = ResilientTransport(max_retries=3, base_delay_seconds=0.01, jitter_range=(0.0, 0.01))
    attempts = 0

    async def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionResetError("Connection reset by peer")
        return httpx.Response(200, json={"status": "ok"})

    response = await transport.execute_with_retry(flaky_call, is_idempotent=True)
    assert response.status_code == 200
    assert attempts == 3
    assert transport.total_retries == 2


@pytest.mark.asyncio
async def test_transient_http_429_retries_and_recovers():
    transport = ResilientTransport(max_retries=3, base_delay_seconds=0.01, jitter_range=(0.0, 0.01))
    attempts = 0

    async def rate_limited_call():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"retry-after": "0.02"})
        return httpx.Response(200, json={"result": "success"})

    response = await transport.execute_with_retry(rate_limited_call, is_idempotent=True)
    assert response.status_code == 200
    assert attempts == 2
    assert transport.total_retries == 1


@pytest.mark.asyncio
async def test_permanent_client_error_fails_fast_without_retry():
    transport = ResilientTransport(max_retries=3, base_delay_seconds=0.01)
    attempts = 0

    async def bad_request_call():
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, json={"error": "Bad request"})

    response = await transport.execute_with_retry(bad_request_call, is_idempotent=True)
    assert response.status_code == 400
    assert attempts == 1
    assert transport.total_retries == 0


@pytest.mark.asyncio
async def test_non_idempotent_post_send_drop_raises_ambiguous_error():
    transport = ResilientTransport(max_retries=3, base_delay_seconds=0.01)
    attempts = 0

    async def non_idempotent_call():
        nonlocal attempts
        attempts += 1
        raise ConnectionResetError("Socket dropped after post-send")

    with pytest.raises(PostSendAmbiguousError):
        await transport.execute_with_retry(non_idempotent_call, is_idempotent=False)
    # Ambiguous post-send failure must NOT be retried automatically even once
    assert attempts == 1
    assert transport.total_retries == 0


@pytest.mark.asyncio
async def test_non_idempotent_pre_send_error_retries_and_recovers():
    transport = ResilientTransport(max_retries=3, base_delay_seconds=0.01, jitter_range=(0.0, 0.01))
    attempts = 0

    async def pre_send_failure_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            # ConnectError is demonstrably pre-send (connection could not be established)
            raise httpx.ConnectError("Connection refused by peer before transmission")
        return httpx.Response(200, json={"status": "ok"})

    response = await transport.execute_with_retry(pre_send_failure_call, is_idempotent=False)
    assert response.status_code == 200
    assert attempts == 3
    assert transport.total_retries == 2


@pytest.mark.asyncio
async def test_non_idempotent_server_error_502_fails_fast_without_duplicate_post():
    transport = ResilientTransport(max_retries=3, base_delay_seconds=0.01)
    attempts = 0

    async def gateway_error_call():
        nonlocal attempts
        attempts += 1
        return httpx.Response(502, json={"error": "Bad Gateway"})

    response = await transport.execute_with_retry(gateway_error_call, is_idempotent=False)
    assert response.status_code == 502
    assert attempts == 1
    assert transport.total_retries == 0


@pytest.mark.asyncio
async def test_non_idempotent_http_429_retries_and_recovers():
    transport = ResilientTransport(max_retries=3, base_delay_seconds=0.01, jitter_range=(0.0, 0.01))
    attempts = 0

    async def rate_limited_call():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"retry-after": "0.01"})
        return httpx.Response(200, json={"result": "success"})

    response = await transport.execute_with_retry(rate_limited_call, is_idempotent=False)
    assert response.status_code == 200
    assert attempts == 2
    assert transport.total_retries == 1
