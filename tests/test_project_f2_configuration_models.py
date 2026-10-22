import pytest
from pydantic import ValidationError

from minime.domain.enums import ProjectType
from minime.domain.models import (
    ProjectAgentProfile,
    ProjectConfigurationInput,
    ProjectConfigurationPatch,
    ProjectProviderConnection,
)
from minime.services.project_service import ProjectService


def _configuration(**overrides):
    data = {
        "project_id": "demo",
        "display_name": "Demo",
        "project_type": ProjectType.BROWNFIELD,
        "repository": "https://github.com/example/demo",
        "provider_connections": {
            "tickets": {
                "provider_id": "github",
                "repository_url": "https://github.com/example/demo",
                "auth_mode": "environment_app",
            },
            "git_pr": {
                "provider_id": "github",
                "repository_url": "https://github.com/example/demo",
                "auth_mode": "environment_app",
            },
        },
        "agent_profiles": {
            name: ProjectAgentProfile(
                agent_id="antigravity" if name == "independent_review" else "codex",
                model_id=(
                    "claude-sonnet-5-5-medium"
                    if name == "independent_review"
                    else "gpt-5.6-luna"
                ),
                effort="medium",
            ).model_dump()
            for name in ("thinking", "execution", "independent_review", "fallback")
        },
    }
    data.update(overrides)
    return ProjectConfigurationInput.model_validate(data)


def test_project_configuration_defaults_optional_branch_to_main():
    assert _configuration().base_branch == "main"


def test_project_configuration_keeps_ticket_and_git_connections_separate():
    project = _configuration()
    assert project.provider_connections["tickets"].repository_url.endswith("/demo")
    assert project.provider_connections["git_pr"].auth_mode == "environment_app"


def test_project_app_connection_requires_credentials_or_a_protected_reference():
    connections = {
        "tickets": {
            "provider_id": "github",
            "repository_url": "https://github.com/example/demo",
            "auth_mode": "project_app",
        },
        "git_pr": {
            "provider_id": "github",
            "repository_url": "https://github.com/example/demo",
            "auth_mode": "environment_app",
        },
    }
    with pytest.raises(ValidationError, match="credentials or a protected reference"):
        _configuration(provider_connections=connections)


def test_f2_rejects_unimplemented_provider():
    with pytest.raises(ValidationError, match="Only the GitHub provider"):
        ProjectProviderConnection(
            provider_id="ado",
            repository_url="https://dev.azure.com/example/demo",
            auth_mode="environment_app",
        )


@pytest.mark.asyncio
async def test_profile_validation_requires_live_model_and_role_evidence(monkeypatch):
    from minime.services.project_catalog_service import ProjectCatalogService

    service = ProjectCatalogService()

    async def observed_catalog(_project_root=None):
        return {
            "agents": [
                {
                    "id": "codex",
                    "roles": ["implementer", "reviewer"],
                    "invocations": {
                        "implementer": {"transport": "stdin"},
                        "reviewer": {"transport": "stdin"},
                    },
                    "file_edit_roles": ["implementer"],
                    "read_only_roles": ["reviewer"],
                    "capability_status": "OBSERVED_READ_ONLY",
                    "models": {"gpt-5.6-luna": ["medium"]},
                    "native_openspec_setup": True,
                },
                {
                    "id": "antigravity",
                    "roles": ["reviewer"],
                    "invocations": {"reviewer": {"transport": "stdin"}},
                    "file_edit_roles": [],
                    "read_only_roles": ["reviewer"],
                    "capability_status": "OBSERVED_READ_ONLY",
                    "models": {"claude-sonnet-5-5-medium": ["medium"]},
                    "native_openspec_setup": True,
                },
            ]
        }

    monkeypatch.setattr(service, "agent_catalog", observed_catalog)
    profiles = _configuration().agent_profiles
    profiles["independent_review"].agent_id = "codex"
    profiles["independent_review"].model_id = "gpt-5.6-luna"
    with pytest.raises(ValueError, match="cannot be the configured thinking author"):
        await service.validate_project_profiles(profiles)
    profiles["independent_review"].agent_id = "antigravity"
    profiles["independent_review"].model_id = "claude-sonnet-5-5-medium"
    await service.validate_project_profiles(profiles)
    profiles["thinking"].workflows = ["/opsx-propose"]
    with pytest.raises(ValueError, match="unverified native workflows"):
        await service.validate_project_profiles(profiles)
    profiles["thinking"].workflows = []
    profiles["thinking"].model_id = "not-observed"
    with pytest.raises(ValueError, match="live codex catalog"):
        await service.validate_project_profiles(profiles)


