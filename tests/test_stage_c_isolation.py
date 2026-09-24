"""Exhaustive adversarial unit tests for Stage C: managed-repository-runtime-isolation invariants."""

import asyncio
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minime.domain.enums import (
    ExternalOutcome,
    ExternalReasonCode,
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
from minime.services.agent_confinement import (
    AgentConfinementError,
    AgentProcessConfinement,
)
from minime.services.deployment_authority import DeploymentAuthority
from minime.services.openspec_sync import OpenSpecSyncService
from minime.services.workspace_guard import (
    ManagedWorkspaceGuard,
    normalize_repository_identity,
)
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

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/org/repo"], cwd=repo_root, check=True)
    with open(os.path.join(repo_root, "README.md"), "w") as f:
        f.write("base\n")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_root, check=True, capture_output=True)

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
    subprocess.run(["git", "init"], cwd=wt_dir, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/org/repo"], cwd=wt_dir, check=True, capture_output=True)
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
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    sync_service = OpenSpecSyncService(project_root=tmp_dirs["runtime"], uow=uow)

    # Sync into runtime root => POLICY_DENIED
    res = sync_service.sync_change_specs(openspec_path="openspec", change_name="test-change", project_id="proj-1")
    assert res.outcome == ExternalOutcome.FAILURE
    assert res.reason_code == ExternalReasonCode.POLICY_DENIED


def test_openspec_archive_runtime_target_denied(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    sync_service = OpenSpecSyncService(project_root=tmp_dirs["runtime"], uow=uow)

    # Archive inside runtime root => POLICY_DENIED
    res = sync_service.archive_change(openspec_path="openspec", change_name="test-change", project_id="proj-1")
    assert res.outcome == ExternalOutcome.FAILURE
    assert res.reason_code == ExternalReasonCode.POLICY_DENIED


def test_worktree_manager_pending_ordering(tmp_dirs):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_dirs["repo_root"], check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_dirs["repo_root"], check=True)
    (Path(tmp_dirs["repo_root"]) / "README.md").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_dirs["repo_root"], check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True)

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    wt_path = wt_manager.worktree_path("job-test-10", project_id="proj-1").resolve()

    asyncio.run(wt_manager.create_worktree("job-test-10", "change-1", "main", project_id="proj-1"))

    ownership = uow.orchestration_worktree_ownerships.get_by_id("wt-job-test-10")
    assert ownership is not None
    assert ownership.canonical_worktree_path == str(wt_path)
    assert ownership.creation_state == WorktreeCreationState.CREATED


def test_worktree_manager_cleanup_unowned_directory_denied(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    unowned_wt = wt_manager.worktrees_root / "unowned-wt-path"
    os.makedirs(unowned_wt, exist_ok=True)

    asyncio.run(wt_manager.remove_clean_worktree_path(unowned_wt, "job-unowned", "proj-1"))
    assert unowned_wt.exists()


def test_worktree_manager_cleanup_marker_conflict_denied(tmp_dirs):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True)
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
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

    marker_file = wt_path / ".minime_worktree_ownership.json"
    marker_file.write_text(json.dumps({"worktree_id": "wt-SPOOFED", "canonical_worktree_path": str(wt_path.resolve())}))

    asyncio.run(wt_manager.remove_clean_worktree_path(wt_path, "job-marker-test", "proj-1"))
    assert wt_path.exists()


def test_guard_denial_happens_before_pending(tmp_dirs):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True)
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    guard = MagicMock(spec=ManagedWorkspaceGuard)
    guard.evaluate_mutation.return_value = MagicMock(allowed=False, provider_detail="Guard Denied", reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN)

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow, workspace_guard=guard)

    with pytest.raises(RuntimeError, match="ManagedWorkspaceGuard denied WORKTREE_CREATE"):
        asyncio.run(wt_manager.create_worktree("job-denied-1", "change-1", "main", project_id="proj-1"))

    ownership = uow.orchestration_worktree_ownerships.get_by_id("wt-job-denied-1")
    assert ownership is None


def test_pending_persistence_failure_prevents_git_add(tmp_dirs):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True)
    bad_uow = MagicMock()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    mock_b_repo = MagicMock()
    mock_b_repo.get_by_project_id.return_value = binding
    bad_uow.project_managed_repository_bindings = mock_b_repo
    bad_uow.orchestration_worktree_ownerships = None
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=bad_uow)

    with patch.object(wt_manager, "_git", new_callable=AsyncMock) as mock_git:
        with pytest.raises(RuntimeError, match="orchestration_worktree_ownerships repository missing"):
            asyncio.run(wt_manager.create_worktree("job-no-uow", "change-1", "main", project_id="proj-1"))

        for call_item in mock_git.call_args_list:
            args = call_item.args[0] if call_item.args else []
            assert "worktree" not in args or "add" not in args


