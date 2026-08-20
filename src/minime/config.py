"""Configuration handling for mini me."""

from __future__ import annotations

import os
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


class ProviderConfig(BaseModel):
    type: str = "cli"
    command: str | None = None
    enabled: bool = True
    roles: list[str] = Field(default_factory=list)
    base_url: str | None = None
    api_key_env: str | None = None
    paid: bool = False
    mode: str | None = None
    budget: dict[str, Any] = Field(default_factory=dict)
    drain: dict[str, Any] = Field(default_factory=dict)


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
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    projects: dict[str, ProjectConfig] = Field(default_factory=dict)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from a YAML file or use default locations."""
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
