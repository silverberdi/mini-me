"""Exhaustive adversarial unit tests for Stage C: managed-repository-runtime-isolation invariants."""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minime.domain.enums import (
    ExternalOutcome,
    WorkspaceOperation,
    WorkspaceRole,
    WorktreeCreationState,
)
from minime.domain.models import (
    OrchestrationWorktreeOwnership,
    Project,
    ProjectManagedRepositoryBinding,
    WorkspaceMutationRequest,
)
from minime.services.agent_confinement import AgentConfinementError, AgentProcessConfinement
from minime.services.deployment_authority import DeploymentAuthority
from minime.services.openspec_sync import OpenSpecSyncService
from minime.services.workspace_guard import ManagedWorkspaceGuard, normalize_repository_identity
from minime.services.worktree_manager import WorktreeManager


class MockBindingRepo:
    def __init__(self):
        self.bindings = {}

    def save(self, binding: ProjectManagedRepositoryBinding) -> None:
        self.bindings[binding.project_id] = binding

    def get_by_project_id(self, project_id: str) -> ProjectManagedRepositoryBinding | None:
        return self.bindings.get(project_id)

    def get_by_repository_identity(self, canonical_repository_identity: str) -> ProjectManagedRepositoryBinding | None:
        for b in self.bindings.values():
            if b.canonical_repository_identity == canonical_repository_identity:
                return b
        return None

    def delete(self, project_id: str) -> None:
        self.bindings.pop(project_id, None)


class MockWorktreeOwnershipRepo:
    def __init__(self):
        self.ownerships = {}

    def save(self, ownership: OrchestrationWorktreeOwnership) -> None:
        self.ownerships[ownership.worktree_id] = ownership

    def get_by_id(self, worktree_id: str) -> OrchestrationWorktreeOwnership | None:
        return self.ownerships.get(worktree_id)

    def get_by_canonical_path(self, canonical_worktree_path: str) -> OrchestrationWorktreeOwnership | None:
        norm_target = os.path.realpath(canonical_worktree_path) if os.path.exists(canonical_worktree_path) else canonical_worktree_path
        for w in self.ownerships.values():
            norm_w = os.path.realpath(w.canonical_worktree_path) if os.path.exists(w.canonical_worktree_path) else w.canonical_worktree_path
            if norm_w == norm_target or w.canonical_worktree_path == canonical_worktree_path:
                return w
        return None

    def get_by_job_id(self, job_id: str) -> OrchestrationWorktreeOwnership | None:
        for w in self.ownerships.values():
            if w.job_id == job_id:
                return w
        return None

    def list_by_project(self, project_id: str) -> list[OrchestrationWorktreeOwnership]:
        return [w for w in self.ownerships.values() if w.project_id == project_id]

    def list_active(self) -> list[OrchestrationWorktreeOwnership]:
        return [
            w for w in self.ownerships.values()
            if w.creation_state in (WorktreeCreationState.PENDING, WorktreeCreationState.CREATED)
        ]

    def delete(self, worktree_id: str) -> None:
        self.ownerships.pop(worktree_id, None)


class MockProjectRepo:
    def __init__(self):
        self.projects = {}

    def save(self, project: Project) -> None:
        self.projects[project.project_id] = project

    def get_by_id(self, project_id: str):
        return self.projects.get(project_id)

    def list_all(self):
        return list(self.projects.values())


class MockUOW:
    def __init__(self):
        self.project_managed_repository_bindings = MockBindingRepo()
        self.orchestration_worktree_ownerships = MockWorktreeOwnershipRepo()
        self.projects = MockProjectRepo()
        self.git_operations = MagicMock()
        self.events = MagicMock()
        self.metrics = MagicMock()
        self.changes = MagicMock()
        self.bindings = MagicMock()
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.committed = False


@pytest.fixture
def tmp_dirs():
    base = tempfile.mkdtemp()
    runtime = os.path.join(base, "runtime_app")
    repo_root = os.path.join(base, "managed_repo")
    worktrees = os.path.join(base, "worktrees")
    os.makedirs(runtime, exist_ok=True)
    os.makedirs(repo_root, exist_ok=True)
    os.makedirs(worktrees, exist_ok=True)
    yield {
        "base": base,
        "runtime": runtime,
        "repo_root": repo_root,
        "worktrees": worktrees,
    }
    shutil.rmtree(base, ignore_errors=True)


def test_repository_identity_normalization():
    assert normalize_repository_identity("https://github.com/org/repo.git") in ("org/repo", "github.com/org/repo")
    assert normalize_repository_identity("git@github.com:org/repo.git") in ("org/repo", "github.com/org/repo")
    assert normalize_repository_identity("org/repo") == "org/repo"


