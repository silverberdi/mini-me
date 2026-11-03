"""Canonical provider/model registry, safe CLI discovery, and admin DTOs."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from minime.db.models import ProviderModelRegistryModel, utc_now

_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")
_SECRET = re.compile(r"(?i)(token|secret|password|private[_ -]?key|api[_ -]?key|credential)")


class DiagnosticDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    summary: str
    verified: bool = False


class ProviderModelDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    provider_id: str
    harness_id: str
    canonical_model_id: str
    origin: str
    max_context_tokens: int | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    discovery_status: str
    diagnostic: DiagnosticDTO | None = None
    observed_cli_version: str | None = None
    last_observed_at: datetime | None = None
    version: int


class CustomModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str
    harness_id: str
    canonical_model_id: str
    max_context_tokens: int | None = Field(default=None, ge=0)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    version: int | None = Field(default=None, gt=0)

    @field_validator("provider_id", "harness_id", "canonical_model_id")
    @classmethod
    def valid_identity(cls, value: str) -> str:
        value = value.strip().lower()
        if not _IDENTITY.fullmatch(value) or _SECRET.search(value):
            raise ValueError("identifier is invalid")
        return value

    @field_validator("capabilities")
    @classmethod
    def safe_capabilities(cls, value: dict[str, bool]) -> dict[str, bool]:
        if any(_SECRET.search(key) for key in value):
            raise ValueError("secret capability metadata is not allowed")
        return {str(key): bool(flag) for key, flag in value.items()}


def _identity_id(provider_id: str, harness_id: str, model_id: str) -> str:
    return uuid5(NAMESPACE_URL, f"mini-me/provider-model/{provider_id}/{harness_id}/{model_id}").hex


def _dto(row: ProviderModelRegistryModel) -> ProviderModelDTO:
    diagnostic = None
    if row.diagnostic_code or row.diagnostic_summary:
        diagnostic = DiagnosticDTO(
            code=row.diagnostic_code or "unknown",
            summary=row.diagnostic_summary or "No diagnostic available",
            verified=row.discovery_status == "available",
        )
    return ProviderModelDTO(
        id=row.id, provider_id=row.provider_id, harness_id=row.harness_id,
        canonical_model_id=row.canonical_model_id, origin=row.origin,
        max_context_tokens=row.max_context_tokens, capabilities=dict(row.capabilities or {}),
        discovery_status=row.discovery_status, diagnostic=diagnostic,
        observed_cli_version=row.observed_cli_version,
        last_observed_at=row.last_observed_at, version=row.version,
    )


class ProviderModelRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, provider_id: str, harness_id: str, model_id: str, *, for_update: bool = False) -> ProviderModelRegistryModel | None:
        statement = select(ProviderModelRegistryModel).where(
            ProviderModelRegistryModel.provider_id == provider_id,
            ProviderModelRegistryModel.harness_id == harness_id,
            ProviderModelRegistryModel.canonical_model_id == model_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list(self) -> list[ProviderModelRegistryModel]:
        return list(self.session.scalars(select(ProviderModelRegistryModel).order_by(
            ProviderModelRegistryModel.provider_id,
            ProviderModelRegistryModel.harness_id,
            ProviderModelRegistryModel.canonical_model_id,
        )))

    def record_harness_diagnostic(
        self,
        harness_id: str,
        result: IntrospectionResult,
    ) -> None:
        """Attach a bounded observation to existing non-custom entries.

        A failed refresh must make previously observed entries unusable instead
        of leaving stale availability in place. Custom metadata is intentionally
        preserved and still requires a separate verified observation.
        """
        now = utc_now()
        rows = self.session.scalars(
            select(ProviderModelRegistryModel).where(
                ProviderModelRegistryModel.harness_id == harness_id,
                ProviderModelRegistryModel.origin != "custom",
            )
        )
        for row in rows:
            row.discovery_status = result.status if result.status in {"available", "unavailable", "blocked"} else "blocked"
            row.diagnostic_code = result.code
            row.diagnostic_summary = result.summary
            row.observed_cli_version = result.cli_version
            row.last_observed_at = now
            row.version += 1
            row.updated_at = now

    def upsert_observation(self, observation: dict[str, Any]) -> ProviderModelRegistryModel:
        row = self.get(observation["provider_id"], observation["harness_id"], observation["canonical_model_id"])
        now = utc_now()
        created = False
        if row is None:
            row = ProviderModelRegistryModel(id=_identity_id(observation["provider_id"], observation["harness_id"], observation["canonical_model_id"]), origin=observation.get("origin", "discovered"), version=1, created_at=now, updated_at=now, **{k: v for k, v in observation.items() if k != "origin"})
            try:
                with self.session.begin_nested():
                    self.session.add(row)
                    self.session.flush()
            except IntegrityError:
                row = self.get(observation["provider_id"], observation["harness_id"], observation["canonical_model_id"], for_update=True)
                if row is None:
                    raise
            else:
                created = True
        if not created and row.origin != "custom":
            for key in ("max_context_tokens", "capabilities", "discovery_status", "diagnostic_code", "diagnostic_summary", "observed_cli_version", "last_observed_at"):
                if key in observation:
                    setattr(row, key, observation[key])
            row.origin = observation.get("origin", row.origin)
            row.version += 1
            row.updated_at = now
        self.session.flush()
        return row

    def upsert_custom(self, payload: CustomModelRequest) -> ProviderModelRegistryModel:
        row = self.get(payload.provider_id, payload.harness_id, payload.canonical_model_id, for_update=True)
        now = utc_now()
        created = False
        if row is None:
            row = ProviderModelRegistryModel(
                id=_identity_id(payload.provider_id, payload.harness_id, payload.canonical_model_id),
                provider_id=payload.provider_id, harness_id=payload.harness_id,
                canonical_model_id=payload.canonical_model_id, origin="custom",
                max_context_tokens=payload.max_context_tokens, capabilities=payload.capabilities,
                discovery_status="unavailable", diagnostic_code="custom_metadata",
                diagnostic_summary="Operator-defined metadata; harness verification required",
                version=1, created_at=now, updated_at=now,
            )
            try:
                with self.session.begin_nested():
                    self.session.add(row)
                    self.session.flush()
            except IntegrityError:
                row = self.get(payload.provider_id, payload.harness_id, payload.canonical_model_id, for_update=True)
                if row is None:
                    raise
            else:
                created = True
        if not created:
            if payload.version is not None and payload.version != row.version:
                raise ValueError("stale provider model version")
            if (
                row.origin == "custom"
                and row.max_context_tokens == payload.max_context_tokens
                and dict(row.capabilities or {}) == payload.capabilities
            ):
                # A retry of the same operator request is idempotent.  Do not
                # manufacture a version change for a request whose durable
                # state is already identical.
                return row
            row.origin = "custom"
            row.max_context_tokens = payload.max_context_tokens
            row.capabilities = payload.capabilities
            row.version += 1
            row.updated_at = now
        self.session.flush()
        return row


@dataclass(frozen=True)
class IntrospectionResult:
    harness_id: str
    status: str
    code: str
    summary: str
    cli_version: str | None = None
    models: tuple[str, ...] = ()


def classify_discovered_model(harness_id: str, model_id: str) -> tuple[str, str, str]:
    """Return the canonical provider, harness and route for one observation."""
    canonical = model_id.strip().lower()
    if harness_id == "opencode":
        if canonical.startswith("deepseek/"):
            return "deepseek", harness_id, "deepseek_direct"
        if canonical.startswith("openrouter/"):
            return "openrouter", harness_id, "openrouter"
        if canonical.startswith("opencode/"):
            return "opencode", harness_id, "opencode_native"
        raise ValueError("OpenCode returned an unnamespaced model")
    return harness_id, harness_id, "local"


class ReadOnlyHarness(Protocol):
    harness_id: str
    async def inspect(self) -> IntrospectionResult: ...


class SafeCliHarness:
    """Run only exact, read-only argv pairs; user input never becomes a command."""
    ALLOWLIST = {
        "opencode": (("--version",), ("models",)),
        "ollama": (("--version",), ("list",)),
    }

    def __init__(
        self,
        harness_id: str,
        executable: str,
        *,
        timeout_seconds: float = 10.0,
        credential_env: str | None = None,
    ):
        if harness_id not in self.ALLOWLIST:
            raise ValueError("unsupported harness")
        self.harness_id, self.executable = harness_id, executable
        self.timeout_seconds = timeout_seconds
        self.credential_env = credential_env

    async def _run(self, args: tuple[str, ...]) -> tuple[int, str, str]:
        if args not in self.ALLOWLIST[self.harness_id]:
            raise ValueError("command is not allowlisted")
        resolved = shutil.which(self.executable)
        if not resolved:
            raise FileNotFoundError(self.executable)
        proc = await asyncio.create_subprocess_exec(resolved, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise TimeoutError("harness introspection timed out")
        return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")

    async def inspect(self) -> IntrospectionResult:
        # Presence is all that can be safely reported here.  The secret value
        # is never read into a DTO, log record, exception, or registry row.
        if self.credential_env:
            import os

            if not os.environ.get(self.credential_env):
                return IntrospectionResult(
                    self.harness_id,
                    "unavailable",
                    "credential_missing",
                    "Configured credential is unavailable",
                )
        try:
            version_code, version_out, version_err = await self._run(("--version",))
            list_code, list_out, list_err = await self._run(("models" if self.harness_id == "opencode" else "list",))
        except FileNotFoundError:
            return IntrospectionResult(self.harness_id, "unavailable", "cli_missing", "Configured CLI is not installed")
        except TimeoutError as exc:
            return IntrospectionResult(self.harness_id, "blocked", "timeout", str(exc))
        except (OSError, ValueError) as exc:
            return IntrospectionResult(self.harness_id, "blocked", "introspection_rejected", str(exc))
        if version_code != 0 or list_code != 0:
            return IntrospectionResult(self.harness_id, "blocked", "cli_error", "Read-only CLI command failed")
        version = (version_out or version_err).strip().splitlines()[0] if (version_out or version_err).strip() else None
        models = _parse_model_output(self.harness_id, list_out)
        if not models:
            return IntrospectionResult(self.harness_id, "unavailable", "malformed_output", "CLI returned no parseable models", version)
        return IntrospectionResult(self.harness_id, "available", "ok", "Read-only introspection succeeded", version, models)


def reject_secret_payload(payload: Any) -> None:
    """Reject secret-bearing metadata before it reaches persistence or logging."""
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if _SECRET.search(str(key)):
                    raise ValueError("secret material is not accepted")
                walk(child)
        elif isinstance(value, (list, tuple, set)):
            for child in value:
                walk(child)

    walk(payload)
    raw = json.dumps(payload, default=str).lower()
    if any(value in raw for value in ("-----begin", "bearer ", "sk-")):
        raise ValueError("secret material is not accepted")


def _parse_model_output(harness_id: str, output: str) -> tuple[str, ...]:
    """Parse only the model column emitted by supported read-only CLIs."""
    models: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or set(line) <= {"-", " ", "|"}:
            continue
        columns = [part.strip() for part in line.strip("|").split() if part.strip()]
        if not columns:
            continue
        candidate = columns[0].lower()
        if candidate in {"model", "name", "models", "id"}:
            continue
        if harness_id == "opencode" and "/" not in candidate:
            continue
        if not _IDENTITY.fullmatch(candidate):
            continue
        if candidate not in models:
            models.append(candidate)
    return tuple(models)


def catalog_payload(rows: Sequence[ProviderModelRegistryModel]) -> dict[str, Any]:
    models = [_dto(row).model_dump(mode="json") for row in rows]
    providers: dict[str, dict[str, Any]] = {}
    harnesses: dict[str, dict[str, Any]] = {}
    for model in models:
        providers.setdefault(model["provider_id"], {"id": model["provider_id"], "harnesses": []})
        harnesses.setdefault(model["harness_id"], {"id": model["harness_id"], "providers": []})
        if model["harness_id"] not in providers[model["provider_id"]]["harnesses"]:
            providers[model["provider_id"]]["harnesses"].append(model["harness_id"])
        if model["provider_id"] not in harnesses[model["harness_id"]]["providers"]:
            harnesses[model["harness_id"]]["providers"].append(model["provider_id"])
    return {"providers": list(providers.values()), "harnesses": list(harnesses.values()), "models": models}


ROLE_CAPABILITIES = {
    "thinker": ("thinking", "workflow"),
    "implementer": ("file_edit", "workflow"),
    "reviewer": ("read_only_review",),
    "backup": ("workflow",),
}


class CanonicalProfileResolver:
    """Resolve role assignments only from an observed canonical registry row."""

    def __init__(self, repository: ProviderModelRepository, freshness: timedelta = timedelta(hours=24)):
        self.repository, self.freshness = repository, freshness

    def resolve(self, role: str, selection: dict[str, Any]) -> dict[str, Any]:
        provider = str(selection.get("provider_id", "")).strip().lower()
        harness = str(selection.get("harness_id", "")).strip().lower()
        model = str(selection.get("canonical_model_id", "")).strip().lower()
        row = self.repository.get(provider, harness, model)
        if row is None:
            raise ValueError(f"{role}: model is absent from provider catalog")
        if row.discovery_status != "available":
            raise ValueError(f"{role}: model diagnostic is {row.discovery_status}")
        if row.last_observed_at is not None and row.last_observed_at < utc_now() - self.freshness:
            raise ValueError(f"{role}: model observation is stale")
        if not row.diagnostic_code or row.diagnostic_code not in {"ok", "custom_metadata"}:
            raise ValueError(f"{role}: credential or harness diagnostic is not verified")
        for capability in ROLE_CAPABILITIES.get(role, ()):
            if not bool((row.capabilities or {}).get(capability)):
                raise ValueError(f"{role}: missing capability {capability}")
        observed_route = (row.capabilities or {}).get("model_route")
        selected_route = selection.get("route")
        if selected_route and observed_route and selected_route != observed_route:
            raise ValueError(f"{role}: route does not match canonical catalog entry")
        return {
            "provider_id": row.provider_id,
            "harness_id": row.harness_id,
            "model": row.canonical_model_id,
            "canonical_model_id": row.canonical_model_id,
            "effort": selection.get("effort"),
            "route": selected_route or observed_route,
        }

    def resolve_roles(self, profiles: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        resolved = {}
        for role in ("thinker", "implementer", "reviewer", "backup"):
            if role not in profiles:
                raise ValueError(f"missing role {role}")
            resolved[role] = self.resolve(role, profiles[role])
        return resolved


def resolveAgentForModel(repository: ProviderModelRepository, selection: dict[str, Any]) -> dict[str, Any]:
    """Compatibility spelling retained for existing UI consumers."""
    return CanonicalProfileResolver(repository).resolve("implementer", selection)


def buildProfile(repository: ProviderModelRepository, role: str, selection: dict[str, Any]) -> dict[str, Any]:
    return CanonicalProfileResolver(repository).resolve(role, selection)


def getRoleModel(repository: ProviderModelRepository, role: str, selection: dict[str, Any]) -> str:
    return buildProfile(repository, role, selection)["canonical_model_id"]
