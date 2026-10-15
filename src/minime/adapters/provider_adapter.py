"""Generic provider adapter abstraction and capability contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from minime.config import AppConfig, load_config
from minime.domain.enums import CapacitySignalSource, ProviderResultClass

logger = logging.getLogger(__name__)
_AGY_STATUSLINE_LOCK = threading.Lock()


@dataclass(frozen=True)
class CapacitySignal:
    result_class: ProviderResultClass
    capacity_reset_at: datetime | None = None
    retry_after_seconds: int | None = None
    source_signal: CapacitySignalSource = CapacitySignalSource.UNKNOWN
    summary: str = ""


@dataclass(frozen=True)
class CapacityObservation:
    """A bounded provider-owned capacity snapshot; unknown is never permission."""

    provider: str
    ordinary_usage_allowed: bool | None
    observed_at: datetime
    expires_at: datetime
    source_signal: CapacitySignalSource
    account_id: str | None = None
    model: str | None = None
    capacity_reset_at: datetime | None = None
    # Ephemeral source-session identity. Persistence stores only its fingerprint.
    source_session_id: str | None = None


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

    async def check_cli_present(self) -> bool:
        # Local, quota-free executable/CLI presence. Subclasses override.
        return True

    async def check_auth_ready(self, timeout_seconds: float = 10.0) -> bool:
        # Non-inference authentication readiness. Subclasses override; HTTP-only
        # adapters cannot prove more locally and default to ready.
        del timeout_seconds
        return True

    @property
    def probe_is_expensive(self) -> bool:
        # True when probe_availability() may consume provider/model inference quota.
        return False

    @property
    def probe_verifies_capacity(self) -> bool:
        # True when a successful probe_availability() is valid evidence that an
        # exhausted provider's inference capacity has actually recovered.
        # Cheap readiness/reachability checks (CLI presence, auth, model catalog)
        # do NOT prove capacity and must NOT promote a provider back to AVAILABLE.
        return False

    @property
    def supports_read_only_capacity_observation(self) -> bool:
        return False

    @property
    def capacity_source_signal(self) -> CapacitySignalSource:
        return CapacitySignalSource.UNKNOWN

    @property
    def valid_capacity_source_signals(self) -> set[CapacitySignalSource]:
        return {self.capacity_source_signal}

    @property
    def requires_account_identity_for_capacity(self) -> bool:
        return False

    def extract_capacity_signal(self, raw_output: str, exit_code: int = 0) -> CapacitySignal | None:
        """Extract capacity/quota signal from raw output or error if supported."""
        return None

    async def read_capacity_observation(
        self, timeout_seconds: float = 10.0
    ) -> CapacityObservation | None:
        """Read quota without inference when the installed provider exposes a source."""
        del timeout_seconds
        return None


class CodexProviderAdapter(ProviderAdapterInterface):
    """Provider adapter for OpenAI Codex CLI."""

    def __init__(self, executable: str = "codex"):
        self._executable = executable

    @property
    def probe_is_expensive(self) -> bool:
        # Capacity uses the App Server rate-limit read, never a Codex turn.
        return False

    @property
    def probe_verifies_capacity(self) -> bool:
        # The App Server backend's ordinaryUsageAllowed field is authoritative.
        return True

    @property
    def supports_read_only_capacity_observation(self) -> bool:
        return True

    @property
    def capacity_source_signal(self) -> CapacitySignalSource:
        return CapacitySignalSource.CODEX_APP_SERVER

    @property
    def requires_account_identity_for_capacity(self) -> bool:
        return True

    def _resolve_executable(self) -> str | None:
        search_path = (
            f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:"
            f"{os.environ.get('PATH', '')}"
        )
        return shutil.which(self._executable, path=search_path)

    async def check_cli_present(self) -> bool:
        return self._resolve_executable() is not None

    async def check_auth_ready(self, timeout_seconds: float = 10.0) -> bool:
        # Non-inference auth readiness via the codex login status command.
        # Verified against the installed codex-cli (0.147.0); never dispatches a
        # codex exec turn for readiness.
        resolved = self._resolve_executable()
        if not resolved:
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                resolved,
                "login",
                "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
                return proc.returncode == 0
            except asyncio.TimeoutError:
                try:
                    proc.terminate()
                except OSError:
                    pass
                return False
        except Exception as exc:
            logger.debug(f"Codex auth readiness check failed: {exc}")
            return False

    @property
    def provider_name(self) -> str:
        return "codex"

    @property
    def supported_roles(self) -> set[str]:
        return {"implementer", "reviewer"}

    async def probe_availability(self, timeout_seconds: float = 30.0) -> bool:
        observation = await self.read_capacity_observation(timeout_seconds=timeout_seconds)
        return observation is not None and observation.ordinary_usage_allowed is True

    async def read_capacity_observation(self, timeout_seconds: float = 10.0) -> CapacityObservation:
        """Read the installed App Server's account rate-limit contract without a turn.

        The response schema documents ``ordinaryUsageAllowed`` as backend permission
        for ordinary included usage, validated against the active account. Missing or
        null values remain UNKNOWN; percentages and reset timestamps never grant use.
        """
        observed_at = datetime.now(UTC)
        expires_at = observed_at + timedelta(seconds=60)
        unresolved = CapacityObservation(
            provider=self.provider_name,
            ordinary_usage_allowed=None,
            observed_at=observed_at,
            expires_at=expires_at,
            source_signal=CapacitySignalSource.CODEX_APP_SERVER,
        )
        search_path = (
            f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:"
            f"{os.environ.get('PATH', '')}"
        )
        resolved = shutil.which(self._executable, path=search_path)
        if not resolved:
            return unresolved

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                resolved,
                "app-server",
                "--stdio",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            initialize = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "mini-me-capacity-read",
                        "title": "mini me capacity read",
                        "version": "1.0",
                    },
                    "capabilities": {},
                },
            }
            if proc.stdin is None or proc.stdout is None:
                return unresolved
            proc.stdin.write((json.dumps(initialize) + "\n").encode())
            await proc.stdin.drain()
            init_response = await self._read_app_server_response(
                proc.stdout, response_id=1, timeout_seconds=timeout_seconds
            )
            if init_response is None or "error" in init_response:
                return unresolved

            proc.stdin.write(
                (
                    json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}) + "\n"
                ).encode()
            )
            request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "account/rateLimits/read",
                "params": {},
            }
            proc.stdin.write((json.dumps(request) + "\n").encode())
            await proc.stdin.drain()
            response = await self._read_app_server_response(
                proc.stdout, response_id=2, timeout_seconds=timeout_seconds
            )
            if response is None or "error" in response:
                return unresolved
            result = response.get("result")
            return self.parse_rate_limits_result(
                result,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        except (OSError, asyncio.TimeoutError, ValueError, json.JSONDecodeError):
            return unresolved
        finally:
            if proc is not None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await proc.wait()
                except Exception:
                    pass

    @staticmethod
    def parse_rate_limits_result(
        result: object, *, observed_at: datetime, expires_at: datetime
    ) -> CapacityObservation:
        """Parse only the installed App Server's authoritative permission field."""
        unknown = CapacityObservation(
            provider="codex",
            ordinary_usage_allowed=None,
            observed_at=observed_at,
            expires_at=expires_at,
            source_signal=CapacitySignalSource.CODEX_APP_SERVER,
        )
        if not isinstance(result, dict):
            return unknown
        account_id = result.get("accountId")
        permission = result.get("ordinaryUsageAllowed")
        buckets = result.get("rateLimitsByLimitId")
        bucket = buckets.get("codex") if isinstance(buckets, dict) else None
        if not isinstance(bucket, dict):
            single = result.get("rateLimits")
            bucket = (
                single if isinstance(single, dict) and single.get("limitId") == "codex" else None
            )
        if (
            not isinstance(account_id, str)
            or not account_id.strip()
            or permission not in (True, False)
            or not isinstance(bucket, dict)
            or bucket.get("limitId") != "codex"
        ):
            return unknown
        reset_candidates = []
        for window_name in ("primary", "secondary"):
            window = bucket.get(window_name)
            reset = window.get("resetsAt") if isinstance(window, dict) else None
            if isinstance(reset, int) and reset > 0:
                try:
                    reset_candidates.append(datetime.fromtimestamp(reset, tz=UTC))
                except (OverflowError, OSError, ValueError):
                    pass
        return CapacityObservation(
            provider="codex",
            ordinary_usage_allowed=permission,
            observed_at=observed_at,
            expires_at=expires_at,
            source_signal=CapacitySignalSource.CODEX_APP_SERVER,
            account_id=account_id,
            model=bucket.get("normalModelSlug") or bucket.get("limitId"),
            capacity_reset_at=min(reset_candidates) if reset_candidates else None,
        )

    @staticmethod
    async def _read_app_server_response(
        stdout: asyncio.StreamReader, response_id: int, timeout_seconds: float
    ) -> dict | None:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            line = await asyncio.wait_for(stdout.readline(), timeout=remaining)
            if not line:
                return None
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(response, dict) and response.get("id") == response_id:
                return response

    def extract_capacity_signal(self, raw_output: str, exit_code: int = 0) -> CapacitySignal | None:
        lower_out = raw_output.lower()
        auth_keywords = [
            "401",
            "token_expired",
            "token is expired",
            "failed to refresh token",
            "please log out and sign in again",
            "authentication required",
            "not logged in",
            "login required",
            "unauthorized",
        ]
        if any(kw in lower_out for kw in auth_keywords):
            return CapacitySignal(
                result_class=ProviderResultClass.AUTH_ERROR,
                summary="Provider authentication token is expired or unauthorized (HTTP 401)",
                source_signal=CapacitySignalSource.RESPONSE_BODY_TIMESTAMP,
            )
        return None


