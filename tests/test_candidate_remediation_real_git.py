"""Real-Git remediation lifecycle acceptance."""

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from minime.domain.enums import (
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    RemediationFailureCode,
    RemediationStatus,
)
from minime.domain.models import (
    CandidateRemediation,
    Job,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
    RemediationContract,
)
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.candidate_remediation import CandidateRemediationService, RemediationError
from minime.services.checks_runner import ChecksRunner
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.worktree_manager import WorktreeManager


class FakeImplementer:
    def __init__(self):
        self.calls = 0

    async def run(self, worktree_path, prompt_context, timeout_seconds):
        self.calls += 1
        (worktree_path / "src").mkdir()
        (worktree_path / "src" / "fix.py").write_text("fixed = True\n", encoding="utf-8")
        return SimpleNamespace(exit_code=0)


class InMemoryRemediationRepository:
    def __init__(self):
        self.items = {}

    def save(self, remediation):
        self.items[remediation.remediation_id] = remediation.model_copy(deep=True)

    def get_by_identity(self, run_id, source_generation, source_candidate_sha, contract_hash):
        return next(
            (
                item.model_copy(deep=True)
                for item in self.items.values()
                if (
                    item.run_id,
                    item.source_generation,
                    item.source_candidate_sha,
                    item.contract_hash,
                )
                == (run_id, source_generation, source_candidate_sha, contract_hash)
            ),
            None,
        )


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def test_real_git_remediation_creates_preserved_next_generation(tmp_path, in_memory_uow):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    project = Project(
        project_id="p",
        display_name="p",
        repository=str(tmp_path),
        checks=[{"name": "fail", "command": "false"}, {"name": "later", "command": "true"}],
    )
    in_memory_uow.candidate_remediations = InMemoryRemediationRepository()
    in_memory_uow.projects.save(project)
    job = Job(
        project_id="p",
        change_name="change",
        implementer_role="codex",
        status=JobStatus.NEEDS_HUMAN,
        candidate_sha=source_sha,
        base_sha=source_sha,
    )
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, source_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    source = OrchestrationCandidate(
        run_id="run",
        generation=1,
        base_sha=source_sha,
        candidate_sha=source_sha,
        candidate_ref="refs/heads/main",
        manifest_id=manifest.manifest_id,
        manifest_hash=manifest.manifest_hash,
    )
    in_memory_uow.orchestration_candidates.save(source)
    run = OrchestrationRun(
        project_id="p",
        change_name="change",
        base_sha=source_sha,
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        active_job_id=job.job_id,
        current_candidate_sha=source_sha,
    )
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    implementer = FakeImplementer()
    pipeline = SimpleNamespace(
        implementer_runner=implementer,
        checks_runner=__import__(
            "minime.services.checks_runner", fromlist=["ChecksRunner"]
        ).ChecksRunner(),
    )
    service = CandidateRemediationService(
        in_memory_uow,
        tmp_path,
        pipeline=pipeline,
        worktree_manager=WorktreeManager(tmp_path, uow=in_memory_uow),
    )
    contract = RemediationContract(
        contract_version="1",
        run_id="run",
        source_candidate_generation=1,
        source_candidate_sha=source_sha,
        source_candidate_base_sha=source_sha,
        change_name="change",
        objective="fix",
        allowed_paths=["src/fix.py"],
        required_outcomes=["checks"],
        verification_commands=["pytest"],
        stop_conditions=["scope"],
    )
    result = service.remediate("run", contract)
    assert result.status == RemediationStatus.CHECKS_FAILED
    assert implementer.calls == 1
    assert git(tmp_path, "rev-parse", source_sha) == source_sha
    candidates = in_memory_uow.orchestration_candidates.list_by_run("run")
    assert [candidate.generation for candidate in candidates] == [1, 2]
    assert candidates[0].superseded_by_id == candidates[1].candidate_id
    assert in_memory_uow.orchestration_runs.get_by_id("run").base_sha == source_sha
    assert len(in_memory_uow.check_results.list_by_job(job.job_id)) == 2
    replay = service.remediate("run", contract)
    assert replay.remediation_id == result.remediation_id
    assert implementer.calls == 1