def test_project_configuration_requires_four_explicit_profiles():
    profiles = {
        name: ProjectAgentProfile(
            agent_id="codex",
            model_id="codex-default",
            effort="medium",
        ).model_dump()
        for name in ("thinking", "execution", "independent_review")
    }
    with pytest.raises(ValidationError, match="Missing agent profiles"):
        _configuration(agent_profiles=profiles)


def test_project_service_rejects_review_by_thinking_author(in_memory_uow):
    configuration = _configuration()
    configuration.agent_profiles["independent_review"].agent_id = "codex"
    configuration.agent_profiles["independent_review"].model_id = "gpt-5.6-luna"

    with pytest.raises(ValueError, match="distinct from the thinking author"):
        ProjectService(in_memory_uow).create_configured_project(configuration)

    assert in_memory_uow.projects.get_by_id("demo") is None


def test_project_credentials_are_kept_out_of_project_configuration(in_memory_uow, tmp_path):
    import json
    import stat

    from minime.services.project_credential_store import ProjectCredentialStore

    connections = {
        "tickets": {
            "provider_id": "github",
            "repository_url": "https://github.com/example/demo",
            "auth_mode": "project_app",
        },
        "git_pr": {
            "provider_id": "github",
            "repository_url": "https://github.com/example/demo",
            "auth_mode": "project_app",
        },
    }
    credentials = {
        "app_id": "12345",
        "installation_id": "67890",
        "private_key": "-----BEGIN PRIVATE KEY-----\nexample\n-----END PRIVATE KEY-----",
    }
    config = _configuration(
        provider_connections=connections, github_app_credentials=credentials
    )
    store = ProjectCredentialStore(tmp_path / "secrets")

    project = ProjectService(in_memory_uow, credential_store=store).create_configured_project(
        config
    )

    ref = project.provider_connections["git_pr"]["secret_reference"]
    credential_path = tmp_path / "secrets" / "demo" / f"{ref}.json"
    stored = json.loads(credential_path.read_text())
    assert stored["private_key"] == credentials["private_key"]
    assert stat.S_IMODE(credential_path.stat().st_mode) == 0o600
    assert "private_key" not in str(project.model_dump(mode="json"))
    assert ref not in credentials["private_key"]


def test_project_github_app_adapters_keep_credentials_and_token_caches_isolated(tmp_path):
    from minime.adapters.github import GitHubAdapter
    from minime.services.project_credential_store import ProjectCredentialStore

    store = ProjectCredentialStore(tmp_path / "secrets")
    key_a = "-----BEGIN PRIVATE KEY-----\nproject-a\n-----END PRIVATE KEY-----"
    key_b = "-----BEGIN PRIVATE KEY-----\nproject-b\n-----END PRIVATE KEY-----"
    ref_a = store.store_github_app("project-a", "111", "101", key_a)
    ref_b = store.store_github_app("project-b", "222", "202", key_b)
    adapter_a = GitHubAdapter.for_project_connection(
        "project-a", {"auth_mode": "project_app", "secret_reference": ref_a}, store
    )
    adapter_b = GitHubAdapter.for_project_connection(
        "project-b", {"auth_mode": "project_app", "secret_reference": ref_b}, store
    )

    assert adapter_a.auth._credentials() == ("111", "101", key_a)
    assert adapter_b.auth._credentials() == ("222", "202", key_b)
    assert adapter_a.auth is not adapter_b.auth
    assert adapter_a.auth._cached is None and adapter_b.auth._cached is None


