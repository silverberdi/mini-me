"""Tests for orchestration coordinator restart, recovery, and external action idempotency."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from minime.domain.enums import (
    ExternalActionType,
    HumanGate,
    OrchestrationStopOutcome,
    ProjectStatus,
    ProviderHealthStatus,
    ReadinessState,
)
from minime.domain.interfaces import GitHubAdapterInterface
from minime.domain.models import (
    CheckResult,
    Event,
    Project,
    ProjectBinding,
    ProviderHealth,
)
from minime.services.checks_runner import ChecksRunResult
from minime.services.deepseek_auditor_runner import MockAuditorRunner
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.implementer_runner import MockImplementerRunner
from minime.services.orchestration_service import OrchestrationService
from minime.services.reviewer_runner import MockReviewerRunner


class CountingGitHubAdapter(GitHubAdapterInterface):
    """Tracks calls to ensure idempotency."""

    def __init__(self):
        self.prs: dict[str, dict[str, Any]] = {}
        self.push_calls = 0
        self.pr_calls = 0
        self.fail_push_once = False
        self.fail_pr_once = False
        self.remote_branch_heads: dict[str, str] = {}
        self.fail_remote_head_query = False

    def validate_issue_binding(
        self, expected_repository: str, issue_number: int, github_repository: str | None = None
    ) -> tuple[bool, str | None]:
        return True, None

    def record_sync_failure(
        self, project_id: str, change_id: str | None, operation: str, error_message: str
    ) -> Event:
        return Event(
            event_type="SYNC_FAILED", project_id=project_id, payload={"error": error_message}
        )

    def get_pull_request(
        self, repository: str, branch: str, base: str | None = None
    ) -> dict[str, Any] | None:
        key = f"{repository}:{branch}"
        return self.prs.get(key)

    def create_pull_request(
        self,
        repository: str,
        branch: str,
        base: str,
        title: str,
        body: str,
        head_sha: str,
    ) -> dict[str, Any]:
        self.pr_calls += 1
        if self.fail_pr_once:
            self.fail_pr_once = False
            raise RuntimeError("Transient GitHub PR 502 Bad Gateway")
        key = f"{repository}:{branch}"
        pr_data = {
            "repository": repository,
            "number": len(self.prs) + 1,
            "url": f"https://github.com/{repository}/pull/{len(self.prs) + 1}",
            "head_sha": head_sha,
            "head_branch": branch,
            "base_branch": base,
            "state": "OPEN",
            "title": title,
            "body": body,
        }
        self.prs[key] = pr_data
        return pr_data

    def push_branch(self, worktree_path: str, remote: str, branch: str, candidate_sha: str) -> bool:
        self.push_calls += 1
        if self.fail_push_once:
            self.fail_push_once = False
            raise RuntimeError("Transient Git push network disconnect")
        # When push succeeds, update remote branch head
        self.remote_branch_heads[f"origin:{branch}"] = candidate_sha
        self.remote_branch_heads[f"{branch}"] = candidate_sha
        return True

    def get_remote_branch_head(
        self, repository: str, branch: str, remote: str = "origin"
    ) -> str | None:
        if self.fail_remote_head_query:
            raise RuntimeError("Cannot reach remote repository")
        return self.remote_branch_heads.get(f"{remote}:{branch}") or self.remote_branch_heads.get(
            branch
        )


class SimpleChecksRunner:
    async def run(
        self,
        job_id: str,
        checks: list[dict],
        worktree_path: str | Path,
        candidate_sha: str = "",
        attempt_id: str | None = None,
    ):
        return ChecksRunResult(
            passed=True,
            results=[
                CheckResult(
                    job_id=job_id,
                    check_name="pytest",
                    command="pytest",
                    exit_code=0,
                    duration_ms=50,
                    output_snippet="Passed",
                )
            ],
            diagnostics=[],
        )


@pytest.fixture
def setup_env(tmp_path: Path, in_memory_uow):
    import subprocess

    from conftest import create_isolated_openspec_change

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True
    )

    project_id = "mini-me"
    change_name = "008-autonomous-change-orchestration"

    project = Project(
        project_id=project_id,
        display_name="Mini Me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
        status=ProjectStatus.ACTIVE,
        checks=[{"name": "pytest", "command": "pytest"}],
    )
    in_memory_uow.projects.save(project)

    binding = ProjectBinding(
        project_id=project_id,
        openspec_change_name=change_name,
        repository="silverberdi/mini-me",
        github_issue_number=16,
        is_valid=True,
    )
    in_memory_uow.bindings.save(binding)

    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE)
    )

    create_isolated_openspec_change(
        tmp_path,
        change_name=change_name,
        proposal_content="# Proposal\n\nRestart tests.\n",
        tasks_content="## 1. Foundation\n- [x] 1.1 Complete schema <!-- id: 1.1 -->\n",
        design_content="# Design\n\nIdempotent actions.\n",
        spec_content="# Spec\n\n## Requirements\nReconstruction from PostgreSQL.\n",
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Add OpenSpec change"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True
    )

    from minime.domain.models import Change

    in_memory_uow.changes.save(
        Change(
            project_id=project_id,
            name=change_name,
            schema_name="feature",
            last_readiness_status=ReadinessState.READY,
        )
    )

    return {"project_id": project_id, "change_name": change_name, "project_root": tmp_path}


def test_idempotent_push_and_pr_pre_reservation(setup_env, in_memory_uow):
    """Verify that external actions are reserved in database before mutating Git/GitHub."""
    env = setup_env
    fake_github = CountingGitHubAdapter()

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=MockImplementerRunner(),
        checks_runner=SimpleChecksRunner(),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                '```json\n{"verdict": "READY_TO_MERGE", "summary": "All good", "findings": []}\n```'
            ]
        ),
        auditor_runner=MockAuditorRunner(
            output=['{"risk": "low", "summary": "Passed", "findings": []}']
        ),
    )

    service = OrchestrationService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        pipeline=pipeline,
        github_adapter=fake_github,
    )

    run = service.start(env["project_id"], env["change_name"])
    assert run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert fake_github.push_calls == 1
    assert fake_github.pr_calls == 1

    # Verify action records in external actions repository
    push_actions = in_memory_uow.orchestration_external_actions.list_by_run(run.run_id)
    assert len(push_actions) >= 2  # At least 1 push action and 1 pr_create action
    action_types = {a.action_type for a in push_actions}
    assert ExternalActionType.BRANCH_PUSH in action_types
    assert ExternalActionType.PR_CREATE in action_types

    # Calling resume on a run that is already ready for human merge does not duplicate push or PR
    resumed = service.resume(run.run_id)
    assert resumed.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert fake_github.push_calls == 1
    assert fake_github.pr_calls == 1


def test_transient_github_pr_failure_and_resume_recovery(setup_env, in_memory_uow):
    """Verify transient PR failure stops at WAITING_EXTERNAL and resume succeeds without re-executing implementation."""
    env = setup_env
    fake_github = CountingGitHubAdapter()
    fake_github.fail_pr_once = True  # First PR creation attempt fails

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=MockImplementerRunner(),
        checks_runner=SimpleChecksRunner(),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                '```json\n{"verdict": "READY_TO_MERGE", "summary": "All good", "findings": []}\n```'
            ]
        ),
        auditor_runner=MockAuditorRunner(
            output=['{"risk": "low", "summary": "Passed", "findings": []}']
        ),
    )

    service = OrchestrationService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        pipeline=pipeline,
        github_adapter=fake_github,
    )

    # First attempt stops at WAITING_EXTERNAL
    run = service.start(env["project_id"], env["change_name"])
    assert run.stop_outcome == OrchestrationStopOutcome.WAITING_EXTERNAL
    assert run.human_gate is None
    assert run.is_active is True
    assert fake_github.pr_calls == 1

    # Resuming re-attempts PR preparation without restarting from scratch
    resumed = service.resume(run.run_id)
    assert resumed.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert resumed.human_gate == HumanGate.READY_FOR_HUMAN_MERGE
    assert fake_github.pr_calls == 2  # Total 2 attempts, second succeeded