def test_real_git_restart_after_workspace_ready_preserves_execution_boundary(
    tmp_path, in_memory_uow
):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True)
    project = Project(project_id="p", display_name="p", repository=str(tmp_path))
    in_memory_uow.candidate_remediations = InMemoryRemediationRepository()
    in_memory_uow.projects.save(project)
    job = Job(
        project_id="p", change_name="change", implementer_role="codex",
        status=JobStatus.NEEDS_HUMAN, candidate_sha=source_sha, base_sha=source_sha,
    )
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, source_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    source = OrchestrationCandidate(
        run_id="run", generation=1, base_sha=source_sha, candidate_sha=source_sha,
        candidate_ref="refs/heads/main", manifest_id=manifest.manifest_id,
        manifest_hash=manifest.manifest_hash,
    )
    in_memory_uow.orchestration_candidates.save(source)
    run = OrchestrationRun(
        project_id="p", change_name="change", base_sha=source_sha,
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN,
        active_job_id=job.job_id, current_candidate_sha=source_sha,
    )
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    manager = WorktreeManager(tmp_path, uow=in_memory_uow)
    workspace = asyncio.run(
        manager.create_remediation_worktree(job.job_id, "change", source_sha, 2, project_id="p")
    )
    contract = RemediationContract(
        contract_version="1", run_id="run", source_candidate_generation=1,
        source_candidate_sha=source_sha, source_candidate_base_sha=source_sha,
        change_name="change", objective="fix", allowed_paths=["src/fix.py"],
    )
    remediation = CandidateRemediation(
        run_id="run", job_id=job.job_id, source_candidate_id=source.candidate_id,
        source_generation=1, source_candidate_sha=source_sha, source_base_sha=source_sha,
        contract_version=contract.contract_version, contract_hash=contract.contract_hash(),
        contract_payload=contract.canonical_payload(), status=RemediationStatus.WORKSPACE_READY,
        workspace_path=str(workspace.path), branch_name=workspace.branch_name,
        authorized_paths=contract.allowed_paths,
    )
    in_memory_uow.candidate_remediations.save(remediation)
    implementer = FakeImplementer()
    service = CandidateRemediationService(
        in_memory_uow,
        tmp_path,
        pipeline=SimpleNamespace(implementer_runner=implementer, checks_runner=ChecksRunner()),
        worktree_manager=manager,
    )
    result = service.remediate("run", contract)
    assert result.remediation_id == remediation.remediation_id
    assert result.status == RemediationStatus.COMPLETED
    assert implementer.calls == 1
    assert (workspace.path / "README.md").read_text(encoding="utf-8") == "source\n"


