from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.api import app as api_module
from minime.db.models import (
    ProjectManagedRepositoryBindingModel,
    ProjectModel,
    ProviderModelRegistryModel,
)
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.services.project_catalog_service import ProjectCatalogService
from minime.services.provider_registry import IntrospectionResult


@pytest.fixture
def persistent_api_client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'provider-model-admin.db'}",
        connect_args={"check_same_thread": False},
    )
    for table in (
        ProjectModel.__table__,
        ProjectManagedRepositoryBindingModel.__table__,
        ProviderModelRegistryModel.__table__,
    ):
        table.create(engine)

    def override_uow():
        session = Session(engine)
        try:
            yield PostgresPersistenceUnitOfWork(session)
        finally:
            session.close()

    async def validated_profiles_without_host_probe(self, profiles, project_root=None):
        return None

    async def observed_harness(self):
        return IntrospectionResult(
            harness_id=self.harness_id,
            status="available",
            code="ok",
            summary="test CLI observed",
            cli_version="1.0",
            models=(),
        )

    api_module.app.dependency_overrides[api_module.get_uow] = override_uow
    api_module.app.dependency_overrides[api_module.get_current_operator] = lambda: object()
    monkeypatch.setattr(
        ProjectCatalogService,
        "validate_project_profiles",
        validated_profiles_without_host_probe,
    )
    monkeypatch.setattr(api_module.SafeCliHarness, "inspect", observed_harness)
    # SQLite drops timezone info from DateTime columns; keep the resolver's
    # test clock comparable to timestamps read back from this persistent DB.
    monkeypatch.setattr("minime.services.provider_registry.utc_now", datetime.now)
    monkeypatch.setenv("MINIME_AUTH_ENABLED", "false")
    with Session(engine) as session:
        session.add_all([
            ProviderModelRegistryModel(
                id="think-model", provider_id="provider-a", harness_id="opencode",
                canonical_model_id="think-v1", origin="discovered",
                capabilities={"thinking": True, "workflow": True, "file_edit": True, "read_only_review": True},
                discovery_status="available", diagnostic_code="ok", diagnostic_summary="observed",
                version=1, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
            ),
            ProviderModelRegistryModel(
                id="review-model", provider_id="provider-b", harness_id="codex",
                canonical_model_id="review-v1", origin="discovered",
                capabilities={"thinking": True, "workflow": True, "file_edit": True, "read_only_review": True},
                discovery_status="available", diagnostic_code="ok", diagnostic_summary="observed",
                version=1, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
            ),
            ProviderModelRegistryModel(
                id="think-model-v2", provider_id="provider-a", harness_id="opencode",
                canonical_model_id="think-v2", origin="discovered",
                capabilities={"thinking": True, "workflow": True, "file_edit": True, "read_only_review": True},
                discovery_status="available", diagnostic_code="ok", diagnostic_summary="observed",
                version=1, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
            ),
        ])
        profiles = {
            role: {
                "agent_id": "codex" if role == "independent_review" else "opencode",
                "provider_id": "provider-b" if role == "independent_review" else "provider-a",
                "harness_id": "codex" if role == "independent_review" else "opencode",
                "model_id": "review-v1" if role == "independent_review" else "think-v1",
                "effort": "medium",
            }
            for role in ("thinking", "execution", "independent_review", "fallback")
        }
        session.add(ProjectModel(
            id="project-253",
            display_name="Issue 253 project",
            repository="owner/project-253",
            project_type="BROWNFIELD",
            provider_connections={},
            agent_profiles=profiles,
            execution_policy={},
            onboarding_checkpoint={},
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
            reviewer="antigravity",
            checks=[],
            external_providers_allowed=[],
            openrouter_drain_allowed=False,
            independent_audit_required=False,
            strict_validation_required=True,
            verify_gate_required=True,
            sync_gate_required=True,
            archive_gate_required=True,
            deployment_preview={},
            deployment_production={},
            onboarding_status="CONFIGURED",
            onboarding_reasons=[],
            status="ACTIVE",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        session.commit()

    yield TestClient(api_module.app)
    api_module.app.dependency_overrides.pop(api_module.get_uow, None)
    api_module.app.dependency_overrides.pop(api_module.get_current_operator, None)
    engine.dispose()


def test_admin_toggle_and_project_role_update_persist_through_real_api(persistent_api_client):
    client = persistent_api_client

    catalog = client.get("/api/v1/admin/providers/catalog")
    assert catalog.status_code == 200
    model = next(item for item in catalog.json()["models"] if item["id"] == "think-model")
    assert model["is_enabled"] is True
    assert model["discovery_status"] == "available"

    disabled = client.patch(
        "/api/v1/admin/providers/models/think-model/enabled",
        json={"is_enabled": False, "version": model["version"]},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_enabled"] is False
    assert disabled.json()["discovery_status"] == "available"
    assert disabled.json()["version"] == model["version"] + 1
    persisted_catalog = client.get("/api/v1/admin/providers/catalog").json()
    persisted = next(item for item in persisted_catalog["models"] if item["id"] == "think-model")
    assert persisted["is_enabled"] is False
    assert persisted["diagnostic"]["code"] == "ok"

    stale = client.patch(
        "/api/v1/admin/providers/models/think-model/enabled",
        json={"is_enabled": True, "version": model["version"]},
    )
    assert stale.status_code == 409

    refreshed = client.post("/api/v1/admin/providers/refresh", json={})
    assert refreshed.status_code == 200
    assert all(item["status"] == "available" for item in refreshed.json()["results"])
    refreshed_model = next(
        item for item in refreshed.json()["catalog"]["models"] if item["id"] == "think-model"
    )
    assert refreshed_model["is_enabled"] is False
    assert refreshed_model["discovery_status"] == "available"

    project = client.get("/api/v1/projects/project-253")
    assert project.status_code == 200
    profiles = project.json()["agent_profiles"]
    rejected = client.patch(
        "/api/v1/projects/project-253", json={"agent_profiles": profiles}
    )
    assert rejected.status_code == 400
    assert "disabled by operator" in rejected.json()["detail"]

    enabled = client.patch(
        "/api/v1/admin/providers/models/think-model/enabled",
        json={"is_enabled": True, "version": refreshed_model["version"]},
    )
    assert enabled.status_code == 200
    profiles["thinking"]["model_id"] = "think-v2"
    saved = client.patch(
        "/api/v1/projects/project-253", json={"agent_profiles": profiles}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["agent_profiles"]["thinking"]["model_id"] == "think-v2"
    assert saved.json()["agent_profiles"]["fallback"]["model_id"] == project.json()["agent_profiles"]["fallback"]["model_id"]
    assert saved.json()["agent_profiles"]["fallback"]["agent_id"] == project.json()["agent_profiles"]["fallback"]["agent_id"]
