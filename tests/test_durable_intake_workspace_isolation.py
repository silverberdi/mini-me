"""Comprehensive integration and unit test suite for Durable Intake Workspace Isolation & Artifact Publication."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from minime.domain.enums import (
    IntakeWorkspaceCreationState,
    IntakeWorkspacePublicationState,
    WorkspaceOperation,
    WorkspaceRole,
)
from minime.domain.exceptions import (
    ManagedWorkspaceGuardDeniedError,
)
from minime.domain.models import (
    BacklogItem,
    IntakeWorkspaceOwnership,
    Project,
    ProjectBinding,
    ProjectManagedRepositoryBinding,
)
from minime.services.intake_service import IntakeService
from minime.services.openspec_generator import OpenSpecGenerator
from minime.services.readiness_service import ReadinessService
from minime.services.workspace_guard import ManagedWorkspaceGuard


class InMemoryIntakeWorkspaceOwnershipRepository:
    """In-memory test double repository for IntakeWorkspaceOwnership."""

    def __init__(self) -> None:
        self._by_id: dict[str, IntakeWorkspaceOwnership] = {}

    def save(self, entity: IntakeWorkspaceOwnership) -> IntakeWorkspaceOwnership:
        self._by_id[entity.workspace_id] = entity
        return entity

    def get_by_id(self, workspace_id: str) -> IntakeWorkspaceOwnership | None:
        return self._by_id.get(workspace_id)

    def get_active_by_item_key(
        self, project_id: str, item_key: str
    ) -> IntakeWorkspaceOwnership | None:
        for entity in self._by_id.values():
            if (
                entity.project_id == project_id
                and entity.item_key == item_key
                and entity.creation_state in (
                    IntakeWorkspaceCreationState.RESERVED,
                    IntakeWorkspaceCreationState.CREATING,
                    IntakeWorkspaceCreationState.ACTIVE,
                )
            ):
                return entity
        return None

    def list_active(self) -> list[IntakeWorkspaceOwnership]:
        return [
            e
            for e in self._by_id.values()
            if e.creation_state in (
                IntakeWorkspaceCreationState.RESERVED,
                IntakeWorkspaceCreationState.CREATING,
                IntakeWorkspaceCreationState.ACTIVE,
            )
        ]

    def list_by_project(self, project_id: str) -> list[IntakeWorkspaceOwnership]:
        return [e for e in self._by_id.values() if e.project_id == project_id]

    def get_by_canonical_path(self, canonical_path: str) -> IntakeWorkspaceOwnership | None:
        real_target = os.path.realpath(canonical_path)
        for entity in self._by_id.values():
            real_ws = os.path.realpath(entity.canonical_workspace_path)
            if real_target == real_ws or real_target.startswith(real_ws + os.sep):
                return entity
        return None


class FakeUnitOfWork:
    """Fake UnitOfWork for unit testing intake workspace isolation."""

    def __init__(self, projects=None, backlog_items=None, bindings=None) -> None:
        self.projects = projects or FakeRepo()
        self.backlog_items = backlog_items or FakeRepo()
        self.bindings = bindings or FakeRepo()
        self.changes = FakeRepo()
        self.events = FakeRepo()
        self.work_queue = FakeRepo()
        self.orchestration_external_actions = FakeRepo()
        self.durable_sagas = FakeRepo()
        self.intake_workspace_ownerships = InMemoryIntakeWorkspaceOwnershipRepository()
        self.project_managed_repository_bindings = FakeBindingRepo()

    def commit(self) -> None:
        pass


class FakeRepo:
    def __init__(self) -> None:
        self.items: dict[str, Any] = {}

    def get_by_id(self, item_id: str) -> Any:
        return self.items.get(item_id)

    def save(self, item: Any) -> Any:
        key = getattr(item, "project_id", getattr(item, "item_key", getattr(item, "id", str(id(item)))))
        self.items[key] = item
        return item

    def get_by_project_and_key(self, project_id: str, key: str) -> Any:
        return self.items.get(f"{project_id}:{key}") or self.items.get(key)

    def get_by_name(self, project_id: str, name: str) -> Any:
        return self.items.get(f"{project_id}:{name}") or self.items.get(name)

    def get_by_project_and_change(self, project_id: str, change_name: str) -> Any:
        return self.items.get(f"{project_id}:{change_name}")

    def get_by_action_key(self, action_key: str) -> Any:
        return self.items.get(action_key)

    def list_by_project(self, project_id: str) -> list[Any]:
        return list(self.items.values())


class FakeBindingRepo:
    def __init__(self) -> None:
        self.bindings: dict[str, Any] = {}

    def get_by_project_id(self, project_id: str) -> Any:
        return self.bindings.get(project_id)


@pytest.fixture
def tmp_env(tmp_path: Path):
    managed_root = tmp_path / "managed_repo"
    managed_root.mkdir()
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=managed_root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=managed_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=managed_root, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/silverberdi/mini-me.git"], cwd=managed_root, check=True)

    marker_content = {
        "project_id": "proj-1",
        "canonical_repository_identity": "silverberdi/mini-me",
    }
    import json
    (managed_root / ".minime-managed-project.json").write_text(json.dumps(marker_content))
    (managed_root / "openspec" / "changes").mkdir(parents=True)

    wt_parent = tmp_path / "worktrees"
    wt_parent.mkdir()

    runtime_root = tmp_path / "runtime_app"
    runtime_root.mkdir()

    project = Project(
        project_id="proj-1",
        display_name="Test Project",
        repository="silverberdi/mini-me",
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )
    managed_binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="silverberdi/mini-me",
        managed_repository_root=str(managed_root),
        worktree_parent_dir=str(wt_parent),
        is_valid=True,
    )
    binding = ProjectBinding(
        project_id="proj-1",
        repository="silverberdi/mini-me",
        openspec_change_name="test-change",
        is_valid=True,
    )

    uow = FakeUnitOfWork()
    uow.projects.save(project)
    uow.project_managed_repository_bindings.bindings["proj-1"] = managed_binding

    return {
        "tmp_path": tmp_path,
        "managed_root": managed_root,
        "wt_parent": wt_parent,
        "runtime_root": runtime_root,
        "project": project,
        "binding": binding,
        "uow": uow,
    }


def test_intake_workspace_ownership_model_creation():
    ow = IntakeWorkspaceOwnership(
        workspace_id="ws-123",
        project_id="proj-1",
        item_key="feature-x",
        saga_id="saga-456",
        change_name="feature-x",
        canonical_workspace_path="/tmp/worktrees/intake-workspaces/proj-1/ws-123",
        canonical_repository_identity="silverberdi/mini-me",
        base_sha="abc1234",
    )
    assert ow.workspace_id == "ws-123"
    assert ow.creation_state == IntakeWorkspaceCreationState.RESERVED
    assert ow.publication_state == IntakeWorkspacePublicationState.UNPUBLISHED
    assert ow.published_ref is None
    assert ow.published_sha is None


def test_managed_workspace_guard_denies_direct_managed_root_authoring(tmp_env):
    uow = tmp_env["uow"]
    guard = ManagedWorkspaceGuard(uow=uow, runtime_root=str(tmp_env["runtime_root"]))

    # Test direct write into managed_repository_root with OPENSPEC_AUTHORING
    from minime.domain.models import WorkspaceMutationRequest
    req = WorkspaceMutationRequest(
        project_id="proj-1",
        target_path=str(tmp_env["managed_root"] / "openspec" / "changes" / "foo"),
        requested_operation=WorkspaceOperation.OPENSPEC_AUTHORING,
    )
    decision = guard.evaluate_mutation_pure(req)
    assert not decision.allowed
    assert "All intake authoring must be conducted within an isolated INTAKE_WORKSPACE" in (decision.provider_detail or "")


def test_managed_workspace_guard_authorizes_active_intake_workspace(tmp_env):
    uow = tmp_env["uow"]
    ws_path = str(tmp_env["wt_parent"] / "intake-workspaces" / "proj-1" / "ws-999")
    os.makedirs(ws_path, exist_ok=True)

    ow = IntakeWorkspaceOwnership(
        workspace_id="ws-999",
        project_id="proj-1",
        item_key="feature-y",
        saga_id="saga-999",
        change_name="feature-y",
        canonical_workspace_path=ws_path,
        canonical_repository_identity="silverberdi/mini-me",
        base_sha="abc1234",
        creation_state=IntakeWorkspaceCreationState.ACTIVE,
    )
    uow.intake_workspace_ownerships.save(ow)

    guard = ManagedWorkspaceGuard(uow=uow, runtime_root=str(tmp_env["runtime_root"]))
    from minime.domain.models import WorkspaceMutationRequest
    req = WorkspaceMutationRequest(
        project_id="proj-1",
        target_path=os.path.join(ws_path, "openspec", "changes", "feature-y", "proposal.md"),
        requested_operation=WorkspaceOperation.OPENSPEC_AUTHORING,
    )
    decision = guard.evaluate_mutation_pure(req)
    assert decision.allowed
    assert decision.workspace_role == WorkspaceRole.INTAKE_WORKSPACE


def test_openspec_generator_rejects_direct_managed_root_write(tmp_env):
    uow = tmp_env["uow"]
    gen = OpenSpecGenerator(project_root=tmp_env["managed_root"], uow=uow)

    item = BacklogItem(
        project_id="proj-1",
        item_key="test-item",
        title="Test Item",
        description="A detailed description for testing direct write rejection.",
        acceptance_criteria=["Criterion 1"],
    )
    generated = gen.generate_from_backlog_item(item)

    with pytest.raises(ManagedWorkspaceGuardDeniedError) as exc_info:
        gen.write_change_to_disk(
            openspec_path="openspec",
            generated=generated,
            project_id="proj-1",
            uow=uow,
            target_workspace_path=tmp_env["managed_root"],
        )
    assert "Direct writes to managed_repository_root" in str(exc_info.value)


def test_readiness_service_requires_published_ref(tmp_env):
    uow = tmp_env["uow"]
    svc = ReadinessService(uow=uow)

    eval_result = svc.evaluate_change_readiness_pure(
        project_id="proj-1",
        change_name="feature-z",
        project_root=str(tmp_env["managed_root"]),
        require_published_ref=True,
    )

    assert not eval_result.is_ready
    assert any("published Git ref" in r for r in eval_result.unmet_reasons)


def test_cleanup_intake_workspace_4_way_corroboration(tmp_env):
    uow = tmp_env["uow"]
    svc = IntakeService(uow=uow, project_root=tmp_env["managed_root"])

    ws_path = str(tmp_env["wt_parent"] / "intake-workspaces" / "proj-1" / "ws-cleanup")
    os.makedirs(ws_path, exist_ok=True)
    marker_path = os.path.join(ws_path, ".minime_intake_workspace")
    Path(marker_path).write_text("{}")

    ow = IntakeWorkspaceOwnership(
        workspace_id="ws-cleanup",
        project_id="proj-1",
        item_key="clean-item",
        saga_id="saga-clean",
        change_name="clean-item",
        canonical_workspace_path=ws_path,
        canonical_repository_identity="silverberdi/mini-me",
        base_sha="sha123",
        creation_state=IntakeWorkspaceCreationState.ACTIVE,
    )
    uow.intake_workspace_ownerships.save(ow)

    # Attempt cleanup when state is ACTIVE (should be denied)
    with pytest.raises(ManagedWorkspaceGuardDeniedError):
        svc.cleanup_intake_workspace("ws-cleanup")

    # A marker-only directory is not a Git corroborated worktree and must
    # remain untouched even when durable cleanup is otherwise authorized.
    ow.creation_state = IntakeWorkspaceCreationState.RELEASED_PENDING_CLEANUP
    uow.intake_workspace_ownerships.save(ow)

    with pytest.raises(ManagedWorkspaceGuardDeniedError, match="not corroborated"):
        svc.cleanup_intake_workspace("ws-cleanup")
    assert Path(ws_path).exists()
    updated_ow = uow.intake_workspace_ownerships.get_by_id("ws-cleanup")
    assert updated_ow.creation_state == IntakeWorkspaceCreationState.RELEASED_PENDING_CLEANUP