def test_connection_verification_keeps_ticket_and_git_repositories_separate(
    in_memory_uow, monkeypatch
):
    from minime.adapters.github import GitHubAdapter
    from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
    from minime.domain.models import ExternalActionResult
    from minime.services.project_connection_service import ProjectConnectionService

    connections = {
        "tickets": {
            "provider_id": "github",
            "repository_url": "tickets-owner/source",
            "auth_mode": "environment_app",
        },
        "git_pr": {
            "provider_id": "github",
            "repository_url": "code-owner/target",
            "auth_mode": "environment_app",
        },
    }
    project = ProjectService(in_memory_uow).create_configured_project(
        _configuration(provider_connections=connections)
    )
    observed = []

    class FakeAdapter:
        def __init__(self, repository):
            self.repository = repository

        def verify_connection_permissions(self, repository, responsibility):
            assert repository == self.repository
            observed.append((repository, responsibility))
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="test",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data={"repository": repository, "permissions": {"read": "read"}},
            )

    def create_adapter(cls, project_id, connection, credential_store):
        assert project_id == project.project_id
        assert credential_store is not None
        return FakeAdapter(connection["repository_url"])

    monkeypatch.setattr(GitHubAdapter, "for_project_connection", classmethod(create_adapter))
    result = ProjectConnectionService().verify(project)

    assert result["tickets"]["verified"] is True
    assert result["git_pr"]["verified"] is True
    assert observed == [
        ("tickets-owner/source", "tickets"),
        ("code-owner/target", "git_pr"),
    ]


def test_public_project_payload_hides_host_reference_without_mutating_durable_project(
    in_memory_uow,
):
    project = ProjectService(in_memory_uow).create_configured_project(_configuration())
    project.provider_connections["git_pr"]["secret_reference"] = "host-only-reference"
    in_memory_uow.projects.save(project)

    payload = ProjectService.public_project_payload(project)

    assert payload["provider_connections"]["git_pr"]["credential_configured"] is True
    assert "secret_reference" not in payload["provider_connections"]["git_pr"]
    assert (
        in_memory_uow.projects.get_by_id("demo")
        .provider_connections["git_pr"]["secret_reference"]
        == "host-only-reference"
    )


def test_project_update_preserves_identity_and_can_change_settings(in_memory_uow):
    service = ProjectService(in_memory_uow)
    original = service.create_configured_project(_configuration())
    updated = service.update_configuration(
        original.project_id,
        ProjectConfigurationPatch(display_name="Renamed", base_branch="develop"),
    )

    assert updated.display_name == "Renamed"
    assert updated.repository == original.repository
    assert updated.project_id == original.project_id
    assert updated.base_branch == "develop"


def test_project_update_fails_closed_on_branch_change_with_invalid_binding(in_memory_uow):
    from minime.domain.models import ProjectManagedRepositoryBinding

    service = ProjectService(in_memory_uow)
    project = service.create_configured_project(_configuration())
    in_memory_uow.project_managed_repository_bindings.save(
        ProjectManagedRepositoryBinding(
            project_id=project.project_id,
            canonical_repository_identity=project.repository,
            managed_repository_root="/tmp/minime-invalid-binding",
            worktree_parent_dir="/tmp/minime-invalid-binding/.minime/worktrees",
            is_valid=False,
        )
    )

    with pytest.raises(ValueError, match="binding is invalid"):
        service.update_configuration(
            project.project_id, ProjectConfigurationPatch(base_branch="release")
        )

    assert in_memory_uow.projects.get_by_id(project.project_id).base_branch == "main"


def test_project_update_advances_verified_base_branch_and_binding(
    in_memory_uow, tmp_path, monkeypatch
):
    from minime.adapters.github import GitHubAdapter
    from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
    from minime.domain.models import ExternalActionResult, ProjectManagedRepositoryBinding
    from minime.services import workspace_guard

    service = ProjectService(in_memory_uow)
    project = service.create_configured_project(_configuration())
    root = tmp_path / "repository"
    root.mkdir()
    binding = ProjectManagedRepositoryBinding(
        project_id=project.project_id,
        canonical_repository_identity=project.repository,
        managed_repository_root=str(root),
        worktree_parent_dir=str(root / ".minime/worktrees"),
    )
    in_memory_uow.project_managed_repository_bindings.save(binding)
    monkeypatch.setattr(workspace_guard, "is_binding_fully_valid", lambda _binding: True)
    monkeypatch.setattr(
        workspace_guard.ManagedWorkspaceGuard,
        "verify_managed_repository_ownership_marker",
        lambda *_args, **_kwargs: (True, "", None, None),
    )
    monkeypatch.setattr(
        workspace_guard.ManagedWorkspaceGuard,
        "verify_git_repository_identity",
        lambda *_args, **_kwargs: (True, None),
    )

    class BranchAdapter:
        def get_remote_branch_head(self, repository, branch, remote):
            assert repository == str(root)
            assert branch == "release"
            assert remote == "origin"
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="test",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data="abc123",
            )

    monkeypatch.setattr(
        GitHubAdapter,
        "for_project_connection",
        classmethod(lambda *_args, **_kwargs: BranchAdapter()),
    )
    updated = service.update_configuration(
        project.project_id, ProjectConfigurationPatch(base_branch="release")
    )

    saved_binding = in_memory_uow.project_managed_repository_bindings.get_by_project_id(
        project.project_id
    )
    assert updated.base_branch == "release"
    assert saved_binding.default_base_branch == "release"


