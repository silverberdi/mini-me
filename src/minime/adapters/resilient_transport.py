"""Resilient HTTP and SSE transport layer with exponential backoff, jitter, and classification."""

from __future__ import annotations

import asyncio
import logging
import random
import socket
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Coroutine

import httpx

logger = logging.getLogger(__name__)

RETRIABLE_STATUS_CODES = {429, 502, 503, 504}
NON_RETRIABLE_CLIENT_STATUS_CODES = {400, 401, 403, 404, 422}


class TransportClassificationError(Exception):
    """Base transport error."""


class PreSendTransportError(TransportClassificationError):
    """Failure occurred prior to request transmission; safe to retry."""


class PostSendAmbiguousError(TransportClassificationError):
    """Failure occurred in-flight after data was transmitted without receiving a terminal response; uncertain exposure."""


class NonRetriableClientError(TransportClassificationError):
    """Permanent client failure (400, 401, 403, invalid schema) that must not be retried."""


def is_retriable_transport_exception(exc: Exception) -> bool:
    """Determine if an exception represents a transient network/socket interruption."""
    if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionRefusedError, socket.error)):
        return True
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.ReadTimeout):
        return True
    return False


def is_retriable_status_code(status_code: int) -> bool:
    return status_code in RETRIABLE_STATUS_CODES


def is_non_retriable_status_code(status_code: int) -> bool:
    return status_code in NON_RETRIABLE_CLIENT_STATUS_CODES


def parse_retry_after(header_value: str | None, default_delay: float) -> float:
    """Parse HTTP Retry-After header as seconds or HTTP-date."""
    if not header_value:
        return default_delay
    header_str = header_value.strip()
    try:
        return max(0.0, float(header_str))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(header_str)
        delay = (dt - datetime.now(dt.tzinfo)).total_seconds()
        return max(0.0, delay)
    except Exception:
        return default_delay


class ResilientTransport:
    """Wraps HTTP and stream operations with exponential backoff, jitter, and classification."""

    def __init__(
        self,
        *,
        max_retries: int = 4,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
        jitter_range: tuple[float, float] = (0.1, 0.5),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay_seconds
        self.max_delay = max_delay_seconds
        self.jitter_range = jitter_range
        self.total_retries: int = 0
        self.cumulative_stall_seconds: float = 0.0

    def calculate_delay(self, attempt: int, retry_after_header: str | None = None) -> float:
        exponential = self.base_delay * (2 ** attempt)
        jitter = random.uniform(*self.jitter_range)
        calculated = min(self.max_delay, exponential + jitter)
        if retry_after_header:
            return min(self.max_delay, parse_retry_after(retry_after_header, calculated))
        return calculated

    async def execute_with_retry(
        self,
        operation: Callable[[], Coroutine[Any, Any, httpx.Response]],
        *,
        is_idempotent: bool = True,
    ) -> httpx.Response:
        """Execute an HTTP operation with retry for transient transport errors."""
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await operation()
                if is_retriable_status_code(response.status_code):
                    if attempt < self.max_retries:
                        retry_after = response.headers.get("retry-after")
                        delay = self.calculate_delay(attempt, retry_after)
                        self.total_retries += 1
                        self.cumulative_stall_seconds += delay
                        logger.warning(
                            f"HTTP {response.status_code} received from provider. Retrying in {delay:.2f}s (attempt {attempt + 1}/{self.max_retries})..."
                        )
                        await asyncio.sleep(delay)
                        continue
                return response
            except Exception as exc:
                last_exc = exc
                if not is_retriable_transport_exception(exc):
                    raise
                if not is_idempotent and attempt > 0:
                    raise PostSendAmbiguousError(
                        f"Non-idempotent request dropped after initial attempt: {exc}"
                    ) from exc
                if attempt < self.max_retries:
                    delay = self.calculate_delay(attempt)
                    self.total_retries += 1
                    self.cumulative_stall_seconds += delay
                    logger.warning(
                        f"Transient transport error ({type(exc).__name__}: {exc}). Retrying in {delay:.2f}s (attempt {attempt + 1}/{self.max_retries})..."
                    )
                    await asyncio.sleep(delay)
                else:
                    break

        if last_exc:
            raise last_exc
        raise TransportClassificationError("Max retries exceeded without a response")