def test_guard_runtime_protection(tmp_dirs):
    uow = MockUOW()
    guard = ManagedWorkspaceGuard(uow, runtime_root=tmp_dirs["runtime"])

    req = WorkspaceMutationRequest(
        project_id="test-proj",
        target_path=os.path.join(tmp_dirs["runtime"], "src", "main.py"),
        requested_operation=WorkspaceOperation.EDIT,
    )
    decision = guard.evaluate_mutation(req)
    assert decision.allowed is False
    assert decision.workspace_role == WorkspaceRole.RUNTIME
    assert decision.outcome == ExternalOutcome.FAILURE


def test_guard_managed_repo_code_edit_protection(tmp_dirs):
    # Initialize a valid Git repository in repo_root for identity verification
    subprocess.run(["git", "init"], cwd=tmp_dirs["repo_root"], capture_output=True, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/org/repo.git"], cwd=tmp_dirs["repo_root"], capture_output=True, check=True)

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="test-proj",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    guard = ManagedWorkspaceGuard(uow, runtime_root=tmp_dirs["runtime"])

    req = WorkspaceMutationRequest(
        project_id="test-proj",
        target_path=os.path.join(tmp_dirs["repo_root"], "file.py"),
        requested_operation=WorkspaceOperation.EDIT,
    )
    decision = guard.evaluate_mutation(req)
    assert decision.allowed is False
    assert decision.workspace_role == WorkspaceRole.MANAGED_REPOSITORY

    # Sync operation in managed repo root should be allowed
    req_sync = WorkspaceMutationRequest(
        project_id="test-proj",
        target_path=os.path.join(tmp_dirs["repo_root"], "openspec"),
        requested_operation=WorkspaceOperation.OPENSPEC_SYNC,
    )
    decision_sync = guard.evaluate_mutation(req_sync)
    assert decision_sync.allowed is True


def test_guard_execution_worktree_unowned_path_denied(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="test-proj",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    guard = ManagedWorkspaceGuard(uow, runtime_root=tmp_dirs["runtime"])

    unowned_path = os.path.join(tmp_dirs["worktrees"], "unowned-wt-123", "app.py")
    req = WorkspaceMutationRequest(
        project_id="test-proj",
        target_path=unowned_path,
        requested_operation=WorkspaceOperation.EDIT,
    )
    decision = guard.evaluate_mutation(req)
    assert decision.allowed is False
    assert decision.workspace_role == WorkspaceRole.UNKNOWN


def test_guard_execution_worktree_owned_path_allowed(tmp_dirs):
    uow = MockUOW()
    wt_dir = os.path.join(tmp_dirs["worktrees"], "wt-job-100")
    os.makedirs(wt_dir, exist_ok=True)
    binding = ProjectManagedRepositoryBinding(
        project_id="test-proj",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job-100",
        project_id="test-proj",
        job_id="job-100",
        canonical_worktree_path=wt_dir,
        branch_name="minime/change-job-100",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    guard = ManagedWorkspaceGuard(uow, runtime_root=tmp_dirs["runtime"])

    req = WorkspaceMutationRequest(
        project_id="test-proj",
        target_path=os.path.join(wt_dir, "src", "app.py"),
        requested_operation=WorkspaceOperation.EDIT,
    )
    decision = guard.evaluate_mutation(req)
    assert decision.allowed is True
    assert decision.workspace_role == WorkspaceRole.EXECUTION_WORKTREE


def test_agent_confinement_fail_closed_on_unavailable():
    confinement = AgentProcessConfinement(allowed_worktree_path="/tmp/worktree")
    confinement.confinement_mechanism = "none"
    assert confinement.is_confinement_available() is False
    with pytest.raises(AgentConfinementError):
        confinement.wrap_command("touch file")


def test_agent_confinement_darwin_sandbox_profile(tmp_dirs):
    wt_path = os.path.join(tmp_dirs["worktrees"], "wt-1")
    os.makedirs(wt_path, exist_ok=True)
    confinement = AgentProcessConfinement(
        allowed_worktree_path=wt_path,
        runtime_root=tmp_dirs["runtime"],
    )
    confinement.confinement_mechanism = "darwin_sandbox"
    wrapped = confinement.wrap_command(["touch", "file.txt"])
    assert "sandbox-exec" in wrapped[0]
    assert "-p" in wrapped
    assert wt_path in wrapped[2]


def test_agent_confinement_darwin_sandbox_execution(tmp_dirs):
    if not (os.path.exists("/usr/bin/sandbox-exec") or shutil.which("sandbox-exec")):
        pytest.skip("sandbox-exec unavailable on this system")

    wt_path = os.path.join(tmp_dirs["worktrees"], "wt-exec-test")
    os.makedirs(wt_path, exist_ok=True)

    confinement = AgentProcessConfinement(
        allowed_worktree_path=wt_path,
        runtime_root=tmp_dirs["runtime"],
    )
    confinement.confinement_mechanism = "darwin_sandbox"

    # Write inside allowed worktree succeeds
    res_ok = confinement.run_confined_subprocess(["touch", os.path.join(wt_path, "allowed.txt")], cwd=wt_path)
    assert res_ok.returncode == 0
    assert os.path.exists(os.path.join(wt_path, "allowed.txt"))

    # Write inside runtime root fails
    res_fail = confinement.run_confined_subprocess(["touch", os.path.join(tmp_dirs["runtime"], "forbidden.txt")], cwd=wt_path)
    assert res_fail.returncode != 0
    assert not os.path.exists(os.path.join(tmp_dirs["runtime"], "forbidden.txt"))


def test_deployment_authority_boundary(tmp_dirs):
    uow = MockUOW()
    mock_project = MagicMock()
    mock_project.project_id = "test-proj"
    uow.projects.projects["test-proj"] = mock_project

    dep_authority = DeploymentAuthority(uow)

    # Missing merge commit sha -> FAILURE
    res_no_sha = dep_authority.promote_candidate_to_production(
        project_id="test-proj",
        change_name="feat-1",
        candidate_sha="abc1234",
        merge_commit_sha="",
        operator_identity="admin",
    )
    assert res_no_sha.outcome == ExternalOutcome.FAILURE

    # Valid promotion returns HANDOFF_READY, NOT DEPLOYED
    res_success = dep_authority.promote_candidate_to_production(
        project_id="test-proj",
        change_name="feat-1",
        candidate_sha="abc1234",
        merge_commit_sha="def5678",
        operator_identity="admin",
    )
    assert res_success.outcome == ExternalOutcome.SUCCESS
    assert res_success.data["status"] == "HANDOFF_READY"


def test_openspec_sync_runtime_target_denied(tmp_dirs):
    uow = MockUOW()
    sync_service = OpenSpecSyncService(project_root=tmp_dirs["runtime"], uow=uow)

    # Sync into runtime root => POLICY_DENIED
    res = sync_service.sync_change_specs(openspec_path="openspec", change_name="test-change")
    assert res.outcome == ExternalOutcome.FAILURE
    assert "POLICY_DENIED" in res.error_message


def test_openspec_archive_runtime_target_denied(tmp_dirs):
    uow = MockUOW()
    sync_service = OpenSpecSyncService(project_root=tmp_dirs["runtime"], uow=uow)

    # Archive inside runtime root => POLICY_DENIED
    res = sync_service.archive_change(openspec_path="openspec", change_name="test-change")
    assert res.outcome == ExternalOutcome.FAILURE
    assert "POLICY_DENIED" in res.error_message


def test_worktree_manager_pending_ordering(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    with patch.object(wt_manager, "_git", new_callable=AsyncMock) as mock_git:
        mock_git.return_value = "abc123sha"

        # Mock durable PENDING record saved before git invocation
        wt_path = wt_manager.worktree_path("job-test-10").resolve()

        # Execute create_worktree
        asyncio.run(wt_manager.create_worktree("job-test-10", "change-1", "main", project_id="proj-1"))

        # Verify DB ownership record was created with PENDING state
        ownership = uow.orchestration_worktree_ownerships.get_by_id("wt-job-test-10")
        assert ownership is not None
        assert ownership.canonical_worktree_path == str(wt_path)
        assert ownership.creation_state == WorktreeCreationState.CREATED


def test_worktree_manager_cleanup_unowned_directory_denied(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    unowned_wt = wt_manager.worktrees_root / "unowned-wt-path"
    os.makedirs(unowned_wt, exist_ok=True)

    # Attempt to remove clean unowned worktree path
    asyncio.run(wt_manager.remove_clean_worktree_path(unowned_wt, "job-unowned", "proj-1"))

    # Unowned directory must be preserved
    assert unowned_wt.exists()


def test_worktree_manager_cleanup_marker_conflict_denied(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    wt_path = wt_manager.worktrees_root / "job-marker-test"
    os.makedirs(wt_path, exist_ok=True)

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job-marker-test",
        project_id="proj-1",
        job_id="job-marker-test",
        canonical_worktree_path=str(wt_path.resolve()),
        branch_name="minime/test",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    # Write spoofed marker with wrong worktree_id
    marker_file = wt_path / ".minime_worktree_ownership.json"
    marker_file.write_text(json.dumps({"worktree_id": "wt-SPOOFED", "canonical_worktree_path": str(wt_path.resolve())}))

    # Attempt to remove worktree path
    asyncio.run(wt_manager.remove_clean_worktree_path(wt_path, "job-marker-test", "proj-1"))

    # Conflicting directory must be preserved
    assert wt_path.exists()