def test_real_git_restart_during_implementer_running_refuses_duplicate_invocation(
    tmp_path, in_memory_uow
):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True)
    project = Project(project_id="p", display_name="p", repository=str(tmp_path))
    in_memory_uow.candidate_remediations = InMemoryRemediationRepository()
    in_memory_uow.projects.save(project)
    job = Job(
        project_id="p", change_name="change", implementer_role="codex",
        status=JobStatus.NEEDS_HUMAN, candidate_sha=source_sha, base_sha=source_sha,
    )
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, source_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    source = OrchestrationCandidate(
        run_id="run", generation=1, base_sha=source_sha, candidate_sha=source_sha,
        candidate_ref="refs/heads/main", manifest_id=manifest.manifest_id,
        manifest_hash=manifest.manifest_hash,
    )
    in_memory_uow.orchestration_candidates.save(source)
    run = OrchestrationRun(
        project_id="p", change_name="change", base_sha=source_sha,
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN,
        active_job_id=job.job_id, current_candidate_sha=source_sha,
    )
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    manager = WorktreeManager(tmp_path, uow=in_memory_uow)
    workspace = asyncio.run(
        manager.create_remediation_worktree(job.job_id, "change", source_sha, 2, project_id="p")
    )
    contract = RemediationContract(
        contract_version="1", run_id="run", source_candidate_generation=1,
        source_candidate_sha=source_sha, source_candidate_base_sha=source_sha,
        change_name="change", objective="fix", allowed_paths=["src/fix.py"],
    )
    remediation = CandidateRemediation(
        run_id="run", job_id=job.job_id, source_candidate_id=source.candidate_id,
        source_generation=1, source_candidate_sha=source_sha, source_base_sha=source_sha,
        contract_version=contract.contract_version, contract_hash=contract.contract_hash(),
        contract_payload=contract.canonical_payload(), status=RemediationStatus.IMPLEMENTER_RUNNING,
        workspace_path=str(workspace.path), branch_name=workspace.branch_name,
        authorized_paths=contract.allowed_paths,
    )
    in_memory_uow.candidate_remediations.save(remediation)
    implementer = FakeImplementer()
    service = CandidateRemediationService(
        in_memory_uow, tmp_path, pipeline=SimpleNamespace(implementer_runner=implementer),
        worktree_manager=manager,
    )
    try:
        service.remediate("run", contract)
    except RemediationError as exc:
        assert exc.code == RemediationFailureCode.PRESERVATION_FAILED
    else:
        raise AssertionError("uncertain implementer execution must fail closed")
    persisted = in_memory_uow.candidate_remediations.get_by_identity(
        "run", 1, source_sha, contract.contract_hash()
    )
    assert persisted.status == RemediationStatus.IMPLEMENTER_RUNNING
    assert implementer.calls == 0
    assert len(in_memory_uow.orchestration_candidates.list_by_run("run")) == 1
    assert (workspace.path / "README.md").read_text(encoding="utf-8") == "source\n"


def test_real_git_restart_after_implementer_completed_reuses_authorized_changes(
    tmp_path, in_memory_uow
):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True)
    project = Project(project_id="p", display_name="p", repository=str(tmp_path))
    in_memory_uow.candidate_remediations = InMemoryRemediationRepository()
    in_memory_uow.projects.save(project)
    job = Job(
        project_id="p", change_name="change", implementer_role="codex",
        status=JobStatus.NEEDS_HUMAN, candidate_sha=source_sha, base_sha=source_sha,
    )
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, source_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    source = OrchestrationCandidate(
        run_id="run", generation=1, base_sha=source_sha, candidate_sha=source_sha,
        candidate_ref="refs/heads/main", manifest_id=manifest.manifest_id,
        manifest_hash=manifest.manifest_hash,
    )
    in_memory_uow.orchestration_candidates.save(source)
    run = OrchestrationRun(
        project_id="p", change_name="change", base_sha=source_sha,
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN,
        active_job_id=job.job_id, current_candidate_sha=source_sha,
    )
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    manager = WorktreeManager(tmp_path, uow=in_memory_uow)
    workspace = asyncio.run(
        manager.create_remediation_worktree(job.job_id, "change", source_sha, 2, project_id="p")
    )
    (workspace.path / "src").mkdir()
    (workspace.path / "src" / "fix.py").write_text("fixed = True\n", encoding="utf-8")
    contract = RemediationContract(
        contract_version="1", run_id="run", source_candidate_generation=1,
        source_candidate_sha=source_sha, source_candidate_base_sha=source_sha,
        change_name="change", objective="fix", allowed_paths=["src/fix.py"],
    )
    remediation = CandidateRemediation(
        run_id="run", job_id=job.job_id, source_candidate_id=source.candidate_id,
        source_generation=1, source_candidate_sha=source_sha, source_base_sha=source_sha,
        contract_version=contract.contract_version, contract_hash=contract.contract_hash(),
        contract_payload=contract.canonical_payload(), status=RemediationStatus.IMPLEMENTER_COMPLETED,
        workspace_path=str(workspace.path), branch_name=workspace.branch_name,
        authorized_paths=contract.allowed_paths,
    )
    in_memory_uow.candidate_remediations.save(remediation)
    implementer = FakeImplementer()
    service = CandidateRemediationService(
        in_memory_uow, tmp_path,
        pipeline=SimpleNamespace(implementer_runner=implementer, checks_runner=ChecksRunner()),
        worktree_manager=manager,
    )
    result = service.remediate("run", contract)
    assert result.remediation_id == remediation.remediation_id
    assert result.status == RemediationStatus.COMPLETED
    assert implementer.calls == 0
    assert git(workspace.path, "status", "--porcelain=v1") == ""
    candidates = in_memory_uow.orchestration_candidates.list_by_run("run")
    assert [item.generation for item in candidates] == [1, 2]
    assert (workspace.path / "src" / "fix.py").read_text(encoding="utf-8") == "fixed = True\n"