def test_marker_only_cleanup_denied(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    marker_only_path = wt_manager.worktrees_root / "marker-only"
    os.makedirs(marker_only_path, exist_ok=True)
    marker_file = marker_only_path / ".minime_worktree_ownership.json"
    marker_file.write_text(json.dumps({"worktree_id": "wt-marker-only", "job_id": "job-marker-only"}))

    # Without durable DB ownership, cleanup must be denied and directory preserved
    asyncio.run(wt_manager.remove_clean_worktree_path(marker_only_path, "job-marker-only", "proj-1"))
    assert marker_only_path.exists()


def test_dot_git_only_cleanup_denied(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    git_only_path = wt_manager.worktrees_root / "git-only"
    os.makedirs(git_only_path, exist_ok=True)
    (git_only_path / ".git").write_text("gitdir: /fake/path")

    # Without durable DB ownership, cleanup must be denied and directory preserved
    asyncio.run(wt_manager.remove_clean_worktree_path(git_only_path, "job-git-only", "proj-1"))
    assert git_only_path.exists()


def test_path_under_root_only_cleanup_denied(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    root_only_path = wt_manager.worktrees_root / "root-only"
    os.makedirs(root_only_path, exist_ok=True)

    # Without durable DB ownership, cleanup must be denied and directory preserved
    asyncio.run(wt_manager.remove_clean_worktree_path(root_only_path, "job-root-only", "proj-1"))
    assert root_only_path.exists()


def test_pending_worktree_denied_for_mutation(tmp_dirs):
    uow = MockUOW()
    wt_dir = os.path.join(tmp_dirs["worktrees"], "wt-pending-job")
    os.makedirs(wt_dir, exist_ok=True)

    binding = ProjectManagedRepositoryBinding(
        project_id="test-proj",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-pending-job",
        project_id="test-proj",
        job_id="pending-job",
        canonical_worktree_path=wt_dir,
        branch_name="minime/change-pending-job",
        creation_state=WorktreeCreationState.PENDING,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    guard = ManagedWorkspaceGuard(uow, runtime_root=tmp_dirs["runtime"])

    req = WorkspaceMutationRequest(
        project_id="test-proj",
        target_path=os.path.join(wt_dir, "src", "app.py"),
        requested_operation=WorkspaceOperation.EDIT,
    )
    decision = guard.evaluate_mutation(req)

    # Mutation on PENDING worktree must be denied
    assert decision.allowed is False
    assert "not CREATED" in decision.provider_detail


def test_worktree_manager_without_uow_fails_closed(tmp_dirs):
    with pytest.raises(ValueError, match="PersistenceUnitOfWork .* is required"):
        WorktreeManager(project_root=tmp_dirs["repo_root"], uow=None)


def test_missing_project_id_fails_closed(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    wt_path = wt_manager.worktrees_root / "wt-no-proj"

    with pytest.raises(ValueError, match="project_id is mandatory"):
        asyncio.run(wt_manager.create_worktree("job-1", "change-1", "main", project_id=None))

    with pytest.raises(ValueError, match="project_id is mandatory"):
        asyncio.run(wt_manager.remove_clean_worktree_path(wt_path, "job-1", project_id=None))


def test_no_synthetic_binding_and_missing_binding_denies(tmp_dirs):
    uow = MockUOW()
    guard = ManagedWorkspaceGuard(uow, runtime_root=tmp_dirs["runtime"])

    req = WorkspaceMutationRequest(
        project_id="unbound-proj",
        target_path=os.path.join(tmp_dirs["repo_root"], "src", "app.py"),
        requested_operation=WorkspaceOperation.EDIT,
    )
    decision = guard.evaluate_mutation(req)

    assert decision.allowed is False
    assert decision.reason_code == ExternalReasonCode.EVIDENCE_INSUFFICIENT
    assert "No managed repository binding found" in decision.provider_detail


def test_dot_minime_path_does_not_synthesize_authorization(tmp_dirs):
    uow = MockUOW()
    guard = ManagedWorkspaceGuard(uow, runtime_root=tmp_dirs["runtime"])

    # Path containing .minime must not synthesize authorization
    minime_path = os.path.join(tmp_dirs["repo_root"], ".minime", "worktrees", "wt-job", "file.py")
    req = WorkspaceMutationRequest(
        project_id="unbound-proj",
        target_path=minime_path,
        requested_operation=WorkspaceOperation.EDIT,
    )
    decision = guard.evaluate_mutation(req)

    assert decision.allowed is False
    assert decision.reason_code == ExternalReasonCode.EVIDENCE_INSUFFICIENT
    assert "No managed repository binding found" in decision.provider_detail


def test_missing_git_remote_fails_identity_proof():
    no_remote_dir = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-b", "main"], cwd=no_remote_dir, check=True, capture_output=True)
        uow = MockUOW()
        guard = ManagedWorkspaceGuard(uow)

        valid, reason = guard.verify_git_repository_identity(
            no_remote_dir, "github.com/org/repo", remote_name="origin"
        )
        assert valid is False
        assert "Configured remote 'origin' missing" in reason
    finally:
        shutil.rmtree(no_remote_dir, ignore_errors=True)


def test_wrong_remote_fails(tmp_dirs):
    uow = MockUOW()
    guard = ManagedWorkspaceGuard(uow)

    # Set origin remote to different repository
    subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/org/wrong-repo.git"], cwd=tmp_dirs["repo_root"], check=True)

    valid, reason = guard.verify_git_repository_identity(
        tmp_dirs["repo_root"], "github.com/org/correct-repo", remote_name="origin"
    )
    assert valid is False
    assert "remote mismatch" in reason


def test_temp_path_outside_configured_trusted_root_denied(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="test-proj",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    # Configure trusted_managed_root to a completely different path
    other_trusted_root = tempfile.mkdtemp()
    try:
        guard = ManagedWorkspaceGuard(uow, runtime_root=tmp_dirs["runtime"], trusted_managed_root=other_trusted_root)
        req = WorkspaceMutationRequest(
            project_id="test-proj",
            target_path=os.path.join(tmp_dirs["repo_root"], "README.md"),
            requested_operation=WorkspaceOperation.READ,
        )
        decision = guard.evaluate_mutation(req)

        assert decision.allowed is False
        assert "lies outside trusted managed root" in decision.provider_detail or "outside trusted managed root" in decision.provider_detail
    finally:
        shutil.rmtree(other_trusted_root, ignore_errors=True)


def test_explicit_trusted_root_allows_valid_temp_fixture(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="test-proj",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    # Configure trusted_managed_root to include parent of repo_root
    parent_trusted = str(Path(tmp_dirs["repo_root"]).parent.resolve())
    guard = ManagedWorkspaceGuard(uow, runtime_root=tmp_dirs["runtime"], trusted_managed_root=parent_trusted)
    req = WorkspaceMutationRequest(
        project_id="test-proj",
        target_path=os.path.join(tmp_dirs["worktrees"], "wt-job", "app.py"),
        requested_operation=WorkspaceOperation.EDIT,
    )

    # Register CREATED worktree ownership so role evaluation succeeds
    wt_path = os.path.join(tmp_dirs["worktrees"], "wt-job")
    os.makedirs(wt_path, exist_ok=True)
    subprocess.run(["git", "init"], cwd=wt_path, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/org/repo"], cwd=wt_path, check=True, capture_output=True)
    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job",
        project_id="test-proj",
        job_id="job",
        canonical_worktree_path=wt_path,
        branch_name="minime/change-job",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    decision = guard.evaluate_mutation(req)
    assert decision.allowed is True


def test_empty_git_worktree_list_prevents_created(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    wt_path = Path(tmp_dirs["worktrees"]) / "wt-empty-list"
    wt_path.mkdir(parents=True, exist_ok=True)

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-empty-list",
        project_id="test-proj",
        job_id="empty-list-job",
        canonical_worktree_path=str(wt_path.resolve()),
        branch_name="main",
        creation_state=WorktreeCreationState.PENDING,
    )

    with patch.object(wt_manager, "_git") as mock_git:
        # Simulate empty worktree list output
        async def mock_git_impl(args, **kwargs):
            if "worktree" in args and "list" in args:
                return ""
            if "branch" in args:
                return "main"
            if "rev-parse" in args:
                return "1234567890abcdef"
            return ""

        mock_git.side_effect = mock_git_impl

        with pytest.raises(RuntimeError, match="not present in git worktree list"):
            asyncio.run(
                wt_manager._verify_creation_postconditions(
                    wt_path, ownership, expected_branch="main", expected_base_sha="1234567890abcdef"
                )
            )


def test_wrong_head_sha_prevents_created(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    wt_path = Path(tmp_dirs["worktrees"]) / "wt-wrong-sha"
    wt_path.mkdir(parents=True, exist_ok=True)

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-wrong-sha",
        project_id="test-proj",
        job_id="wrong-sha-job",
        canonical_worktree_path=str(wt_path.resolve()),
        branch_name="main",
        creation_state=WorktreeCreationState.PENDING,
    )

    with patch.object(wt_manager, "_git") as mock_git:
        async def mock_git_impl(args, **kwargs):
            if "worktree" in args and "list" in args:
                return f"worktree {wt_path.resolve()}\n"
            if "branch" in args:
                return "main"
            if "rev-parse" in args:
                if "HEAD" in args:
                    return "actual_sha_123"
                return "expected_sha_456"
            return ""

        mock_git.side_effect = mock_git_impl

        with pytest.raises(RuntimeError, match="actual HEAD SHA 'actual_sha_123' does not match expected SHA 'expected_sha_456'"):
            asyncio.run(
                wt_manager._verify_creation_postconditions(
                    wt_path, ownership, expected_branch="main", expected_base_sha="expected_sha_456"
                )
            )


def test_correct_head_sha_allows_created(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    wt_path = Path(tmp_dirs["worktrees"]) / "wt-correct-sha"
    wt_path.mkdir(parents=True, exist_ok=True)
    wt_manager._write_ownership_marker(
        wt_path,
        OrchestrationWorktreeOwnership(
            worktree_id="wt-correct-sha",
            project_id="test-proj",
            job_id="correct-sha-job",
            canonical_worktree_path=str(wt_path.resolve()),
            branch_name="main",
            creation_state=WorktreeCreationState.PENDING,
        ),
    )

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-correct-sha",
        project_id="test-proj",
        job_id="correct-sha-job",
        canonical_worktree_path=str(wt_path.resolve()),
        branch_name="main",
        creation_state=WorktreeCreationState.PENDING,
    )

    with patch.object(wt_manager, "_git") as mock_git:
        async def mock_git_impl(args, **kwargs):
            if "worktree" in args and "list" in args:
                return f"worktree {wt_path.resolve()}\n"
            if "branch" in args:
                return "main"
            if "rev-parse" in args:
                return "matching_sha_789"
            return ""

        mock_git.side_effect = mock_git_impl

        # Should complete without raising any exception
        asyncio.run(
            wt_manager._verify_creation_postconditions(
                wt_path, ownership, expected_branch="main", expected_base_sha="matching_sha_789"
            )
        )


def test_darwin_sandbox_profile_deny_by_default(tmp_dirs):
    wt_path = os.path.realpath(tmp_dirs["worktrees"])
    rt_path = os.path.realpath(tmp_dirs["runtime"])
    confinement = AgentProcessConfinement(
        allowed_worktree_path=wt_path,
        runtime_root=rt_path,
    )
    profile = confinement._generate_darwin_sandbox_profile()
    assert "(deny file-write*)" in profile
    assert f'(allow file-write* (subpath "{wt_path}"))' in profile
    assert f'(deny file-write* (subpath "{rt_path}"))' in profile
    assert '(allow file-write* (subpath "/tmp"))' not in profile
    assert '(allow file-write* (subpath "/private/tmp"))' not in profile


def test_darwin_sandbox_executable_write_confinement(tmp_dirs):
    if platform.system().lower() != "darwin" or not shutil.which("sandbox-exec"):
        pytest.skip("sandbox-exec unavailable on platform")

    wt_path = os.path.realpath(tmp_dirs["worktrees"])
    rt_path = os.path.realpath(tmp_dirs["runtime"])
    confinement = AgentProcessConfinement(
        allowed_worktree_path=wt_path,
        runtime_root=rt_path,
    )
    profile = confinement._generate_darwin_sandbox_profile()

    # 1. touch inside worktree => succeeds
    r_ok = subprocess.run(
        ["sandbox-exec", "-p", profile, "touch", os.path.join(wt_path, "ok.txt")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r_ok.returncode == 0, f"Worktree write failed: {r_ok.stderr}"

    # 2. touch /tmp/minime-stage-c-test => fails
    r_tmp = subprocess.run(
        ["sandbox-exec", "-p", profile, "touch", "/tmp/minime-stage-c-test"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r_tmp.returncode != 0

    # 3. touch <runtime_root>/forbidden => fails
    r_rt = subprocess.run(
        ["sandbox-exec", "-p", profile, "touch", os.path.join(rt_path, "forbidden")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r_rt.returncode != 0


def test_mutating_git_operations_require_guard_authorization(tmp_dirs):
    class MockBindingRepo:
        def get_by_project_id(self, pid):
            return ProjectManagedRepositoryBinding(
                project_id=pid,
                canonical_repository_identity="github.com/test/repo",
                remote_name="origin",
                managed_repository_root=tmp_dirs["repo_root"],
                worktree_parent_dir=tmp_dirs["worktrees"],
            )

    class MockOwnershipRepo:
        def get_by_canonical_path(self, path):
            return None
        def get_by_job_id(self, jid):
            return None

    class DeniedUOW:
        def __init__(self):
            self.project_managed_repository_bindings = MockBindingRepo()
            self.orchestration_worktree_ownerships = MockOwnershipRepo()
            self.git_operations = MagicMock()
        def commit(self): pass

    uow = DeniedUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    # 1. Missing project_id fails closed with ValueError
    with pytest.raises(ValueError, match="project_id is mandatory"):
        asyncio.run(wt_manager.create_recovery_snapshot("job-123", project_id=None))

    with pytest.raises(ValueError, match="project_id is mandatory"):
        asyncio.run(wt_manager.finalize_candidate_commit(tmp_dirs["worktrees"], "job-123", project_id=None))

    with pytest.raises(ValueError, match="project_id is mandatory"):
        asyncio.run(wt_manager.cherry_pick(tmp_dirs["worktrees"], ["sha1"], "job-123", project_id=None))

    # 2. Denied ownership / missing CREATED record fails closed with RuntimeError
    with pytest.raises(RuntimeError, match="no valid worktree ownership found"):
        asyncio.run(wt_manager.finalize_candidate_commit(tmp_dirs["worktrees"], "job-123", project_id="test-proj"))


def test_openspec_sync_service_without_uow_fails_closed(tmp_dirs):
    with pytest.raises(ValueError, match="PersistenceUnitOfWork \\(uow\\) is mandatory"):
        OpenSpecSyncService(project_root=tmp_dirs["repo_root"], uow=None)


def test_worktree_manager_uses_binding_worktree_parent_dir(tmp_dirs):
    custom_wt_dir = os.path.join(tmp_dirs["repo_root"], "custom-worktrees")
    os.makedirs(custom_wt_dir, exist_ok=True)

    class BindingRepo:
        def get_by_project_id(self, pid):
            if pid == "custom-proj":
                return ProjectManagedRepositoryBinding(
                    project_id=pid,
                    canonical_repository_identity="github.com/test/repo",
                    remote_name="origin",
                    managed_repository_root=tmp_dirs["repo_root"],
                    worktree_parent_dir=custom_wt_dir,
                )
            return None

    class MockUOWLocal:
        def __init__(self):
            self.project_managed_repository_bindings = BindingRepo()

    uow = MockUOWLocal()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    resolved_path = wt_manager.worktree_path("job-999", project_id="custom-proj")
    assert str(resolved_path.resolve()) == os.path.realpath(os.path.join(custom_wt_dir, "job-999"))

    remediation_path = wt_manager.remediation_worktree_path("job-999", 1, project_id="custom-proj")
    assert str(remediation_path.resolve()) == os.path.realpath(os.path.join(custom_wt_dir, "job-999-remediation-gen1"))


def test_persisted_ownership_exact_identity_fields(tmp_dirs):
    class MockBindingRepo:
        def get_by_project_id(self, pid):
            return ProjectManagedRepositoryBinding(
                project_id=pid,
                canonical_repository_identity="github.com/org/exact-repo",
                remote_name="origin",
                managed_repository_root=tmp_dirs["repo_root"],
                worktree_parent_dir=tmp_dirs["worktrees"],
            )

    class MockOwnershipRepo:
        def __init__(self):
            self.store = {}
        def save(self, obj):
            self.store[obj.worktree_id] = obj
        def get_by_id(self, wid):
            return self.store.get(wid)
        def get_by_canonical_path(self, path):
            for v in self.store.values():
                if v.canonical_worktree_path == path:
                    return v
            return None

    class MockUOWExact:
        def __init__(self):
            self.project_managed_repository_bindings = MockBindingRepo()
            self.orchestration_worktree_ownerships = MockOwnershipRepo()
        def commit(self): pass

    uow = MockUOWExact()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    wt_target = Path(tmp_dirs["worktrees"]) / "job-exact-1"

    ownership = wt_manager._persist_pending_ownership(
        job_id="job-exact-1",
        project_id="exact-proj",
        path=wt_target,
        branch="minime/feature-x",
        run_id="run-exact-100",
        change_name="my-change-spec",
        source_base_sha="abcdef1234567890",
    )

    assert ownership.branch == "minime/feature-x"
    assert ownership.branch_name == "minime/feature-x"
    assert ownership.run_id == "run-exact-100"
    assert ownership.change_name == "my-change-spec"
    assert ownership.source_repository_identity == "github.com/org/exact-repo"
    assert ownership.source_base_sha == "abcdef1234567890"
    assert ownership.creation_state == WorktreeCreationState.PENDING


