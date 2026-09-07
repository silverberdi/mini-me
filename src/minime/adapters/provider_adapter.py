"""Generic provider adapter abstraction and capability contracts."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from minime.config import AppConfig, load_config
from minime.domain.enums import CapacitySignalSource, ProviderResultClass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapacitySignal:
    result_class: ProviderResultClass
    capacity_reset_at: datetime | None = None
    retry_after_seconds: int | None = None
    source_signal: CapacitySignalSource = CapacitySignalSource.UNKNOWN
    summary: str = ""


class ProviderAdapterInterface(ABC):
    """Generic contract for execution, review, audit, and drain providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g., 'codex', 'antigravity', 'openrouter', 'cursor')."""
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_roles(self) -> set[str]:
        """Roles supported by this provider (e.g., {'implementer', 'reviewer'})."""
        raise NotImplementedError

    @abstractmethod
    async def probe_availability(self, timeout_seconds: float = 30.0) -> bool:
        """Perform a lightweight, non-destructive probe to check provider availability.

        Guarantees:
        - Creates 0 Runs
        - Creates 0 Jobs
        - Consumes 0 implementation retry budget
        - Does not start new tasks
        """
        raise NotImplementedError

    def extract_capacity_signal(
        self, raw_output: str, exit_code: int = 0
    ) -> CapacitySignal | None:
        """Extract capacity/quota signal from raw output or error if supported."""
        return None


class CodexProviderAdapter(ProviderAdapterInterface):
    """Provider adapter for OpenAI Codex CLI."""

    def __init__(self, executable: str = "codex"):
        self._executable = executable

    @property
    def provider_name(self) -> str:
        return "codex"

    @property
    def supported_roles(self) -> set[str]:
        return {"implementer", "reviewer"}

    async def probe_availability(self, timeout_seconds: float = 30.0) -> bool:
        search_path = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}"
        resolved = shutil.which(self._executable, path=search_path)
        if not resolved:
            return False

        try:
            # Lightweight ephemeral probe
            proc = await asyncio.create_subprocess_exec(
                resolved,
                "exec",
                "-",
                "--ephemeral",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(b"echo probe"),
                    timeout=timeout_seconds,
                )
                return proc.returncode == 0
            except asyncio.TimeoutError:
                try:
                    proc.terminate()
                except OSError:
                    pass
                return False
        except Exception as exc:
            logger.debug(f"Codex availability probe failed: {exc}")
            return False


class AntigravityProviderAdapter(ProviderAdapterInterface):
    """Provider adapter for Antigravity (agy) CLI."""

    def __init__(self, executable: str = "agy"):
        self._executable = executable

    @property
    def provider_name(self) -> str:
        return "antigravity"

    @property
    def supported_roles(self) -> set[str]:
        return {"implementer", "reviewer"}

    async def probe_availability(self, timeout_seconds: float = 30.0) -> bool:
        search_path = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}"
        resolved = shutil.which(self._executable, path=search_path)
        if not resolved:
            return False

        try:
            # Lightweight probe verifying execution and authentication readiness (agy models)
            proc = await asyncio.create_subprocess_exec(
                resolved,
                "models",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_seconds,
                )
                if proc.returncode != 0:
                    return False
                combined = (
                    stdout.decode("utf-8", errors="replace")
                    + " "
                    + stderr.decode("utf-8", errors="replace")
                ).lower()
                if (
                    "authentication required" in combined
                    or "sign in" in combined
                    or "not logged in" in combined
                    or "login required" in combined
                ):
                    return False
                return True
            except asyncio.TimeoutError:
                try:
                    proc.terminate()
                except OSError:
                    pass
                return False
        except Exception as exc:
            logger.debug(f"Antigravity availability probe failed: {exc}")
            return False


class OpenRouterProviderAdapter(ProviderAdapterInterface):
    """Provider adapter for OpenRouter API."""

    def __init__(
        self,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key_env: str = "OPENROUTER_API_KEY",
    ):
        self._base_url = base_url
        self._api_key_env = api_key_env

    @property
    def provider_name(self) -> str:
        return "openrouter"

    @property
    def supported_roles(self) -> set[str]:
        return {"implementer", "reviewer"}

    async def probe_availability(self, timeout_seconds: float = 30.0) -> bool:
        api_key = os.environ.get(self._api_key_env, "").strip()
        if not api_key:
            return False
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=timeout_seconds
            ) as client:
                res = await client.get(
                    "/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                return res.status_code == 200
        except Exception as exc:
            logger.debug(f"OpenRouter availability probe failed: {exc}")
            return False


class DeepSeekProviderAdapter(ProviderAdapterInterface):
    """Provider adapter for DeepSeek API."""

    def __init__(
        self,
        base_url: str = "https://api.deepseek.com",
        api_key_env: str = "DEEPSEEK_API_KEY",
    ):
        self._base_url = base_url
        self._api_key_env = api_key_env

    @property
    def provider_name(self) -> str:
        return "deepseek"

    @property
    def supported_roles(self) -> set[str]:
        return {"auditor"}

    async def probe_availability(self, timeout_seconds: float = 30.0) -> bool:
        api_key = os.environ.get(self._api_key_env, "").strip()
        if not api_key:
            return False
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=timeout_seconds
            ) as client:
                res = await client.get(
                    "/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                return res.status_code == 200
        except Exception as exc:
            logger.debug(f"DeepSeek availability probe failed: {exc}")
            return False


class FakeProviderAdapter(ProviderAdapterInterface):
    """Test / Future provider adapter (e.g. proving Cursor integration without scheduler rewrite)."""

    def __init__(
        self,
        name: str = "fake-provider",
        supported_roles: set[str] | None = None,
        available: bool = True,
    ):
        self._name = name
        self._supported_roles = supported_roles or {"implementer", "reviewer"}
        self.available = available
        self.probe_call_count = 0

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def supported_roles(self) -> set[str]:
        return self._supported_roles

    async def probe_availability(self, timeout_seconds: float = 30.0) -> bool:
        self.probe_call_count += 1
        return self.available


# Global registry for pluggable provider adapters
_ADAPTER_REGISTRY: dict[str, ProviderAdapterInterface] = {}


def register_provider_adapter(adapter: ProviderAdapterInterface) -> None:
    """Register or override a provider adapter."""
    _ADAPTER_REGISTRY[adapter.provider_name] = adapter


def get_provider_adapter(
    provider: str, config: AppConfig | None = None
) -> ProviderAdapterInterface:
    """Get the registered provider adapter or construct a default instance."""
    if provider in _ADAPTER_REGISTRY:
        return _ADAPTER_REGISTRY[provider]

    app_config = config or load_config()
    p_config = app_config.providers.get(provider)

    if provider == "codex":
        cmd = p_config.command if p_config and p_config.command else "codex"
        adapter = CodexProviderAdapter(executable=cmd)
    elif provider == "antigravity":
        cmd = p_config.command if p_config and p_config.command else "agy"
        adapter = AntigravityProviderAdapter(executable=cmd)
    elif provider == "openrouter":
        url = p_config.base_url if p_config and p_config.base_url else "https://openrouter.ai/api/v1"
        key_env = p_config.api_key_env if p_config and p_config.api_key_env else "OPENROUTER_API_KEY"
        adapter = OpenRouterProviderAdapter(base_url=url, api_key_env=key_env)
    elif provider == "deepseek":
        url = p_config.base_url if p_config and p_config.base_url else "https://api.deepseek.com"
        key_env = p_config.api_key_env if p_config and p_config.api_key_env else "DEEPSEEK_API_KEY"
        adapter = DeepSeekProviderAdapter(base_url=url, api_key_env=key_env)
    else:
        # Generic fallback / custom provider
        cmd = p_config.command if p_config and p_config.command else provider
        adapter = FakeProviderAdapter(name=provider)

    _ADAPTER_REGISTRY[provider] = adapter
    return adapter