def test_real_git_restart_after_scope_validated_finalizes_once(tmp_path, in_memory_uow):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True)
    project = Project(project_id="p", display_name="p", repository=str(tmp_path))
    in_memory_uow.candidate_remediations = InMemoryRemediationRepository()
    in_memory_uow.projects.save(project)
    job = Job(project_id="p", change_name="change", implementer_role="codex", status=JobStatus.NEEDS_HUMAN, candidate_sha=source_sha, base_sha=source_sha)
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, source_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    source = OrchestrationCandidate(run_id="run", generation=1, base_sha=source_sha, candidate_sha=source_sha, candidate_ref="refs/heads/main", manifest_id=manifest.manifest_id, manifest_hash=manifest.manifest_hash)
    in_memory_uow.orchestration_candidates.save(source)
    run = OrchestrationRun(project_id="p", change_name="change", base_sha=source_sha, current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW, stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN, active_job_id=job.job_id, current_candidate_sha=source_sha)
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    manager = WorktreeManager(tmp_path, uow=in_memory_uow)
    workspace = asyncio.run(manager.create_remediation_worktree(job.job_id, "change", source_sha, 2, project_id="p"))
    (workspace.path / "src").mkdir()
    (workspace.path / "src" / "fix.py").write_text("fixed = True\n", encoding="utf-8")
    contract = RemediationContract(contract_version="1", run_id="run", source_candidate_generation=1, source_candidate_sha=source_sha, source_candidate_base_sha=source_sha, change_name="change", objective="fix", allowed_paths=["src/fix.py"])
    remediation = CandidateRemediation(run_id="run", job_id=job.job_id, source_candidate_id=source.candidate_id, source_generation=1, source_candidate_sha=source_sha, source_base_sha=source_sha, contract_version=contract.contract_version, contract_hash=contract.contract_hash(), contract_payload=contract.canonical_payload(), status=RemediationStatus.SCOPE_VALIDATED, workspace_path=str(workspace.path), branch_name=workspace.branch_name, authorized_paths=contract.allowed_paths, tree_fingerprint=asyncio.run(manager.working_state_fingerprint(workspace.path)))
    in_memory_uow.candidate_remediations.save(remediation)
    implementer = FakeImplementer()
    service = CandidateRemediationService(in_memory_uow, tmp_path, pipeline=SimpleNamespace(implementer_runner=implementer, checks_runner=ChecksRunner()), worktree_manager=manager)
    result = service.remediate("run", contract)
    assert result.remediation_id == remediation.remediation_id
    assert result.status == RemediationStatus.COMPLETED
    assert implementer.calls == 0
    candidates = in_memory_uow.orchestration_candidates.list_by_run("run")
    assert [item.generation for item in candidates] == [1, 2]