class AntigravityProviderAdapter(ProviderAdapterInterface):
    """Provider adapter for Antigravity (agy) CLI."""

    SUPPORTED_GEMINI_MODELS: dict[str, str] = {
        "gemini models": "Gemini Models",
        "gemini flash": "Gemini Models",
        "gemini pro": "Gemini Models",
        "gemini-1.5-pro": "Gemini Models",
        "gemini-1.5-flash": "Gemini Models",
        "gemini-2.0-flash": "Gemini Models",
        "gemini 3.8 flash (high)": "Gemini Models",
        "google/gemini-1.5-pro": "Gemini Models",
        "google/gemini-1.5-flash": "Gemini Models",
        "google:gemini-1.5-pro": "Gemini Models",
        "google:gemini-1.5-flash": "Gemini Models",
    }

    @classmethod
    def map_model_to_quota_group(cls, model_name: str) -> str | None:
        norm = model_name.strip().lower()
        if norm in cls.SUPPORTED_GEMINI_MODELS:
            return cls.SUPPORTED_GEMINI_MODELS[norm]
        if norm.startswith("gemini-") or norm.startswith("gemini "):
            return "Gemini Models"
        return None

    def __init__(self, executable: str = "agy", model: str | None = None):
        self._executable = executable
        self._model = model

    @property
    def supports_read_only_capacity_observation(self) -> bool:
        return True

    @property
    def capacity_source_signal(self) -> CapacitySignalSource:
        return CapacitySignalSource.AGY_PRINT_USAGE

    @property
    def valid_capacity_source_signals(self) -> set[CapacitySignalSource]:
        # statusLine is demoted to non-authoritative telemetry and cannot authorize dispatch.
        # Only explicit headless print-mode /usage provides authoritative capacity evidence.
        return {CapacitySignalSource.AGY_PRINT_USAGE}

    @property
    def requires_account_identity_for_capacity(self) -> bool:
        return True

    def _resolve_executable(self) -> str | None:
        search_path = (
            f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:"
            f"{os.environ.get('PATH', '')}"
        )
        return shutil.which(self._executable, path=search_path)

    async def check_cli_present(self) -> bool:
        return self._resolve_executable() is not None

    async def check_auth_ready(self, timeout_seconds: float = 10.0) -> bool:
        # agy models is non-inference: it proves the CLI runs and that the account
        # and model catalog are reachable. It does NOT prove inference capacity;
        # capacity probing stays a separate operation.
        return await self.probe_availability(timeout_seconds=timeout_seconds)

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

    async def read_capacity_observation(
        self, timeout_seconds: float = 10.0, selected_model: str | None = None
    ) -> CapacityObservation:
        """Read the authenticated headless /usage quota snapshot without sending a turn.

        The CLI in headless print mode exposes the read-only /usage slash command, which
        returns model quota buckets without executing an agent turn or spending tokens.
        """
        observed_at = datetime.now(UTC)
        unknown = CapacityObservation(
            provider=self.provider_name,
            ordinary_usage_allowed=None,
            observed_at=observed_at,
            expires_at=observed_at,
            source_signal=self.capacity_source_signal,
        )
        resolved = self._resolve_executable()
        if not resolved or not await self.check_cli_present():
            logger.debug("AGY /usage capacity source unavailable: CLI not found")
            return unknown
        if not _AGY_STATUSLINE_LOCK.acquire(blocking=False):
            logger.debug("AGY capacity observation busy")
            return unknown
        try:
            return await self._read_print_usage_snapshot(
                resolved, timeout_seconds, selected_model=selected_model or self._model
            )
        except Exception as exc:
            logger.info(
                "Antigravity /usage capacity observation unavailable (%s)",
                type(exc).__name__,
            )
            return unknown
        finally:
            _AGY_STATUSLINE_LOCK.release()

    async def _read_print_usage_snapshot(
        self, executable: str, timeout_seconds: float, selected_model: str | None = None
    ) -> CapacityObservation:
        observed_at = datetime.now(UTC)
        unknown = CapacityObservation(
            provider=self.provider_name,
            ordinary_usage_allowed=None,
            observed_at=observed_at,
            expires_at=observed_at,
            source_signal=self.capacity_source_signal,
        )
        if Path(executable).name not in ("agy", "antigravity"):
            logger.debug("AGY /usage unsupported executable: %s", executable)
            return unknown

        with tempfile.TemporaryDirectory(prefix="minime-agy-usage-") as private_dir:
            private = Path(private_dir)
            os.chmod(private, 0o700)
            log_path = private / "cli.log"
            cmd = [
                executable,
                "--log-file",
                str(log_path),
                "--output-format",
                "json",
                "-p",
                "/usage",
            ]
            start_time = datetime.now(UTC)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(private.resolve()),
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except (OSError, asyncio.TimeoutError):
                    try:
                        proc.kill()
                        await proc.wait()
                    except OSError:
                        pass
                logger.debug("AGY /usage timed out")
                return unknown

            completion_time = datetime.now(UTC)
            if completion_time < start_time or completion_time > start_time + timedelta(
                seconds=timeout_seconds + 5
            ):
                return unknown
            observed_at = completion_time

            if proc.returncode != 0:
                logger.debug(
                    "AGY /usage exited %d: %s",
                    proc.returncode,
                    stderr.decode("utf-8", errors="replace"),
                )
                return unknown

            try:
                payload = json.loads(stdout.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return unknown

            account_fingerprint = None
            if not log_path.exists():
                return unknown
            try:
                log_text = log_path.read_text(encoding="utf-8", errors="replace")
                auth_events: list[tuple[str | None, str | None]] = []
                for line in log_text.splitlines():
                    if "applyAuthResult:" in line:
                        email_match = re.search(r"email=([^,\s\)]+)", line)
                        method_match = re.search(r"authMethod=([^,\s\)]+)", line)
                        email = email_match.group(1).strip().lower() if email_match else None
                        method = method_match.group(1).strip().lower() if method_match else None
                        auth_events.append((email, method))

                if not auth_events:
                    logger.debug("AGY /usage log missing applyAuthResult event")
                    return unknown

                for email, method in auth_events:
                    if not email or method != "consumer":
                        logger.debug(
                            "AGY /usage auth event not supported consumer: email=%s, method=%s",
                            email,
                            method,
                        )
                        return unknown

                unique_emails = {email for email, _ in auth_events}
                if len(unique_emails) != 1:
                    logger.debug(
                        "AGY /usage log contains conflicting account identities: %s",
                        unique_emails,
                    )
                    return unknown

                account_fingerprint = hashlib.sha256(list(unique_emails)[0].encode()).hexdigest()
            except OSError:
                return unknown

            return self.parse_print_usage_payload(
                payload,
                observed_at=observed_at,
                account_fingerprint=account_fingerprint,
                selected_model=selected_model,
            )

    async def _read_statusline_snapshot(
        self, executable: str, timeout_seconds: float
    ) -> CapacityObservation:
        import fcntl
        import pty
        import struct
        import termios

        observed_at = datetime.now(UTC)
        unknown = CapacityObservation(
            provider=self.provider_name,
            ordinary_usage_allowed=None,
            observed_at=observed_at,
            expires_at=observed_at,
            source_signal=self.capacity_source_signal,
        )
        home = Path.home().resolve(strict=True)
        settings_path = home / ".gemini" / "antigravity-cli" / "settings.json"
        settings_dir = settings_path.parent
        if (
            settings_path.is_symlink()
            or settings_dir.is_symlink()
            or (home / ".gemini").is_symlink()
            or settings_path.resolve(strict=True) != settings_path
            or settings_dir.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            logger.debug("AGY statusLine capacity source rejected unsafe settings path")
            return unknown
        mode = settings_path.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            logger.debug("AGY statusLine capacity source rejected non-private settings")
            return unknown
        original_bytes = settings_path.read_bytes()
        settings = json.loads(original_bytes)
        if not isinstance(settings, dict) or settings.get("statusLine") is not None:
            # Do not override or race an operator-managed statusLine hook.
            logger.debug("AGY statusLine capacity source rejected existing statusLine setting")
            return unknown

        with tempfile.TemporaryDirectory(prefix="minime-agy-capacity-") as private_dir:
            private = Path(private_dir)
            os.chmod(private, 0o700)
            snapshot_path = private / "snapshot.json"
            script_path = private / "capture.py"
            script = (
                "#!/usr/bin/env python3\n"
                "import datetime, hashlib, json, os, sys\n"
                "p=json.load(sys.stdin)\n"
                "email=p.get('email')\n"
                "o={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),"
                "'version':p.get('version'),'product':p.get('product'),"
                "'account_fingerprint':hashlib.sha256(email.encode()).hexdigest() "
                "if isinstance(email,str) and email else None,"
                "'session_id':p.get('session_id'),"
                "'conversation_id':p.get('conversation_id'),"
                "'callback_pid':os.getpid(),'callback_parent_pid':os.getppid(),"
                "'cwd':p.get('cwd'),'workspace':p.get('workspace'),"
                "'model':p.get('model'),'quota':p.get('quota'),"
                "'agent_state':p.get('agent_state')}\n"
                f"open({str(snapshot_path)!r}+'-'+str(o['callback_pid']),'w').write(json.dumps(o))\n"
            )
            script_path.write_text(script)
            os.chmod(script_path, 0o700)
            temporary_settings = dict(settings)
            temporary_settings["statusLine"] = {
                "type": "command",
                "command": str(script_path),
                "enabled": True,
            }
            installed_bytes = json.dumps(temporary_settings, indent=2).encode() + b"\n"
            lock_fd = os.open(settings_path, os.O_RDONLY)
            master_fd = slave_fd = None
            proc = None
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._atomic_replace_settings(settings_path, installed_bytes, stat.S_IMODE(mode))
                master_fd, slave_fd = pty.openpty()
                fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
                proc = await asyncio.create_subprocess_exec(
                    executable,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=str(private.resolve()),
                )
                os.close(slave_fd)
                slave_fd = None
                loop = asyncio.get_running_loop()
                deadline = loop.time() + timeout_seconds
                payload: dict[str, Any] | None = None
                callback_count = 0
                correlated_count = 0
                seen_callbacks: dict[Path, bytes] = {}

                def drain_pty() -> None:
                    try:
                        while os.read(master_fd, 8192):
                            pass
                    except (BlockingIOError, OSError):
                        pass

                os.set_blocking(master_fd, False)
                loop.add_reader(master_fd, drain_pty)
                try:
                    while loop.time() < deadline:
                        for callback_path in private.glob("snapshot.json-*"):
                            try:
                                raw_callback = callback_path.read_bytes()
                                if seen_callbacks.get(callback_path) == raw_callback:
                                    continue
                                seen_callbacks[callback_path] = raw_callback
                                candidate = json.loads(raw_callback)
                                callback_count += 1
                                if self._statusline_callback_matches_observer(
                                    candidate, proc.pid, str(private.resolve())
                                ):
                                    correlated_count += 1
                                    payload = candidate
                                    payload["observer_process_pid"] = proc.pid
                                    if candidate.get("agent_state") == "idle":
                                        break
                            except (OSError, json.JSONDecodeError):
                                continue
                        if payload is not None and payload.get("agent_state") == "idle":
                            break
                        if proc.returncode is not None:
                            break
                        await asyncio.sleep(0.05)
                finally:
                    loop.remove_reader(master_fd)
                observation = self.parse_statusline_payload(payload)
                logger.debug(
                    "AGY statusLine callback_count=%d correlated_count=%d cli_returncode=%s accepted=%s",
                    callback_count,
                    correlated_count,
                    proc.returncode,
                    observation.ordinary_usage_allowed is not None,
                )
                return observation
            finally:
                if proc is not None and proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                if master_fd is not None:
                    os.close(master_fd)
                if slave_fd is not None:
                    os.close(slave_fd)
                try:
                    current = json.loads(settings_path.read_bytes())
                    # Preserve concurrent unrelated preferences and never overwrite
                    # a statusLine the operator changed while the TUI was running.
                    if settings_path.read_bytes() == installed_bytes:
                        self._atomic_replace_settings(
                            settings_path, original_bytes, stat.S_IMODE(mode)
                        )
                    elif current.get("statusLine") == temporary_settings["statusLine"]:
                        current.pop("statusLine", None)
                        self._atomic_replace_settings(
                            settings_path,
                            json.dumps(current, indent=2).encode() + b"\n",
                            stat.S_IMODE(mode),
                        )
                finally:
                    os.close(lock_fd)

    @staticmethod
    def _statusline_callback_matches_observer(
        payload: object, observer_pid: int, observer_cwd: str
    ) -> bool:
        if not isinstance(payload, dict):
            return False
        callback_pid = payload.get("callback_pid")
        callback_parent_pid = payload.get("callback_parent_pid")
        if (
            not isinstance(callback_pid, int)
            or isinstance(callback_pid, bool)
            or callback_pid <= 1
            or not isinstance(callback_parent_pid, int)
            or isinstance(callback_parent_pid, bool)
            or callback_parent_pid <= 1
            or observer_pid <= 1
            or callback_pid == observer_pid
        ):
            return False
        workspace = payload.get("workspace")
        if (
            payload.get("cwd") != observer_cwd
            or not isinstance(workspace, dict)
            or workspace.get("current_dir") != observer_cwd
            or (
                workspace.get("project_dir") is not None
                and workspace.get("project_dir") != observer_cwd
            )
        ):
            return False
        session_id = payload.get("session_id")
        conversation_id = payload.get("conversation_id")
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 256:
            return False
        if conversation_id is not None and conversation_id != session_id:
            return False
        return True

    @staticmethod
    def _atomic_replace_settings(path: Path, content: bytes, mode: int) -> None:
        import tempfile

        fd, temporary_name = tempfile.mkstemp(prefix=".minime-statusline-", dir=path.parent)
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def parse_statusline_payload(payload: object) -> CapacityObservation:
        observed = datetime.now(UTC)
        unknown = CapacityObservation(
            provider="antigravity",
            ordinary_usage_allowed=None,
            observed_at=observed,
            expires_at=observed,
            source_signal=CapacitySignalSource.AGY_STATUSLINE,
        )
        if not isinstance(payload, dict) or payload.get("product") != "antigravity":
            return unknown
        raw_observed = payload.get("observed_at")
        try:
            observed_at = datetime.fromisoformat(raw_observed)
            if observed_at.tzinfo is None:
                return unknown
            observed_at = observed_at.astimezone(UTC)
        except (TypeError, ValueError):
            return unknown
        now = datetime.now(UTC)
        if observed_at > now + timedelta(seconds=5) or now - observed_at > timedelta(seconds=60):
            return unknown
        model = payload.get("model")
        model_id = model.get("id") if isinstance(model, dict) else None
        account_fingerprint = payload.get("account_fingerprint")
        buckets = payload.get("quota")
        if (
            payload.get("agent_state") != "idle"
            or not isinstance(model_id, str)
            or not model_id.strip()
            or not isinstance(account_fingerprint, str)
            or len(account_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in account_fingerprint)
            or not isinstance(buckets, dict)
            or not isinstance(payload.get("session_id"), str)
            or not payload.get("session_id", "").strip()
            or len(payload.get("session_id", "")) > 256
            or (
                payload.get("conversation_id") is not None
                and payload.get("conversation_id") != payload.get("session_id")
            )
        ):
            return unknown
        family = "gemini" if "gemini" in model_id.lower() else None
        if family is None:
            return unknown
        relevant = {
            key: value for key, value in buckets.items() if key in {"gemini-5h", "gemini-weekly"}
        }
        if set(relevant) != {"gemini-5h", "gemini-weekly"}:
            return unknown
        remaining = []
        for bucket in relevant.values():
            if not isinstance(bucket, dict):
                return unknown
            fraction = bucket.get("remaining_fraction")
            reset_text = bucket.get("reset_time")
            reset_seconds = bucket.get("reset_in_seconds")
            if (
                not isinstance(fraction, (int, float))
                or isinstance(fraction, bool)
                or not 0 <= fraction <= 1
                or not isinstance(reset_text, str)
                or not isinstance(reset_seconds, (int, float))
                or reset_seconds < 0
            ):
                return unknown
            try:
                reset_at = datetime.fromisoformat(reset_text.replace("Z", "+00:00"))
            except ValueError:
                return unknown
            if reset_at.tzinfo is None:
                return unknown
            delta = (reset_at.astimezone(UTC) - observed_at).total_seconds()
            if abs(delta - float(reset_seconds)) > 60:
                return unknown
            remaining.append(float(fraction))
        return CapacityObservation(
            provider="antigravity",
            ordinary_usage_allowed=all(value > 0 for value in remaining),
            observed_at=observed_at,
            expires_at=observed_at + timedelta(seconds=60),
            source_signal=CapacitySignalSource.AGY_STATUSLINE,
            account_id=account_fingerprint,
            model=model_id,
            source_session_id=payload["session_id"],
            capacity_reset_at=min(
                datetime.fromisoformat(b["reset_time"].replace("Z", "+00:00")).astimezone(UTC)
                for b in relevant.values()
            ),
        )

    @classmethod
    def parse_print_usage_payload(
        cls,
        payload: object,
        observed_at: datetime | None = None,
        account_fingerprint: str | None = None,
        selected_model: str | None = None,
    ) -> CapacityObservation:
        observed = observed_at or datetime.now(UTC)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        else:
            observed = observed.astimezone(UTC)
        unknown = CapacityObservation(
            provider="antigravity",
            ordinary_usage_allowed=None,
            observed_at=observed,
            expires_at=observed,
            source_signal=CapacitySignalSource.AGY_PRINT_USAGE,
        )
        if not isinstance(payload, dict):
            return unknown
        if payload.get("status") != "SUCCESS":
            return unknown

        # Positive proof of non-inferential execution is mandatory.
        # Absent or incomplete num_turns or usage data NEVER equates to zero consumption.
        if "num_turns" not in payload:
            return unknown
        num_turns = payload["num_turns"]
        if (
            num_turns is None
            or not isinstance(num_turns, int)
            or isinstance(num_turns, bool)
            or num_turns != 0
        ):
            return unknown

        if "usage" not in payload:
            return unknown
        usage_meta = payload["usage"]
        if not isinstance(usage_meta, dict):
            return unknown

        for req_key in ("total_tokens", "input_tokens", "output_tokens"):
            if req_key not in usage_meta:
                return unknown
            val = usage_meta[req_key]
            if val is None or not isinstance(val, int) or isinstance(val, bool) or val != 0:
                return unknown

        for opt_key in ("thinking_tokens", "cache_read_tokens"):
            if opt_key in usage_meta:
                opt_val = usage_meta[opt_key]
                if (
                    opt_val is None
                    or not isinstance(opt_val, int)
                    or isinstance(opt_val, bool)
                    or opt_val != 0
                ):
                    return unknown

        command = payload.get("command")
        if not isinstance(command, dict) or command.get("name") != "usage":
            return unknown
        cmd_data = command.get("data")
        if not isinstance(cmd_data, dict):
            return unknown
        groups = cmd_data.get("groups")
        if not isinstance(groups, list) or not groups:
            return unknown

        if (
            not isinstance(account_fingerprint, str)
            or len(account_fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in account_fingerprint)
        ):
            return unknown

        target_model = selected_model or "Gemini Models"
        mapped_group_name = cls.map_model_to_quota_group(target_model)
        if mapped_group_name is None:
            return unknown

        matching_groups = [
            g
            for g in groups
            if isinstance(g, dict) and mapped_group_name.lower() in str(g.get("name", "")).lower()
        ]
        if len(matching_groups) != 1:
            return unknown
        gemini_group = matching_groups[0]

        buckets = gemini_group.get("buckets")
        if not isinstance(buckets, list) or not buckets:
            return unknown

        seen_bucket_ids = set()
        bucket_map = {}
        for b in buckets:
            if not isinstance(b, dict):
                return unknown
            b_id = b.get("id")
            if not isinstance(b_id, str) or not b_id.strip():
                return unknown
            if b_id in seen_bucket_ids:
                return unknown
            seen_bucket_ids.add(b_id)
            bucket_map[b_id] = b

        if not {"gemini-5h", "gemini-weekly"}.issubset(bucket_map.keys()):
            return unknown

        remaining_fractions = []
        reset_datetimes = []
        for bucket_id in ("gemini-5h", "gemini-weekly"):
            b = bucket_map[bucket_id]
            if "remaining_fraction" not in b:
                return unknown
            fraction = b.get("remaining_fraction")
            if (
                fraction is None
                or not isinstance(fraction, (int, float))
                or isinstance(fraction, bool)
                or not 0 <= fraction <= 1
            ):
                return unknown
            reset_text = b.get("reset_time")
            if not isinstance(reset_text, str) or not reset_text.strip():
                return unknown
            try:
                reset_at = datetime.fromisoformat(reset_text.replace("Z", "+00:00"))
            except ValueError:
                return unknown
            if reset_at.tzinfo is None:
                return unknown
            reset_utc = reset_at.astimezone(UTC)
            if reset_utc <= observed:
                return unknown
            reset_datetimes.append(reset_utc)
            remaining_fractions.append(float(fraction))

        model_name = (
            selected_model if selected_model else (gemini_group.get("name") or "Gemini Models")
        )
        allowed = all(f > 0 for f in remaining_fractions)
        return CapacityObservation(
            provider="antigravity",
            ordinary_usage_allowed=allowed,
            observed_at=observed,
            expires_at=observed + timedelta(seconds=60),
            source_signal=CapacitySignalSource.AGY_PRINT_USAGE,
            account_id=account_fingerprint,
            model=model_name,
            capacity_reset_at=min(reset_datetimes),
        )


class OpenRouterProviderAdapter(ProviderAdapterInterface):
    """Provider adapter for OpenRouter API."""

    def __init__(
        self,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key_env: str = "OPENROUTER_API_KEY",
    ):
        self._base_url = base_url
        self._api_key_env = api_key_env

    async def check_auth_ready(self, timeout_seconds: float = 10.0) -> bool:
        del timeout_seconds
        return bool(os.environ.get(self._api_key_env, "").strip())

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

    async def check_auth_ready(self, timeout_seconds: float = 10.0) -> bool:
        del timeout_seconds
        return bool(os.environ.get(self._api_key_env, "").strip())

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
    """Test-only provider double. Never selected by the operational adapter registry."""

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

    @property
    def probe_verifies_capacity(self) -> bool:
        # Test/future double: `available=True` simulates verified capacity recovery.
        return True

    async def probe_availability(self, timeout_seconds: float = 30.0) -> bool:
        self.probe_call_count += 1
        return self.available


# Global registry for pluggable provider adapters
_ADAPTER_REGISTRY: dict[str, ProviderAdapterInterface] = {}


def register_provider_adapter(adapter: ProviderAdapterInterface) -> None:
    """Register or override a provider adapter."""
    if isinstance(adapter, FakeProviderAdapter) and "pytest" not in sys.modules:
        raise RuntimeError("FakeProviderAdapter is restricted to test processes.")
    _ADAPTER_REGISTRY[adapter.provider_name] = adapter


def get_provider_adapter(
    provider: str, config: AppConfig | None = None
) -> ProviderAdapterInterface:
    """Get the registered provider adapter or construct a default instance."""
    if provider in _ADAPTER_REGISTRY:
        adapter = _ADAPTER_REGISTRY[provider]
        if isinstance(adapter, FakeProviderAdapter) and "pytest" not in sys.modules:
            raise RuntimeError("FakeProviderAdapter is restricted to test processes.")
        return adapter

    app_config = config or load_config()
    p_config = app_config.providers.get(provider)

    if provider == "codex":
        cmd = p_config.command if p_config and p_config.command else "codex"
        adapter = CodexProviderAdapter(executable=cmd)
    elif provider == "antigravity":
        cmd = p_config.command if p_config and p_config.command else "agy"
        adapter = AntigravityProviderAdapter(executable=cmd)
    elif provider == "openrouter":
        url = (
            p_config.base_url if p_config and p_config.base_url else "https://openrouter.ai/api/v1"
        )
        key_env = (
            p_config.api_key_env if p_config and p_config.api_key_env else "OPENROUTER_API_KEY"
        )
        adapter = OpenRouterProviderAdapter(base_url=url, api_key_env=key_env)
    elif provider == "deepseek":
        url = p_config.base_url if p_config and p_config.base_url else "https://api.deepseek.com"
        key_env = p_config.api_key_env if p_config and p_config.api_key_env else "DEEPSEEK_API_KEY"
        adapter = DeepSeekProviderAdapter(base_url=url, api_key_env=key_env)
    else:
        raise ValueError(
            f"No operational provider adapter registered for unknown provider '{provider}'."
        )

    _ADAPTER_REGISTRY[provider] = adapter
    return adapter