def test_project_cli_update_uses_shared_configuration_service(in_memory_uow, tmp_path, monkeypatch):
    from contextlib import contextmanager

    from typer.testing import CliRunner

    from minime.cli import main as cli

    service = ProjectService(in_memory_uow)
    service.create_configured_project(_configuration())

    @contextmanager
    def session():
        yield in_memory_uow

    monkeypatch.setattr(cli.db_manager, "session", session)
    monkeypatch.setattr(cli, "PostgresPersistenceUnitOfWork", lambda value: value)

    async def profiles_available(self, profiles):
        assert profiles

    monkeypatch.setattr(cli.ProjectCatalogService, "validate_project_profiles", profiles_available)
    patch_path = tmp_path / "patch.json"
    patch_path.write_text('{"display_name":"Updated from CLI"}', encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["project", "update", "demo", str(patch_path)])

    assert result.exit_code == 0, result.output
    assert "updated demo" in result.output
    assert in_memory_uow.projects.get_by_id("demo").display_name == "Updated from CLI"


def test_project_patch_rejects_identity_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProjectConfigurationPatch.model_validate({"repository": "attacker/other"})


def test_project_lifecycle_pause_and_activate_does_not_change_onboarding(in_memory_uow):
    service = ProjectService(in_memory_uow)
    project = service.create_configured_project(_configuration())

    paused = service.set_lifecycle(project.project_id, active=False)
    activated = service.set_lifecycle(project.project_id, active=True)

    assert paused.status.value == "PAUSED"
    assert activated.status.value == "ACTIVE"
    assert activated.onboarding_status.value == "CONFIGURED"


def test_brownfield_service_registers_configuration_without_prepared_claim(in_memory_uow):
    project = ProjectService(in_memory_uow).create_configured_project(_configuration())

    assert project.repository == "example/demo"
    assert project.onboarding_status.value == "CONFIGURED"
    assert project.project_type == ProjectType.BROWNFIELD
    assert in_memory_uow.projects.get_by_id("demo").onboarding_status.value == "CONFIGURED"


def test_greenfield_service_rejects_without_zip_before_persistence(in_memory_uow):
    configuration = _configuration(project_type=ProjectType.GREENFIELD)

    with pytest.raises(ValueError, match="requires a validated ZIP"):
        ProjectService(in_memory_uow).create_configured_project(configuration)

    assert in_memory_uow.projects.get_by_id("demo") is None


def test_versioned_project_api_requires_authenticated_operator(in_memory_uow):
    from fastapi.testclient import TestClient

    from minime.api.app import app, get_uow

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    try:
        response = TestClient(app).get("/api/v1/projects")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401, response.json()


def test_project_query_aliases_require_authenticated_operator(in_memory_uow):
    from fastapi.testclient import TestClient

    from minime.api.app import app, get_uow

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    try:
        client = TestClient(app)
        listed = client.get("/projects")
        retrieved = client.get("/projects/not-a-real-project")
        context = client.get("/api/v1/projects/not-a-real-project/context")
        verify_connections = client.post(
            "/api/v1/projects/not-a-real-project/connections/verify"
        )
    finally:
        app.dependency_overrides.clear()

    assert listed.status_code == 401
    assert retrieved.status_code == 401
    assert context.status_code == 401
    assert verify_connections.status_code == 401