def test_real_git_finalization_crash_reconciles_identity_before_candidate_persistence(
    tmp_path, in_memory_uow
):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True)
    project = Project(project_id="p", display_name="p", repository=str(tmp_path))
    in_memory_uow.candidate_remediations = InMemoryRemediationRepository()
    in_memory_uow.projects.save(project)
    job = Job(project_id="p", change_name="change", implementer_role="codex", status=JobStatus.NEEDS_HUMAN, candidate_sha=source_sha, base_sha=source_sha)
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, source_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    source = OrchestrationCandidate(run_id="run", generation=1, base_sha=source_sha, candidate_sha=source_sha, candidate_ref="refs/heads/main", manifest_id=manifest.manifest_id, manifest_hash=manifest.manifest_hash)
    in_memory_uow.orchestration_candidates.save(source)
    run = OrchestrationRun(project_id="p", change_name="change", base_sha=source_sha, current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW, stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN, active_job_id=job.job_id, current_candidate_sha=source_sha)
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    manager = WorktreeManager(tmp_path, uow=in_memory_uow)
    contract = RemediationContract(contract_version="1", run_id="run", source_candidate_generation=1, source_candidate_sha=source_sha, source_candidate_base_sha=source_sha, change_name="change", objective="fix", allowed_paths=["src/fix.py"])

    original_save = in_memory_uow.orchestration_candidates.save
    crash = {"armed": True}

    def crash_after_result_candidate(candidate):
        if candidate.generation == 2 and crash["armed"]:
            crash["armed"] = False
            raise RuntimeError("simulated process crash before candidate persistence")
        original_save(candidate)

    in_memory_uow.orchestration_candidates.save = crash_after_result_candidate
    first_runner = FakeImplementer()
    first_service = CandidateRemediationService(
        in_memory_uow, tmp_path,
        pipeline=SimpleNamespace(implementer_runner=first_runner, checks_runner=ChecksRunner()),
        worktree_manager=manager,
    )
    with pytest.raises(RuntimeError, match="simulated process crash"):
        first_service.remediate("run", contract)
    in_memory_uow.orchestration_candidates.save = original_save
    assert first_runner.calls == 1
    assert len(in_memory_uow.orchestration_candidates.list_by_run("run")) == 1
    workspace_path = manager.remediation_worktree_path(job.job_id, 2)
    committed_sha = git(workspace_path, "rev-parse", "HEAD")
    assert committed_sha != source_sha
    assert git(workspace_path, "rev-parse", "HEAD^") == source_sha

    second_runner = FakeImplementer()
    second_service = CandidateRemediationService(
        in_memory_uow, tmp_path,
        pipeline=SimpleNamespace(implementer_runner=second_runner, checks_runner=ChecksRunner()),
        worktree_manager=manager,
    )
    result = second_service.remediate("run", contract)
    assert result.status == RemediationStatus.COMPLETED
    assert second_runner.calls == 0
    candidates = in_memory_uow.orchestration_candidates.list_by_run("run")
    assert [item.generation for item in candidates] == [1, 2]
    assert git(workspace_path, "rev-parse", "HEAD") == committed_sha


def test_real_git_reconciliation_rejects_wrong_remediation_trailer(tmp_path, in_memory_uow):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    manager = WorktreeManager(tmp_path, uow=in_memory_uow)
    workspace = asyncio.run(
        manager.create_remediation_worktree("job", "change", source_sha, 2, project_id="p")
    )
    (workspace.path / "src").mkdir()
    (workspace.path / "src" / "fix.py").write_text("fixed = True\n", encoding="utf-8")
    committed_sha = asyncio.run(
        manager.finalize_candidate_commit(
            workspace.path, "job", "p", "remediation-id", "contract-hash"
        )
    )
    subprocess.run(
        ["git", "commit", "--amend", "-m", "untrusted remediation commit"],
        cwd=workspace.path,
        check=True,
        capture_output=True,
    )
    assert git(workspace.path, "rev-parse", "HEAD") != committed_sha
    valid, error = asyncio.run(
        manager.verify_remediation_commit(
            workspace.path,
            source_sha,
            workspace.branch_name,
            "remediation-id",
            "contract-hash",
            ["src/fix.py"],
        )
    )
    assert valid is False
    assert "trailers" in (error or "")


