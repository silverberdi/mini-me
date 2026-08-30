"""Adversarial durable-authority tests for preserved-candidate remediation."""

import subprocess
from types import SimpleNamespace

import pytest

from minime.domain.enums import HumanGate, JobStatus, OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import (
    Job,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
    RemediationContract,
)
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.candidate_remediation import CandidateRemediationService, RemediationError


class DurableMemory:
    def __init__(self):
        self.items = {}
        self.calls = 0

    def save(self, item):
        self.items[item.remediation_id] = item.model_copy(deep=True)

    def get_by_identity(self, run_id, source_generation, source_candidate_sha, contract_hash):
        self.calls += 1
        return next((item for item in self.items.values() if (item.run_id, item.source_generation, item.source_candidate_sha, item.contract_hash) == (run_id, source_generation, source_candidate_sha, contract_hash)), None)


class NoCallManager:
    def __init__(self):
        self.calls = 0

    async def create_remediation_worktree(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("worktree must not be created")


def stopped_run(uow, *, candidates=()):
    project = Project(project_id="p", display_name="p", repository="/tmp/repo")
    uow.projects.save(project)
    job = Job(project_id="p", change_name="change", implementer_role="codex", status=JobStatus.NEEDS_HUMAN, candidate_sha="a" * 40, base_sha="b" * 40)
    uow.jobs.save(job)
    run = OrchestrationRun(project_id="p", change_name="change", base_sha="b" * 40, current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW, stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN, active_job_id=job.job_id, current_generation=1, current_candidate_sha="a" * 40)
    run.run_id = "run"
    uow.orchestration_runs.save(run)
    for candidate in candidates:
        uow.orchestration_candidates.save(candidate)
    return run, job


def valid_contract():
    return RemediationContract(
        contract_version="1", run_id="run", source_candidate_generation=1,
        source_candidate_sha="a" * 40, source_candidate_base_sha="b" * 40,
        change_name="change", objective="test", allowed_paths=["src/fix.py"],
    )


def test_missing_durable_repository_fails_closed_before_git(in_memory_uow, tmp_path):
    run, _ = stopped_run(in_memory_uow)
    manager = NoCallManager()
    service = CandidateRemediationService(in_memory_uow, tmp_path, worktree_manager=manager)
    with pytest.raises(RemediationError, match="[Dd]urable candidate remediation repository"):
        service.remediate(run.run_id, valid_contract())
    assert manager.calls == 0


@pytest.mark.parametrize("candidate_count", [0, 2])
def test_current_candidate_requires_exactly_one_non_superseded(in_memory_uow, tmp_path, candidate_count):
    candidates = [
        OrchestrationCandidate(run_id="run", generation=i + 1, base_sha="b" * 40, candidate_sha="a" * 40, candidate_ref="refs/heads/missing", manifest_hash="m" * 64)
        for i in range(candidate_count)
    ]
    run, _ = stopped_run(in_memory_uow, candidates=candidates)
    durable = DurableMemory()
    in_memory_uow.candidate_remediations = durable
    manager = NoCallManager()
    service = CandidateRemediationService(in_memory_uow, tmp_path, worktree_manager=manager)
    with pytest.raises(RemediationError, match="Latest non-superseded candidate"):
        service.remediate(run.run_id, valid_contract())
    assert manager.calls == 0
    assert durable.items == {}


def test_invalid_candidate_ref_never_invokes_implementer(tmp_path, in_memory_uow):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    project = Project(project_id="p", display_name="p", repository=str(tmp_path))
    in_memory_uow.projects.save(project)
    job = Job(project_id="p", change_name="change", implementer_role="codex", status=JobStatus.NEEDS_HUMAN, candidate_sha=sha, base_sha=sha)
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, sha, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    candidate = OrchestrationCandidate(run_id="run", generation=1, base_sha=sha, candidate_sha=sha, candidate_ref="refs/heads/does-not-exist", manifest_id=manifest.manifest_id, manifest_hash=manifest.manifest_hash)
    in_memory_uow.orchestration_candidates.save(candidate)
    run = OrchestrationRun(project_id="p", change_name="change", base_sha=sha, current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW, stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN, human_gate=HumanGate.NEEDS_HUMAN, active_job_id=job.job_id, current_candidate_sha=sha)
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.candidate_remediations = DurableMemory()
    manager = NoCallManager()
    service = CandidateRemediationService(in_memory_uow, tmp_path, pipeline=SimpleNamespace(implementer_runner=SimpleNamespace()), worktree_manager=manager)
    with pytest.raises(RemediationError, match="[Cc]andidate ref"):
        service.remediate("run", valid_contract().model_copy(update={"source_candidate_sha": sha, "source_candidate_base_sha": sha}))
    assert manager.calls == 0


@pytest.mark.parametrize(
    ("candidate_ref", "expected_sha"),
    [
        (None, None),
        ("refs/heads/main", "b" * 40),
    ],
    ids=["absent", "resolves-to-wrong-sha"],
)
def test_candidate_ref_must_authoritatively_resolve_to_candidate_sha(
    tmp_path, in_memory_uow, candidate_ref, expected_sha
):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    (tmp_path / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "source"], cwd=tmp_path, check=True, capture_output=True)
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    project = Project(project_id="p", display_name="p", repository=str(tmp_path))
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
    candidate = OrchestrationCandidate(
        run_id="run",
        generation=1,
        base_sha=source_sha,
        candidate_sha=expected_sha if expected_sha is not None else source_sha,
        candidate_ref=candidate_ref,
        manifest_id=manifest.manifest_id,
        manifest_hash=manifest.manifest_hash,
    )
    in_memory_uow.orchestration_candidates.save(candidate)
    run = OrchestrationRun(
        project_id="p",
        change_name="change",
        base_sha=source_sha,
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        active_job_id=job.job_id,
        current_candidate_sha=candidate.candidate_sha,
    )
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    durable = DurableMemory()
    in_memory_uow.candidate_remediations = durable
    manager = NoCallManager()
    implementer = SimpleNamespace(calls=0)
    service = CandidateRemediationService(
        in_memory_uow,
        tmp_path,
        pipeline=SimpleNamespace(implementer_runner=implementer),
        worktree_manager=manager,
    )
    contract = valid_contract().model_copy(
        update={
            "source_candidate_sha": candidate.candidate_sha,
            "source_candidate_base_sha": source_sha,
        }
    )
    with pytest.raises(RemediationError) as exc_info:
        service.remediate("run", contract)
    assert exc_info.value.code.value == "REMEDIATION_AUTHORITY_MISMATCH"
    assert manager.calls == 0
    assert implementer.calls == 0
    assert durable.items == {}
    assert len(in_memory_uow.orchestration_candidates.list_by_run("run")) == 1


