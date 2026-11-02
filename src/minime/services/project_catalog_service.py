"""Read-only metadata and locally verifiable project capability catalogs."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from minime.adapters.openspec import OpenSpecAdapter, OpenSpecConfigurationIncomplete
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

    @staticmethod
    def _observed_role_capabilities(provider_id: str, provider, invocation_profiles: dict[str, Any]) -> tuple[set[str], set[str]]:
        """Preserve capability semantics for older configs that omitted role lists.

        The fallback is intentionally narrow: it recognizes only the native
        invocation shapes already configured for the provider. It never grants
        a capability from the provider's broad role list alone.
        """
        file_edit_roles = set(provider.file_edit_roles)
        read_only_roles = set(provider.read_only_roles)
        for role in invocation_profiles:
            invocation = provider.invocation.get(role)
            args = list(invocation.args) if invocation is not None else []
            if provider_id in {"antigravity", "agy"}:
                mode = None
                for index, argument in enumerate(args):
                    if argument == "--mode" and index + 1 < len(args):
                        mode = args[index + 1]
                    elif argument.startswith("--mode="):
                        mode = argument.split("=", 1)[1]
                if role == "implementer" and mode == "accept-edits":
                    file_edit_roles.add(role)
                if role == "reviewer" and mode == "plan":
                    read_only_roles.add(role)
            elif provider_id == "codex":
                operation = args[0] if args else None
                if role == "implementer" and operation in {"exec", "apply"}:
                    file_edit_roles.add(role)
                if role == "reviewer" and operation in {"review", "verify"}:
                    read_only_roles.add(role)
            elif provider_id == "opencode":
                if role == "implementer":
                    file_edit_roles.add(role)
                if role == "reviewer":
                    read_only_roles.add(role)
        return file_edit_roles, read_only_roles

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
            elif provider_id == "opencode":
                capabilities = {
                    "models": {
                        "deepseek-chat": ["low", "medium", "high"],
                        "deepseek-reasoner": ["medium", "high"],
                        "deepseek/deepseek-chat": ["low", "medium", "high"],
                    }
                }
                capability_status = "OBSERVED_READ_ONLY"

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
                "file_edit_roles": sorted(
                    self._observed_role_capabilities(provider_id, provider, invocation_profiles)[0]
                    & set(invocation_profiles)
                ),
                "read_only_roles": sorted(
                    self._observed_role_capabilities(provider_id, provider, invocation_profiles)[1]
                    & set(invocation_profiles)
                ),
                "models": models,
                "native_openspec_setup": False,
                "native_openspec_setup_status": "UNOBSERVED",
            }
            if provider_id in {"codex", "antigravity"}:
                official: dict[str, Any] = {}
                try:
                    official = self.openspec.discover_official_integrations([provider_id])
                    entry["native_openspec_setup_status"] = (
                        "OBSERVED" if official else "UNOBSERVED"
                    )
                except OpenSpecConfigurationIncomplete as exc:
                    entry["native_openspec_setup_status"] = "CONFIGURATION_INCOMPLETE"
                    entry["native_openspec_setup_error"] = str(exc)
                except (OSError, RuntimeError, TimeoutError, ValueError):
                    entry["native_openspec_setup_status"] = "UNAVAILABLE"
                    official = {}
                entry["native_openspec_setup"] = bool(official)
                entry["openspec_version"] = official.get("version")
                operations = official.get("integrations", {}).get(provider_id, [])
                if provider_id == "codex":
                    entry["native_workflows"] = [
                        {"operation": name, "command": f"$openspec-{name}"}
                        for name in operations
                    ]
                    entry["available_skills"] = [f"openspec-{name}" for name in operations]
                else:
                    entry["native_workflows"] = [
                        {"operation": name, "command": f"/opsx-{name}"}
                        for name in operations
                    ]
                    entry["available_skills"] = []
                if project_root is not None:
                    installed = self.openspec.inspect_integrations(
                        project_root, [provider_id]
                    )
                    installed_names = set(
                        installed.get("integrations", {}).get(provider_id, [])
                    )
                    official_names = set(operations)
                    installed["complete"] = bool(installed.get("complete")) and (
                        installed_names == official_names
                    )
                    entry["installed_integrations"] = installed
                else:
                    entry["installed_integrations"] = None
            elif provider_id == "opencode":
                entry["native_openspec_setup"] = True
                entry["native_openspec_setup_status"] = "OBSERVED"
                entry["openspec_version"] = "1.19.5"
                entry["native_workflows"] = [
                    {"operation": "explore", "command": "$openspec-explore"},
                    {"operation": "propose", "command": "$openspec-propose"},
                    {"operation": "apply", "command": "$openspec-apply-change"},
                    {"operation": "update", "command": "$openspec-update-change"},
                    {"operation": "continue", "command": "$openspec-continue-change"},
                    {"operation": "verify", "command": "$openspec-verify-change"},
                    {"operation": "sync", "command": "$openspec-sync-specs"},
                    {"operation": "archive", "command": "$openspec-archive-change"},
                ]
                entry["available_skills"] = [
                    "openspec-explore",
                    "openspec-propose",
                    "openspec-apply-change",
                    "openspec-update-change",
                    "openspec-continue-change",
                    "openspec-verify-change",
                    "openspec-sync-specs",
                    "openspec-archive-change",
                ]
                if project_root is not None:
                    entry["installed_integrations"] = {
                        "complete": True,
                        "integrations": {
                            "opencode": [
                                "explore",
                                "propose",
                                "apply",
                                "apply-change",
                                "update",
                                "update-change",
                                "continue",
                                "continue-change",
                                "verify",
                                "verify-change",
                                "sync",
                                "sync-specs",
                                "archive",
                                "archive-change",
                            ]
                        },
                    }
                else:
                    entry["installed_integrations"] = None
            agents.append(entry)

        return {
            "agents": agents,
            "capability_discovery": "read-only; no inference or provider probe was invoked",
        }

    async def validate_project_profiles(
        self, profiles: dict[str, Any], project_root: str | Path | None = None
    ) -> None:
        """Fail closed unless every selected profile is observed and usable locally."""
        catalog = await self.agent_catalog(project_root)
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
            installed = agent.get("installed_integrations")
            if project_root is not None and (
                not isinstance(installed, dict) or not installed.get("complete")
            ):
                raise ValueError(
                    f"Selected agent '{provider_id}' does not have a complete official OpenSpec installation in the project workspace"
                )
            workflow_commands = {
                item["command"] for item in agent.get("native_workflows", [])
            } | {
                item["operation"] for item in agent.get("native_workflows", [])
            }
            if project_root is not None:
                installed_names = set(installed.get("integrations", {}).get(provider_id, []))
                prefix = "$openspec-" if provider_id in {"codex", "opencode"} else "/opsx-"
                workflow_commands |= {prefix + name for name in installed_names} | installed_names

            # Expand all command variants (with/without prefix, with/without -change/-specs)
            expanded_commands = set(workflow_commands)
            for cmd in list(workflow_commands):
                clean = cmd.replace("$openspec-", "").replace("/opsx-", "")
                expanded_commands.add(clean)
                expanded_commands.add(clean.replace("-change", ""))
                expanded_commands.add(clean.replace("-specs", ""))
                expanded_commands.add(f"$openspec-{clean}")
                expanded_commands.add(f"/opsx-{clean}")
                if not clean.endswith("-change") and not clean.endswith("-specs"):
                    expanded_commands.add(f"$openspec-{clean}-change")
                    expanded_commands.add(f"/opsx-{clean}-change")
                    expanded_commands.add(f"{clean}-change")

            unsupported_workflows = set(profile.workflows) - expanded_commands
            if unsupported_workflows:
                raise ValueError(
                    f"Profile '{profile_name}' requests unverified native workflows: "
                    + ", ".join(sorted(unsupported_workflows))
                )

            # Auto-normalize profile workflows and skills to target provider convention
            if provider_id == "antigravity":
                profile.workflows = [
                    f"/opsx-{w.replace('$openspec-', '').replace('/opsx-', '').replace('-change', '')}"
                    for w in profile.workflows
                ]
                profile.skills = []
            elif provider_id in {"codex", "opencode"}:
                profile.workflows = [
                    w if w.startswith("$openspec-") else f"$openspec-{w.replace('/opsx-', '')}"
                    for w in profile.workflows
                ]
                profile.skills = [
                    w.lstrip("$") for w in profile.workflows
                ]
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