@pytest.mark.parametrize(
    "persisted_status",
    [RemediationStatus.CANDIDATE_PERSISTED, RemediationStatus.CHECKS_RUNNING],
    ids=["candidate-persisted", "checks-running"],
)
def test_real_git_restart_after_candidate_persisted_reuses_exact_result(
    tmp_path, in_memory_uow, persisted_status
):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True)
    project = Project(project_id="p", display_name="p", repository=str(tmp_path))
    in_memory_uow.candidate_remediations = InMemoryRemediationRepository()
    in_memory_uow.projects.save(project)
    job = Job(project_id="p", change_name="change", implementer_role="codex", status=JobStatus.NEEDS_HUMAN, candidate_sha=source_sha, base_sha=source_sha)
    in_memory_uow.jobs.save(job)
    source_manifest = CandidateManifestService().generate_manifest(tmp_path, source_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(source_manifest)
    source = OrchestrationCandidate(run_id="run", generation=1, base_sha=source_sha, candidate_sha=source_sha, candidate_ref="refs/heads/main", manifest_id=source_manifest.manifest_id, manifest_hash=source_manifest.manifest_hash)
    in_memory_uow.orchestration_candidates.save(source)
    run = OrchestrationRun(project_id="p", change_name="change", base_sha=source_sha, current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW, stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN, active_job_id=job.job_id, current_generation=2, current_candidate_sha="")
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    manager = WorktreeManager(tmp_path, uow=in_memory_uow)
    workspace = asyncio.run(manager.create_remediation_worktree(job.job_id, "change", source_sha, 2, project_id="p"))
    (workspace.path / "src").mkdir()
    (workspace.path / "src" / "fix.py").write_text("fixed = True\n", encoding="utf-8")
    contract = RemediationContract(contract_version="1", run_id="run", source_candidate_generation=1, source_candidate_sha=source_sha, source_candidate_base_sha=source_sha, change_name="change", objective="fix", allowed_paths=["src/fix.py"])
    remediation_id = "remediation-k1"
    result_sha = asyncio.run(manager.finalize_candidate_commit(workspace.path, job.job_id, "p", remediation_id, contract.contract_hash()))
    result_manifest = CandidateManifestService().generate_manifest(workspace.path, result_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(result_manifest)
    result_candidate = OrchestrationCandidate(run_id="run", generation=2, base_sha=source_sha, candidate_sha=result_sha, candidate_ref=workspace.branch_name, manifest_id=result_manifest.manifest_id, manifest_hash=result_manifest.manifest_hash, authorship_summary={"remediation_id": remediation_id}, is_frozen=True)
    in_memory_uow.orchestration_candidates.save(result_candidate)
    in_memory_uow.orchestration_candidates.supersede(source.candidate_id, result_candidate.candidate_id)
    job.candidate_sha = result_sha
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.update_candidate_binding("run", 2, result_sha)
    remediation = CandidateRemediation(remediation_id=remediation_id, run_id="run", job_id=job.job_id, source_candidate_id=source.candidate_id, source_generation=1, source_candidate_sha=source_sha, source_base_sha=source_sha, contract_version=contract.contract_version, contract_hash=contract.contract_hash(), contract_payload=contract.canonical_payload(), status=persisted_status, workspace_path=str(workspace.path), branch_name=workspace.branch_name, authorized_paths=contract.allowed_paths, result_candidate_id=result_candidate.candidate_id, result_generation=2, result_candidate_sha=result_sha)
    in_memory_uow.candidate_remediations.save(remediation)
    restarted_runner = FakeImplementer()
    restarted = CandidateRemediationService(in_memory_uow, tmp_path, pipeline=SimpleNamespace(implementer_runner=restarted_runner, checks_runner=ChecksRunner()), worktree_manager=manager)
    result = restarted.remediate("run", contract)
    assert result.remediation_id == remediation.remediation_id
    assert result.status == RemediationStatus.COMPLETED
    assert restarted_runner.calls == 0
    assert git(workspace.path, "rev-parse", "HEAD") == result_sha
    candidates = in_memory_uow.orchestration_candidates.list_by_run("run")
    assert len(candidates) == 2
    assert in_memory_uow.orchestration_runs.get_by_id("run").current_candidate_sha == result_sha


class PathImplementer:
    def __init__(self, relative_path):
        self.relative_path = relative_path
        self.calls = 0

    async def run(self, worktree_path, prompt_context, timeout_seconds):
        self.calls += 1
        path = worktree_path / self.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unauthorized\n", encoding="utf-8")
        return SimpleNamespace(exit_code=0)


class SequentialImplementer:
    def __init__(self):
        self.calls = 0

    async def run(self, worktree_path, prompt_context, timeout_seconds):
        self.calls += 1
        path = worktree_path / "src" / f"fix{self.calls}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"generation = {self.calls}\n", encoding="utf-8")
        return SimpleNamespace(exit_code=0)


@pytest.mark.parametrize(
    ("target", "protected_paths"),
    [("src/secret.py", ["src/secret.py"]), ("docs/outside.md", [])],
    ids=["protected-path", "outside-allowlist"],
)
def test_real_git_scope_violation_fails_without_candidate_or_commit(
    tmp_path, in_memory_uow, target, protected_paths
):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True)
    project = Project(project_id="p", display_name="p", repository=str(tmp_path), checks=[])
    in_memory_uow.candidate_remediations = InMemoryRemediationRepository()
    in_memory_uow.projects.save(project)
    job = Job(project_id="p", change_name="change", implementer_role="codex", status=JobStatus.NEEDS_HUMAN, candidate_sha=source_sha, base_sha=source_sha)
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, source_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    source = OrchestrationCandidate(run_id="run", generation=1, base_sha=source_sha, candidate_sha=source_sha, candidate_ref="refs/heads/main", manifest_id=manifest.manifest_id, manifest_hash=manifest.manifest_hash)
    in_memory_uow.orchestration_candidates.save(source)
    run = OrchestrationRun(project_id="p", change_name="change", base_sha=source_sha, current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW, stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN, active_job_id=job.job_id, current_candidate_sha=source_sha)
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    contract = RemediationContract(contract_version="1", run_id="run", source_candidate_generation=1, source_candidate_sha=source_sha, source_candidate_base_sha=source_sha, change_name="change", objective="fix", allowed_paths=["src/fix.py"], protected_paths=protected_paths)
    implementer = PathImplementer(target)
    manager = WorktreeManager(tmp_path, uow=in_memory_uow)
    service = CandidateRemediationService(in_memory_uow, tmp_path, pipeline=SimpleNamespace(implementer_runner=implementer, checks_runner=ChecksRunner()), worktree_manager=manager)
    with pytest.raises(RemediationError) as exc_info:
        service.remediate("run", contract)
    assert exc_info.value.code == RemediationFailureCode.SCOPE_VIOLATION
    assert implementer.calls == 1
    assert len(in_memory_uow.orchestration_candidates.list_by_run("run")) == 1
    assert git(tmp_path, "rev-parse", "HEAD") == source_sha
    persisted = in_memory_uow.candidate_remediations.get_by_identity("run", 1, source_sha, contract.contract_hash())
    assert persisted.status == RemediationStatus.SCOPE_FAILED
    assert target in persisted.failure_reason


def test_real_execution_pipeline_routes_remediation_to_its_implementer_runner(
    tmp_path, in_memory_uow
):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True)
    project = Project(project_id="p", display_name="p", repository=str(tmp_path), checks=[])
    in_memory_uow.candidate_remediations = InMemoryRemediationRepository()
    in_memory_uow.projects.save(project)
    job = Job(project_id="p", change_name="change", implementer_role="codex", status=JobStatus.NEEDS_HUMAN, candidate_sha=source_sha, base_sha=source_sha)
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, source_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    source = OrchestrationCandidate(run_id="run", generation=1, base_sha=source_sha, candidate_sha=source_sha, candidate_ref="refs/heads/main", manifest_id=manifest.manifest_id, manifest_hash=manifest.manifest_hash)
    in_memory_uow.orchestration_candidates.save(source)
    run = OrchestrationRun(project_id="p", change_name="change", base_sha=source_sha, current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW, stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN, active_job_id=job.job_id, current_candidate_sha=source_sha)
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    fake_runner = PathImplementer("src/pipeline-fix.py")
    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=tmp_path,
        implementer_runner=fake_runner,
        checks_runner=ChecksRunner(),
    )
    manager = WorktreeManager(tmp_path, uow=in_memory_uow)
    service = CandidateRemediationService(in_memory_uow, tmp_path, pipeline=pipeline, worktree_manager=manager)
    contract = RemediationContract(contract_version="1", run_id="run", source_candidate_generation=1, source_candidate_sha=source_sha, source_candidate_base_sha=source_sha, change_name="change", objective="fix", allowed_paths=["src/pipeline-fix.py"])
    result = service.remediate("run", contract)
    assert result.status == RemediationStatus.COMPLETED
    assert pipeline.implementer_runner is fake_runner
    assert fake_runner.calls == 1


