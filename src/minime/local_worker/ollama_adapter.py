"""Minimal local/Ollama provider adapter for the local worker bootstrap.

The adapter performs deterministic preflight (reachability + canonical model existence) and
bounded generation through Ollama's HTTP API. It never runs live in tests: callers inject an
``httpx.AsyncClient`` backed by ``httpx.MockTransport`` so all test scenarios run offline.

Timeout enforces the bounded-execution guarantee; cancellation and cleanup of the in-flight
request is delegated to the HTTP layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import httpx

from minime.domain.enums import ProviderResultClass
from minime.local_worker.model_identity import OLLAMA_PROVIDER
from minime.local_worker.models import PreflightResult, PreflightStatus

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class OllamaGenerateResponse:
    result_class: ProviderResultClass
    text: str = ""
    done: bool = False
    error: str = ""


class LocalOllamaAdapter:
    """Thin, deterministic Ollama adapter with offline-testable injected transport."""

    def __init__(
        self,
        model: str,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.provider = OLLAMA_PROVIDER
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.request_timeout_seconds = request_timeout_seconds

    async def _client(self, client: httpx.AsyncClient | None) -> httpx.AsyncClient:
        if client is not None:
            return client
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.request_timeout_seconds)

    @staticmethod
    def _parse_tags_model_names(raw: bytes | str) -> list[str]:
        try:
            payload = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return []
        models = payload.get("models", []) if isinstance(payload, dict) else []
        names: list[str] = []
        for entry in models:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("model")
                if name:
                    names.append(str(name))
        return names

    async def preflight(
        self, *, client: httpx.AsyncClient | None = None
    ) -> PreflightResult:
        """Reachability + canonical-model-existence preflight.

        Reachability: GET /api/tags returns 200 -> reachable.
        Model presence: response model names exactly contain the canonical identity.
        """
        async with await self._client(client) as active:
            try:
                res = await asyncio.wait_for(
                    active.get("/api/tags"),
                    timeout=self.request_timeout_seconds,
                )
            except asyncio.TimeoutError:
                return PreflightResult(
                    provider=self.provider,
                    model=self.model,
                    status=PreflightStatus.UNREACHABLE,
                    reason="Ollama unreachable: /api/tags timed out",
                    reachable=False,
                    model_present=False,
                )
            except httpx.HTTPError:
                return PreflightResult(
                    provider=self.provider,
                    model=self.model,
                    status=PreflightStatus.UNREACHABLE,
                    reason="Ollama unreachable: /api/tags request error",
                    reachable=False,
                    model_present=False,
                )

        if res.status_code != 200:
            return PreflightResult(
                provider=self.provider,
                model=self.model,
                status=PreflightStatus.UNREACHABLE,
                reason=f"Ollama unreachable: /api/tags returned HTTP {res.status_code}",
                reachable=False,
                model_present=False,
            )

        names = self._parse_tags_model_names(res.content)
        present = self.model in names
        if not present:
            return PreflightResult(
                provider=self.provider,
                model=self.model,
                status=PreflightStatus.MODEL_MISSING,
                reason=f"Required model '{self.model}' is not present in the local Ollama registry",
                reachable=True,
                model_present=False,
            )

        return PreflightResult(
            provider=self.provider,
            model=self.model,
            status=PreflightStatus.READY,
            reason="Ollama reachable and required model present",
            reachable=True,
            model_present=True,
        )

    async def generate(
        self,
        *,
        system_prompt: str,
        prompt: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float | None = None,
    ) -> OllamaGenerateResponse:
        """Send one bounded chat/generate request and return the normalized result.

        Bounded time is enforced via ``asyncio.wait_for`` so a stalled local model cannot run
        indefinitely. Cancellation propagates through the async request; the harness layer
        supplies overall process/cancellation cleanup semantics.
        """
        deadline_s = timeout_seconds or max(1.0, self.request_timeout_seconds)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.0},
        }
        async with await self._client(client) as active:
            try:
                res = await asyncio.wait_for(
                    active.post("/api/chat", json=body),
                    timeout=deadline_s,
                )
            except asyncio.TimeoutError:
                return OllamaGenerateResponse(
                    result_class=ProviderResultClass.TIMEOUT,
                    error="Ollama generate timed out and was cancelled",
                )
            except httpx.HTTPError as exc:
                return OllamaGenerateResponse(
                    result_class=ProviderResultClass.UNKNOWN_ERROR,
                    error=f"Ollama generate HTTP error: {exc.__class__.__name__}",
                )

        if res.status_code != 200:
            response_class = (
                ProviderResultClass.RATE_LIMIT
                if res.status_code == 429
                else (
                    ProviderResultClass.TRANSIENT_ERROR
                    if res.status_code >= 500
                    else ProviderResultClass.UNKNOWN_ERROR
                )
            )
            return OllamaGenerateResponse(
                result_class=response_class,
                error=f"Ollama generate HTTP {res.status_code}: {res.text[:300]}",
            )

        try:
            payload = res.json()
        except ValueError:
            return OllamaGenerateResponse(
                result_class=ProviderResultClass.MALFORMED_OUTPUT,
                error="Ollama generate returned non-JSON body",
            )

        if isinstance(payload, dict) and payload.get("error"):
            return OllamaGenerateResponse(
                result_class=ProviderResultClass.UNKNOWN_ERROR,
                error=str(payload.get("error"))[:300],
            )

        if isinstance(payload, dict) and payload.get("message"):
            text = str(payload.get("message", {}).get("content", ""))
        else:
            text = str(payload.get("response", "")) if isinstance(payload, dict) else ""

        if not text.strip():
            return OllamaGenerateResponse(
                result_class=ProviderResultClass.MALFORMED_OUTPUT,
                error="Ollama generate returned empty content",
            )

        return OllamaGenerateResponse(
            result_class=ProviderResultClass.SUCCESS,
            text=text,
            done=bool(payload.get("done", True)),
        )