def test_versioned_project_api_creates_brownfield_configuration(in_memory_uow, monkeypatch):
    from fastapi.testclient import TestClient

    from minime.api.app import app, get_current_operator, get_uow

    async def profiles_available(self, profiles):
        assert profiles

    monkeypatch.setattr(
        "minime.api.app.ProjectCatalogService.validate_project_profiles", profiles_available
    )

    monkeypatch.setenv("MINIME_AUTH_ENABLED", "false")
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_current_operator] = lambda: object()
    try:
        response = TestClient(app).post(
            "/api/v1/projects", json=_configuration().model_dump(mode="json")
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201, response.json()
    assert response.json()["onboarding_status"] == "CONFIGURED"
    assert "private_key" not in response.text


def test_authenticated_api_stores_project_key_outside_persistence(in_memory_uow, monkeypatch, tmp_path):
    import json
    import stat

    from fastapi.testclient import TestClient

    from minime.api.app import app, get_current_operator, get_uow

    async def profiles_available(self, profiles):
        assert profiles

    monkeypatch.setattr(
        "minime.api.app.ProjectCatalogService.validate_project_profiles", profiles_available
    )

    key = "-----BEGIN PRIVATE KEY-----\napi-secret-test\n-----END PRIVATE KEY-----"
    raw = _configuration().model_dump(mode="json")
    raw["provider_connections"]["git_pr"]["auth_mode"] = "project_app"
    raw["github_app_credentials"] = {
        "app_id": "api-app",
        "installation_id": "api-install",
        "private_key": key,
    }
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "false")
    monkeypatch.setenv("MINIME_PROJECT_SECRET_ROOT", str(tmp_path / "secrets"))
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_current_operator] = lambda: object()
    try:
        response = TestClient(app).post("/api/v1/projects", json=raw)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201, response.json()
    assert key not in response.text
    assert response.json()["provider_connections"]["git_pr"]["credential_configured"] is True
    assert "secret_reference" not in response.json()["provider_connections"]["git_pr"]
    project = in_memory_uow.projects.get_by_id("demo")
    reference = project.provider_connections["git_pr"]["secret_reference"]
    stored_file = tmp_path / "secrets" / "demo" / f"{reference}.json"
    assert stat.S_IMODE(stored_file.stat().st_mode) == 0o600
    assert json.loads(stored_file.read_text())["private_key"] == key
    assert key not in str(project.model_dump(mode="json"))


def test_project_api_never_exposes_secret_reference(in_memory_uow, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from minime.api.app import app, get_current_operator, get_uow

    async def profiles_available(self, profiles):
        assert profiles

    monkeypatch.setattr(
        "minime.api.app.ProjectCatalogService.validate_project_profiles", profiles_available
    )

    raw = _configuration().model_dump(mode="json")
    raw["provider_connections"]["git_pr"]["auth_mode"] = "project_app"
    raw["github_app_credentials"] = {
        "app_id": "api-app",
        "installation_id": "api-install",
        "private_key": "-----BEGIN PRIVATE KEY-----\nresponse-test\n-----END PRIVATE KEY-----",
    }
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "false")
    monkeypatch.setenv("MINIME_PROJECT_SECRET_ROOT", str(tmp_path / "secrets"))
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_current_operator] = lambda: object()
    try:
        client = TestClient(app)
        created = client.post("/api/v1/projects", json=raw)
        listed = client.get("/api/v1/projects")
        retrieved = client.get("/api/v1/projects/demo")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    for response in (created, listed, retrieved):
        assert response.status_code == 200 or response is created
        assert "secret_reference" not in response.text
        assert "response-test" not in response.text


def test_invalid_api_request_never_echoes_private_key(in_memory_uow, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from minime.api.app import app, get_current_operator, get_uow

    key = "-----BEGIN PRIVATE KEY-----very-secret-test-value"
    raw = _configuration().model_dump(mode="json")
    raw["provider_connections"]["git_pr"] = {
        "provider_id": "github",
        "repository_url": "https://github.com/example/demo",
        "auth_mode": "project_app",
    }
    raw["github_app_credentials"] = {
        "app_id": "123",
        "installation_id": "456",
        "private_key": key,
    }
    raw["agent_profiles"].pop("fallback")
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "false")
    monkeypatch.setenv("MINIME_PROJECT_SECRET_ROOT", str(tmp_path / "secrets"))
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_current_operator] = lambda: object()
    try:
        response = TestClient(app).post("/api/v1/projects", json=raw)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert key not in response.text
    assert not (tmp_path / "secrets").exists()


def test_agent_catalog_requires_authentication(in_memory_uow):
    from fastapi.testclient import TestClient

    from minime.api.app import app, get_uow

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    try:
        response = TestClient(app).get("/api/v1/catalogs/agents")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
