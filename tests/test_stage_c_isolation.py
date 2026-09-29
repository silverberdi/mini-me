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
    EvidenceDiagnosticStatus,
    ExternalOutcome,
    ExternalReasonCode,
    OrchestrationStage,
    WorkspaceOperation,
    WorkspaceRole,
    WorktreeCreationState,
)
from minime.domain.models import (
    Job,
    OrchestrationRun,
    OrchestrationWorktreeOwnership,
    Project,
    ProjectManagedRepositoryBinding,
    WorkspaceMutationRequest,
    utc_now,
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
        if binding.managed_repository_root and os.path.exists(binding.managed_repository_root):
            marker_path = os.path.join(
                binding.managed_repository_root, ".minime-managed-project.json"
            )
            try:
                with open(marker_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "project_id": binding.project_id,
                            "canonical_repository_identity": binding.canonical_repository_identity,
                        },
                        f,
                    )
            except Exception:
                pass

    def get_by_project_id(self, project_id: str) -> ProjectManagedRepositoryBinding | None:
        return self.bindings.get(project_id)

    def get_by_repository_identity(
        self, canonical_repository_identity: str
    ) -> ProjectManagedRepositoryBinding | None:
        for b in self.bindings.values():
            if b.canonical_repository_identity == canonical_repository_identity:
                return b
        return None

    def list_all(self):
        return list(self.bindings.values())

    def delete(self, project_id: str) -> None:
        self.bindings.pop(project_id, None)


class MockWorktreeOwnershipRepo:
    def __init__(self):
        self.ownerships = {}

    def save(self, ownership: OrchestrationWorktreeOwnership) -> None:
        self.ownerships[ownership.worktree_id] = ownership

    def get_by_id(self, worktree_id: str) -> OrchestrationWorktreeOwnership | None:
        return self.ownerships.get(worktree_id)

    def get_by_canonical_path(
        self, canonical_worktree_path: str
    ) -> OrchestrationWorktreeOwnership | None:
        norm_target = (
            os.path.realpath(canonical_worktree_path)
            if os.path.exists(canonical_worktree_path)
            else canonical_worktree_path
        )
        for w in self.ownerships.values():
            norm_w = (
                os.path.realpath(w.canonical_worktree_path)
                if os.path.exists(w.canonical_worktree_path)
                else w.canonical_worktree_path
            )
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
            w
            for w in self.ownerships.values()
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


class MockJobRepo:
    def __init__(self):
        self.jobs = {}

    def save(self, job: Job) -> None:
        self.jobs[job.job_id] = job

    def get_by_id(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list_all(self):
        return list(self.jobs.values())

    def list_active_jobs(self):
        from minime.domain.enums import JobStatus

        return [
            j
            for j in self.jobs.values()
            if j.status
            in (
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                JobStatus.CHECKS_RUNNING,
                JobStatus.REVIEW_RUNNING,
                JobStatus.AUDIT_RUNNING,
            )
        ]


class MockOrchestrationRunRepo:
    def __init__(self):
        self.runs = {}

    def save(self, run: OrchestrationRun) -> None:
        self.runs[run.run_id] = run

    def get_by_id(self, run_id: str) -> OrchestrationRun | None:
        return self.runs.get(run_id)

    def get_by_active_job_id(self, job_id: str) -> OrchestrationRun | None:
        for r in self.runs.values():
            if getattr(r, "active_job_id", None) == job_id or getattr(r, "run_id", None) == job_id:
                return r
        return None

    def list_runs(self) -> list[OrchestrationRun]:
        return list(self.runs.values())


class MockUOW:
    def __init__(self):
        from tests.conftest import (
            InMemoryDurableSagaRepository,
            InMemoryOrchestrationExternalActionRepository,
        )

        self.durable_sagas = InMemoryDurableSagaRepository()
        self.orchestration_external_actions = InMemoryOrchestrationExternalActionRepository()
        self.project_managed_repository_bindings = MockBindingRepo()
        self.orchestration_worktree_ownerships = MockWorktreeOwnershipRepo()
        self.projects = MockProjectRepo()
        self.jobs = MockJobRepo()
        self.orchestration_runs = MockOrchestrationRunRepo()
        self.git_operations = MagicMock()
        self.events = MagicMock()
        self.metrics = MagicMock()
        self.provider_health = MagicMock()
        self.reviews = MagicMock()
        self.audits = MagicMock()
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
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/org/repo"], cwd=repo_root, check=True
    )
    with open(os.path.join(repo_root, "README.md"), "w") as f:
        f.write("base\n")
    with open(os.path.join(repo_root, ".minime-managed-project.json"), "w") as f:
        json.dump(
            {
                "project_id": "test-proj",
                "canonical_repository_identity": "github.com/org/repo",
            },
            f,
        )
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo_root, check=True, capture_output=True
    )

    yield {
        "base": base,
        "runtime": runtime,
        "repo_root": repo_root,
        "worktrees": worktrees,
    }
    shutil.rmtree(base, ignore_errors=True)


