"""OpenRouter adapter for paid drain fallback execution with authorized envelope verification."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from minime.domain.enums import ProviderResultClass
from minime.domain.models import (
    AUTHORITATIVE_PRICING_SOURCES,
    NormalizedProviderResult,
    OpenRouterPricingSnapshot,
)
from minime.logging import redact_secrets


@dataclass(frozen=True)
class OpenRouterRequest:
    model: str
    canonical_model_identity: str
    prompt: str
    max_output_tokens: int
    authorized_max_output_tokens: int
    api_key: str
    pricing_snapshot: OpenRouterPricingSnapshot | None
    pricing_snapshot_id: str | None = None
    system_prompt: str | None = None
    temperature: float = 0.0
    timeout_seconds: float = 60.0


class OpenRouterAdapter:
    """Async HTTP adapter for OpenRouter with strict pinned routing, envelope authorization, and secret redaction."""

    def __init__(self, base_url: str = "https://openrouter.ai/api/v1", default_timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_timeout = default_timeout

    def verify_authorization_envelope(self, request: OpenRouterRequest) -> tuple[bool, str | None]:
        """Defense-in-depth verification of execution envelope against authorized pricing snapshot."""
        if not request.pricing_snapshot or not request.pricing_snapshot.snapshot_id:
            return False, "PRICING_SNAPSHOT_MISSING: Missing or invalid pricing snapshot binding"

        snapshot = request.pricing_snapshot
        if not getattr(snapshot, "is_verified", False) and snapshot.source not in AUTHORITATIVE_PRICING_SOURCES:
            return False, f"PRICING_UNVERIFIED: Pricing snapshot '{snapshot.snapshot_id}' source '{snapshot.source}' is not authoritative"

        snapshot_id = request.pricing_snapshot_id or snapshot.snapshot_id
        if snapshot_id != snapshot.snapshot_id:
            return False, f"PRICING_MODEL_MISMATCH: Pricing snapshot id mismatch: '{snapshot_id}' vs snapshot '{snapshot.snapshot_id}'"

        if request.model != snapshot.routed_model_identity:
            return False, (
                f"PRICING_MODEL_MISMATCH: Dispatched model '{request.model}' does not match authorized "
                f"snapshot routed model '{snapshot.routed_model_identity}'"
            )

        if request.canonical_model_identity != snapshot.canonical_model_identity:
            return False, (
                f"PRICING_MODEL_MISMATCH: Canonical model identity '{request.canonical_model_identity}' does not match "
                f"authorized snapshot canonical identity '{snapshot.canonical_model_identity}'"
            )

        if request.model.startswith("openrouter/auto") or ":auto" in request.model or request.model == "auto":
            return False, "Auto-routing endpoints are strictly prohibited; pinned route required"

        if ":auto" in snapshot.routed_model_identity or snapshot.routed_model_identity == "openrouter/auto":
            return False, "Snapshot routed model contains auto-routing; pinned route required"

        if request.max_output_tokens <= 0:
            return False, "Missing or non-positive max output token bound"

        if request.max_output_tokens > request.authorized_max_output_tokens:
            return False, (
                f"Requested max_output_tokens ({request.max_output_tokens}) exceeds "
                f"authorized reservation bound ({request.authorized_max_output_tokens})"
            )

        if not request.api_key:
            return False, "Missing OPENROUTER_API_KEY"

        return True, None

    async def execute(
        self,
        request: OpenRouterRequest,
        client: httpx.AsyncClient | None = None,
    ) -> tuple[NormalizedProviderResult, dict[str, Any]]:
        """Execute OpenRouter chat completion request after verifying authorized envelope."""
        valid, reason = self.verify_authorization_envelope(request)
        if not valid:
            return self._denied(reason or "Envelope authorization failed")

        timeout_sec = request.timeout_seconds if request.timeout_seconds > 0 else self.default_timeout
        endpoint_url = f"{self.base_url}/chat/completions"

        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        payload = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }

        headers = {
            "Authorization": f"Bearer {request.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/silverberdi/mini-me",
            "X-Title": "mini-me",
        }

        snapshot_id = request.pricing_snapshot.snapshot_id if request.pricing_snapshot else (request.pricing_snapshot_id or "")

        try:
            if client is not None:
                response = await client.post(endpoint_url, json=payload, headers=headers, timeout=timeout_sec)
            else:
                async with httpx.AsyncClient(timeout=timeout_sec) as http_client:
                    response = await http_client.post(endpoint_url, json=payload, headers=headers)

            return self._process_response(response, request)

        except (httpx.TimeoutException, asyncio.TimeoutError):
            return (
                NormalizedProviderResult(
                    result_class=ProviderResultClass.TIMEOUT,
                    provider="openrouter",
                    role="fallback",
                    model=request.model,
                    summary=f"OpenRouter request timed out after {timeout_sec}s",
                ),
                {"pricing_snapshot_id": snapshot_id, "model": request.model},
            )
        except httpx.RequestError as exc:
            err_msg = redact_secrets(f"OpenRouter network request error: {exc}", [request.api_key])
            return (
                NormalizedProviderResult(
                    result_class=ProviderResultClass.TRANSIENT_ERROR,
                    provider="openrouter",
                    role="fallback",
                    model=request.model,
                    summary=err_msg,
                ),
                {"pricing_snapshot_id": snapshot_id, "model": request.model},
            )
        except Exception as exc:
            err_msg = redact_secrets(f"Unexpected OpenRouter error: {exc}", [request.api_key])
            return (
                NormalizedProviderResult(
                    result_class=ProviderResultClass.UNKNOWN_ERROR,
                    provider="openrouter",
                    role="fallback",
                    model=request.model,
                    summary=err_msg,
                ),
                {"pricing_snapshot_id": snapshot_id, "model": request.model},
            )

    def _process_response(
        self, response: httpx.Response, request: OpenRouterRequest
    ) -> tuple[NormalizedProviderResult, dict[str, Any]]:
        status_code = response.status_code
        retry_after = response.headers.get("retry-after") or response.headers.get("Retry-After")
        snapshot_id = request.pricing_snapshot.snapshot_id if request.pricing_snapshot else (request.pricing_snapshot_id or "")

        if status_code == 200:
            try:
                data = response.json()
            except Exception as e:
                return (
                    NormalizedProviderResult(
                        result_class=ProviderResultClass.MALFORMED_OUTPUT,
                        provider="openrouter",
                        role="fallback",
                        model=request.model,
                        summary=f"Malformed JSON response from OpenRouter: {e}",
                    ),
                    {"pricing_snapshot_id": snapshot_id, "model": request.model},
                )

            choices = data.get("choices")
            if not choices or not isinstance(choices, list) or len(choices) == 0:
                return (
                    NormalizedProviderResult(
                        result_class=ProviderResultClass.MALFORMED_OUTPUT,
                        provider="openrouter",
                        role="fallback",
                        model=request.model,
                        summary="OpenRouter response choices missing or empty",
                    ),
                    {"pricing_snapshot_id": snapshot_id, "model": request.model},
                )

            first_choice = choices[0]
            message = first_choice.get("message", {})
            content = message.get("content")
            if content is None:
                return (
                    NormalizedProviderResult(
                        result_class=ProviderResultClass.MALFORMED_OUTPUT,
                        provider="openrouter",
                        role="fallback",
                        model=request.model,
                        summary="OpenRouter choice message content is null",
                    ),
                    {"pricing_snapshot_id": snapshot_id, "model": request.model},
                )

            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
            reported_cost = usage.get("cost")

            meta: dict[str, Any] = {
                "pricing_snapshot_id": snapshot_id,
                "model": request.model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "actual_cost_usd": Decimal(str(reported_cost)) if reported_cost is not None else None,
            }

            return (
                NormalizedProviderResult(
                    result_class=ProviderResultClass.SUCCESS,
                    provider="openrouter",
                    role="fallback",
                    model=request.model,
                    summary="OpenRouter fallback completed successfully",
                    raw_output=content,
                ),
                meta,
            )

        # Non-200 responses
        body_text = redact_secrets(response.text[:500], [request.api_key])
        if status_code in {401, 403}:
            result_class = ProviderResultClass.AUTH_ERROR
            summary = f"OpenRouter authentication error ({status_code}): {body_text}"
        elif status_code == 429:
            result_class = ProviderResultClass.RATE_LIMIT
            summary = f"OpenRouter rate limit exceeded ({status_code}): {body_text}"
        elif status_code == 402:
            result_class = ProviderResultClass.QUOTA_LIMIT
            summary = f"OpenRouter quota limit / insufficient balance ({status_code}): {body_text}"
        elif status_code in {500, 502, 503, 504}:
            result_class = ProviderResultClass.TRANSIENT_ERROR
            summary = f"OpenRouter transient server error ({status_code}): {body_text}"
        else:
            result_class = ProviderResultClass.UNKNOWN_ERROR
            summary = f"OpenRouter API error ({status_code}): {body_text}"

        return (
            NormalizedProviderResult(
                result_class=result_class,
                provider="openrouter",
                role="fallback",
                model=request.model,
                retry_after=retry_after,
                summary=summary,
            ),
            {"pricing_snapshot_id": snapshot_id, "model": request.model, "status_code": status_code},
        )

    def _denied(self, summary: str) -> tuple[NormalizedProviderResult, dict[str, Any]]:
        return (
            NormalizedProviderResult(
                result_class=ProviderResultClass.POLICY_DENIED,
                provider="openrouter",
                role="fallback",
                summary=redact_secrets(summary),
            ),
            {},
        )


class MockOpenRouterAdapter(OpenRouterAdapter):
    """Mock adapter for offline tests recording dispatched requests after envelope verification."""

    def __init__(
        self,
        canned_result: NormalizedProviderResult | None = None,
        canned_meta: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.calls: list[OpenRouterRequest] = []
        self.canned_result = canned_result or NormalizedProviderResult(
            result_class=ProviderResultClass.SUCCESS,
            provider="openrouter",
            role="fallback",
            summary="Mock OpenRouter success",
            raw_output="Mock OpenRouter raw output",
        )
        self.canned_meta = canned_meta or {}

    async def execute(
        self, request: OpenRouterRequest, client: httpx.AsyncClient | None = None
    ) -> tuple[NormalizedProviderResult, dict[str, Any]]:
        valid, reason = self.verify_authorization_envelope(request)
        if not valid:
            return self._denied(reason or "Envelope authorization failed")

        self.calls.append(request)
        meta = dict(self.canned_meta)
        snapshot_id = request.pricing_snapshot.snapshot_id if request.pricing_snapshot else (request.pricing_snapshot_id or "")
        meta.setdefault("pricing_snapshot_id", snapshot_id)
        meta.setdefault("model", request.model)
        return self.canned_result, meta
