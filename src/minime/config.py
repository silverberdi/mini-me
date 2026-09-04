"""Configuration handling for mini me."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


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


class CliInvocationConfig(BaseModel):
    args: list[str] = Field(default_factory=list)
    prompt_transport: str = "stdin"


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


def resolve_cli_invocation(
    provider: str, role: str, config: AppConfig | None = None
) -> CliInvocationProfile:
    """Resolve and validate one provider/role CLI invocation from app configuration."""
    app_config = config or load_config()
    provider_config = app_config.providers.get(provider)
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
    return CliInvocationProfile(
        provider=provider,
        role=role,
        executable=executable,
        args=tuple(invocation.args),
        prompt_transport=invocation.prompt_transport,
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