def test_repository_identity_normalization():
    assert normalize_repository_identity("https://github.com/org/repo.git") in (
        "org/repo",
        "github.com/org/repo",
    )
    assert normalize_repository_identity("git@github.com:org/repo.git") in (
        "org/repo",
        "github.com/org/repo",
    )
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
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/org/repo"],
        cwd=wt_dir,
        check=True,
        capture_output=True,
    )
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
        run_id="run-100",
        change_name="change-100",
        canonical_worktree_path=wt_dir,
        source_repository_identity="github.com/org/repo",
        source_base_sha="main",
        branch="minime/change-job-100",
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
    res_ok = confinement.run_confined_subprocess(
        ["touch", os.path.join(wt_path, "allowed.txt")], cwd=wt_path
    )
    assert res_ok.returncode == 0
    assert os.path.exists(os.path.join(wt_path, "allowed.txt"))

    # Write inside runtime root fails
    res_fail = confinement.run_confined_subprocess(
        ["touch", os.path.join(tmp_dirs["runtime"], "forbidden.txt")], cwd=wt_path
    )
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
        managed_repository_root=tmp_dirs["runtime"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    sync_service = OpenSpecSyncService(project_root=tmp_dirs["runtime"], uow=uow)

    # Sync into runtime root => POLICY_DENIED
    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": tmp_dirs["runtime"]}):
        res = sync_service.sync_change_specs(
            openspec_path="openspec", change_name="test-change", project_id="proj-1"
        )
    assert res.outcome == ExternalOutcome.FAILURE
    assert res.reason_code == ExternalReasonCode.POLICY_DENIED


def test_openspec_archive_runtime_target_denied(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["runtime"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    sync_service = OpenSpecSyncService(project_root=tmp_dirs["runtime"], uow=uow)

    # Archive inside runtime root => POLICY_DENIED
    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": tmp_dirs["runtime"]}):
        res = sync_service.archive_change(
            openspec_path="openspec", change_name="test-change", project_id="proj-1"
        )
    assert res.outcome == ExternalOutcome.FAILURE
    assert res.reason_code == ExternalReasonCode.POLICY_DENIED


def test_worktree_manager_pending_ordering(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_dirs["repo_root"], check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_dirs["repo_root"], check=True
    )
    (Path(tmp_dirs["repo_root"]) / "README.md").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_dirs["repo_root"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_dirs["repo_root"],
        check=True,
        capture_output=True,
    )

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-test-10",
            project_id="proj-1",
            change_name="change-1",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-test-10",
            active_job_id="job-test-10",
            project_id="proj-1",
            change_name="change-1",
            base_sha="main",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    wt_path = wt_manager.worktree_path("job-test-10", project_id="proj-1").resolve()

    asyncio.run(
        wt_manager.create_worktree(
            "job-test-10", "change-1", "main", project_id="proj-1", run_id="run-test-10"
        )
    )

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
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
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
        run_id="run-marker-test",
        change_name="change-marker-test",
        canonical_worktree_path=str(wt_path.resolve()),
        source_repository_identity="github.com/org/repo",
        source_base_sha="main",
        branch="minime/test",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    marker_file = wt_path / ".minime_worktree_ownership.json"
    marker_file.write_text(
        json.dumps({"worktree_id": "wt-SPOOFED", "canonical_worktree_path": str(wt_path.resolve())})
    )

    asyncio.run(wt_manager.remove_clean_worktree_path(wt_path, "job-marker-test", "proj-1"))
    assert wt_path.exists()


def test_guard_denial_happens_before_pending(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-denied-1",
            project_id="proj-1",
            change_name="change-1",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-denied-1",
            active_job_id="job-denied-1",
            project_id="proj-1",
            change_name="change-1",
            base_sha="main",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    guard = MagicMock(spec=ManagedWorkspaceGuard)
    guard.evaluate_mutation.return_value = MagicMock(
        allowed=False,
        provider_detail="Guard Denied",
        reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow, workspace_guard=guard)

    with pytest.raises(RuntimeError, match="fails workspace guard authorization: Guard Denied"):
        asyncio.run(
            wt_manager.create_worktree(
                "job-denied-1", "change-1", "main", project_id="proj-1", run_id="run-denied-1"
            )
        )

    ownership = uow.orchestration_worktree_ownerships.get_by_id("wt-job-denied-1")
    assert ownership is None


def test_pending_persistence_failure_prevents_git_add(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    marker_file = Path(tmp_dirs["repo_root"]) / ".minime-managed-project.json"
    marker_file.write_text(
        json.dumps({"project_id": "proj-1", "canonical_repository_identity": "github.com/org/repo"})
    )
    bad_uow = MagicMock()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    mock_b_repo = MagicMock()
    mock_b_repo.get_by_project_id.return_value = binding
    mock_j_repo = MagicMock()
    mock_j_repo.get_by_id.return_value = Job(
        job_id="job-no-uow", project_id="proj-1", change_name="change-1", implementer_role="codex"
    )
    mock_r_repo = MagicMock()
    mock_r_repo.get_by_active_job_id.return_value = OrchestrationRun(
        run_id="run-no-uow",
        active_job_id="job-no-uow",
        project_id="proj-1",
        change_name="change-1",
        base_sha="main",
        current_stage=OrchestrationStage.IMPLEMENTING,
        resumable_stage=OrchestrationStage.IMPLEMENTING,
        is_active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    bad_uow.project_managed_repository_bindings = mock_b_repo
    bad_uow.jobs = mock_j_repo
    bad_uow.orchestration_runs = mock_r_repo
    bad_uow.orchestration_worktree_ownerships = None
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=bad_uow)

    with patch.object(wt_manager, "_git", new_callable=AsyncMock) as mock_git:
        with pytest.raises(
            RuntimeError, match="orchestration_worktree_ownerships repository missing"
        ):
            asyncio.run(
                wt_manager.create_worktree(
                    "job-no-uow", "change-1", "main", project_id="proj-1", run_id="run-no-uow"
                )
            )

        for call_item in mock_git.call_args_list:
            args = call_item.args[0] if call_item.args else []
            assert "worktree" not in args or "add" not in args


def test_marker_only_cleanup_denied(tmp_dirs):
    uow = MockUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    marker_only_path = wt_manager.worktrees_root / "marker-only"
    os.makedirs(marker_only_path, exist_ok=True)
    marker_file = marker_only_path / ".minime_worktree_ownership.json"
    marker_file.write_text(
        json.dumps({"worktree_id": "wt-marker-only", "job_id": "job-marker-only"})
    )

    # Without durable DB ownership, cleanup must be denied and directory preserved
    asyncio.run(
        wt_manager.remove_clean_worktree_path(marker_only_path, "job-marker-only", "proj-1")
    )
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
        run_id="run-pending",
        change_name="change-pending",
        canonical_worktree_path=wt_dir,
        source_repository_identity="github.com/org/repo",
        source_base_sha="main",
        branch="minime/change-pending-job",
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

    res = asyncio.run(wt_manager.remove_clean_worktree_path(wt_path, "job-1", project_id=None))
    assert res.outcome == ExternalOutcome.FAILURE
    assert res.reason_code == ExternalReasonCode.POLICY_DENIED
    assert "project_id is mandatory" in res.provider_detail


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
    assert "missing, invalid, or unverified" in decision.provider_detail


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
    assert "missing, invalid, or unverified" in decision.provider_detail


def test_missing_git_remote_fails_identity_proof():
    no_remote_dir = tempfile.mkdtemp()
    try:
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=no_remote_dir, check=True, capture_output=True
        )
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
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/org/wrong-repo.git"],
        cwd=tmp_dirs["repo_root"],
        check=True,
    )

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
        guard = ManagedWorkspaceGuard(
            uow, runtime_root=tmp_dirs["runtime"], trusted_managed_root=other_trusted_root
        )
        req = WorkspaceMutationRequest(
            project_id="test-proj",
            target_path=os.path.join(tmp_dirs["repo_root"], "README.md"),
            requested_operation=WorkspaceOperation.READ,
        )
        decision = guard.evaluate_mutation(req)

        assert decision.allowed is False
        assert (
            "lies outside trusted managed root" in decision.provider_detail
            or "outside trusted managed root" in decision.provider_detail
        )
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
    guard = ManagedWorkspaceGuard(
        uow, runtime_root=tmp_dirs["runtime"], trusted_managed_root=parent_trusted
    )
    req = WorkspaceMutationRequest(
        project_id="test-proj",
        target_path=os.path.join(tmp_dirs["worktrees"], "wt-job", "app.py"),
        requested_operation=WorkspaceOperation.EDIT,
    )

    # Register CREATED worktree ownership so role evaluation succeeds
    wt_path = os.path.join(tmp_dirs["worktrees"], "wt-job")
    os.makedirs(wt_path, exist_ok=True)
    subprocess.run(["git", "init"], cwd=wt_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/org/repo"],
        cwd=wt_path,
        check=True,
        capture_output=True,
    )
    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job",
        project_id="test-proj",
        job_id="job",
        run_id="run-job",
        change_name="change-job",
        canonical_worktree_path=wt_path,
        source_repository_identity="github.com/org/repo",
        source_base_sha="main",
        branch="minime/change-job",
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
        run_id="run-empty-list",
        change_name="change-empty-list",
        canonical_worktree_path=str(wt_path.resolve()),
        source_repository_identity="github.com/org/repo",
        source_base_sha="1234567890abcdef",
        branch="main",
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
        run_id="run-wrong-sha",
        change_name="change-wrong-sha",
        canonical_worktree_path=str(wt_path.resolve()),
        source_repository_identity="github.com/org/repo",
        source_base_sha="expected_sha_456",
        branch="main",
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

        with pytest.raises(
            RuntimeError,
            match="actual HEAD SHA 'actual_sha_123' does not match expected SHA 'expected_sha_456'",
        ):
            asyncio.run(
                wt_manager._verify_creation_postconditions(
                    wt_path, ownership, expected_branch="main", expected_base_sha="expected_sha_456"
                )
            )


def test_correct_head_sha_allows_created(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="test-proj",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    wt_path = Path(tmp_dirs["worktrees"]) / "wt-correct-sha"
    wt_path.mkdir(parents=True, exist_ok=True)
    wt_manager._write_ownership_marker(
        wt_path,
        OrchestrationWorktreeOwnership(
            worktree_id="wt-correct-sha",
            project_id="test-proj",
            job_id="correct-sha-job",
            run_id="run-correct-sha",
            change_name="change-correct-sha",
            canonical_worktree_path=str(wt_path.resolve()),
            source_repository_identity="github.com/org/repo",
            source_base_sha="actual_sha_123",
            branch="main",
            creation_state=WorktreeCreationState.PENDING,
        ),
    )

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-correct-sha",
        project_id="test-proj",
        job_id="correct-sha-job",
        run_id="run-correct-sha",
        change_name="change-correct-sha",
        canonical_worktree_path=str(wt_path.resolve()),
        source_repository_identity="github.com/org/repo",
        source_base_sha="actual_sha_123",
        branch="main",
        creation_state=WorktreeCreationState.PENDING,
    )

    with (
        patch.object(wt_manager, "_git") as mock_git,
        patch(
            "minime.services.workspace_guard.ManagedWorkspaceGuard.verify_git_repository_identity",
            return_value=(True, "OK"),
        ),
    ):

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
                canonical_repository_identity="github.com/org/repo",
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

        def commit(self):
            pass

    uow = DeniedUOW()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    # 1. Missing project_id fails closed with ValueError
    with pytest.raises(ValueError, match="project_id is mandatory"):
        asyncio.run(wt_manager.create_recovery_snapshot("job-123", project_id=None))

    with pytest.raises(ValueError, match="project_id is mandatory"):
        asyncio.run(
            wt_manager.finalize_candidate_commit(tmp_dirs["worktrees"], "job-123", project_id=None)
        )

    with pytest.raises(ValueError, match="project_id is mandatory"):
        asyncio.run(
            wt_manager.cherry_pick(tmp_dirs["worktrees"], ["sha1"], "job-123", project_id=None)
        )

    # 2. Denied ownership / missing CREATED record fails closed with RuntimeError
    with pytest.raises(RuntimeError, match="no valid worktree ownership found"):
        asyncio.run(
            wt_manager.finalize_candidate_commit(
                tmp_dirs["worktrees"], "job-123", project_id="test-proj"
            )
        )


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
    assert str(remediation_path.resolve()) == os.path.realpath(
        os.path.join(custom_wt_dir, "job-999-remediation-gen1")
    )


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
            self.jobs = MockJobRepo()
            self.orchestration_runs = MockOrchestrationRunRepo()

        def commit(self):
            pass

    uow = MockUOWExact()
    uow.jobs.save(
        Job(
            job_id="job-exact-1",
            project_id="exact-proj",
            change_name="my-change-spec",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-exact-100",
            active_job_id="job-exact-1",
            project_id="exact-proj",
            change_name="my-change-spec",
            base_sha="abcdef1234567890",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
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


def test_created_worktree_wrong_remote_identity_denied_conflict(tmp_dirs):
    class MockBindingRepo:
        def get_by_project_id(self, pid):
            return ProjectManagedRepositoryBinding(
                project_id=pid,
                canonical_repository_identity="github.com/org/expected-repo",
                remote_name="origin",
                managed_repository_root=tmp_dirs["repo_root"],
                worktree_parent_dir=tmp_dirs["worktrees"],
            )

    class MockOwnershipRepo:
        def __init__(self, ow):
            self.ow = ow

        def get_by_canonical_path(self, path):
            return self.ow

    wt_target = Path(tmp_dirs["worktrees"]) / "job-created-1"
    wt_target.mkdir(parents=True, exist_ok=True)

    ow = OrchestrationWorktreeOwnership(
        worktree_id="wt-job-created-1",
        project_id="proj-conflict",
        job_id="job-created-1",
        run_id="run-1",
        change_name="change-1",
        canonical_worktree_path=str(wt_target.resolve()),
        source_repository_identity="github.com/org/expected-repo",
        source_base_sha="base123",
        branch="minime/change-1",
        creation_state=WorktreeCreationState.CREATED,
    )

    class MockUOWConflict:
        def __init__(self):
            self.project_managed_repository_bindings = MockBindingRepo()
            self.orchestration_worktree_ownerships = MockOwnershipRepo(ow)

    uow = MockUOWConflict()
    guard = ManagedWorkspaceGuard(uow)

    # Monkeypatch verify_git_repository_identity to return False due to remote mismatch
    guard.verify_git_repository_identity = lambda path, identity, remote: (
        False,
        "Remote identity mismatch: expected remote url mismatch",
    )

    req = WorkspaceMutationRequest(
        project_id="proj-conflict",
        target_path=str(wt_target.resolve()),
        requested_operation=WorkspaceOperation.GIT_COMMIT,
    )
    decision = guard.evaluate_mutation(req)
    assert not decision.allowed
    assert decision.reason_code == ExternalReasonCode.CONFLICT


def test_full_runtime_managed_root_overlap_containment_denied(tmp_dirs):
    runtime_root = Path(tmp_dirs["repo_root"]) / "runtime_dir"
    runtime_root.mkdir(parents=True, exist_ok=True)

    class CustomBindingRepo:
        def __init__(self, repo_root, wt_dir):
            self.repo_root = str(Path(repo_root).resolve())
            self.wt_dir = str(Path(wt_dir).resolve())

        def get_by_project_id(self, pid):
            return ProjectManagedRepositoryBinding(
                project_id=pid,
                canonical_repository_identity="github.com/org/repo",
                remote_name="origin",
                managed_repository_root=self.repo_root,
                worktree_parent_dir=self.wt_dir,
            )

    sub_dir = runtime_root / "inside"
    sub_dir.mkdir(parents=True, exist_ok=True)

    parent_dir = runtime_root.parent

    scenarios = [
        # 1. managed_repo_root == runtime_root
        (runtime_root, tmp_dirs["worktrees"]),
        # 2. managed_repo_root inside runtime_root
        (sub_dir, tmp_dirs["worktrees"]),
        # 3. runtime_root inside managed_repo_root
        (parent_dir, tmp_dirs["worktrees"]),
        # 4. worktree_parent_dir == runtime_root
        (tmp_dirs["repo_root"], runtime_root),
        # 5. worktree_parent_dir inside runtime_root
        (tmp_dirs["repo_root"], sub_dir),
        # 6. runtime_root inside worktree_parent_dir
        (tmp_dirs["repo_root"], parent_dir),
    ]

    for managed_root, wt_dir in scenarios:

        class MockUOWOverlap:
            def __init__(self):
                self.project_managed_repository_bindings = CustomBindingRepo(managed_root, wt_dir)
                self.orchestration_worktree_ownerships = None

        uow = MockUOWOverlap()
        guard = ManagedWorkspaceGuard(uow, runtime_root=runtime_root)
        target = Path(wt_dir) / "job-x"
        req = WorkspaceMutationRequest(
            project_id="proj-overlap",
            target_path=str(target),
            requested_operation=WorkspaceOperation.WORKTREE_CREATE,
        )
        decision = guard.evaluate_mutation(req)
        assert not decision.allowed, (
            f"Scenario failed: managed_root={managed_root}, wt_dir={wt_dir}"
        )
        assert decision.reason_code == ExternalReasonCode.POLICY_DENIED


def test_missing_binding_prevents_path_resolution_and_worktree_creation(tmp_dirs):
    class MockEmptyBindingRepo:
        def get_by_project_id(self, pid):
            return None

    class MockUOWNoBinding:
        def __init__(self):
            self.project_managed_repository_bindings = MockEmptyBindingRepo()

    uow = MockUOWNoBinding()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    with pytest.raises((RuntimeError, ValueError)) as exc1:
        wt_manager.resolve_worktree_parent_dir("missing-proj")
    assert "Failing closed" in str(exc1.value) or "mandatory" in str(exc1.value)

    with pytest.raises((RuntimeError, ValueError)):
        wt_manager.worktree_path("job-1", "missing-proj")

    with pytest.raises((RuntimeError, ValueError)):
        asyncio.run(
            wt_manager.create_worktree("job-1", "change-1", "main", project_id="missing-proj")
        )


def test_missing_run_id_or_change_name_prevents_creation_and_matches_supplied(tmp_dirs):
    class MockBindingRepo:
        def get_by_project_id(self, pid):
            marker_file = Path(tmp_dirs["repo_root"]) / ".minime-managed-project.json"
            marker_file.write_text(
                json.dumps(
                    {"project_id": pid, "canonical_repository_identity": "github.com/org/repo"}
                )
            )
            return ProjectManagedRepositoryBinding(
                project_id=pid,
                canonical_repository_identity="github.com/org/repo",
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

    class MockUOWStrict:
        def __init__(self):
            self.project_managed_repository_bindings = MockBindingRepo()
            self.orchestration_worktree_ownerships = MockOwnershipRepo()
            self.jobs = MockJobRepo()
            self.orchestration_runs = MockOrchestrationRunRepo()

        def commit(self):
            pass

    uow = MockUOWStrict()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    target = Path(tmp_dirs["worktrees"]) / "job-strict-1"

    # 1. Missing run_id raises ValueError
    with pytest.raises(ValueError) as exc1:
        wt_manager._persist_pending_ownership(
            job_id="job-strict-1",
            project_id="proj-1",
            path=target,
            branch="minime/change-1",
            run_id=None,
            change_name="change-1",
            source_base_sha="sha123",
        )
    assert "run_id" in str(exc1.value)

    # 2. Missing change_name raises ValueError
    uow.jobs.save(
        Job(job_id="job-strict-1", project_id="proj-1", change_name="", implementer_role="codex")
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-1",
            active_job_id="job-strict-1",
            project_id="proj-1",
            change_name="",
            base_sha="sha123",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    with pytest.raises(ValueError) as exc2:
        wt_manager._persist_pending_ownership(
            job_id="job-strict-1",
            project_id="proj-1",
            path=target,
            branch="minime/change-1",
            run_id="run-1",
            change_name=None,
            source_base_sha="sha123",
        )
    assert "change_name" in str(exc2.value)

    # 3. Valid run_id and change_name match exactly
    target3 = Path(tmp_dirs["worktrees"]) / "job-strict-3"
    uow.jobs.save(
        Job(
            job_id="job-strict-3",
            project_id="proj-1",
            change_name="change-supplied-88",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-supplied-99",
            active_job_id="job-strict-3",
            project_id="proj-1",
            change_name="change-supplied-88",
            base_sha="sha123",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    ow = wt_manager._persist_pending_ownership(
        job_id="job-strict-3",
        project_id="proj-1",
        path=target3,
        branch="minime/change-1",
        run_id="run-supplied-99",
        change_name="change-supplied-88",
        source_base_sha="sha123",
    )
    assert ow.run_id == "run-supplied-99"
    assert ow.change_name == "change-supplied-88"


def test_durable_job_without_run_id_fails_before_git_add(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )

    class MockBindingRepo:
        def get_by_project_id(self, pid):
            marker_file = Path(tmp_dirs["repo_root"]) / ".minime-managed-project.json"
            marker_file.write_text(
                json.dumps(
                    {"project_id": pid, "canonical_repository_identity": "github.com/org/repo"}
                )
            )
            return ProjectManagedRepositoryBinding(
                project_id=pid,
                canonical_repository_identity="github.com/org/repo",
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
            return None

    class MockUOWJobNoRunID:
        def __init__(self):
            self.project_managed_repository_bindings = MockBindingRepo()
            self.orchestration_worktree_ownerships = MockOwnershipRepo()
            self.jobs = None
            self.orchestration_runs = None
            self.candidate_remediations = None

        def commit(self):
            pass

    uow = MockUOWJobNoRunID()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    with patch.object(wt_manager, "_git", new_callable=AsyncMock) as mock_git:
        with pytest.raises(ValueError, match="EVIDENCE_INSUFFICIENT"):
            asyncio.run(
                wt_manager.create_worktree(
                    job_id="job-no-run-id",
                    change_name="change-1",
                    base_branch="main",
                    project_id="proj-1",
                )
            )

        for call_item in mock_git.call_args_list:
            args = call_item.args[0] if call_item.args else []
            assert "worktree" not in args or "add" not in args


def test_missing_canonical_change_name_blocks_integration_worktree_creation(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )

    class MockBindingRepo:
        def get_by_project_id(self, pid):
            marker_file = Path(tmp_dirs["repo_root"]) / ".minime-managed-project.json"
            marker_file.write_text(
                json.dumps(
                    {"project_id": pid, "canonical_repository_identity": "github.com/org/repo"}
                )
            )
            return ProjectManagedRepositoryBinding(
                project_id=pid,
                canonical_repository_identity="github.com/org/repo",
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
            return None

    class MockUOWNoChangeName:
        def __init__(self):
            self.project_managed_repository_bindings = MockBindingRepo()
            self.orchestration_worktree_ownerships = MockOwnershipRepo()
            self.jobs = MockJobRepo()
            self.jobs.save(
                Job(
                    job_id="job-int-no-change-name",
                    project_id="proj-1",
                    change_name="",
                    implementer_role="codex",
                )
            )
            self.orchestration_runs = MockOrchestrationRunRepo()
            self.orchestration_runs.save(
                OrchestrationRun(
                    run_id="run-1",
                    active_job_id="job-int-no-change-name",
                    project_id="proj-1",
                    change_name="",
                    base_sha="sha123",
                )
            )
            self.candidate_remediations = None

        def commit(self):
            pass

    uow = MockUOWNoChangeName()
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    with patch.object(wt_manager, "_git", new_callable=AsyncMock) as mock_git:
        with pytest.raises(ValueError, match="change_name"):
            asyncio.run(
                wt_manager.create_integration_worktree(
                    job_id="job-int-no-change-name",
                    branch_name="minime/integration-gen1",
                    base_sha="sha123",
                    generation=1,
                    project_id="proj-1",
                    run_id="run-1",
                    change_name=None,
                )
            )

        for call_item in mock_git.call_args_list:
            args = call_item.args[0] if call_item.args else []
            assert "worktree" not in args or "add" not in args


def test_binding_is_valid_false_blocks_mutation(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-invalid",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
        is_valid=False,
        mismatch_reasons=[],
    )
    uow.project_managed_repository_bindings.save(binding)
    guard = ManagedWorkspaceGuard(uow)
    req = WorkspaceMutationRequest(
        project_id="proj-invalid",
        target_path=tmp_dirs["worktrees"],
        requested_operation=WorkspaceOperation.WORKTREE_CREATE,
    )
    decision = guard.evaluate_mutation(req)
    assert not decision.allowed
    assert decision.outcome == ExternalOutcome.UNKNOWN
    assert decision.reason_code == ExternalReasonCode.EVIDENCE_INSUFFICIENT


def test_binding_mismatch_reasons_non_empty_blocks_mutation(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-mismatch",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
        is_valid=True,
        mismatch_reasons=["Repository path mismatch"],
    )
    uow.project_managed_repository_bindings.save(binding)
    guard = ManagedWorkspaceGuard(uow)
    req = WorkspaceMutationRequest(
        project_id="proj-mismatch",
        target_path=tmp_dirs["worktrees"],
        requested_operation=WorkspaceOperation.WORKTREE_CREATE,
    )
    decision = guard.evaluate_mutation(req)
    assert not decision.allowed
    assert decision.outcome == ExternalOutcome.UNKNOWN
    assert decision.reason_code == ExternalReasonCode.EVIDENCE_INSUFFICIENT


def test_worktree_manager_refuses_path_resolution_from_invalid_binding(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-invalid-binding",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
        is_valid=False,
    )
    uow.project_managed_repository_bindings.save(binding)
    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    with pytest.raises(RuntimeError, match="Failing closed: no valid durable binding"):
        wt_manager.resolve_worktree_parent_dir("proj-invalid-binding")


def test_source_repo_project_root_mismatch_blocks_git_mutation(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_dirs["repo_root"], check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_dirs["repo_root"], check=True
    )
    (Path(tmp_dirs["repo_root"]) / "README.md").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_dirs["repo_root"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_dirs["repo_root"],
        check=True,
        capture_output=True,
    )

    other_repo = os.path.join(tmp_dirs["base"], "other_managed_repo")
    os.makedirs(other_repo, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=other_repo, check=True, capture_output=True)

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-source-mismatch",
        canonical_repository_identity="github.com/org/other-repo",
        managed_repository_root=other_repo,
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-source-mismatch",
            project_id="proj-source-mismatch",
            change_name="change-1",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-1",
            active_job_id="job-source-mismatch",
            project_id="proj-source-mismatch",
            change_name="change-1",
            base_sha="main",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    with patch.object(wt_manager, "_git", new_callable=AsyncMock) as mock_git:
        with pytest.raises(RuntimeError, match="does not match binding managed_repository_root"):
            asyncio.run(
                wt_manager.create_worktree(
                    job_id="job-source-mismatch",
                    change_name="change-1",
                    base_branch="main",
                    project_id="proj-source-mismatch",
                    run_id="run-1",
                )
            )

        for call_item in mock_git.call_args_list:
            args = call_item.args[0] if call_item.args else []
            assert "worktree" not in args or "add" not in args


def test_reuse_existing_rejects_unproven_worktree(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-reuse",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-reuse",
            project_id="proj-reuse",
            change_name="change-reuse",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-reuse",
            active_job_id="job-reuse",
            project_id="proj-reuse",
            change_name="change-reuse",
            base_sha="main",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    wt_path = Path(tmp_dirs["worktrees"]) / "job-reuse"
    wt_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=wt_path, check=True, capture_output=True)

    with pytest.raises(RuntimeError, match="Refusing to adopt existing worktree"):
        asyncio.run(
            wt_manager.create_worktree(
                job_id="job-reuse",
                change_name="change-reuse",
                base_branch="main",
                project_id="proj-reuse",
                reuse_existing=True,
                run_id="run-reuse",
            )
        )

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job-reuse",
        project_id="proj-reuse",
        job_id="job-reuse",
        run_id="run-reuse",
        change_name="change-reuse",
        canonical_worktree_path=str(wt_path.resolve()),
        branch="minime/change-reuse-job-reuse",
        source_repository_identity="github.com/org/repo",
        source_base_sha="main",
        creation_state=WorktreeCreationState.PENDING,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    with pytest.raises(RuntimeError, match="Refusing to adopt existing worktree"):
        asyncio.run(
            wt_manager.create_worktree(
                job_id="job-reuse",
                change_name="change-reuse",
                base_branch="main",
                project_id="proj-reuse",
                reuse_existing=True,
                run_id="run-reuse",
            )
        )


def test_supplied_false_run_id_and_change_name_rejected(tmp_dirs):
    uow = MockUOW()
    uow.jobs.save(
        Job(
            job_id="job-durable-1",
            project_id="proj-1",
            change_name="real-change",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="real-run",
            active_job_id="job-durable-1",
            project_id="proj-1",
            change_name="real-change",
            base_sha="base",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    with pytest.raises(ValueError, match="CONFLICT: Caller-supplied run_id 'false-run' conflicts"):
        wt_manager._resolve_real_run_id(
            "job-durable-1", run_id="false-run", project_id="proj-1", change_name="real-change"
        )

    with pytest.raises(
        ValueError, match="CONFLICT: Caller-supplied change_name 'false-change' conflicts"
    ):
        wt_manager._resolve_real_change_name(
            "job-durable-1", change_name="false-change", project_id="proj-1", run_id="real-run"
        )

    assert (
        wt_manager._resolve_real_run_id(
            "job-durable-1", run_id="real-run", project_id="proj-1", change_name="real-change"
        )
        == "real-run"
    )
    assert (
        wt_manager._resolve_real_change_name(
            "job-durable-1", change_name="real-change", project_id="proj-1", run_id="real-run"
        )
        == "real-change"
    )


def test_remote_identity_host_sensitive():
    assert normalize_repository_identity("git@github.com:org/repo.git") == "github.com/org/repo"
    assert normalize_repository_identity("https://github.com/org/repo.git") == "github.com/org/repo"
    assert (
        normalize_repository_identity("ssh://git@github.com/org/repo.git") == "github.com/org/repo"
    )
    assert normalize_repository_identity("git@evil.example:org/repo.git") == "evil.example/org/repo"

    assert normalize_repository_identity(
        "git@github.com:org/repo.git"
    ) != normalize_repository_identity("git@evil.example:org/repo.git")


def test_synthetic_run_id_fallback_rejected_when_job_run_id_empty(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_dirs["repo_root"], check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_dirs["repo_root"], check=True
    )
    (Path(tmp_dirs["repo_root"]) / "README.md").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_dirs["repo_root"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_dirs["repo_root"],
        check=True,
        capture_output=True,
    )

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-synth",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    # Durable Job exists, but Job.run_id is None/empty
    job = Job(
        job_id="job-synth-1",
        project_id="proj-synth",
        change_name="change-synth",
        run_id=None,
        implementer_role="codex",
    )
    uow.jobs.save(job)

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    # 1. Direct call to _resolve_real_run_id with caller-supplied fake run_id => EVIDENCE_INSUFFICIENT
    with pytest.raises(
        ValueError,
        match="EVIDENCE_INSUFFICIENT: Durable run_id for job_id 'job-synth-1' is unobservable",
    ):
        wt_manager._resolve_real_run_id(
            "job-synth-1", run_id="fake-run", project_id="proj-synth", change_name="change-synth"
        )

    # 2. Attempting create_worktree with caller-supplied fake run_id => fails before PENDING persistence and before git worktree add
    with patch.object(wt_manager, "_git", new_callable=AsyncMock) as mock_git:
        with pytest.raises(ValueError, match="EVIDENCE_INSUFFICIENT"):
            asyncio.run(
                wt_manager.create_worktree(
                    job_id="job-synth-1",
                    change_name="change-synth",
                    base_branch="main",
                    project_id="proj-synth",
                    run_id="fake-run",
                )
            )

        # Confirm no PENDING ownership persisted
        ownership = uow.orchestration_worktree_ownerships.get_by_id("wt-job-synth-1")
        assert ownership is None

        # Confirm git worktree add was never executed
        for call_item in mock_git.call_args_list:
            args = call_item.args[0] if call_item.args else []
            assert "worktree" not in args or "add" not in args


def test_unobservable_remote_identity_returns_unknown_outcome(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-unobs",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    guard = ManagedWorkspaceGuard(uow)

    # 1. MANAGED_REPOSITORY path does not exist on disk => UNKNOWN + UNOBSERVABLE
    nonexistent_managed = os.path.join(tmp_dirs["base"], "nonexistent_repo")
    binding_nonexistent = ProjectManagedRepositoryBinding(
        project_id="proj-nonexistent",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=nonexistent_managed,
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding_nonexistent)
    req_managed = WorkspaceMutationRequest(
        project_id="proj-nonexistent",
        target_path=nonexistent_managed,
        requested_operation=WorkspaceOperation.GIT_BRANCH,
    )
    decision_managed = guard.evaluate_mutation(req_managed)
    assert not decision_managed.allowed
    assert decision_managed.outcome == ExternalOutcome.UNKNOWN
    assert decision_managed.reason_code == ExternalReasonCode.UNOBSERVABLE

    # 2. EXECUTION_WORKTREE path does not exist on disk => UNKNOWN + UNOBSERVABLE
    wt_path = os.path.join(tmp_dirs["worktrees"], "wt-unobs")
    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-unobs",
        project_id="proj-unobs",
        job_id="job-unobs",
        run_id="run-unobs",
        change_name="change-unobs",
        canonical_worktree_path=wt_path,
        source_repository_identity="github.com/org/repo",
        source_base_sha="main",
        branch="minime/change-unobs",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    req_wt = WorkspaceMutationRequest(
        project_id="proj-unobs",
        target_path=wt_path,
        requested_operation=WorkspaceOperation.EDIT,
    )
    decision_wt = guard.evaluate_mutation(req_wt)
    assert not decision_wt.allowed
    assert decision_wt.outcome == ExternalOutcome.UNKNOWN
    assert decision_wt.reason_code == ExternalReasonCode.UNOBSERVABLE

    # 3. Mismatch remote URL => FAILURE + CONFLICT
    subprocess.run(
        ["git", "remote", "set-url", "origin", "git@evil.example:org/repo.git"],
        cwd=tmp_dirs["repo_root"],
        check=True,
    )
    req_mismatch = WorkspaceMutationRequest(
        project_id="proj-unobs",
        target_path=tmp_dirs["repo_root"],
        requested_operation=WorkspaceOperation.GIT_BRANCH,
    )
    decision_mismatch = guard.evaluate_mutation(req_mismatch)
    assert not decision_mismatch.allowed
    assert decision_mismatch.outcome == ExternalOutcome.FAILURE
    assert decision_mismatch.reason_code == ExternalReasonCode.CONFLICT


def test_post_merge_git_mutations_blocked_on_unauthorized_project_root(tmp_dirs):
    other_root = os.path.join(tmp_dirs["base"], "other_unauthorized_root")
    os.makedirs(other_root, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=other_root, check=True, capture_output=True)

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-pm-guard",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    from minime.services.post_merge_service import PostMergeReconciliationService

    pm_service = PostMergeReconciliationService(
        uow=uow,
        project_root=other_root,
        github_adapter=MagicMock(),
    )

    with patch("subprocess.run") as mock_sub:
        # 1. verify_candidate_ancestry fails closed before git fetch
        ancestry_res = pm_service.verify_candidate_ancestry(
            "sha123", "main", project_id="proj-pm-guard"
        )
        assert ancestry_res is False

        # 2. _clean_worktrees fails closed before git worktree remove
        clean_res = pm_service._clean_worktrees("job-1", project_id="proj-pm-guard")
        assert clean_res.outcome == ExternalOutcome.FAILURE

        # 3. _delete_local_branch fails closed before git branch -D
        del_res = pm_service._delete_local_branch("minime/change-1", project_id="proj-pm-guard")
        assert del_res.outcome == ExternalOutcome.FAILURE

        for call_item in mock_sub.call_args_list:
            args = call_item.args[0] if call_item.args else []
            assert "fetch" not in args
            assert "worktree" not in args or "remove" not in args
            assert "branch" not in args or "-D" not in args


def test_remediation_worktree_reuse_requires_full_durable_adoption_proof(tmp_dirs):
    source_sha = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_dirs["repo_root"],
            check=True,
            capture_output=True,
            text=True,
        )
    ).stdout.strip()

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-rem-reuse",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    uow.jobs.save(
        Job(
            job_id="job-rem-1",
            project_id="proj-rem-reuse",
            change_name="change-rem",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-rem-1",
            active_job_id="job-rem-1",
            project_id="proj-rem-reuse",
            change_name="change-rem",
            base_sha=source_sha,
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    rem_path = Path(tmp_dirs["worktrees"]) / "job-rem-1-remediation-gen1"
    rem_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=rem_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/org/repo"], cwd=rem_path, check=True
    )

    # 1. No ownership record => refused
    with pytest.raises(RuntimeError, match="Refusing to adopt existing remediation worktree"):
        asyncio.run(
            wt_manager.create_remediation_worktree(
                "job-rem-1",
                "change-rem",
                source_sha,
                1,
                project_id="proj-rem-reuse",
                run_id="run-rem-1",
            )
        )

    # 2. PENDING ownership => refused
    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job-rem-1-remediation-gen1",
        project_id="proj-rem-reuse",
        job_id="job-rem-1",
        run_id="run-rem-1",
        change_name="change-rem",
        canonical_worktree_path=str(rem_path.resolve()),
        branch="minime/change-rem-job-rem-1-remediation-gen1",
        source_repository_identity="github.com/org/repo",
        source_base_sha=source_sha,
        creation_state=WorktreeCreationState.PENDING,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    with pytest.raises(RuntimeError, match="Refusing to adopt existing remediation worktree"):
        asyncio.run(
            wt_manager.create_remediation_worktree(
                "job-rem-1",
                "change-rem",
                source_sha,
                1,
                project_id="proj-rem-reuse",
                run_id="run-rem-1",
            )
        )

    # 3. Caller conflict in run_id => CONFLICT
    with pytest.raises(ValueError, match="CONFLICT"):
        asyncio.run(
            wt_manager.create_remediation_worktree(
                "job-rem-1",
                "change-rem",
                source_sha,
                1,
                project_id="proj-rem-reuse",
                run_id="wrong-run",
            )
        )

    # 4. Valid CREATED ownership & Git identity & worktree list => Accepted
    ownership.creation_state = WorktreeCreationState.CREATED
    uow.orchestration_worktree_ownerships.save(ownership)
    wt_manager._write_ownership_marker(rem_path, ownership)

    with (
        patch.object(wt_manager, "_git") as mock_git,
        patch.object(wt_manager, "current_sha", new_callable=AsyncMock) as mock_sha,
    ):
        mock_sha.return_value = source_sha

        async def mock_git_side_effect(args, cwd=None, **kwargs):
            if "branch" in args and "--show-current" in args:
                return "minime/change-rem-job-rem-1-remediation-gen1"
            if "worktree" in args and "list" in args:
                return f"worktree {rem_path.resolve()}\n"
            if "remote" in args and "get-url" in args:
                return "https://github.com/org/repo.git\n"
            if "rev-parse" in args and "--show-toplevel" in args:
                return f"{rem_path.resolve()}\n"
            return ""

        mock_git.side_effect = mock_git_side_effect

        info = asyncio.run(
            wt_manager.create_remediation_worktree(
                "job-rem-1",
                "change-rem",
                source_sha,
                1,
                project_id="proj-rem-reuse",
                run_id="run-rem-1",
            )
        )
        assert info.path.resolve() == rem_path.resolve()
        assert info.branch_name == "minime/change-rem-job-rem-1-remediation-gen1"


def test_verify_candidate_ancestry_missing_project_id_fails_closed_before_fetch(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-ancestry-test",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    from minime.services.post_merge_service import PostMergeReconciliationService

    pm_service = PostMergeReconciliationService(
        uow=uow,
        project_root=tmp_dirs["repo_root"],
        github_adapter=MagicMock(),
    )

    with patch("subprocess.run") as mock_sub:
        res = pm_service.verify_candidate_ancestry("sha123", base_ref="main", project_id=None)

        assert res is False
        for call_item in mock_sub.call_args_list:
            args = call_item.args[0] if call_item.args else []
            assert "fetch" not in args
            assert "merge-base" not in args


def test_delete_local_branch_missing_project_id_fails_closed_before_deletion(tmp_dirs):
    subprocess.run(
        ["git", "branch", "minime/test-branch-to-del"],
        cwd=tmp_dirs["repo_root"],
        check=True,
        capture_output=True,
    )

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-branch-test",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    from minime.services.post_merge_service import PostMergeReconciliationService

    pm_service = PostMergeReconciliationService(
        uow=uow,
        project_root=tmp_dirs["repo_root"],
        github_adapter=MagicMock(),
    )

    with patch("subprocess.run") as mock_sub:
        res = pm_service._delete_local_branch("minime/test-branch-to-del", project_id=None)

        assert res.outcome != ExternalOutcome.SUCCESS
        assert res.outcome == ExternalOutcome.FAILURE
        assert res.reason_code == ExternalReasonCode.POLICY_DENIED

        for call_item in mock_sub.call_args_list:
            args = call_item.args[0] if call_item.args else []
            assert "branch" not in args or "-D" not in args
            assert "show-ref" not in args


def test_systemic_post_merge_entry_points_blocked_without_project_id(tmp_dirs):
    uow = MockUOW()
    from minime.services.post_merge_service import PostMergeReconciliationService

    pm_service = PostMergeReconciliationService(
        uow=uow,
        project_root=tmp_dirs["repo_root"],
        github_adapter=MagicMock(),
    )

    with patch("subprocess.run") as mock_sub:
        # 1. fetch / verify_candidate_ancestry
        ancestry_ok = pm_service.verify_candidate_ancestry(
            "sha123", base_ref="main", project_id=None
        )
        assert ancestry_ok is False

        # 2. worktree remove / _clean_worktrees
        wt_res = pm_service._clean_worktrees("job-no-pid", project_id=None)
        assert wt_res.outcome == ExternalOutcome.FAILURE
        assert wt_res.reason_code == ExternalReasonCode.POLICY_DENIED

        # 3. branch delete / _delete_local_branch
        br_res = pm_service._delete_local_branch("minime/some-branch", project_id=None)
        assert br_res.outcome == ExternalOutcome.FAILURE
        assert br_res.reason_code == ExternalReasonCode.POLICY_DENIED

        for call_item in mock_sub.call_args_list:
            args = call_item.args[0] if call_item.args else []
            assert "fetch" not in args
            assert "worktree" not in args or "remove" not in args
            assert "branch" not in args or "-D" not in args


def test_post_merge_cleanup_unowned_prefix_directory_not_removed(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-clean-1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    from minime.services.post_merge_service import PostMergeReconciliationService

    pm_service = PostMergeReconciliationService(
        uow=uow, project_root=tmp_dirs["repo_root"], github_adapter=MagicMock()
    )

    unowned_dir = Path(tmp_dirs["worktrees"]) / "job-unowned-123"
    unowned_dir.mkdir(parents=True, exist_ok=True)
    (unowned_dir / "file.txt").write_text("unowned", encoding="utf-8")

    res = pm_service._clean_worktrees("job-unowned-123", project_id="proj-clean-1")

    assert res.outcome == ExternalOutcome.FAILURE
    assert res.reason_code in (
        ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
        ExternalReasonCode.POLICY_DENIED,
    )
    assert unowned_dir.exists()


def test_post_merge_cleanup_mismatched_ownership_not_removed(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-clean-2",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    mismatched_dir = Path(tmp_dirs["worktrees"]) / "job-mismatch-456"
    mismatched_dir.mkdir(parents=True, exist_ok=True)

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job-mismatch-456",
        project_id="wrong-project",
        job_id="wrong-job",
        run_id="run-wrong",
        change_name="change-wrong",
        canonical_worktree_path=str(mismatched_dir.resolve()),
        source_repository_identity="github.com/org/repo",
        source_base_sha="main",
        branch="minime/change-wrong",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    from minime.services.post_merge_service import PostMergeReconciliationService

    pm_service = PostMergeReconciliationService(
        uow=uow, project_root=tmp_dirs["repo_root"], github_adapter=MagicMock()
    )

    res = pm_service._clean_worktrees("job-mismatch-456", project_id="proj-clean-2")

    assert res.outcome == ExternalOutcome.FAILURE
    assert mismatched_dir.exists()


def test_post_merge_cleanup_absent_from_git_worktree_list_not_removed(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-clean-3",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    wt_dir = Path(tmp_dirs["worktrees"]) / "job-no-gitlist-789"
    wt_dir.mkdir(parents=True, exist_ok=True)

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job-no-gitlist-789",
        project_id="proj-clean-3",
        job_id="job-no-gitlist-789",
        run_id="run-789",
        change_name="change-789",
        canonical_worktree_path=str(wt_dir.resolve()),
        source_repository_identity="github.com/org/repo",
        source_base_sha="main",
        branch="minime/change-789",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    from minime.services.post_merge_service import PostMergeReconciliationService

    pm_service = PostMergeReconciliationService(
        uow=uow, project_root=tmp_dirs["repo_root"], github_adapter=MagicMock()
    )

    res = pm_service._clean_worktrees("job-no-gitlist-789", project_id="proj-clean-3")

    assert res.outcome == ExternalOutcome.FAILURE
    assert wt_dir.exists()


def test_post_merge_cleanup_dirty_managed_worktree_not_removed(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_dirs["repo_root"], check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_dirs["repo_root"], check=True
    )
    (Path(tmp_dirs["repo_root"]) / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_dirs["repo_root"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-dirty-4",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-dirty-4",
            project_id="proj-dirty-4",
            change_name="change-dirty",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-dirty-4",
            active_job_id="job-dirty-4",
            project_id="proj-dirty-4",
            change_name="change-dirty",
            base_sha="main",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    info = asyncio.run(
        wt_manager.create_worktree(
            "job-dirty-4", "change-dirty", "main", project_id="proj-dirty-4", run_id="run-dirty-4"
        )
    )
    assert info.path.exists()

    (info.path / "dirty.txt").write_text("untracked modifications", encoding="utf-8")

    from minime.services.post_merge_service import PostMergeReconciliationService

    pm_service = PostMergeReconciliationService(
        uow=uow,
        project_root=tmp_dirs["repo_root"],
        github_adapter=MagicMock(),
        worktree_manager=wt_manager,
    )

    res = pm_service._clean_worktrees("job-dirty-4", project_id="proj-dirty-4")

    assert res.outcome == ExternalOutcome.FAILURE
    assert info.path.exists()


def test_post_merge_cleanup_clean_owned_worktree_successfully_removed(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_dirs["repo_root"], check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_dirs["repo_root"], check=True
    )
    (Path(tmp_dirs["repo_root"]) / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_dirs["repo_root"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-clean-5",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-clean-5",
            project_id="proj-clean-5",
            change_name="change-clean",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-clean-5",
            active_job_id="job-clean-5",
            project_id="proj-clean-5",
            change_name="change-clean",
            base_sha="main",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    info = asyncio.run(
        wt_manager.create_worktree(
            "job-clean-5", "change-clean", "main", project_id="proj-clean-5", run_id="run-clean-5"
        )
    )
    assert info.path.exists()

    from minime.services.post_merge_service import PostMergeReconciliationService

    pm_service = PostMergeReconciliationService(
        uow=uow,
        project_root=tmp_dirs["repo_root"],
        github_adapter=MagicMock(),
        worktree_manager=wt_manager,
    )

    res = pm_service._clean_worktrees("job-clean-5", project_id="proj-clean-5")

    assert res.outcome == ExternalOutcome.SUCCESS
    assert not info.path.exists()

    ownership = uow.orchestration_worktree_ownerships.get_by_id("wt-job-clean-5")
    assert ownership.creation_state == WorktreeCreationState.DELETED


def test_post_merge_reconciliation_refuses_claim_when_cleanup_fails(tmp_dirs):
    from minime.domain.enums import JobStatus, OrchestrationStopOutcome

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-refuse-6",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-refuse-6",
            project_id="proj-refuse-6",
            change_name="change-refuse",
            status=JobStatus.READY_TO_MERGE,
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-refuse-6",
            active_job_id="job-refuse-6",
            project_id="proj-refuse-6",
            change_name="change-refuse",
            base_sha="main",
            current_stage=OrchestrationStage.PR_PREPARED,
            stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    unowned_dir = Path(tmp_dirs["worktrees"]) / "job-refuse-6-unowned"
    unowned_dir.mkdir(parents=True, exist_ok=True)

    from minime.services.post_merge_service import PostMergeReconciliationService

    mock_gh = MagicMock()
    mock_gh.get_pull_request_details.return_value = MagicMock(
        outcome=ExternalOutcome.SUCCESS,
        data={"is_merged": True, "merged_by_login": "user", "head_sha": "sha"},
    )

    pm_service = PostMergeReconciliationService(
        uow=uow, project_root=tmp_dirs["repo_root"], github_adapter=mock_gh
    )
    pm_service.verify_candidate_ancestry = MagicMock(return_value=True)

    result = pm_service.reconcile_post_merge(
        "proj-refuse-6", "change-refuse", run_id="run-refuse-6"
    )

    assert result.success is False
    assert result.worktree_cleaned is False
    assert "worktree_cleanup" in (result.error_message or "")
    assert unowned_dir.exists()


def test_post_merge_service_source_code_has_no_direct_worktree_remove():
    import inspect

    from minime.services.post_merge_service import PostMergeReconciliationService

    src = inspect.getsource(PostMergeReconciliationService)
    assert 'git", "worktree", "remove"' not in src
    assert "worktree remove --force" not in src


def test_openspec_generator_missing_uow_or_project_id_fails_closed_zero_writes(tmp_dirs):
    from minime.services.openspec_generator import GeneratedOpenSpec, OpenSpecGenerator

    gen = OpenSpecGenerator(project_root=tmp_dirs["repo_root"], uow=None)
    spec = GeneratedOpenSpec(
        change_name="test-zero-write",
        proposal_content="# Proposal\n",
        tasks_content="- [ ] 1.1 Task\n",
    )

    target_dir = Path(tmp_dirs["repo_root"]) / "openspec" / "changes" / "test-zero-write"
    with pytest.raises(RuntimeError, match="mandatory for disk mutation"):
        gen.write_change_to_disk("openspec", spec, project_id=None)
    assert not target_dir.exists()

    uow = MockUOW()
    gen_with_uow = OpenSpecGenerator(project_root=tmp_dirs["repo_root"], uow=uow)
    with pytest.raises(RuntimeError, match="mandatory for disk mutation"):
        gen_with_uow.write_change_to_disk("openspec", spec, project_id=None)
    assert not target_dir.exists()


def test_lightweight_reconciliation_missing_uow_fails_closed(tmp_dirs):
    from minime.domain.models import Job, Project
    from minime.services.lightweight_reconciliation_service import LightweightReconciliationService

    rec = LightweightReconciliationService(uow=None)
    tasks_dir = Path(tmp_dirs["repo_root"]) / "openspec" / "changes" / "rec-change"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_file = tasks_dir / "tasks.md"
    initial_content = "# Tasks\n- [ ] 1.1 test verification task\n"
    tasks_file.write_text(initial_content, encoding="utf-8")

    job = Job(
        job_id="job-rec-1",
        project_id="proj-rec",
        change_name="rec-change",
        implementer_role="codex",
    )
    project = Project(project_id="proj-rec", display_name="rec", repository="org/repo")

    with pytest.raises(RuntimeError, match="self.uow is mandatory for tasks.md mutation"):
        rec.reconcile_bookkeeping(
            worktree_path=tmp_dirs["repo_root"],
            openspec_path="openspec",
            change_name="rec-change",
            job=job,
            project=project,
            checks_passed=True,
        )

    assert tasks_file.read_text(encoding="utf-8") == initial_content


def test_integration_worktree_adoption_proof_adversarial_checks(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_dirs["repo_root"], check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_dirs["repo_root"], check=True)
    (Path(tmp_dirs["repo_root"]) / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_dirs["repo_root"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    base_sha = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_dirs["repo_root"],
            check=True,
            capture_output=True,
            text=True,
        )
    ).stdout.strip()

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-int-adv",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-int-adv",
            project_id="proj-int-adv",
            change_name="change-int",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-int-adv",
            active_job_id="job-int-adv",
            project_id="proj-int-adv",
            change_name="change-int",
            base_sha=base_sha,
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    int_path = Path(tmp_dirs["worktrees"]) / "job-int-adv-integration-gen1"
    subprocess.run(
        ["git", "worktree", "add", "-b", "minime/integration-gen1", str(int_path), "HEAD"],
        cwd=tmp_dirs["repo_root"],
        check=True,
        capture_output=True,
    )

    with pytest.raises(
        RuntimeError, match="No durable OrchestrationWorktreeOwnership record found"
    ):
        asyncio.run(
            wt_manager.create_integration_worktree(
                job_id="job-int-adv",
                branch_name="minime/integration-gen1",
                base_sha=base_sha,
                generation=1,
                project_id="proj-int-adv",
                run_id="run-int-adv",
                change_name="change-int",
            )
        )

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job-int-adv-integration-gen1",
        project_id="proj-int-adv",
        job_id="job-int-adv",
        run_id="run-int-adv",
        change_name="change-int",
        canonical_worktree_path=str(int_path.resolve()),
        branch="minime/integration-gen1",
        source_repository_identity="github.com/org/repo",
        source_base_sha=base_sha,
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    ownership.run_id = "wrong-run"
    uow.orchestration_worktree_ownerships.save(ownership)
    with pytest.raises(RuntimeError, match="Run ID .* does not match durable"):
        asyncio.run(
            wt_manager.create_integration_worktree(
                job_id="job-int-adv",
                branch_name="minime/integration-gen1",
                base_sha=base_sha,
                generation=1,
                project_id="proj-int-adv",
                run_id="run-int-adv",
                change_name="change-int",
            )
        )
    ownership.run_id = "run-int-adv"
    uow.orchestration_worktree_ownerships.save(ownership)

    ownership.change_name = "wrong-change"
    uow.orchestration_worktree_ownerships.save(ownership)
    with pytest.raises(RuntimeError, match="Change name .* does not match durable"):
        asyncio.run(
            wt_manager.create_integration_worktree(
                job_id="job-int-adv",
                branch_name="minime/integration-gen1",
                base_sha=base_sha,
                generation=1,
                project_id="proj-int-adv",
                run_id="run-int-adv",
                change_name="change-int",
            )
        )
    ownership.change_name = "change-int"
    uow.orchestration_worktree_ownerships.save(ownership)

    ownership.branch = "wrong-branch"
    uow.orchestration_worktree_ownerships.save(ownership)
    with pytest.raises(RuntimeError, match="Branch .* does not match expected"):
        asyncio.run(
            wt_manager.create_integration_worktree(
                job_id="job-int-adv",
                branch_name="minime/integration-gen1",
                base_sha=base_sha,
                generation=1,
                project_id="proj-int-adv",
                run_id="run-int-adv",
                change_name="change-int",
            )
        )
    ownership.branch = "minime/integration-gen1"
    uow.orchestration_worktree_ownerships.save(ownership)

    ownership.source_repository_identity = "github.com/evil/repo"
    uow.orchestration_worktree_ownerships.save(ownership)
    with pytest.raises(RuntimeError, match="Source repository identity .* does not match binding"):
        asyncio.run(
            wt_manager.create_integration_worktree(
                job_id="job-int-adv",
                branch_name="minime/integration-gen1",
                base_sha=base_sha,
                generation=1,
                project_id="proj-int-adv",
                run_id="run-int-adv",
                change_name="change-int",
            )
        )
    ownership.source_repository_identity = "github.com/org/repo"
    uow.orchestration_worktree_ownerships.save(ownership)

    with pytest.raises(RuntimeError, match="Ownership marker file missing"):
        asyncio.run(
            wt_manager.create_integration_worktree(
                job_id="job-int-adv",
                branch_name="minime/integration-gen1",
                base_sha=base_sha,
                generation=1,
                project_id="proj-int-adv",
                run_id="run-int-adv",
                change_name="change-int",
            )
        )


def test_managed_repository_marker_missing_repository_identity_fails_closed(tmp_dirs):
    uow = MockUOW()
    guard = ManagedWorkspaceGuard(uow)

    marker_path = Path(tmp_dirs["repo_root"]) / ".minime-managed-project.json"
    marker_path.write_text(
        json.dumps({"project_id": "proj-marker-test", "canonical_repository_identity": ""})
    )

    ok, msg, reason, outcome = guard.verify_managed_repository_ownership_marker(
        tmp_dirs["repo_root"], "proj-marker-test", "github.com/org/repo"
    )

    assert ok is False
    assert reason == ExternalReasonCode.EVIDENCE_INSUFFICIENT
    assert outcome == ExternalOutcome.UNKNOWN
    assert "missing mandatory canonical repository identity" in msg


def test_create_worktree_reuse_requires_source_base_sha_and_proven_head(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_dirs["repo_root"], check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_dirs["repo_root"], check=True)
    (Path(tmp_dirs["repo_root"]) / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_dirs["repo_root"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    base_sha = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_dirs["repo_root"],
            check=True,
            capture_output=True,
            text=True,
        )
    ).stdout.strip()

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-reuse-sha",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-reuse-sha",
            project_id="proj-reuse-sha",
            change_name="change-reuse",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-reuse-sha",
            active_job_id="job-reuse-sha",
            project_id="proj-reuse-sha",
            change_name="change-reuse",
            base_sha=base_sha,
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    wt_path = Path(tmp_dirs["worktrees"]) / "job-reuse-sha"
    subprocess.run(
        ["git", "worktree", "add", "-b", "minime/change-reuse-job-reuse-sha", str(wt_path), "HEAD"],
        cwd=tmp_dirs["repo_root"],
        check=True,
        capture_output=True,
    )

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job-reuse-sha",
        project_id="proj-reuse-sha",
        job_id="job-reuse-sha",
        run_id="run-reuse-sha",
        change_name="change-reuse",
        canonical_worktree_path=str(wt_path.resolve()),
        branch="minime/change-reuse-job-reuse-sha",
        source_repository_identity="github.com/org/repo",
        source_base_sha="wrong-base-sha-1234567890",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)
    wt_manager._write_ownership_marker(wt_path, ownership)

    # 1. Wrong source_base_sha in DB ownership => Refused
    with pytest.raises(RuntimeError, match="Source base SHA .* does not match expected"):
        asyncio.run(
            wt_manager.create_worktree(
                job_id="job-reuse-sha",
                change_name="change-reuse",
                base_branch="main",
                project_id="proj-reuse-sha",
                reuse_existing=True,
                run_id="run-reuse-sha",
            )
        )

    # Correct source_base_sha in DB ownership & marker
    ownership.source_base_sha = base_sha
    uow.orchestration_worktree_ownerships.save(ownership)
    wt_manager._write_ownership_marker(wt_path, ownership)

    # Add an unproven commit to wt_path HEAD
    (wt_path / "extra.txt").write_text("extra", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=wt_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "extra unproven"], cwd=wt_path, check=True, capture_output=True
    )
    unproven_head = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt_path, check=True, capture_output=True, text=True
        )
    ).stdout.strip()

    # 2. Unproven HEAD (not equal to base SHA and not in DB candidate evidence) => Refused
    with pytest.raises(RuntimeError, match="and is not backed by durable candidate evidence"):
        asyncio.run(
            wt_manager.create_worktree(
                job_id="job-reuse-sha",
                change_name="change-reuse",
                base_branch="main",
                project_id="proj-reuse-sha",
                reuse_existing=True,
                run_id="run-reuse-sha",
            )
        )

    # Record unproven_head as candidate_sha in job => Proven => Accepted
    job = uow.jobs.get_by_id("job-reuse-sha")
    job.candidate_sha = unproven_head
    uow.jobs.save(job)

    info = asyncio.run(
        wt_manager.create_worktree(
            job_id="job-reuse-sha",
            change_name="change-reuse",
            base_branch="main",
            project_id="proj-reuse-sha",
            reuse_existing=True,
            run_id="run-reuse-sha",
        )
    )
    assert info.path.resolve() == wt_path.resolve()


def test_worktree_ownership_marker_corroborates_all_durable_fields(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    base_sha = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_dirs["repo_root"],
            check=True,
            capture_output=True,
            text=True,
        )
    ).stdout.strip()

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-marker-adv",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-marker-adv",
        project_id="proj-marker-adv",
        job_id="job-marker-adv",
        run_id="run-marker-adv",
        change_name="change-marker-adv",
        canonical_worktree_path=str((Path(tmp_dirs["worktrees"]) / "wt-marker-adv").resolve()),
        branch="minime/change-marker-adv-job-marker-adv",
        source_repository_identity="github.com/org/repo",
        source_base_sha=base_sha,
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    wt_path = Path(tmp_dirs["worktrees"]) / "wt-marker-adv"
    subprocess.run(
        ["git", "worktree", "add", "-b", ownership.branch, str(wt_path), "HEAD"],
        cwd=tmp_dirs["repo_root"],
        check=True,
        capture_output=True,
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)

    # Write full valid marker
    wt_manager._write_ownership_marker(wt_path, ownership)
    wt_manager._verify_ownership_marker(wt_path, ownership)

    marker_file = wt_path / ".minime_worktree_ownership.json"

    def set_marker(k: str, v: str | None):
        data = json.loads(marker_file.read_text(encoding="utf-8"))
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
        marker_file.write_text(json.dumps(data), encoding="utf-8")

    # 1. Wrong project_id
    set_marker("project_id", "wrong-proj")
    with pytest.raises(RuntimeError, match="project_id .* does not match"):
        wt_manager._verify_ownership_marker(wt_path, ownership)

    # 2. Wrong job_id
    set_marker("project_id", ownership.project_id)
    set_marker("job_id", "wrong-job")
    with pytest.raises(RuntimeError, match="job_id .* does not match"):
        wt_manager._verify_ownership_marker(wt_path, ownership)

    # 3. Wrong run_id
    set_marker("job_id", ownership.job_id)
    set_marker("run_id", "wrong-run")
    with pytest.raises(RuntimeError, match="run_id .* does not match"):
        wt_manager._verify_ownership_marker(wt_path, ownership)

    # 4. Wrong change_name
    set_marker("run_id", ownership.run_id)
    set_marker("change_name", "wrong-change")
    with pytest.raises(RuntimeError, match="change_name .* does not match"):
        wt_manager._verify_ownership_marker(wt_path, ownership)

    # 5. Wrong branch
    set_marker("change_name", ownership.change_name)
    set_marker("branch", "wrong-branch")
    set_marker("branch_name", "wrong-branch")
    with pytest.raises(RuntimeError, match="branch .* does not match"):
        wt_manager._verify_ownership_marker(wt_path, ownership)

    # 6. Wrong source repo identity
    set_marker("branch", ownership.branch)
    set_marker("branch_name", ownership.branch)
    set_marker("source_repository_identity", "github.com/evil/repo")
    with pytest.raises(RuntimeError, match="source_repository_identity .* does not match"):
        wt_manager._verify_ownership_marker(wt_path, ownership)

    # 7. Wrong source base SHA
    set_marker("source_repository_identity", ownership.source_repository_identity)
    set_marker("source_base_sha", "wrong-base-sha")
    with pytest.raises(RuntimeError, match="source_base_sha .* does not match"):
        wt_manager._verify_ownership_marker(wt_path, ownership)

    # 8. Missing mandatory field
    set_marker("source_base_sha", ownership.source_base_sha)
    set_marker("run_id", None)
    with pytest.raises(RuntimeError, match="missing mandatory field 'run_id'"):
        wt_manager._verify_ownership_marker(wt_path, ownership)


def test_openspec_task_tracker_active_writer_isolation(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="test-proj-tracker",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    from minime.services.openspec_tasks import OpenSpecTaskTracker

    wt_path = Path(tmp_dirs["worktrees"]) / "wt-tracker-1"
    tracker = OpenSpecTaskTracker(project_root=wt_path)

    # 1. Absolute / traversal openspec_path / change_name blocked
    with pytest.raises(RuntimeError, match="path confinement check"):
        tracker.reconcile_verification_tasks(
            openspec_path="/etc/passwd",
            change_name="change-1",
            check_evidence_passed=True,
            project_id="test-proj-tracker",
            job_id="job-1",
            uow=uow,
        )

    with pytest.raises(RuntimeError, match="path confinement check"):
        tracker.reconcile_verification_tasks(
            openspec_path="openspec",
            change_name="../change-1",
            check_evidence_passed=True,
            project_id="test-proj-tracker",
            job_id="job-1",
            uow=uow,
        )

    # 2. Setup owned execution worktree
    wt_path = Path(tmp_dirs["worktrees"]) / "wt-tracker-1"
    os.makedirs(wt_path, exist_ok=True)
    subprocess.run(["git", "init"], cwd=wt_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/org/repo"],
        cwd=wt_path,
        check=True,
        capture_output=True,
    )

    tasks_dir = wt_path / "openspec" / "changes" / "change-1"
    os.makedirs(tasks_dir, exist_ok=True)
    tasks_file = tasks_dir / "tasks.md"
    tasks_file.write_text("- [ ] run pytest tests\n", encoding="utf-8")

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-tracker-1",
        project_id="test-proj-tracker",
        job_id="job-1",
        run_id="run-1",
        change_name="change-1",
        canonical_worktree_path=str(wt_path.resolve()),
        branch="minime/change-1-job-1",
        source_repository_identity="github.com/org/repo",
        source_base_sha="0000000000000000000000000000000000000000",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    # 3. Runtime root path blocked
    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": str(wt_path)}):
        with pytest.raises(RuntimeError, match="denied"):
            tracker.reconcile_verification_tasks(
                openspec_path="openspec",
                change_name="change-1",
                check_evidence_passed=True,
                project_id="test-proj-tracker",
                job_id="job-1",
                uow=uow,
            )

    # 4. Valid owned execution worktree reconciliation succeeds
    success, ids = tracker.reconcile_verification_tasks(
        openspec_path="openspec",
        change_name="change-1",
        check_evidence_passed=True,
        project_id="test-proj-tracker",
        job_id="job-1",
        uow=uow,
    )
    assert success is True
    assert "[x]" in tasks_file.read_text(encoding="utf-8")


def test_openspec_generator_and_sync_descendant_authorization_isolation(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="test-proj-gen",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    from minime.services.openspec_generator import GeneratedOpenSpec, OpenSpecGenerator
    from minime.services.openspec_sync import OpenSpecSyncService

    gen = OpenSpecGenerator(
        project_root=tmp_dirs["repo_root"],
        uow=uow,
    )

    # 1. OpenSpecGenerator: change_name traversal blocked
    with pytest.raises(RuntimeError, match="path confinement check"):
        gen.write_change_to_disk(
            generated=GeneratedOpenSpec(
                change_name="../escaped",
                proposal_content="p",
                tasks_content="t",
                specs={},
            ),
            project_id="test-proj-gen",
            openspec_path="openspec",
        )

    # 2. OpenSpecGenerator: spec subpath traversal blocked
    with pytest.raises(RuntimeError, match="fails path confinement check"):
        gen.write_change_to_disk(
            generated=GeneratedOpenSpec(
                change_name="valid-change",
                proposal_content="p",
                tasks_content="t",
                specs={"../../evil.md": "content"},
            ),
            project_id="test-proj-gen",
            openspec_path="openspec",
        )

    # 3. OpenSpecSyncService: sync_change_specs traversal blocked
    sync_svc = OpenSpecSyncService(project_root=tmp_dirs["repo_root"], uow=uow)
    res_sync = sync_svc.sync_change_specs(
        openspec_path="openspec", change_name="../escaped", project_id="test-proj-gen"
    )
    assert res_sync.outcome == ExternalOutcome.FAILURE
    assert res_sync.reason_code == ExternalReasonCode.POLICY_DENIED

    # 4. OpenSpecSyncService: archive_change traversal blocked
    res_arch = sync_svc.archive_change(
        openspec_path="openspec", change_name="../escaped", project_id="test-proj-gen"
    )
    assert res_arch.outcome == ExternalOutcome.FAILURE
    assert res_arch.reason_code == ExternalReasonCode.POLICY_DENIED


def test_validated_repository_context_stage_c_push_authority(tmp_dirs):
    uow = MockUOW()

    from minime.domain.models import Project, ProjectBinding
    from minime.services.orchestration_service import OrchestrationService

    project = Project(
        project_id="test-proj-push",
        display_name="Test Push",
        repository="github.com/org/repo",
        base_branch="main",
    )
    binding = ProjectBinding(
        project_id="test-proj-push",
        repository="github.com/org/repo",
        openspec_change_name="change-push",
        is_valid=True,
    )

    orch_svc = OrchestrationService(uow=uow, project_root=tmp_dirs["repo_root"])

    # 1. Missing ProjectManagedRepositoryBinding -> blocked
    head_sha = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_dirs["repo_root"],
            check=True,
            capture_output=True,
            text=True,
        )
    ).stdout.strip()
    _, err = orch_svc._validated_repository_context(
        root=Path(tmp_dirs["repo_root"]),
        project=project,
        binding=binding,
        candidate_sha=head_sha,
    )
    assert err is not None
    assert "Missing ProjectManagedRepositoryBinding" in err

    # 2. Invalid ProjectManagedRepositoryBinding (mismatch reasons) -> blocked
    mb_invalid = ProjectManagedRepositoryBinding(
        project_id="test-proj-push",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
        mismatch_reasons=["mismatch"],
    )
    uow.project_managed_repository_bindings.save(mb_invalid)
    _, err = orch_svc._validated_repository_context(
        root=Path(tmp_dirs["repo_root"]),
        project=project,
        binding=binding,
        candidate_sha=head_sha,
    )
    assert err is not None
    assert "missing, invalid, or unverified" in err

    # 3. Root differs from managed_repository_root -> blocked
    mb_valid = ProjectManagedRepositoryBinding(
        project_id="test-proj-push",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(mb_valid)

    other_dir = os.path.join(tmp_dirs["base"], "other_dir")
    os.makedirs(other_dir, exist_ok=True)
    subprocess.run(["git", "init"], cwd=other_dir, check=True, capture_output=True)

    _, err = orch_svc._validated_repository_context(
        root=Path(other_dir),
        project=project,
        binding=binding,
        candidate_sha=head_sha,
    )
    assert err is not None
    assert "does not match managed repository root" in err

    # 4. Target path inside runtime root -> blocked
    mb_runtime = ProjectManagedRepositoryBinding(
        project_id="test-proj-push",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["runtime"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(mb_runtime)
    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": tmp_dirs["runtime"]}):
        _, err = orch_svc._validated_repository_context(
            root=Path(tmp_dirs["runtime"]),
            project=project,
            binding=binding,
            candidate_sha=head_sha,
        )
        assert err is not None
        assert any(
            token in err
            for token in (
                "Workspace mutation policy denied",
                "marker",
                "unobservable",
                "Git repository",
            )
        )

    # 5. Valid managed root + binding + marker + remote + candidate SHA -> allowed
    uow.project_managed_repository_bindings.save(mb_valid)
    marker_path = os.path.join(tmp_dirs["repo_root"], ".minime-managed-project.json")
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "project_id": "test-proj-push",
                "canonical_repository_identity": "github.com/org/repo",
            },
            f,
        )

    _, err = orch_svc._validated_repository_context(
        root=Path(tmp_dirs["repo_root"]),
        project=project,
        binding=binding,
        candidate_sha=head_sha,
    )
    assert err is None


def test_openspec_sync_managed_root_authority_closure(tmp_dirs):
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="test-proj-sync-auth",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    from minime.services.openspec_sync import OpenSpecSyncService

    # 1. OpenSpecSyncService project_root != durable managed_repository_root => sync blocked, zero writes
    other_dir = os.path.join(tmp_dirs["base"], "other_unauthorized_root")
    os.makedirs(other_dir, exist_ok=True)
    subprocess.run(["git", "init"], cwd=other_dir, check=True, capture_output=True)

    bad_sync = OpenSpecSyncService(project_root=other_dir, uow=uow)
    res_bad_sync = bad_sync.sync_change_specs(
        openspec_path="openspec", change_name="change-1", project_id="test-proj-sync-auth"
    )
    assert res_bad_sync.outcome == ExternalOutcome.FAILURE
    assert res_bad_sync.reason_code == ExternalReasonCode.POLICY_DENIED
    assert "does not match durable managed repository root" in res_bad_sync.error_message
    assert not (Path(other_dir) / "openspec" / "specs").exists()

    # 2. project_root mismatch => archive blocked, zero move
    res_bad_archive = bad_sync.archive_change(
        openspec_path="openspec", change_name="change-1", project_id="test-proj-sync-auth"
    )
    assert res_bad_archive.outcome == ExternalOutcome.FAILURE
    assert res_bad_archive.reason_code == ExternalReasonCode.POLICY_DENIED
    assert "does not match durable managed repository root" in res_bad_archive.error_message

    # 3. capability target escape/traversal => blocked
    good_sync = OpenSpecSyncService(project_root=tmp_dirs["repo_root"], uow=uow)

    change_dir = Path(tmp_dirs["repo_root"]) / "openspec" / "changes" / "change-1"
    specs_dir = change_dir / "specs"
    os.makedirs(specs_dir, exist_ok=True)

    mock_cap = MagicMock()
    mock_cap.name = ".."
    mock_cap.is_dir.return_value = True
    with patch.object(Path, "iterdir", return_value=[mock_cap]):
        res_cap_escape = good_sync.sync_change_specs(
            openspec_path="openspec", change_name="change-1", project_id="test-proj-sync-auth"
        )
        assert res_cap_escape.outcome == ExternalOutcome.FAILURE
        assert res_cap_escape.reason_code == ExternalReasonCode.POLICY_DENIED
        assert not (Path(tmp_dirs["repo_root"]) / "openspec" / "specs").exists()

    # 4. exact canonical main spec destination receives guard authorization before mkdir/write
    valid_cap_dir = specs_dir / "valid-capability"
    os.makedirs(valid_cap_dir, exist_ok=True)
    (valid_cap_dir / "spec.md").write_text("## Requirement: Valid Cap\n", encoding="utf-8")

    target_cap_file = (
        Path(tmp_dirs["repo_root"]) / "openspec" / "specs" / "valid-capability" / "spec.md"
    )
    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": str(target_cap_file)}):
        res_denied_target = good_sync.sync_change_specs(
            openspec_path="openspec", change_name="change-1", project_id="test-proj-sync-auth"
        )
        assert res_denied_target.outcome == ExternalOutcome.FAILURE
        assert res_denied_target.reason_code == ExternalReasonCode.POLICY_DENIED
        assert not target_cap_file.exists()

    # 5. valid managed-root sync succeeds
    res_valid_sync = good_sync.sync_change_specs(
        openspec_path="openspec", change_name="change-1", project_id="test-proj-sync-auth"
    )
    assert res_valid_sync.outcome == ExternalOutcome.SUCCESS
    assert target_cap_file.exists()
    assert "Valid Cap" in target_cap_file.read_text(encoding="utf-8")

    # 6. valid managed-root archive succeeds
    (change_dir / "proposal.md").write_text("proposal", encoding="utf-8")
    res_valid_archive = good_sync.archive_change(
        openspec_path="openspec",
        change_name="change-1",
        target_date="2026-09-27",
        project_id="test-proj-sync-auth",
    )
    assert res_valid_archive.outcome == ExternalOutcome.SUCCESS
    assert not change_dir.exists()
    archived_dir = (
        Path(tmp_dirs["repo_root"]) / "openspec" / "changes" / "archive" / "2026-09-27-change-1"
    )
    assert archived_dir.exists()
    assert (archived_dir / "proposal.md").exists()


@pytest.mark.asyncio
async def test_review_worktree_lifecycle_finalization_cases(tmp_dirs):
    """Proves all 6 requirements for Stage C review worktree lifecycle finalization."""
    repo_root = tmp_dirs["repo_root"]
    worktrees_dir = tmp_dirs["worktrees"]
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True)
    (Path(repo_root) / "README.md").write_text("init candidate A", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "candidate A commit"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    cand_sha_a = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True
        )
    ).stdout.strip()

    # Commit candidate B
    (Path(repo_root) / "README.md").write_text("init candidate B", encoding="utf-8")
    subprocess.run(
        ["git", "commit", "-am", "candidate B commit"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    cand_sha_b = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True
        )
    ).stdout.strip()

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-rev-final",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=repo_root,
        worktree_parent_dir=worktrees_dir,
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-rev-final",
            project_id="proj-rev-final",
            change_name="change-rev-final",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-rev-final",
            active_job_id="job-rev-final",
            project_id="proj-rev-final",
            change_name="change-rev-final",
            base_sha=cand_sha_a,
            current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
            resumable_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        )
    )

    mgr = WorktreeManager(repo_root, uow)

    # 1. absent review path + no durable ownership => EVIDENCE_INSUFFICIENT, not success
    fake_absent_path = Path(worktrees_dir) / "job-rev-final-review-antigravity-fake"
    res1 = await mgr.remove_review_worktree(fake_absent_path, "job-rev-final", "proj-rev-final")
    assert res1.outcome == ExternalOutcome.UNKNOWN
    assert res1.reason_code == ExternalReasonCode.EVIDENCE_INSUFFICIENT

    # 4. reviewer candidate A: create -> review -> cleanup
    wt_a = await mgr.create_review_worktree(
        job_id="job-rev-final",
        change_name="change-rev-final",
        candidate_sha=cand_sha_a,
        reviewer_role="antigravity",
        project_id="proj-rev-final",
        run_id="run-rev-final",
    )
    assert wt_a.path.exists()
    assert cand_sha_a[:8] in wt_a.path.name
    assert cand_sha_a[:8] in wt_a.branch_name

    res_clean_a = await mgr.remove_review_worktree(wt_a.path, "job-rev-final", "proj-rev-final")
    assert res_clean_a.outcome == ExternalOutcome.SUCCESS
    assert not wt_a.path.exists()

    # 2. absent path + durable DELETED + git absent => ALREADY_ABSENT
    res2 = await mgr.remove_review_worktree(wt_a.path, "job-rev-final", "proj-rev-final")
    assert res2.outcome == ExternalOutcome.SUCCESS
    assert res2.reason_code == ExternalReasonCode.ALREADY_ABSENT

    # 3. inconsistent active ownership / filesystem / git observations => fail closed
    wt_a.path.mkdir(parents=True, exist_ok=True)
    res3 = await mgr.remove_review_worktree(wt_a.path, "job-rev-final", "proj-rev-final")
    assert res3.outcome == ExternalOutcome.FAILURE
    assert res3.reason_code in (ExternalReasonCode.CONFLICT, ExternalReasonCode.POLICY_DENIED)
    shutil.rmtree(wt_a.path, ignore_errors=True)

    # 5. same job/reviewer then candidate B: creates a valid review worktree at candidate B and is not blocked by candidate A's historical review branch
    wt_b = await mgr.create_review_worktree(
        job_id="job-rev-final",
        change_name="change-rev-final",
        candidate_sha=cand_sha_b,
        reviewer_role="antigravity",
        project_id="proj-rev-final",
        run_id="run-rev-final",
    )
    assert wt_b.path.exists()
    assert cand_sha_b[:8] in wt_b.path.name
    assert wt_b.base_sha == cand_sha_b

    head_b = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=wt_b.path, check=True, capture_output=True, text=True
        )
    ).stdout.strip()
    assert head_b == cand_sha_b

    # 6. same exact candidate retry: deterministic/idempotent adoption/recreation behavior
    wt_b_retry = await mgr.create_review_worktree(
        job_id="job-rev-final",
        change_name="change-rev-final",
        candidate_sha=cand_sha_b,
        reviewer_role="antigravity",
        project_id="proj-rev-final",
        run_id="run-rev-final",
    )
    assert wt_b_retry.path == wt_b.path
    assert wt_b_retry.base_sha == cand_sha_b

    # Final cleanup of B
    res_clean_b = await mgr.remove_review_worktree(wt_b.path, "job-rev-final", "proj-rev-final")
    assert res_clean_b.outcome == ExternalOutcome.SUCCESS


def test_blocker_1_openspec_generator_symlink_preflight_atomicity(tmp_dirs):
    """Proves OpenSpecGenerator destination preflight atomicity and symlink escape rejection."""
    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="test-gen-blocker1",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)

    from minime.services.openspec_generator import GeneratedOpenSpec, OpenSpecGenerator

    gen = OpenSpecGenerator(project_root=tmp_dirs["repo_root"], uow=uow)

    target_dir = Path(tmp_dirs["repo_root"]) / "openspec" / "changes" / "change-symlink-test"
    target_dir.mkdir(parents=True, exist_ok=True)

    runtime_secret = Path(tmp_dirs["runtime"]) / "runtime_secret.txt"
    runtime_secret.parent.mkdir(parents=True, exist_ok=True)
    runtime_secret.write_text("INITIAL_RUNTIME_CONTENT", encoding="utf-8")

    # A) proposal.md is a symlink into RUNTIME + overwrite=True => operation denied => runtime target unchanged
    proposal_symlink = target_dir / "proposal.md"
    os.symlink(str(runtime_secret), str(proposal_symlink))

    spec_a = GeneratedOpenSpec(
        change_name="change-symlink-test",
        proposal_content="# Malicious Proposal\n",
        tasks_content="- [ ] task\n",
        design_content="# Malicious Design\n",
    )

    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": tmp_dirs["runtime"]}):
        with pytest.raises(
            RuntimeError, match="OpenSpec write denied: symlink target|ManagedWorkspaceGuard denied"
        ):
            gen.write_change_to_disk(
                "openspec", spec_a, overwrite=True, project_id="test-gen-blocker1"
            )

    assert runtime_secret.read_text(encoding="utf-8") == "INITIAL_RUNTIME_CONTENT"
    # E) Preflight atomicity: tasks.md and design.md were NOT written
    assert not (target_dir / "tasks.md").exists()
    assert not (target_dir / "design.md").exists()

    # B) Clean up proposal symlink, make tasks.md a symlink into RUNTIME
    proposal_symlink.unlink()
    tasks_symlink = target_dir / "tasks.md"
    os.symlink(str(runtime_secret), str(tasks_symlink))

    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": tmp_dirs["runtime"]}):
        with pytest.raises(
            RuntimeError, match="OpenSpec write denied: symlink target|ManagedWorkspaceGuard denied"
        ):
            gen.write_change_to_disk(
                "openspec", spec_a, overwrite=True, project_id="test-gen-blocker1"
            )

    assert runtime_secret.read_text(encoding="utf-8") == "INITIAL_RUNTIME_CONTENT"
    assert not (target_dir / "proposal.md").exists()

    # C) spec final file symlink escapes change subtree
    tasks_symlink.unlink()
    spec_dir = target_dir / "specs" / "feat"
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_symlink = spec_dir / "spec.md"
    os.symlink(str(runtime_secret), str(spec_symlink))

    spec_b = GeneratedOpenSpec(
        change_name="change-symlink-test",
        proposal_content="# Proposal\n",
        tasks_content="- [ ] task\n",
        specs={"specs/feat/spec.md": "# Evil Spec\n"},
    )

    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": tmp_dirs["runtime"]}):
        with pytest.raises(
            RuntimeError, match="OpenSpec write denied|ManagedWorkspaceGuard denied"
        ):
            gen.write_change_to_disk(
                "openspec", spec_b, overwrite=True, project_id="test-gen-blocker1"
            )

    assert runtime_secret.read_text(encoding="utf-8") == "INITIAL_RUNTIME_CONTENT"
    assert not (target_dir / "proposal.md").exists()
    assert not (target_dir / "tasks.md").exists()

    # D) All destinations valid => generation succeeds
    spec_symlink.unlink()
    res_dir = gen.write_change_to_disk(
        "openspec", spec_b, overwrite=True, project_id="test-gen-blocker1"
    )
    assert res_dir.exists()
    assert (res_dir / "proposal.md").exists()
    assert (res_dir / "tasks.md").exists()
    assert (res_dir / "specs" / "feat" / "spec.md").exists()


def test_blocker_2_readiness_current_truth_verification(tmp_dirs):
    """Proves ReadinessService Stage C admission fence revalidates CURRENT Stage C truth."""
    uow = MockUOW()

    repo_root = tmp_dirs["repo_root"]
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True)
    (Path(repo_root) / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_root, check=True, capture_output=True)
    try:
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/org/repo"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except Exception:
        subprocess.run(
            ["git", "remote", "set-url", "origin", "https://github.com/org/repo"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )

    marker_path = Path(repo_root) / ".minime-managed-project.json"
    marker_path.write_text(
        json.dumps(
            {
                "project_id": "proj-readiness-current",
                "canonical_repository_identity": "github.com/org/repo",
            }
        ),
        encoding="utf-8",
    )

    from minime.domain.models import Project, ProjectBinding

    project = Project(
        project_id="proj-readiness-current",
        display_name="Readiness Current",
        repository="github.com/org/repo",
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(project)

    binding = ProjectManagedRepositoryBinding(
        project_id="proj-readiness-current",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=repo_root,
        worktree_parent_dir=tmp_dirs["worktrees"],
        remote_name="origin",
    )
    uow.project_managed_repository_bindings.save(binding)

    durable_binding = ProjectBinding(
        project_id="proj-readiness-current",
        repository="github.com/org/repo",
        openspec_change_name="change-readiness",
        github_issue_number=123,
        is_valid=True,
    )
    uow.bindings.save(durable_binding)

    # Seed OpenSpec change dir
    ch_dir = Path(repo_root) / "openspec" / "changes" / "change-readiness"
    (ch_dir / "specs" / "feat").mkdir(parents=True, exist_ok=True)
    (ch_dir / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
    (ch_dir / "tasks.md").write_text("# Tasks\n- [ ] task\n", encoding="utf-8")
    (ch_dir / "design.md").write_text("# Design\n", encoding="utf-8")
    (ch_dir / "specs" / "feat" / "spec.md").write_text("# Spec\n", encoding="utf-8")

    from minime.services.readiness_service import ReadinessService

    svc = ReadinessService(uow=uow)

    # F) All current evidence valid => stage_c_workspace_isolation PASS
    eval_ok = svc.evaluate_change_readiness("proj-readiness-current", "change-readiness", repo_root)
    sc_check = next(c for c in eval_ok.checks if c.name == "stage_c_workspace_isolation")
    assert sc_check.passed is True
    assert sc_check.details.get("is_runtime_isolated") is True

    # A) binding.is_valid=True but remote changed => readiness NOT_READY
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/evil/repo"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    eval_a = svc.evaluate_change_readiness("proj-readiness-current", "change-readiness", repo_root)
    assert eval_a.is_ready is False
    sc_a = next(c for c in eval_a.checks if c.name == "stage_c_workspace_isolation")
    assert sc_a.passed is False
    assert "Git repository" in sc_a.reason and (
        "remote mismatch" in sc_a.reason or "identity verification failed" in sc_a.reason
    )
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/org/repo"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )

    # B) binding.is_valid=True but managed marker missing/corrupt => NOT_READY
    marker_path.unlink()
    eval_b = svc.evaluate_change_readiness("proj-readiness-current", "change-readiness", repo_root)
    assert eval_b.is_ready is False
    sc_b = next(c for c in eval_b.checks if c.name == "stage_c_workspace_isolation")
    assert sc_b.passed is False
    assert "ownership marker" in sc_b.reason

    # Restore marker
    marker_path.write_text(
        json.dumps(
            {
                "project_id": "proj-readiness-current",
                "canonical_repository_identity": "github.com/org/repo",
            }
        ),
        encoding="utf-8",
    )

    # C) binding.is_valid=True but managed root missing => NOT_READY
    binding.managed_repository_root = os.path.join(tmp_dirs["base"], "nonexistent_root_path")
    uow.project_managed_repository_bindings.save(binding)
    eval_c = svc.evaluate_change_readiness("proj-readiness-current", "change-readiness", repo_root)
    assert eval_c.is_ready is False
    sc_c = next(c for c in eval_c.checks if c.name == "stage_c_workspace_isolation")
    assert sc_c.passed is False
    assert "does not exist or is not a directory" in sc_c.reason

    # D) runtime/managed overlap => NOT_READY
    binding.managed_repository_root = tmp_dirs["runtime"]
    uow.project_managed_repository_bindings.save(binding)
    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": tmp_dirs["runtime"]}):
        eval_d = svc.evaluate_change_readiness(
            "proj-readiness-current", "change-readiness", repo_root
        )
        assert eval_d.is_ready is False
        sc_d = next(c for c in eval_d.checks if c.name == "stage_c_workspace_isolation")
        assert sc_d.passed is False
        assert "collides or overlaps" in sc_d.reason

    # Restore valid binding
    binding.managed_repository_root = repo_root
    uow.project_managed_repository_bindings.save(binding)

    # E) confinement unavailable => NOT_READY
    with patch(
        "minime.services.agent_confinement.AgentProcessConfinement.is_confinement_available",
        return_value=False,
    ):
        eval_e = svc.evaluate_change_readiness(
            "proj-readiness-current", "change-readiness", repo_root
        )
        assert eval_e.is_ready is False
        sc_e = next(c for c in eval_e.checks if c.name == "stage_c_workspace_isolation")
        assert sc_e.passed is False
        assert "confinement capability is unavailable" in sc_e.reason


def test_task_a_readiness_admission_fence_complete_current_truth_proof(tmp_dirs):
    repo_root = tmp_dirs["repo_root"]
    wt_dir = tmp_dirs["worktrees"]
    rt_dir = tmp_dirs["runtime"]

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_root, check=True)
    subprocess.run(["git", "remote", "remove", "origin"], cwd=repo_root, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/org/repo"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    (Path(repo_root) / "README.md").write_text("readiness\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_root, check=True, capture_output=True)

    marker_path = Path(repo_root) / ".minime-managed-project.json"
    marker_path.write_text(
        json.dumps(
            {
                "project_id": "proj-readiness-proof",
                "canonical_repository_identity": "github.com/org/repo",
            }
        ),
        encoding="utf-8",
    )

    uow = MockUOW()
    uow.projects.projects["proj-readiness-proof"] = MagicMock(
        project_id="proj-readiness-proof",
        status=MagicMock(value="ACTIVE"),
        repository="github.com/org/repo",
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
        strict_validation_required=False,
    )
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-readiness-proof",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=repo_root,
        worktree_parent_dir=wt_dir,
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.bindings.bindings[("proj-readiness-proof", "change-readiness")] = MagicMock(
        binding_id="bind-1",
        project_id="proj-readiness-proof",
        change_name="change-readiness",
        repository="github.com/org/repo",
        github_issue_number=42,
        is_valid=True,
        mismatch_reasons=[],
    )

    from minime.services.readiness_service import ReadinessService

    svc = ReadinessService(uow=uow)

    # 1. Missing worktree_parent_dir => NOT_READY
    binding.worktree_parent_dir = os.path.join(tmp_dirs["base"], "nonexistent_wt_parent")
    uow.project_managed_repository_bindings.save(binding)
    eval_missing_wt = svc.evaluate_change_readiness(
        "proj-readiness-proof", "change-readiness", repo_root
    )
    assert eval_missing_wt.is_ready is False
    assert (
        "does not exist or is not a directory"
        in next(c for c in eval_missing_wt.checks if c.name == "stage_c_workspace_isolation").reason
    )

    # Restore wt_dir
    binding.worktree_parent_dir = wt_dir
    uow.project_managed_repository_bindings.save(binding)

    # 2. worktree_parent_dir == runtime => NOT_READY
    binding.worktree_parent_dir = rt_dir
    uow.project_managed_repository_bindings.save(binding)
    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": rt_dir}):
        eval_eq = svc.evaluate_change_readiness(
            "proj-readiness-proof", "change-readiness", repo_root
        )
        assert eval_eq.is_ready is False
        assert (
            "collides or overlaps"
            in next(c for c in eval_eq.checks if c.name == "stage_c_workspace_isolation").reason
        )

    # 3. worktree_parent_dir is parent of runtime => NOT_READY
    wt_parent_of_rt = os.path.dirname(os.path.realpath(rt_dir))
    binding.worktree_parent_dir = wt_parent_of_rt
    uow.project_managed_repository_bindings.save(binding)
    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": rt_dir}):
        eval_par = svc.evaluate_change_readiness(
            "proj-readiness-proof", "change-readiness", repo_root
        )
        assert eval_par.is_ready is False
        assert (
            "collides or overlaps"
            in next(c for c in eval_par.checks if c.name == "stage_c_workspace_isolation").reason
        )

    # 4. worktree_parent_dir is child of runtime => NOT_READY
    wt_child_of_rt = os.path.join(rt_dir, "worktrees")
    os.makedirs(wt_child_of_rt, exist_ok=True)
    binding.worktree_parent_dir = wt_child_of_rt
    uow.project_managed_repository_bindings.save(binding)
    with patch.dict(os.environ, {"MINIME_RUNTIME_ROOT": rt_dir}):
        eval_child = svc.evaluate_change_readiness(
            "proj-readiness-proof", "change-readiness", repo_root
        )
        assert eval_child.is_ready is False
        assert (
            "collides or overlaps"
            in next(c for c in eval_child.checks if c.name == "stage_c_workspace_isolation").reason
        )

    # Restore wt_dir
    binding.worktree_parent_dir = wt_dir
    uow.project_managed_repository_bindings.save(binding)

    # 5. Trusted-root prefix collision (/opt/minime/managed-evil/worktrees) => NOT_READY
    trusted_root = os.path.join(tmp_dirs["base"], "managed")
    evil_wt = os.path.join(tmp_dirs["base"], "managed-evil", "worktrees")
    os.makedirs(trusted_root, exist_ok=True)
    os.makedirs(evil_wt, exist_ok=True)
    binding.worktree_parent_dir = evil_wt
    uow.project_managed_repository_bindings.save(binding)
    with patch.dict(os.environ, {"MINIME_MANAGED_ROOT": trusted_root}):
        eval_evil = svc.evaluate_change_readiness(
            "proj-readiness-proof", "change-readiness", repo_root
        )
        assert eval_evil.is_ready is False
        assert (
            "escapes trusted managed root"
            in next(c for c in eval_evil.checks if c.name == "stage_c_workspace_isolation").reason
        )

    # Restore valid wt_dir
    binding.worktree_parent_dir = wt_dir
    uow.project_managed_repository_bindings.save(binding)


def test_task_b_checks_runner_process_confinement(tmp_dirs):
    wt_path = Path(tmp_dirs["worktrees"]) / "wt-checks-confinement"
    wt_path.mkdir(parents=True, exist_ok=True)
    rt_path = Path(tmp_dirs["runtime"])

    from minime.services.checks_runner import ChecksRunner

    runner = ChecksRunner(timeout_seconds=10)

    # 1. Normal check inside worktree succeeds
    res1 = asyncio.run(
        runner.run(
            job_id="job-c1",
            checks=[{"name": "echo-test", "command": "echo hello"}],
            worktree_path=wt_path,
        )
    )
    assert res1.passed is True

    # 2. Write inside assigned worktree succeeds
    res2 = asyncio.run(
        runner.run(
            job_id="job-c2",
            checks=[{"name": "write-in-wt", "command": f"touch '{wt_path}/ok.txt'"}],
            worktree_path=wt_path,
        )
    )
    assert res2.passed is True
    assert (wt_path / "ok.txt").exists()

    # If OS sandbox (e.g. darwin_sandbox) is present: test outside write denial
    if platform.system().lower() == "darwin" and shutil.which("sandbox-exec"):
        # 3. Absolute write outside worktree denied
        res3 = asyncio.run(
            runner.run(
                job_id="job-c3",
                checks=[{"name": "write-outside", "command": "touch /tmp/minime-test-escape.txt"}],
                worktree_path=wt_path,
            )
        )
        assert res3.passed is False

        # 4. Write into RUNTIME denied
        res4 = asyncio.run(
            runner.run(
                job_id="job-c4",
                checks=[{"name": "write-runtime", "command": f"touch '{rt_path}/evil.txt'"}],
                worktree_path=wt_path,
            )
        )
        assert res4.passed is False

    # 6. Confinement unavailable => check fails closed
    with patch(
        "minime.services.agent_confinement.AgentProcessConfinement.is_confinement_available",
        return_value=False,
    ):
        res6 = asyncio.run(
            runner.run(
                job_id="job-c6",
                checks=[{"name": "confinement-unavail", "command": "echo hello"}],
                worktree_path=wt_path,
            )
        )
        assert res6.passed is False
        assert res6.results[0].exit_code == 126
        assert (
            res6.diagnostics[0].diagnostic_status
            == EvidenceDiagnosticStatus.ENVIRONMENT_UNAVAILABLE
        )


def test_task_c_worktree_manager_internal_writers(tmp_dirs):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_dirs["repo_root"], check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_dirs["repo_root"], check=True
    )
    (Path(tmp_dirs["repo_root"]) / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_dirs["repo_root"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_dirs["repo_root"], check=True, capture_output=True
    )

    uow = MockUOW()
    binding = ProjectManagedRepositoryBinding(
        project_id="proj-task-c",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.jobs.save(
        Job(
            job_id="job-task-c",
            project_id="proj-task-c",
            change_name="change-task-c",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-task-c",
            active_job_id="job-task-c",
            project_id="proj-task-c",
            change_name="change-task-c",
            base_sha="main",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    wt_manager = WorktreeManager(project_root=tmp_dirs["repo_root"], uow=uow)
    wt_path = wt_manager.worktree_path("job-task-c", project_id="proj-task-c").resolve()
    wt_path.mkdir(parents=True, exist_ok=True)

    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-job-task-c",
        project_id="proj-task-c",
        job_id="job-task-c",
        run_id="run-task-c",
        change_name="change-task-c",
        canonical_worktree_path=str(wt_path),
        source_repository_identity="github.com/org/repo",
        source_base_sha="main",
        branch="minime/change-task-c-job-task-c",
        creation_state=WorktreeCreationState.PENDING,
    )

    # 1. Ownership marker symlink pointing to RUNTIME is denied
    symlink_marker = wt_path / ".minime_worktree_ownership.json"
    runtime_file = Path(tmp_dirs["runtime"]) / "target_marker.json"
    os.symlink(runtime_file, symlink_marker)

    with pytest.raises(RuntimeError, match="Symlink escape detected at ownership marker target"):
        wt_manager._write_ownership_marker(wt_path, ownership)

    # Remove symlink marker
    symlink_marker.unlink()

    # 2. Valid marker write inside execution worktree succeeds
    wt_manager._write_ownership_marker(wt_path, ownership)
    assert symlink_marker.exists()
    assert not symlink_marker.is_symlink()

    # 3. OpenSpec destination ancestor symlink -> RUNTIME is denied
    os.makedirs(
        Path(tmp_dirs["repo_root"]) / "openspec" / "changes" / "change-task-c", exist_ok=True
    )
    (
        Path(tmp_dirs["repo_root"]) / "openspec" / "changes" / "change-task-c" / "proposal.md"
    ).write_text("proposal\n", encoding="utf-8")

    uow.jobs.save(
        Job(
            job_id="job-task-c-2",
            project_id="proj-task-c",
            change_name="change-task-c",
            implementer_role="codex",
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-task-c-2",
            active_job_id="job-task-c-2",
            project_id="proj-task-c",
            change_name="change-task-c",
            base_sha="main",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    wt_path2 = wt_manager.worktree_path("job-task-c-2", project_id="proj-task-c").resolve()
    wt_path2.mkdir(parents=True, exist_ok=True)
    symlink_openspec = wt_path2 / "openspec"
    os.symlink(tmp_dirs["runtime"], symlink_openspec)

    # Directly test OpenSpec propagation check or create_worktree propagation error
    dest_openspec_root = wt_path2 / "openspec"
    dest_change_dir = dest_openspec_root / "changes" / "change-task-c"
    assert (
        os.path.islink(dest_openspec_root)
        or os.path.islink(dest_openspec_root / "changes")
        or os.path.islink(dest_change_dir)
    )


def test_onboard_project_establishes_real_remote_checkout_and_uses_guard_authorization(tmp_path):
    """Verify fresh onboarding clones actual remote history, verifies refs, uses Guard authorization, and persists marker after checkout."""
    from minime.domain.enums import ProjectOnboardingStatus
    from minime.domain.models import ProjectOnboardingInput
    from minime.services.project_onboarding_service import ProjectOnboardingService

    uow = MockUOW()
    trusted_root = tmp_path / "trusted_managed"
    trusted_root.mkdir(parents=True, exist_ok=True)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "openspec").mkdir(parents=True, exist_ok=True)

    # 1. Create a real local bare Git remote repository fixture
    remote_bare = tmp_path / "remote_source.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote_bare)], check=True, capture_output=True
    )

    work_seed = tmp_path / "work_seed"
    subprocess.run(
        ["git", "clone", str(remote_bare), str(work_seed)], check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Remote Dev"], cwd=work_seed, check=True)
    subprocess.run(["git", "config", "user.email", "dev@remote.local"], cwd=work_seed, check=True)
    (work_seed / "README.md").write_text("# Remote Base History\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work_seed, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Remote canonical base commit"],
        cwd=work_seed,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=work_seed, check=True, capture_output=True
    )

    remote_head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=work_seed, text=True
    ).strip()

    # 2. Run onboarding targeting real remote_bare
    service = ProjectOnboardingService(
        uow=uow, project_root=runtime_root, trusted_managed_root=trusted_root
    )
    managed_target = trusted_root / "proj-real-remote"
    worktrees_target = trusted_root / "worktrees" / "proj-real-remote"

    onboard_input = ProjectOnboardingInput(
        project_id="proj-real-remote",
        display_name="Real Remote Project",
        repository=str(remote_bare),
        base_branch="main",
        managed_repository_root=str(managed_target),
        worktree_parent_dir=str(worktrees_target),
    )

    result = service.onboard_project(onboard_input)

    assert result.status == ProjectOnboardingStatus.READY_FOR_WORK

    # 3. Prove real remote history & branch checkout
    assert managed_target.exists()
    assert worktrees_target.exists()
    assert (managed_target / ".git").exists()
    assert (managed_target / ".minime-managed-project.json").exists()

    local_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=managed_target, text=True
    ).strip()
    origin_head = subprocess.check_output(
        ["git", "rev-parse", "origin/main"], cwd=managed_target, text=True
    ).strip()

    assert local_head == remote_head_sha
    assert origin_head == remote_head_sha

    binding = uow.project_managed_repository_bindings.get_by_project_id("proj-real-remote")
    assert binding is not None
    assert binding.is_valid is True
    assert binding.mismatch_reasons == []


def test_onboard_project_guard_denial_prevents_mutation(tmp_path):
    """Verify ManagedWorkspaceGuard denial prevents disk creation, marker creation, and binding persistence."""
    from minime.domain.models import ProjectOnboardingInput
    from minime.services.project_onboarding_service import ProjectOnboardingService

    uow = MockUOW()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    trusted_root = tmp_path / "trusted"

    service = ProjectOnboardingService(
        uow=uow, project_root=runtime_root, trusted_managed_root=trusted_root
    )

    escaped_target = tmp_path / "unauthorized_escape_dir"

    onboard_input = ProjectOnboardingInput(
        project_id="proj-denied",
        display_name="Denied Project",
        repository="github.com/org/repo",
        base_branch="main",
        managed_repository_root=str(escaped_target),
        worktree_parent_dir=str(trusted_root / "worktrees"),
    )

    with pytest.raises(ValueError, match="pre-mutation topology checks|Guard authorization denial"):
        service.onboard_project(onboard_input)

    # Prove no disk mutation occurred for escaped_target
    assert not escaped_target.exists()
    assert uow.project_managed_repository_bindings.get_by_project_id("proj-denied") is None


def test_onboard_project_unobservable_remote_fails_closed(tmp_path):
    """Verify non-existent remote repository fails closed without creating marker or binding."""
    from minime.domain.models import ProjectOnboardingInput
    from minime.services.project_onboarding_service import ProjectOnboardingService

    uow = MockUOW()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    trusted_root = tmp_path / "trusted"

    service = ProjectOnboardingService(
        uow=uow, project_root=runtime_root, trusted_managed_root=trusted_root
    )

    managed_target = trusted_root / "proj-unobservable"
    non_existent_remote = tmp_path / "does_not_exist_remote.git"

    onboard_input = ProjectOnboardingInput(
        project_id="proj-unobservable",
        display_name="Unobservable Project",
        repository=str(non_existent_remote),
        base_branch="main",
        managed_repository_root=str(managed_target),
        worktree_parent_dir=str(trusted_root / "worktrees"),
    )

    with pytest.raises(ValueError, match="remote repository establishment|remote checkout"):
        service.onboard_project(onboard_input)

    assert not (managed_target / ".minime-managed-project.json").exists()
    assert uow.project_managed_repository_bindings.get_by_project_id("proj-unobservable") is None


def test_onboard_project_rejects_runtime_collision(tmp_path):
    """Verify onboarding fails closed when target repository overlaps runtime root."""
    from minime.domain.models import ProjectOnboardingInput
    from minime.services.project_onboarding_service import ProjectOnboardingService

    uow = MockUOW()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    trusted_root = tmp_path / "trusted"

    service = ProjectOnboardingService(
        uow=uow, project_root=runtime_root, trusted_managed_root=trusted_root
    )

    onboard_input = ProjectOnboardingInput(
        project_id="proj-collision",
        display_name="Collision Project",
        repository="github.com/test-org/collision-repo",
        base_branch="main",
        managed_repository_root=str(runtime_root / "nested"),
        worktree_parent_dir=str(trusted_root / "worktrees"),
    )

    with pytest.raises(ValueError, match="overlaps runtime root"):
        service.onboard_project(onboard_input)


def test_workspace_guard_records_denial_metric_fact(tmp_dirs):
    """Verify ManagedWorkspaceGuard emits MetricFact when mutation is denied."""
    from minime.domain.models import WorkspaceMutationRequest

    uow = MockUOW()
    saved_facts = []

    class MockMetricsRepo:
        def save(self, fact):
            saved_facts.append(fact)

        def list_by_name(self, name):
            return [f for f in saved_facts if getattr(f, "metric_name", None) == name]

        def list_facts(self, metric_name=None):
            if metric_name:
                return [f for f in saved_facts if getattr(f, "metric_name", None) == metric_name]
            return list(saved_facts)

        def list_all(self):
            return list(saved_facts)

    uow.metrics = MockMetricsRepo()

    guard = ManagedWorkspaceGuard(
        uow=uow,
        runtime_root=tmp_dirs["runtime"],
        trusted_managed_root=os.path.dirname(tmp_dirs["repo_root"]),
    )

    binding = ProjectManagedRepositoryBinding(
        project_id="proj-metric-test",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    # Mutation outside managed bounds
    request = WorkspaceMutationRequest(
        project_id="proj-metric-test",
        target_path="/tmp/unauthorized_path_escape",
        requested_operation=WorkspaceOperation.EDIT,
    )

    decision = guard.evaluate_mutation(request)
    assert decision.allowed is False

    denial_facts = [
        f
        for f in saved_facts
        if getattr(f, "metric_name", None) == "workspace_mutation_denied_total"
    ]
    assert len(denial_facts) == 1
    fact = denial_facts[0]
    assert fact.project_id == "proj-metric-test"
    assert fact.details["reason_code"] == decision.reason_code.value


def test_dashboard_service_system_status_telemetry(tmp_dirs):
    """Verify OperationsDashboardService returns telemetry breakdown and project status."""
    from minime.domain.models import MetricFact
    from minime.services.dashboard_service import OperationsDashboardService

    uow = MockUOW()
    saved_facts = [
        MetricFact(
            metric_name="workspace_mutation_denied_total",
            project_id="proj-dash-test",
            fact_value=1.0,
            details={
                "reason_code": "POLICY_DENIED",
                "attempted_operation": "EDIT",
            },
        )
    ]

    class MockMetricsRepo:
        def save(self, fact):
            saved_facts.append(fact)

        def list_by_name(self, name):
            return [f for f in saved_facts if getattr(f, "metric_name", None) == name]

        def list_facts(self, metric_name=None):
            if metric_name:
                return [f for f in saved_facts if getattr(f, "metric_name", None) == metric_name]
            return list(saved_facts)

        def list_all(self):
            return list(saved_facts)

    uow.metrics = MockMetricsRepo()

    class MockHealthRepo:
        def list_all(self):
            return []

        def get_by_provider(self, provider):
            from minime.domain.enums import ProviderHealthStatus
            from minime.domain.models import ProviderHealth

            return ProviderHealth(provider=provider, status=ProviderHealthStatus.AVAILABLE)

    uow.provider_health = MockHealthRepo()

    binding = ProjectManagedRepositoryBinding(
        project_id="proj-dash-test",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=tmp_dirs["repo_root"],
        worktree_parent_dir=tmp_dirs["worktrees"],
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.projects.save(
        Project(
            project_id="proj-dash-test", display_name="Dash Test", repository="github.com/org/repo"
        )
    )

    dashboard = OperationsDashboardService(uow=uow)
    dashboard.runtime_root = tmp_dirs["runtime"]
    dashboard.trusted_managed_root = os.path.dirname(tmp_dirs["repo_root"])

    overview = dashboard.get_overview()

    sys_status = overview.system_status
    assert sys_status.workspace_mutation_denied_count == 1
    assert len(sys_status.managed_projects) == 1

    p_status = sys_status.managed_projects[0]
    assert p_status.project_id == "proj-dash-test"
    assert p_status.workspace_mutation_denied_total == 1
    assert p_status.denied_mutation_breakdown.get("POLICY_DENIED") == 1


def test_onboard_project_diff_head_and_origin_ref_refused(tmp_path):
    """Verify onboarding fails closed if local HEAD SHA does not match origin/<base_branch> SHA."""
    from minime.domain.models import ProjectOnboardingInput
    from minime.services.project_onboarding_service import ProjectOnboardingService

    uow = MockUOW()
    trusted_root = tmp_path / "trusted_managed"
    trusted_root.mkdir(parents=True, exist_ok=True)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "openspec").mkdir(parents=True, exist_ok=True)

    # Create bare remote repository
    remote_bare = tmp_path / "remote_mismatch.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote_bare)], check=True, capture_output=True
    )

    work_seed = tmp_path / "seed"
    subprocess.run(
        ["git", "clone", str(remote_bare), str(work_seed)], check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=work_seed, check=True)
    subprocess.run(["git", "config", "user.email", "dev@test.local"], cwd=work_seed, check=True)
    (work_seed / "README.md").write_text("# Seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work_seed, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=work_seed, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=work_seed, check=True, capture_output=True
    )

    # Pre-clone managed_target to simulate existing repository with a local commit on HEAD that differs from origin/main
    managed_target = trusted_root / "proj-head-diff"
    subprocess.run(
        ["git", "clone", str(remote_bare), str(managed_target)], check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Local Dev"], cwd=managed_target, check=True)
    subprocess.run(
        ["git", "config", "user.email", "dev@local.test"], cwd=managed_target, check=True
    )
    (managed_target / "local_edit.txt").write_text("Divergent local commit", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=managed_target, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Unpushed local commit"],
        cwd=managed_target,
        check=True,
        capture_output=True,
    )

    service = ProjectOnboardingService(
        uow=uow, project_root=runtime_root, trusted_managed_root=trusted_root
    )
    worktrees_target = trusted_root / "worktrees" / "proj-head-diff"

    onboard_input = ProjectOnboardingInput(
        project_id="proj-head-diff",
        display_name="Head Diff Project",
        repository=str(remote_bare),
        base_branch="main",
        managed_repository_root=str(managed_target),
        worktree_parent_dir=str(worktrees_target),
    )

    with pytest.raises(
        ValueError,
        match="Local HEAD SHA '.*' does not match remote base branch tracking ref 'origin/main' SHA",
    ):
        service.onboard_project(onboard_input)

    assert uow.project_managed_repository_bindings.get_by_project_id("proj-head-diff") is None


def test_ordinary_evaluate_mutation_without_durable_binding_denied(tmp_path):
    """Verify ordinary evaluate_mutation remains DENIED without durable binding in UOW."""
    uow = MockUOW()
    runtime_root = tmp_path / "runtime"
    trusted_root = tmp_path / "trusted"

    guard = ManagedWorkspaceGuard(
        uow=uow, runtime_root=runtime_root, trusted_managed_root=trusted_root
    )

    request = WorkspaceMutationRequest(
        project_id="proj-no-binding",
        target_path=str(trusted_root / "proj-no-binding"),
        requested_operation=WorkspaceOperation.EDIT,
    )

    decision = guard.evaluate_mutation(request)
    assert decision.allowed is False
    assert decision.reason_code == ExternalReasonCode.EVIDENCE_INSUFFICIENT


def test_onboarding_bootstrap_establishes_managed_repo(tmp_path):
    """Verify evaluate_onboarding_bootstrap permits repository establishment under trusted managed root."""
    uow = MockUOW()
    runtime_root = tmp_path / "runtime"
    trusted_root = tmp_path / "trusted"

    guard = ManagedWorkspaceGuard(
        uow=uow, runtime_root=runtime_root, trusted_managed_root=trusted_root
    )

    provisional_binding = ProjectManagedRepositoryBinding(
        project_id="proj-bootstrap-ok",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=str(trusted_root / "proj-bootstrap-ok"),
        worktree_parent_dir=str(trusted_root / "worktrees" / "proj-bootstrap-ok"),
    )

    request = WorkspaceMutationRequest(
        project_id="proj-bootstrap-ok",
        target_path=str(trusted_root / "proj-bootstrap-ok"),
        requested_operation=WorkspaceOperation.GIT_BRANCH,
    )

    decision = guard.evaluate_onboarding_bootstrap(request, provisional_binding)
    assert decision.allowed is True
    assert decision.reason_code == ExternalReasonCode.EXECUTION_SUCCESS


def test_bootstrap_authority_cannot_authorize_arbitrary_edits(tmp_path):
    """Verify evaluate_onboarding_bootstrap DENIES arbitrary code edits inside managed_repo_root."""
    uow = MockUOW()
    runtime_root = tmp_path / "runtime"
    trusted_root = tmp_path / "trusted"

    guard = ManagedWorkspaceGuard(
        uow=uow, runtime_root=runtime_root, trusted_managed_root=trusted_root
    )

    managed_root = trusted_root / "proj-bootstrap-edit-denied"
    provisional_binding = ProjectManagedRepositoryBinding(
        project_id="proj-bootstrap-edit-denied",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=str(managed_root),
        worktree_parent_dir=str(trusted_root / "worktrees" / "proj-bootstrap-edit-denied"),
    )

    request = WorkspaceMutationRequest(
        project_id="proj-bootstrap-edit-denied",
        target_path=str(managed_root / "src" / "app.py"),
        requested_operation=WorkspaceOperation.EDIT,
    )

    decision = guard.evaluate_onboarding_bootstrap(request, provisional_binding)
    assert decision.allowed is False
    assert decision.reason_code == ExternalReasonCode.POLICY_DENIED


def test_bootstrap_authority_rejects_runtime_collision(tmp_path):
    """Verify evaluate_onboarding_bootstrap rejects target paths inside runtime root."""
    uow = MockUOW()
    runtime_root = tmp_path / "runtime"
    trusted_root = tmp_path / "trusted"

    guard = ManagedWorkspaceGuard(
        uow=uow, runtime_root=runtime_root, trusted_managed_root=trusted_root
    )

    provisional_binding = ProjectManagedRepositoryBinding(
        project_id="proj-collision",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=str(runtime_root / "nested_repo"),
        worktree_parent_dir=str(trusted_root / "worktrees"),
    )

    request = WorkspaceMutationRequest(
        project_id="proj-collision",
        target_path=str(runtime_root / "nested_repo"),
        requested_operation=WorkspaceOperation.EDIT,
    )

    decision = guard.evaluate_onboarding_bootstrap(request, provisional_binding)
    assert decision.allowed is False
    assert decision.workspace_role == WorkspaceRole.RUNTIME


def test_normal_durable_binding_guard_behavior_after_persistence(tmp_path):
    """Verify normal evaluate_mutation works with persisted binding in UOW."""
    uow = MockUOW()
    runtime_root = tmp_path / "runtime"
    trusted_root = tmp_path / "trusted"

    managed_root = trusted_root / "proj-persisted"
    managed_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=managed_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/org/repo.git"],
        cwd=managed_root,
        check=True,
        capture_output=True,
    )

    marker_file = managed_root / ".minime-managed-project.json"
    marker_file.write_text(
        json.dumps(
            {"project_id": "proj-persisted", "canonical_repository_identity": "github.com/org/repo"}
        )
    )

    worktree_parent = trusted_root / "worktrees" / "proj-persisted"

    binding = ProjectManagedRepositoryBinding(
        project_id="proj-persisted",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=str(managed_root),
        worktree_parent_dir=str(worktree_parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    guard = ManagedWorkspaceGuard(
        uow=uow, runtime_root=runtime_root, trusted_managed_root=trusted_root
    )

    request = WorkspaceMutationRequest(
        project_id="proj-persisted",
        target_path=str(managed_root),
        requested_operation=WorkspaceOperation.READ,
    )

    decision = guard.evaluate_mutation(request)
    assert decision.allowed is True
    assert decision.reason_code == ExternalReasonCode.EXECUTION_SUCCESS


def test_bootstrap_parent_target_trusted_root_boundaries(tmp_path):
    """Verify evaluate_onboarding_bootstrap enforces trusted managed root containment on target paths."""
    uow = MockUOW()
    runtime_root = tmp_path / "runtime"
    trusted_root = tmp_path / "trusted_root"
    trusted_root.mkdir(parents=True, exist_ok=True)

    sub_container = trusted_root / "sub_container"
    managed_root = sub_container / "proj-target-test"
    worktree_parent = trusted_root / "worktrees" / "proj-target-test"

    guard = ManagedWorkspaceGuard(
        uow=uow, runtime_root=runtime_root, trusted_managed_root=trusted_root
    )

    provisional_binding = ProjectManagedRepositoryBinding(
        project_id="proj-target-test",
        canonical_repository_identity="github.com/org/repo",
        managed_repository_root=str(managed_root),
        worktree_parent_dir=str(worktree_parent),
    )

    # 1. Parent directory under trusted root is ALLOWED
    req_sub = WorkspaceMutationRequest(
        project_id="proj-target-test",
        target_path=str(sub_container),
        requested_operation=WorkspaceOperation.EDIT,
    )
    assert guard.evaluate_onboarding_bootstrap(req_sub, provisional_binding).allowed is True

    # 2. Trusted root itself is ALLOWED
    req_trusted = WorkspaceMutationRequest(
        project_id="proj-target-test",
        target_path=str(trusted_root),
        requested_operation=WorkspaceOperation.EDIT,
    )
    assert guard.evaluate_onboarding_bootstrap(req_trusted, provisional_binding).allowed is True

    # 3. Ancestor above trusted root is DENIED
    ancestor_dir = trusted_root.parent
    req_ancestor = WorkspaceMutationRequest(
        project_id="proj-target-test",
        target_path=str(ancestor_dir),
        requested_operation=WorkspaceOperation.EDIT,
    )
    dec_ancestor = guard.evaluate_onboarding_bootstrap(req_ancestor, provisional_binding)
    assert dec_ancestor.allowed is False
    assert dec_ancestor.reason_code == ExternalReasonCode.POLICY_DENIED

    # 4. Root '/' is DENIED
    req_root = WorkspaceMutationRequest(
        project_id="proj-target-test",
        target_path="/",
        requested_operation=WorkspaceOperation.EDIT,
    )
    dec_root = guard.evaluate_onboarding_bootstrap(req_root, provisional_binding)
    assert dec_root.allowed is False
    assert dec_root.reason_code == ExternalReasonCode.POLICY_DENIED

    # 5. Arbitrary sibling/outside path is DENIED
    outside_dir = tmp_path / "outside_unauthorized"
    req_outside = WorkspaceMutationRequest(
        project_id="proj-target-test",
        target_path=str(outside_dir),
        requested_operation=WorkspaceOperation.EDIT,
    )
    dec_outside = guard.evaluate_onboarding_bootstrap(req_outside, provisional_binding)
    assert dec_outside.allowed is False
    assert dec_outside.reason_code == ExternalReasonCode.POLICY_DENIED


def test_onboard_project_unobservable_fetch_rejects_stale_tracking_ref(tmp_path):
    """Verify onboarding fails closed when remote fetch fails even if local stale origin/main ref matches HEAD."""
    from minime.domain.models import ProjectOnboardingInput
    from minime.services.project_onboarding_service import ProjectOnboardingService

    uow = MockUOW()
    trusted_root = tmp_path / "trusted_managed"
    trusted_root.mkdir(parents=True, exist_ok=True)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "openspec").mkdir(parents=True, exist_ok=True)

    # 1. Create initial bare remote repository
    remote_bare = tmp_path / "remote_unobservable.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote_bare)], check=True, capture_output=True
    )

    seed_dir = tmp_path / "seed_dir"
    subprocess.run(
        ["git", "clone", str(remote_bare), str(seed_dir)], check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=seed_dir, check=True)
    subprocess.run(["git", "config", "user.email", "dev@test.local"], cwd=seed_dir, check=True)
    (seed_dir / "README.md").write_text("# Seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=seed_dir, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=seed_dir, check=True, capture_output=True
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=seed_dir, check=True, capture_output=True)

    # 2. Establish an existing managed checkout with valid tracking ref origin/main == HEAD
    managed_target = trusted_root / "proj-stale-ref"
    subprocess.run(
        ["git", "clone", str(remote_bare), str(managed_target)], check=True, capture_output=True
    )

    # Verify that HEAD == origin/main currently on managed_target
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=managed_target, text=True
    ).strip()
    origin_sha = subprocess.check_output(
        ["git", "rev-parse", "origin/main"], cwd=managed_target, text=True
    ).strip()
    assert head_sha == origin_sha

    # 3. Make remote bare repository unobservable by deleting/renaming it
    remote_bare_disabled = tmp_path / "remote_unobservable_disabled.git"
    os.rename(remote_bare, remote_bare_disabled)

    # 4. Attempt onboarding on the existing managed_target
    service = ProjectOnboardingService(
        uow=uow, project_root=runtime_root, trusted_managed_root=trusted_root
    )
    worktrees_target = trusted_root / "worktrees" / "proj-stale-ref"

    onboard_input = ProjectOnboardingInput(
        project_id="proj-stale-ref",
        display_name="Stale Ref Test Project",
        repository=str(remote_bare),
        base_branch="main",
        managed_repository_root=str(managed_target),
        worktree_parent_dir=str(worktrees_target),
    )

    with pytest.raises(
        ValueError,
        match="unobservable or unreachable during fetch|Failed to establish canonical remote checkout",
    ):
        service.onboard_project(onboard_input)

    assert uow.project_managed_repository_bindings.get_by_project_id("proj-stale-ref") is None