def test_real_git_failed_n_plus_one_then_explicit_n_plus_two_preserves_lineage(
    tmp_path, in_memory_uow
):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True)
    project = Project(project_id="p", display_name="p", repository=str(tmp_path), checks=[{"name": "fail", "command": "false"}, {"name": "later", "command": "true"}])
    in_memory_uow.candidate_remediations = InMemoryRemediationRepository()
    in_memory_uow.projects.save(project)
    job = Job(project_id="p", change_name="change", implementer_role="codex", status=JobStatus.NEEDS_HUMAN, candidate_sha=source_sha, base_sha=source_sha)
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, source_sha, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    source = OrchestrationCandidate(run_id="run", generation=1, base_sha=source_sha, candidate_sha=source_sha, candidate_ref="refs/heads/main", manifest_id=manifest.manifest_id, manifest_hash=manifest.manifest_hash)
    in_memory_uow.orchestration_candidates.save(source)
    run = OrchestrationRun(project_id="p", change_name="change", base_sha=source_sha, current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW, stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN, active_job_id=job.job_id, current_candidate_sha=source_sha)
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    manager = WorktreeManager(tmp_path, uow=in_memory_uow)
    implementer = SequentialImplementer()
    service = CandidateRemediationService(in_memory_uow, tmp_path, pipeline=SimpleNamespace(implementer_runner=implementer, checks_runner=ChecksRunner()), worktree_manager=manager)
    contract1 = RemediationContract(contract_version="1", run_id="run", source_candidate_generation=1, source_candidate_sha=source_sha, source_candidate_base_sha=source_sha, change_name="change", objective="fix one", allowed_paths=["src/fix1.py"])
    first = service.remediate("run", contract1)
    assert first.status == RemediationStatus.CHECKS_FAILED
    candidates_after_first = in_memory_uow.orchestration_candidates.list_by_run("run")
    n_plus_one = next(item for item in candidates_after_first if item.generation == 2)
    n_plus_one_identity = (n_plus_one.candidate_sha, n_plus_one.candidate_ref, n_plus_one.manifest_id, n_plus_one.manifest_hash, n_plus_one.base_sha)
    project.checks = [{"name": "pass", "command": "true"}]
    in_memory_uow.projects.save(project)
    contract2 = RemediationContract(contract_version="1", run_id="run", source_candidate_generation=2, source_candidate_sha=n_plus_one.candidate_sha, source_candidate_base_sha=n_plus_one.base_sha, change_name="change", objective="fix two", allowed_paths=["src/fix2.py"])
    second = service.remediate("run", contract2)
    assert second.status == RemediationStatus.COMPLETED
    candidates = in_memory_uow.orchestration_candidates.list_by_run("run")
    n_plus_two = next(item for item in candidates if item.generation == 3)
    source = in_memory_uow.orchestration_candidates.get_by_id(source.candidate_id)
    n_plus_one = in_memory_uow.orchestration_candidates.get_by_id(n_plus_one.candidate_id)
    run = in_memory_uow.orchestration_runs.get_by_id("run")
    job = in_memory_uow.jobs.get_by_id(job.job_id)
    assert (source.candidate_sha, source.candidate_ref, source.manifest_id, source.manifest_hash, source.base_sha) == (source_sha, "refs/heads/main", manifest.manifest_id, manifest.manifest_hash, source_sha)
    assert (n_plus_one.candidate_sha, n_plus_one.candidate_ref, n_plus_one.manifest_id, n_plus_one.manifest_hash, n_plus_one.base_sha) == n_plus_one_identity
    assert source.superseded_by_id == n_plus_one.candidate_id
    assert n_plus_one.superseded_by_id == n_plus_two.candidate_id
    assert len([item for item in candidates if not item.superseded_by_id]) == 1
    assert run.current_generation == 3
    assert run.current_candidate_sha == n_plus_two.candidate_sha
    assert job.candidate_sha == n_plus_two.candidate_sha
    assert job.base_sha == n_plus_two.base_sha
    assert implementer.calls == 2
