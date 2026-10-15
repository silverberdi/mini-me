"""Configuration handling for mini me."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class OpenSpecStage(str, Enum):
    PLAN = "PLAN"
    CONTRACT_REVIEW = "CONTRACT_REVIEW"
    APPLY = "APPLY"
    TEST = "TEST"
    VERIFY = "VERIFY"
    REVIEW = "REVIEW"


class StageProfileConfig(BaseModel):
    provider: str
    model: str | None = None
    effort: str | None = None
    workflow: str | None = None
    cost_basis: str = "standard"
    is_premium: bool = False


class StageProfileError(ValueError):
    """Raised when stage profile resolution or capability validation fails."""


SUPPORTED_PROVIDER_MODELS: dict[str, dict[str, bool]] = {
    # provider -> {model_name: is_premium}
    "antigravity": {
        "gemini-3.8-flash-low": False,
        "gemini-3.8-flash-medium": False,
        "gemini-3.8-flash-high": False,
        "gemini-2.5-flash": False,
        "gemini-2.0-flash": False,
        "gemini-flash": False,
        "claude-sonnet-5-5-low": False,
        "claude-sonnet-5-5-medium": False,
        "claude-sonnet-5-5-high": False,
        "gpt-oss-120b-medium": False,
        "gemini-2.5-pro": True,
        "gemini-pro": True,
        "gemini-1.5-pro": True,
        "claude-opus-5-5-low": True,
        "claude-opus-5-5-medium": True,
        "claude-opus-5-5-high": True,
    },
    "codex": {
        "gpt-5.6-luna": False,
        "gpt-6-luna": False,
        "gpt-5.6-sol": True,
        "gpt-5.6-terra": True,
        "gpt-6-sol": True,
        "gpt-6.1-sol": True,
        "gpt-6-astra": True,
        "gpt-5.5": False,
        "gpt-4o-mini": False,
        "o3-mini": False,
        "codex-mini": False,
        "gpt-4o": True,
        "o1": True,
        "o1-preview": True,
        "o1-mini": True,
    },
    "deepseek": {
        "deepseek-chat": False,
        "deepseek-reasoner": True,
    },
}

SUPPORTED_PROVIDER_EFFORTS: dict[str, set[str]] = {
    "antigravity": {"low", "medium", "high", "xhigh", "max"},
    "codex": {"low", "medium", "high", "xhigh", "max"},
    "deepseek": {"low", "medium"},
}

DEFAULT_R01_STAGE_PROFILES: dict[str, StageProfileConfig] = {
    "PLAN": StageProfileConfig(
        provider="codex",
        model="gpt-5.6-luna",
        effort="medium",
        workflow="openspec-propose",
    ),
    "CONTRACT_REVIEW": StageProfileConfig(
        provider="deepseek",
        model="deepseek-chat",
        effort="low",
        workflow="openspec-explore",
    ),
    "APPLY": StageProfileConfig(
        provider="antigravity",
        model="gemini-3.8-flash-medium",
        effort="medium",
        workflow="openspec-apply-change",
    ),
    "TEST": StageProfileConfig(
        provider="antigravity",
        model="gemini-3.8-flash-low",
        effort="low",
        workflow="deterministic-tests",
    ),
    "VERIFY": StageProfileConfig(
        provider="codex",
        model="gpt-5.6-luna",
        effort="medium",
        workflow="openspec-verify-change",
    ),
    "REVIEW": StageProfileConfig(
        provider="codex",
        model="gpt-5.6-luna",
        effort="medium",
        workflow="review",
    ),
}


class ServerConfig(BaseModel):
    bind_host: str = "127.0.0.1"
    bind_port: int = 8787


class DatabaseConfig(BaseModel):
    url_env: str = "MINIME_DATABASE_URL"
    url: str | None = None

    def resolve_url(self) -> str:
        """Resolve the PostgreSQL database URL from the environment or explicit config."""
        if self.url:
            raw_url = self.url
        else:
            raw_url = os.environ.get(self.url_env, "")
            if not raw_url:
                discover_and_load_env_file()
                raw_url = os.environ.get(self.url_env, "")

        if not raw_url:
            raise ValueError(
                f"Database URL is not configured. Please set the '{self.url_env}' "
                f"environment variable."
            )

        # Enforce PostgreSQL dialect
        if not raw_url.startswith(("postgresql://", "postgresql+")):
            raise ValueError(
                f"Invalid database URL: '{raw_url}'. mini me strictly requires PostgreSQL."
            )
        return raw_url


class PathsConfig(BaseModel):
    repos_root: str = "/var/lib/minime/repos"
    worktrees_root: str = "/var/lib/minime/worktrees"
    runtime_root: str = "/var/lib/minime/runtime"


class SchedulerConfig(BaseModel):
    max_global_jobs: int = 1
    mode: str = "RUN"
    one_active_implementation_per_project: bool = True
    max_review_rounds: int = 2


class ProbeConfig(BaseModel):
    cooldown_seconds: int = 300
    backoff_base_seconds: int = 300
    backoff_max_seconds: int = 3600
    max_per_hour: int = 4

    @field_validator(
        "cooldown_seconds", "backoff_base_seconds", "backoff_max_seconds", "max_per_hour"
    )
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("probe timing/rate values must be non-negative")
        return v

    @field_validator("backoff_max_seconds")
    @classmethod
    def _backoff_max_ge_base(cls, v: int, info) -> int:
        base = info.data.get("backoff_base_seconds")
        if base is not None and v < base:
            raise ValueError("backoff_max_seconds must be >= backoff_base_seconds")
        return v


class CliInvocationConfig(BaseModel):
    args: list[str] = Field(default_factory=list)
    prompt_transport: str = "stdin"
    model: str | None = None
    effort: str | None = None


class ProviderConfig(BaseModel):
    type: str = "cli"
    command: str | None = None
    enabled: bool = True
    roles: list[str] = Field(default_factory=list)
    invocation: dict[str, CliInvocationConfig] = Field(default_factory=dict)
    base_url: str | None = None
    api_key_env: str | None = None
    paid: bool = False
    mode: str | None = None
    budget: dict[str, Any] = Field(default_factory=dict)
    drain: dict[str, Any] = Field(default_factory=dict)
    probe: ProbeConfig = Field(default_factory=ProbeConfig)


class BudgetConfig(BaseModel):
    enabled: bool = False
    daily_cap_usd: Decimal = Field(default_factory=lambda: Decimal("0.0"))
    monthly_cap_usd: Decimal = Field(default_factory=lambda: Decimal("0.0"))
    currency: str = "USD"
    policy_version: int = 1


class OpenRouterConfig(BaseModel):
    enabled: bool = False
    api_key_env: str = "OPENROUTER_API_KEY"
    base_url: str = "https://openrouter.ai/api/v1"
    model: str | None = None
    fallback_models: list[str] = Field(default_factory=list)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)


class GitHubConfig(BaseModel):
    account_scope: str = "personal"
    owner: str = ""
    app_id_env: str = "MINIME_GITHUB_APP_ID"
    installation_id_env: str = "MINIME_GITHUB_INSTALLATION_ID"
    private_key_path_env: str = "MINIME_GITHUB_PRIVATE_KEY_PATH"
    global_project_number: int | None = None


class SecurityConfig(BaseModel):
    redact_secrets: bool = True
    autonomous_merge: bool = False
    allow_paid_fallback_by_default: bool = False


class AuthConfig(BaseModel):
    enabled: bool = True
    provider: str = "google"
    client_id_env: str = "GOOGLE_CLIENT_ID"
    client_secret_env: str = "GOOGLE_CLIENT_SECRET"
    client_secret_path: str = "/etc/minime/secrets/google_oauth_client_secret"
    authorized_operators_env: str = "MINIME_AUTHORIZED_OPERATORS"
    redirect_uri: str | None = None
    session_lifetime_seconds: int = 604800
    cookie_secure: str = "auto"
    authorized_operators: list[dict[str, Any]] = Field(default_factory=list)


class ProjectDeploymentPreviewConfig(BaseModel):
    required_for_ui_changes: bool = True
    strategy: str = "compose"
    ui_url: str | None = None
    compose_file: str | None = None


class ProjectDeploymentProductionConfig(BaseModel):
    deploy_after_merge: bool = True
    compose_file: str | None = None
    rollback_requires_human: bool = True


class ProjectDeploymentConfig(BaseModel):
    preview: ProjectDeploymentPreviewConfig = Field(default_factory=ProjectDeploymentPreviewConfig)
    production: ProjectDeploymentProductionConfig = Field(
        default_factory=ProjectDeploymentProductionConfig
    )


class ProjectConfig(BaseModel):
    enabled: bool = True
    repository: str  # owner/repo or local/remote path
    base_branch: str = "main"
    openspec_path: str = "openspec"
    implementer: str = "codex"
    reviewer: str = "antigravity"
    checks: list[dict[str, Any]] = Field(default_factory=list)
    external_providers_allowed: list[str] = Field(
        default_factory=lambda: ["codex", "antigravity", "deepseek"]
    )
    openrouter_drain_allowed: bool = False
    deployment: ProjectDeploymentConfig = Field(default_factory=ProjectDeploymentConfig)
    stage_profiles: dict[str, StageProfileConfig] = Field(default_factory=dict)


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    projects: dict[str, ProjectConfig] = Field(default_factory=dict)


@dataclass(frozen=True)
class CliInvocationProfile:
    provider: str
    role: str
    executable: str
    args: tuple[str, ...]
    prompt_transport: str
    model: str | None = None
    effort: str | None = None


@dataclass(frozen=True)
class ResolvedStageProfile:
    stage: str
    provider: str
    model: str
    effort: str
    workflow: str
    cost_basis: str
    is_premium: bool
    is_escalated: bool
    cli_invocation: CliInvocationProfile | None = None


def resolve_cli_invocation(
    provider: str,
    role: str,
    config: AppConfig | None = None,
    *,
    model: str | None = None,
    effort: str | None = None,
) -> CliInvocationProfile:
    """Resolve and validate one provider/role CLI invocation from app configuration."""
    app_config = config or load_config()
    provider_key = provider.lower()
    provider_config = app_config.providers.get(provider_key)
    if provider_config is None and provider_key == "agy":
        provider_config = app_config.providers.get("antigravity")
    elif provider_config is None and provider_key == "antigravity":
        provider_config = app_config.providers.get("agy")
    if provider_config is None:
        raise ValueError(f"CLI provider '{provider}' is not configured.")
    if not provider_config.enabled:
        raise ValueError(f"CLI provider '{provider}' is disabled.")
    if provider_config.type != "cli":
        raise ValueError(f"Provider '{provider}' is not configured as a CLI provider.")
    if role not in provider_config.roles:
        raise ValueError(f"Provider '{provider}' does not allow role '{role}'.")
    executable = (provider_config.command or "").strip()
    if not executable:
        raise ValueError(f"CLI provider '{provider}' has no executable command configured.")
    invocation = provider_config.invocation.get(role)
    if invocation is None:
        raise ValueError(f"CLI provider '{provider}' has no invocation profile for role '{role}'.")
    if invocation.prompt_transport not in {"stdin", "argument"}:
        raise ValueError(
            f"Unsupported prompt transport '{invocation.prompt_transport}' for provider "
            f"'{provider}' role '{role}'."
        )
    if any(not isinstance(arg, str) for arg in invocation.args):
        raise ValueError(f"CLI provider '{provider}' has non-string invocation arguments.")
    if invocation.prompt_transport == "argument" and not any(
        "{prompt}" in arg for arg in invocation.args
    ):
        raise ValueError(
            f"CLI provider '{provider}' argument transport requires a '{{prompt}}' argument "
            f"for role '{role}'."
        )

    effective_model = model or invocation.model
    effective_effort = effort or invocation.effort
    args_list = list(invocation.args)

    if provider.lower() in ("antigravity", "agy"):
        if effective_model and "--model" not in args_list:
            prompt_idx = next(
                (i for i, a in enumerate(args_list) if "{prompt}" in a), len(args_list)
            )
            args_list[prompt_idx:prompt_idx] = ["--model", effective_model]
        if effective_effort and "--effort" not in args_list:
            prompt_idx = next(
                (i for i, a in enumerate(args_list) if "{prompt}" in a), len(args_list)
            )
            args_list[prompt_idx:prompt_idx] = ["--effort", effective_effort]
    elif provider.lower() == "codex":
        if effective_model and "--model" not in args_list and "-m" not in args_list:
            args_list.extend(["--model", effective_model])
        if effective_effort and "model_reasoning_effort" not in " ".join(args_list):
            args_list.extend(["-c", f'model_reasoning_effort="{effective_effort}"'])

    return CliInvocationProfile(
        provider=provider,
        role=role,
        executable=executable,
        args=tuple(args_list),
        prompt_transport=invocation.prompt_transport,
        model=effective_model,
        effort=effective_effort,
    )


def resolve_stage_profile(
    project_config: ProjectConfig,
    stage: str | OpenSpecStage,
    *,
    app_config: AppConfig | None = None,
    escalation_authorized: bool = False,
    escalation_rationale: str | None = None,
    budget_authorized: bool = False,
    implementer_provider: str | None = None,
    requested_provider: str | None = None,
    requested_model: str | None = None,
    requested_effort: str | None = None,
) -> ResolvedStageProfile:
    """Resolve and validate an independent, static profile for one OpenSpec stage.

    Enforces non-premium and bounded-effort defaults. Unsupported models, unsupported
    efforts, unbudgeted/unjustified escalation, and same-author review fail closed.
    """
    stage_str = stage.value if isinstance(stage, OpenSpecStage) else str(stage).strip().upper()
    if stage_str in ("VERIFY_E2E", "VERIFY-E2E"):
        stage_str = "VERIFY"
    if stage_str not in {s.value for s in OpenSpecStage}:
        raise StageProfileError(f"UNSUPPORTED_STAGE: Unknown stage '{stage}'.")

    raw_profile = project_config.stage_profiles.get(stage_str)
    if raw_profile is None:
        raw_profile = DEFAULT_R01_STAGE_PROFILES.get(stage_str)
    if raw_profile is None:
        raise StageProfileError(
            f"NO_PROFILE_FOR_STAGE: No profile configured for stage '{stage_str}'."
        )

    if requested_provider:
        req_p = requested_provider.strip().lower()
        if req_p in ("antigravity", "agy"):
            req_p = "antigravity"
        req_m = requested_model or (
            raw_profile.model if raw_profile.provider.strip().lower() == req_p else None
        )
        req_e = requested_effort or raw_profile.effort
        raw_profile = StageProfileConfig(
            provider=req_p,
            model=req_m or "",
            effort=req_e or "medium",
            workflow=raw_profile.workflow,
        )
    elif requested_model or requested_effort:
        raw_profile = StageProfileConfig(
            provider=raw_profile.provider,
            model=requested_model or raw_profile.model,
            effort=requested_effort or raw_profile.effort,
            workflow=raw_profile.workflow,
        )

    provider = raw_profile.provider.strip().lower()
    if provider in ("antigravity", "agy"):
        provider = "antigravity"

    # CONTRACT_REVIEW prefers DeepSeek Direct; if not permitted or unconfigured, falls back to Antigravity
    if stage_str == "CONTRACT_REVIEW" and provider == "deepseek":
        deepseek_allowed = (
            "deepseek" in project_config.external_providers_allowed
            and (
                app_config is None
                or app_config.providers.get("deepseek", ProviderConfig(enabled=True)).enabled
            )
            and bool(os.environ.get("DEEPSEEK_API_KEY"))
        )
        if not deepseek_allowed:
            provider = "antigravity"
            raw_profile = StageProfileConfig(
                provider="antigravity",
                model="gemini-3.8-flash-low",
                effort="low",
                workflow=raw_profile.workflow or "openspec-explore",
            )

    if provider not in project_config.external_providers_allowed:
        raise StageProfileError(
            f"PROVIDER_NOT_ALLOWED: Provider '{provider}' is not in project allowed providers: "
            f"{project_config.external_providers_allowed}."
        )

    if stage_str == "REVIEW" and implementer_provider:
        imp_p = implementer_provider.strip().lower()
        if imp_p in ("antigravity", "agy"):
            imp_p = "antigravity"
        if provider == imp_p:
            raise StageProfileError(
                f"REVIEWER_IDENTITY_COLLISION: Reviewer provider '{provider}' cannot match "
                f"implementer provider '{implementer_provider}'."
            )

    supported_models = SUPPORTED_PROVIDER_MODELS.get(provider)
    if supported_models is None:
        raise StageProfileError(
            f"UNKNOWN_PROVIDER: Provider '{provider}' has no model capability catalog."
        )

    model = raw_profile.model
    if not model:
        model = next((m for m, prem in supported_models.items() if not prem), None)
        if not model:
            raise StageProfileError(
                f"NO_DEFAULT_MODEL: No default non-premium model for provider '{provider}'."
            )

    model_norm = model.strip().lower()
    if model_norm not in supported_models:
        raise StageProfileError(
            f"UNSUPPORTED_MODEL: Model '{model}' is not supported by provider '{provider}'. "
            f"Supported models: {sorted(supported_models.keys())}."
        )

    is_premium = supported_models[model_norm]
    is_escalated = False

    if is_premium:
        if not (
            escalation_authorized
            and escalation_rationale
            and escalation_rationale.strip()
            and budget_authorized
        ):
            raise StageProfileError(
                f"PREMIUM_MODEL_REJECTED: Premium model '{model}' for provider '{provider}' "
                f"is rejected by default. Escalation requires explicit authorization, non-empty rationale, "
                f"and budget approval."
            )
        is_escalated = True

    supported_efforts = SUPPORTED_PROVIDER_EFFORTS.get(provider, {"low", "medium"})
    effort = raw_profile.effort
    if not effort:
        effort = "medium" if "medium" in supported_efforts else "low"

    effort_norm = effort.strip().lower()
    if effort_norm not in supported_efforts:
        raise StageProfileError(
            f"UNSUPPORTED_EFFORT: Effort '{effort}' is not supported by provider '{provider}'. "
            f"Supported efforts: {sorted(supported_efforts)}."
        )

    if effort_norm in ("max", "xhigh"):
        if not (
            escalation_authorized
            and escalation_rationale
            and escalation_rationale.strip()
            and budget_authorized
        ):
            raise StageProfileError(
                f"MAX_EFFORT_REJECTED: Max-effort '{effort}' for provider '{provider}' "
                f"is rejected by default. Escalation requires explicit authorization, non-empty rationale, "
                f"and budget approval."
            )
        is_escalated = True

    cli_invocation = None
    role_map = {
        "PLAN": "implementer",
        "APPLY": "implementer",
        "TEST": "implementer",
        "CONTRACT_REVIEW": "reviewer",
        "VERIFY": "reviewer",
        "REVIEW": "reviewer",
    }
    role = role_map.get(stage_str, "implementer")
    app_cfg = app_config or load_config()
    lookup_provider = provider
    if lookup_provider not in app_cfg.providers:
        if lookup_provider == "antigravity" and "agy" in app_cfg.providers:
            lookup_provider = "agy"
        elif lookup_provider == "agy" and "antigravity" in app_cfg.providers:
            lookup_provider = "antigravity"
    if lookup_provider in app_cfg.providers and app_cfg.providers[lookup_provider].type == "cli":
        try:
            cli_invocation = resolve_cli_invocation(
                lookup_provider,
                role,
                app_cfg,
                model=model_norm,
                effort=effort_norm,
            )
        except ValueError as exc:
            raise StageProfileError(f"CLI_RESOLUTION_FAILED: {exc}") from exc

    return ResolvedStageProfile(
        stage=stage_str,
        provider=provider,
        model=model_norm,
        effort=effort_norm,
        workflow=raw_profile.workflow or "",
        cost_basis="premium" if is_premium else "standard",
        is_premium=is_premium,
        is_escalated=is_escalated,
        cli_invocation=cli_invocation,
    )


def discover_and_load_env_file(env_path: str | Path | None = None) -> list[str]:
    """Discover and safely load environment variables from canonical .env files.

    Checks in order:
    1. Explicit env_path argument
    2. MINIME_CONFIG_PATH environment variable
    3. MINIME_ENV_FILE environment variable
    4. /etc/minime/minime.env
    5. .env in current working directory

    Populates os.environ using setdefault so existing process environment is preserved.
    Returns list of loaded variable names.
    """
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    if os.environ.get("MINIME_CONFIG_PATH"):
        candidates.append(Path(os.environ["MINIME_CONFIG_PATH"]))
    if os.environ.get("MINIME_ENV_FILE"):
        candidates.append(Path(os.environ["MINIME_ENV_FILE"]))
    candidates.extend(
        [
            Path("/etc/minime/minime.env"),
            Path(".env"),
        ]
    )

    loaded_vars: list[str] = []
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.R_OK):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip()
                            if (val.startswith('"') and val.endswith('"')) or (
                                val.startswith("'") and val.endswith("'")
                            ):
                                val = val[1:-1]
                            if key and key not in os.environ:
                                os.environ[key] = val
                                loaded_vars.append(key)
                if loaded_vars:
                    break
            except Exception:
                continue
    return loaded_vars


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from a YAML file or use default locations."""
    discover_and_load_env_file()
    if config_path:
        path = Path(config_path)
    else:
        candidates = [
            Path("config/minime.yaml"),
            Path("config/minime.example.yaml"),
            Path("/etc/minime/minime.yaml"),
        ]
        path = next((p for p in candidates if p.exists()), candidates[0])

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
            return AppConfig.model_validate(raw)

    return AppConfig()


def probe_configs_from_app_config(app_config: AppConfig) -> dict[str, ProbeConfig]:
    """Return per-provider probe policies keyed by provider name.

    Provider probe policy is authoritative over the process-wide default; any
    provider without an explicit ``probe`` block falls back to its Pydantic
    defaults so no operator-critical timing value is ever hidden in code.
    """
    return {name: provider.probe for name, provider in app_config.providers.items()}


def get_secret_patterns() -> list[str]:
    """Retrieve known secret values from environment to assist in redaction."""
    secret_envs = [
        "MINIME_DATABASE_URL",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "MINIME_GITHUB_APP_ID",
        "MINIME_GITHUB_INSTALLATION_ID",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ]
    secrets: list[str] = []
    for var in secret_envs:
        val = os.environ.get(var)
        if val and len(val) >= 4:
            secrets.append(val)
    return secrets