def test_authoritative_base_advance_fails_closed_before_remediation(tmp_path, in_memory_uow):
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    (tmp_path / "README.md").write_text("base one\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base one"], cwd=tmp_path, check=True, capture_output=True)
    base_one = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    subprocess.run(["git", "branch", "candidate", base_one], cwd=tmp_path, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path)], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "README.md").write_text("base two\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base two"], cwd=tmp_path, check=True, capture_output=True)
    base_two = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    subprocess.run(
        ["git", "fetch", "origin", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    assert base_two != base_one
    project = Project(
        project_id="p", display_name="p", repository=str(tmp_path), base_branch="main"
    )
    in_memory_uow.projects.save(project)
    job = Job(
        project_id="p",
        change_name="change",
        implementer_role="codex",
        status=JobStatus.NEEDS_HUMAN,
        candidate_sha=base_one,
        base_sha=base_one,
    )
    in_memory_uow.jobs.save(job)
    manifest = CandidateManifestService().generate_manifest(tmp_path, base_one, job.job_id)
    in_memory_uow.candidate_manifests.save(manifest)
    candidate = OrchestrationCandidate(
        run_id="run",
        generation=1,
        base_sha=base_one,
        candidate_sha=base_one,
        candidate_ref="refs/heads/candidate",
        manifest_id=manifest.manifest_id,
        manifest_hash=manifest.manifest_hash,
    )
    in_memory_uow.orchestration_candidates.save(candidate)
    run = OrchestrationRun(
        project_id="p",
        change_name="change",
        base_sha=base_one,
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        active_job_id=job.job_id,
        current_candidate_sha=base_one,
    )
    run.run_id = "run"
    in_memory_uow.orchestration_runs.save(run)
    durable = DurableMemory()
    in_memory_uow.candidate_remediations = durable
    manager = NoCallManager()
    implementer = SimpleNamespace(calls=0)
    service = CandidateRemediationService(
        in_memory_uow,
        tmp_path,
        pipeline=SimpleNamespace(implementer_runner=implementer),
        worktree_manager=manager,
    )
    with pytest.raises(RemediationError) as exc_info:
        service.remediate(
            "run",
            valid_contract().model_copy(
                update={
                    "source_candidate_sha": base_one,
                    "source_candidate_base_sha": base_one,
                }
            ),
        )
    assert exc_info.value.code.value == "BASE_ADVANCED_REQUIRES_INTEGRATION"
    assert manager.calls == 0
    assert implementer.calls == 0
    assert durable.items == {}
    assert candidate.candidate_sha == base_one
    assert run.current_candidate_sha == base_one
