"""Real-Git verification for preserved-candidate human resolution."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from minime.domain.enums import (
    ChangeStatus,
    EventType,
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
)
from minime.domain.models import (
    Change,
    Job,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
)
from minime.services.checks_runner import ChecksRunner
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.orchestration_service import OrchestrationService
from minime.services.worktree_manager import WorktreeManager


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def make_repo(tmp_path: Path, conflict: bool) -> tuple[Path, str, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "shared.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base A")
    base_a = git(repo, "rev-parse", "HEAD")

    git(repo, "switch", "-c", "historical-candidate")
    (repo / "shared.txt").write_text("candidate\n", encoding="utf-8")
    (repo / "candidate.txt").write_text("candidate change\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "candidate C")
    candidate_sha = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "main")

    (repo / "shared.txt").write_text(
        "base B\n" if conflict else "base\n", encoding="utf-8"
    )
    (repo / "base.txt").write_text("base advancement\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base B")
    base_b = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", base_b)
    git(repo, "update-ref", "refs/heads/historical-candidate", candidate_sha)
    return repo, base_a, candidate_sha, base_b


def make_service(uow, repo: Path, base_a: str, candidate_sha: str, candidate_ref: str):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/repo",
        repo_path=str(repo),
        base_branch="main",
        checks=[{"name": "valid", "command": "test -f candidate.txt"}],
    )
    change = Change(
        project_id="mini-me",
        name="010-governance-and-recovery-hardening",
        status=ChangeStatus.READY,
    )
    job = Job(
        job_id="job-human-resolution",
        project_id="mini-me",
        change_name=change.name,
        implementer_role="codex",
        status=JobStatus.NEEDS_HUMAN,
        base_sha=base_a,
        candidate_sha=candidate_sha,
    )
    run = OrchestrationRun(
        run_id="run-human-resolution",
        project_id=project.project_id,
        change_name=change.name,
        base_sha=base_a,
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        resumable_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        active_job_id=job.job_id,
        is_active=False,
    )
    candidate = OrchestrationCandidate(
        run_id=run.run_id,
        generation=1,
        base_sha=base_a,
        candidate_sha=candidate_sha,
        candidate_ref=candidate_ref,
        manifest_hash="historical-manifest",
    )
    uow.projects.save(project)
    uow.changes.save(change)
    uow.jobs.save(job)
    uow.orchestration_runs.save(run)
    uow.orchestration_candidates.save(candidate)
    manager = WorktreeManager(repo, uow=uow)
    pipeline = ExecutionPipelineService(
        uow=uow,
        project_root=repo,
        worktree_manager=manager,
        checks_runner=ChecksRunner(),
    )
    service = OrchestrationService(uow, project_root=repo, pipeline=pipeline)
    return service, run.run_id


def test_advanced_base_real_git_integration_and_idempotency(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, base_b = make_repo(tmp_path, conflict=False)
    service, run_id = make_service(
        in_memory_uow, repo, base_a, candidate_sha, "refs/heads/historical-candidate"
    )
    service.drive_coordinator = lambda run_id, project_root=None: (
        in_memory_uow.orchestration_runs.get_by_id(run_id)
    )

    resolved = service.resolve_preserved_candidate(
        run_id, continue_preserved_candidate=True, project_root=repo
    )

    candidates = in_memory_uow.orchestration_candidates.list_by_run(run_id)
    old, new = candidates
    assert resolved.current_stage == OrchestrationStage.RUNNING_CHECKS
    assert new.generation == 2
    assert new.base_sha == base_b
    assert new.candidate_sha != old.candidate_sha
    assert git(repo, "rev-parse", old.candidate_ref) == candidate_sha
    assert git(repo, "rev-parse", new.candidate_ref) == new.candidate_sha
    assert git(repo, "merge-base", "--is-ancestor", base_b, new.candidate_sha) == ""
    assert old.superseded_by_id == new.candidate_id
    assert (repo / ".minime" / "worktrees" / f"{in_memory_uow.jobs.get_by_id('job-human-resolution').job_id}-integration-gen2").exists() is False
    assert in_memory_uow.jobs.get_by_id("job-human-resolution").base_sha == base_b

    again = service.resolve_preserved_candidate(
        run_id, continue_preserved_candidate=True, project_root=repo
    )
    assert again.current_generation == 2
    assert len(in_memory_uow.orchestration_candidates.list_by_run(run_id)) == 2
    resolutions = [
        event
        for event in in_memory_uow.orchestration_stage_events.list_by_run(run_id)
        if event.event_type == EventType.HUMAN_RESOLUTION.value
        and event.evidence_references.get("resulting_candidate_sha")
    ]
    assert len(resolutions) == 1


def test_advanced_base_real_git_conflict_preserves_integration_state(
    tmp_path, in_memory_uow
):
    repo, base_a, candidate_sha, base_b = make_repo(tmp_path, conflict=True)
    service, run_id = make_service(
        in_memory_uow, repo, base_a, candidate_sha, "refs/heads/historical-candidate"
    )

    resolved = service.resolve_preserved_candidate(
        run_id, continue_preserved_candidate=True, project_root=repo
    )
    assert resolved.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
    assert len(in_memory_uow.orchestration_candidates.list_by_run(run_id)) == 1
    assert git(repo, "rev-parse", "refs/heads/historical-candidate") == candidate_sha

    integration_path = (
        repo / ".minime" / "worktrees" / "job-human-resolution-integration-gen2"
    )
    integration_branch = (
        "refs/heads/minime/010-governance-and-recovery-hardening-"
        "job-human-resolution-integration-gen2"
    )
    assert integration_path.exists()
    assert git(repo, "show-ref", "--verify", integration_branch)
    assert "UU shared.txt" in git(integration_path, "status", "--short")
    conflict_events = [
        event
        for event in in_memory_uow.orchestration_stage_events.list_by_run(run_id)
        if event.evidence_references.get("code") == "BASE_INTEGRATION_CONFLICT"
    ]
    assert len(conflict_events) == 1

    with pytest.raises(ValueError, match="Human integration"):
        service.resolve_preserved_candidate(
            run_id, continue_preserved_candidate=True, project_root=repo
        )
    again = in_memory_uow.orchestration_runs.get_by_id(run_id)
    assert again.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
    assert len(in_memory_uow.orchestration_candidates.list_by_run(run_id)) == 1
    assert integration_path.exists()
    assert len(
        [
            event
            for event in in_memory_uow.orchestration_stage_events.list_by_run(run_id)
            if event.evidence_references.get("code") == "BASE_INTEGRATION_CONFLICT"
        ]
    ) == 1


def test_completed_human_integration_is_reconciled_idempotently(tmp_path, in_memory_uow):
    repo, base_a, candidate_sha, base_b = make_repo(tmp_path, conflict=True)
    service, run_id = make_service(
        in_memory_uow, repo, base_a, candidate_sha, "refs/heads/historical-candidate"
    )
    service.drive_coordinator = lambda run_id, project_root=None: (
        in_memory_uow.orchestration_runs.get_by_id(run_id)
    )

    service.resolve_preserved_candidate(
        run_id, continue_preserved_candidate=True, project_root=repo
    )
    integration_path = repo / ".minime" / "worktrees" / "job-human-resolution-integration-gen2"
    (integration_path / "shared.txt").write_text("candidate\n", encoding="utf-8")
    git(integration_path, "add", "shared.txt")
    git(integration_path, "-c", "core.editor=true", "cherry-pick", "--continue")
    assert git(integration_path, "rev-parse", "HEAD^") == base_b
    assert git(integration_path, "status", "--porcelain") == ""

    resolved = service.resolve_preserved_candidate(
        run_id, continue_preserved_candidate=True, project_root=repo
    )
    candidates = in_memory_uow.orchestration_candidates.list_by_run(run_id)
    assert resolved.current_generation == 2
    assert [candidate.generation for candidate in candidates] == [1, 2]
    assert candidates[0].superseded_by_id == candidates[1].candidate_id
    assert in_memory_uow.jobs.get_by_id("job-human-resolution").candidate_sha == candidates[1].candidate_sha

    again = service.resolve_preserved_candidate(
        run_id, continue_preserved_candidate=True, project_root=repo
    )
    assert again.current_generation == 2
    assert len(in_memory_uow.orchestration_candidates.list_by_run(run_id)) == 2
    resolutions = [
        event
        for event in in_memory_uow.orchestration_stage_events.list_by_run(run_id)
        if event.event_type == EventType.HUMAN_RESOLUTION.value
        and event.evidence_references.get("resulting_candidate_sha")
    ]
    assert len(resolutions) == 1
