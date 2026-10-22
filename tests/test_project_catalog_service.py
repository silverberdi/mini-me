import asyncio

import pytest

from minime.config import AppConfig, CliInvocationConfig, ProviderConfig
from minime.services.project_catalog_service import ProjectCatalogService


class _NativeSetup:
    def inspect_cli(self):
        return {"available": True, "init_tools_supported": True, "version": "test"}

    def inspect_integrations(self, root, agents):
        return {
            "complete": True,
            "agents": agents,
            "root": str(root),
            "integrations": {"codex": ["propose", "verify-change"]},
        }

    def discover_official_integrations(self, agents):
        integrations = {"codex": ["propose", "verify-change"]}
        return {
            "version": "test",
            "integrations": {agent: integrations[agent] for agent in agents},
        }


class _Capabilities:
    def __init__(self, provider_name, capabilities):
        self.provider_name = provider_name
        self.capabilities = capabilities

    async def discover_account_capabilities(self, timeout_seconds=10):
        return self.capabilities


def _config():
    codex = ProviderConfig(
        command="fake-codex",
        roles=["implementer", "reviewer"],
        file_edit_roles=["implementer"],
        read_only_roles=["reviewer"],
        invocation={
            "implementer": CliInvocationConfig(
                args=["exec", "-"], model="live-codex", effort="medium"
            ),
            "reviewer": CliInvocationConfig(
                args=["review", "-"], model="live-codex", effort="medium"
            ),
        },
    )
    return AppConfig(providers={"codex": codex})


def test_catalog_exposes_only_read_only_discovered_models(monkeypatch):
    import minime.services.project_catalog_service as catalog_module

    monkeypatch.setattr(catalog_module.shutil, "which", lambda _: "/bin/fake-codex")
    monkeypatch.setattr(
        catalog_module,
        "get_provider_adapter",
        lambda provider_id, config: _Capabilities(provider_id, {"models": {"live-codex": ["low", "medium"]}}),
    )

    catalog = asyncio.run(ProjectCatalogService(_config(), _NativeSetup()).agent_catalog())

    assert len(catalog["agents"]) == 1
    agent = catalog["agents"][0]
    assert agent["models"] == {"live-codex": ["low", "medium"]}
    assert agent["capability_status"] == "OBSERVED_READ_ONLY"
    assert agent["file_edit_roles"] == ["implementer"]
    assert agent["read_only_roles"] == ["reviewer"]
    assert agent["native_openspec_setup"] is True
    assert agent["native_workflows"] == [
        {"operation": "propose", "command": "$openspec-propose"},
        {"operation": "verify-change", "command": "$openspec-verify-change"},
    ]
    assert agent["available_skills"] == ["openspec-propose", "openspec-verify-change"]
    assert catalog["capability_discovery"].startswith("read-only")


def test_catalog_does_not_fabricate_models_when_discovery_fails(monkeypatch):
    import minime.services.project_catalog_service as catalog_module

    monkeypatch.setattr(catalog_module.shutil, "which", lambda _: "/bin/fake-codex")
    monkeypatch.setattr(
        catalog_module,
        "get_provider_adapter",
        lambda provider_id, config: _Capabilities(provider_id, {}),
    )

    catalog = asyncio.run(ProjectCatalogService(_config(), _NativeSetup()).agent_catalog())

    assert catalog["agents"][0]["models"] == {}
    assert catalog["agents"][0]["capability_status"] == "UNAVAILABLE"


def test_target_workspace_catalog_requires_the_full_official_integration_set(monkeypatch):
    import minime.services.project_catalog_service as catalog_module

    monkeypatch.setattr(catalog_module.shutil, "which", lambda _: "/bin/fake-codex")
    monkeypatch.setattr(
        catalog_module,
        "get_provider_adapter",
        lambda provider_id, config: _Capabilities(
            provider_id, {"models": {"live-codex": ["medium"]}}
        ),
    )

    catalog = asyncio.run(
        ProjectCatalogService(_config(), _NativeSetup()).agent_catalog("/verified/workspace")
    )

    assert catalog["agents"][0]["installed_integrations"]["complete"] is True
    assert catalog["agents"][0]["installed_integrations"]["integrations"]["codex"] == [
        "propose", "verify-change"
    ]


def test_project_profile_workflows_and_skills_must_exist_in_target_workspace(monkeypatch):
    import minime.services.project_catalog_service as catalog_module
    from minime.domain.models import ProjectAgentProfile

    monkeypatch.setattr(catalog_module.shutil, "which", lambda _: "/bin/fake-codex")
    monkeypatch.setattr(
        catalog_module,
        "get_provider_adapter",
        lambda provider_id, config: _Capabilities(
            provider_id, {"models": {"live-codex": ["medium"]}}
        ),
    )
    service = ProjectCatalogService(_config(), _NativeSetup())
    profiles = {
        "thinking": ProjectAgentProfile(
            agent_id="codex",
            model_id="live-codex",
            effort="medium",
            workflows=["$openspec-propose"],
            skills=["openspec-propose"],
        )
    }

    asyncio.run(service.validate_project_profiles(profiles, "/verified/workspace"))

    profiles["thinking"].workflows = ["$openspec-sync-specs"]
    with pytest.raises(ValueError, match="unverified native workflows"):
        asyncio.run(service.validate_project_profiles(profiles, "/verified/workspace"))


def test_text_only_provider_is_not_exposed_as_an_agent_capability():
    text_provider = ProviderConfig(
        type="api",
        command="text-api",
        roles=["implementer", "reviewer"],
        file_edit_roles=["implementer"],
        read_only_roles=["reviewer"],
        invocation={
            "implementer": CliInvocationConfig(args=["call"]),
            "reviewer": CliInvocationConfig(args=["call"]),
        },
    )
    catalog = ProjectCatalogService(
        AppConfig(providers={"text": text_provider}), _NativeSetup()
    )
    assert asyncio.run(catalog.agent_catalog())["agents"] == []


def test_profile_resolution_rejects_unavailable_prompt_transport():
    from minime.config import resolve_cli_invocation

    bad = ProviderConfig(
        command="codex",
        roles=["implementer"],
        invocation={
            "implementer": CliInvocationConfig(
                args=["exec"], prompt_transport="file", model="m", effort="medium"
            )
        },
    )
    with pytest.raises(ValueError, match="Unsupported prompt transport"):
        resolve_cli_invocation("codex", "implementer", AppConfig(providers={"codex": bad}))


def test_provider_catalog_separates_metadata_from_connections():
    catalog = ProjectCatalogService(_config(), _NativeSetup()).provider_catalog()

    github = next(item for item in catalog if item["id"] == "github")
    ado = next(item for item in catalog if item["id"] == "ado")
    assert set(github["responsibilities"]) == {"tickets", "git_pr"}
    assert "issues.list" in github["capabilities"]["tickets"]
    assert "pull_request.create" in github["capabilities"]["git_pr"]
    assert {field["name"] for field in github["fields"]} >= {
        "repository_url", "auth_mode", "app_id", "installation_id", "private_key"
    }
    assert all(field.get("write_only") for field in github["fields"] if field["name"] in {"app_id", "installation_id", "private_key"})
    assert ado["available"] is False
    assert not any("repository_url" in item for item in catalog)
    assert not hasattr(_config().github, "global_project_number")
