"""Read-only metadata and locally verifiable project capability catalogs."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from minime.adapters.openspec import OpenSpecAdapter
from minime.adapters.provider_adapter import get_provider_adapter
from minime.config import AppConfig, load_config, resolve_cli_invocation


class ProjectCatalogService:
    """Expose selectable metadata without persisting connections or probing inference."""

    PROVIDERS = (
        {
            "id": "github",
            "responsibilities": ["tickets", "git_pr"],
            "capabilities": {
                "tickets": ["issues.list", "issues.read", "issues.create", "issues.comment", "issues.close"],
                "git_pr": ["repository.verify", "branch.read", "branch.create", "git.push", "pull_request.create", "pull_request.read", "pull_request.merge_observe"],
            },
            "auth_modes": ["environment_app", "project_app"],
            "fields": [
                {
                    "name": "repository_url",
                    "type": "https_repository_url",
                    "required_for": ["tickets", "git_pr"],
                },
                {
                    "name": "auth_mode",
                    "type": "enum",
                    "values": ["environment_app", "project_app"],
                    "required_for": ["tickets", "git_pr"],
                },
                {
                    "name": "app_id",
                    "type": "string",
                    "required_when": {"auth_mode": "project_app"},
                    "write_only": True,
                },
                {
                    "name": "installation_id",
                    "type": "string",
                    "required_when": {"auth_mode": "project_app"},
                    "write_only": True,
                },
                {
                    "name": "private_key",
                    "type": "pem_private_key",
                    "required_when": {"auth_mode": "project_app"},
                    "write_only": True,
                },
            ],
            "available": True,
        },
        {
            "id": "ado",
            "responsibilities": [],
            "capabilities": {"tickets": [], "git_pr": []},
            "auth_modes": [],
            "required_fields": [],
            "available": False,
        },
    )

    def __init__(self, config: AppConfig | None = None, openspec: OpenSpecAdapter | None = None):
        self.config = config or load_config()
        self.openspec = openspec or OpenSpecAdapter()

    def provider_catalog(self) -> list[dict[str, Any]]:
        """Return provider definitions only; no project connection can enter this response."""
        return [dict(item) for item in self.PROVIDERS]

    async def agent_catalog(self, project_root: str | Path | None = None) -> dict[str, Any]:
        agents: list[dict[str, Any]] = []
        for provider_id, provider in sorted(self.config.providers.items()):
            executable_name = (provider.command or "").strip().split(maxsplit=1)
            if not provider.enabled or provider.type != "cli" or not executable_name:
                continue
            executable = shutil.which(executable_name[0])
            if executable is None:
                continue

            invocation_profiles: dict[str, dict[str, str]] = {}
            for role in provider.roles:
                invocation = provider.invocation.get(role)
                if invocation is None:
                    continue
                try:
                    resolved = resolve_cli_invocation(provider_id, role, self.config)
                except ValueError:
                    continue
                invocation_profiles[role] = {
                    "transport": resolved.prompt_transport,
                    "executable": resolved.executable,
                }

            capabilities: dict[str, Any] = {}
            capability_status = "UNAVAILABLE"
            if provider_id in {"codex", "antigravity"}:
                try:
                    adapter = get_provider_adapter(provider_id, self.config)
                    capabilities = await asyncio.wait_for(
                        adapter.discover_account_capabilities(timeout_seconds=10), timeout=11
                    )
                    if capabilities.get("models"):
                        capability_status = "OBSERVED_READ_ONLY"
                except (OSError, RuntimeError, TimeoutError, ValueError):
                    capabilities = {}

            models: dict[str, list[str] | None] = {}
            observed_models = capabilities.get("models", {})
            if isinstance(observed_models, dict):
                for model, efforts in observed_models.items():
                    if isinstance(model, str):
                        models[model] = sorted(
                            {str(value).lower() for value in efforts if value}
                        ) if isinstance(efforts, list) else None
            elif isinstance(observed_models, list):
                effort_map = capabilities.get("model_efforts", {})
                for model in observed_models:
                    if isinstance(model, str):
                        effort = effort_map.get(model) if isinstance(effort_map, dict) else None
                        models[model] = [str(effort)] if effort else None

            entry: dict[str, Any] = {
                "id": provider_id,
                "executable": executable,
                "available": True,
                "capability_status": capability_status,
                "roles": [role for role in provider.roles if role in invocation_profiles],
                "invocations": invocation_profiles,
                "file_edit_roles": sorted(set(provider.file_edit_roles) & set(invocation_profiles)),
                "read_only_roles": sorted(set(provider.read_only_roles) & set(invocation_profiles)),
                "models": models,
                "native_openspec_setup": False,
            }
            if provider_id in {"codex", "antigravity"}:
                cli = self.openspec.inspect_cli()
                entry["native_openspec_setup"] = bool(
                    cli.get("available") and cli.get("init_tools_supported")
                )
                entry["openspec_version"] = cli.get("version")
                if project_root is not None:
                    entry["installed_integrations"] = self.openspec.inspect_integrations(
                        project_root, [provider_id]
                    )
                else:
                    entry["installed_integrations"] = None
            agents.append(entry)

        return {
            "agents": agents,
            "capability_discovery": "read-only; no inference or provider probe was invoked",
        }

    async def validate_project_profiles(self, profiles: dict[str, Any]) -> None:
        """Fail closed unless every selected profile is observed and usable locally."""
        catalog = await self.agent_catalog()
        agents = {item["id"]: item for item in catalog["agents"]}
        role_map = {
            "thinking": ("implementer", "file_edit_roles"),
            "execution": ("implementer", "file_edit_roles"),
            "independent_review": ("reviewer", "read_only_roles"),
            "fallback": ("implementer", "file_edit_roles"),
        }
        for profile_name, profile in profiles.items():
            provider_id = profile.agent_id.strip().lower()
            provider_id = "antigravity" if provider_id == "agy" else provider_id
            agent = agents.get(provider_id)
            if agent is None:
                raise ValueError(f"Selected agent '{provider_id}' is not locally available")
            invocation_role, capability_field = role_map[profile_name]
            if invocation_role not in agent["roles"] or invocation_role not in agent["invocations"]:
                raise ValueError(
                    f"Selected agent '{provider_id}' has no verified {invocation_role} invocation"
                )
            if invocation_role not in agent[capability_field]:
                raise ValueError(
                    f"Selected agent '{provider_id}' is not verified for {profile_name} file capability"
                )
            if agent["capability_status"] != "OBSERVED_READ_ONLY":
                raise ValueError(f"Selected agent '{provider_id}' model catalog is unobservable")
            supported_efforts = agent["models"].get(profile.model_id)
            if supported_efforts is None or profile.effort.lower() not in supported_efforts:
                raise ValueError(
                    f"Model/effort for profile '{profile_name}' is not in the live {provider_id} catalog"
                )
            if provider_id in {"codex", "antigravity"} and not agent["native_openspec_setup"]:
                raise ValueError(
                    f"Selected agent '{provider_id}' has no verified official OpenSpec setup"
                )
        reviewer = profiles.get("independent_review")
        if reviewer is not None:
            reviewer_id = reviewer.agent_id.strip().lower()
            reviewer_id = "antigravity" if reviewer_id == "agy" else reviewer_id
            for author_role in ("thinking", "execution"):
                author = profiles.get(author_role)
                if author is None:
                    continue
                author_id = author.agent_id.strip().lower()
                author_id = "antigravity" if author_id == "agy" else author_id
                if reviewer_id == author_id:
                    raise ValueError(
                        f"Independent reviewer cannot be the configured {author_role} author"
                    )
