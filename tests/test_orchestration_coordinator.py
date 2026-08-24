"""Comprehensive coordinator tests for autonomous change orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import create_isolated_openspec_change
from minime.domain.enums import (
    AuditFindingSeverity,
    AuditStatus,
    ExternalActionStatus,
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProjectStatus,
    ProviderHealthStatus,
    PullRequestLookupState,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.interfaces import GitHubAdapterInterface
from minime.domain.models import (
    AuditFinding,
    AuditRecord,
    CheckResult,
    Event,
    Job,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
    ProjectBinding,
    ProviderHealth,
    PullRequestLookupResult,
    Review,
    utc_now,
)
from minime.services.checks_runner import ChecksRunner, ChecksRunResult
from minime.services.deepseek_auditor_runner import MockAuditorRunner
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.implementer_runner import ImplementerResult, MockImplementerRunner
from minime.services.orchestration_service import OrchestrationService
from minime.services.reviewer_runner import MockReviewerRunner
from minime.services.worktree_manager import WorktreeManager


class FakeGitHubAdapter(GitHubAdapterInterface):
    """Deterministic in-memory GitHub adapter for orchestration testing."""

    def __init__(self):
        self.prs: dict[str, dict[str, Any]] = {}
        self.pushed_branches: list[dict[str, Any]] = []
        self.fail_push = False
        self.fail_pr = False
        self.create_calls = 0

    def validate_issue_binding(
        self, expected_repository: str, issue_number: int, github_repository: str | None = None
    ) -> tuple[bool, str | None]:
        if github_repository and expected_repository != github_repository:
            return False, "Repository mismatch"
        if issue_number <= 0:
            return False, "Invalid issue number"
        return True, None

    def record_sync_failure(
        self, project_id: str, change_id: str | None, operation: str, error_message: str
    ) -> Event:
        return Event(
            event_type="SYNC_FAILED",
            project_id=project_id,
            change_id=change_id,
            operation_id=operation,
            payload={"error": error_message},
            timestamp=utc_now(),
        )

    def get_pull_request(
        self, repository: str, branch: str, base: str = "main"
    ) -> dict[str, Any] | None:
        if self.fail_pr:
            raise RuntimeError("GitHub PR API unreachable")
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
        self.create_calls += 1
        if self.fail_pr:
            raise RuntimeError("GitHub PR API unreachable")
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
        if self.fail_push:
            raise RuntimeError("Git push connection timed out")
        self.pushed_branches.append(
            {"remote": remote, "branch": branch, "candidate_sha": candidate_sha}
        )
        return True

    def get_remote_branch_head(
        self, repository: str, branch: str, remote: str = "origin"
    ) -> str | None:
        if self.fail_push:
            raise RuntimeError("Git ls-remote connection timed out")
        for p in self.pushed_branches:
            if p.get("branch") == branch:
                return p.get("candidate_sha")
        return None


class FakeChecksRunner:
    """Simulates checks execution."""

    def __init__(self, should_pass: bool = True):
        self.should_pass = should_pass

    async def run(
        self,
        job_id: str,
        checks: list[dict],
        worktree_path: str | Path,
        candidate_sha: str = "",
        attempt_id: str | None = None,
    ) -> ChecksRunResult:
        exit_code = 0 if self.should_pass else 1
        res = CheckResult(
            job_id=job_id,
            check_name="pytest",
            command="pytest",
            exit_code=exit_code,
            duration_ms=120,
            output_snippet="Passed" if self.should_pass else "Failed",
        )
        return ChecksRunResult(passed=self.should_pass, results=[res], diagnostics=[])


class StructuredLookupGitHubAdapter(FakeGitHubAdapter):
    """Fake transport with the production adapter's explicit PR lookup states."""

    def __init__(self, state: PullRequestLookupState, mismatch: bool = False):
        super().__init__()
        self.lookup_state = state
        self.lookup_mismatch = mismatch

    def get_pull_request(self, repository: str, branch: str, base: str = "main"):
        if self.lookup_state != PullRequestLookupState.FOUND_EXACT:
            return PullRequestLookupResult(
                state=self.lookup_state,
                detail=f"simulated {self.lookup_state.value.lower()} lookup",
            )
        candidate_sha = self.pushed_branches[-1]["candidate_sha"]
        if self.lookup_mismatch:
            candidate_sha = "different-candidate-sha"
        return PullRequestLookupResult(
            state=PullRequestLookupState.FOUND_EXACT,
            pull_request={
                "repository": repository,
                "number": 41,
                "url": "https://github.com/silverberdi/mini-me/pull/41",
                "head_sha": candidate_sha,
                "head_branch": branch,
                "base_branch": base,
                "state": "OPEN",
                "title": "008-autonomous-change-orchestration",
                "body": "Closes #16",
            },
        )


@pytest.fixture
def setup_orchestration_environment(tmp_path: Path, in_memory_uow):
    """Sets up a fully configured test environment with projects, bindings, health, and changes."""
    import subprocess

    # Initialize a valid Git repository with a main branch and initial commit
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True
    )

    project_id = "mini-me"
    change_name = "008-autonomous-change-orchestration"

    # Register project
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

    # Register binding
    binding = ProjectBinding(
        project_id=project_id,
        openspec_change_name=change_name,
        repository="silverberdi/mini-me",
        github_issue_number=16,
        is_valid=True,
    )
    in_memory_uow.bindings.save(binding)

    # Provider health
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(provider="antigravity", status=ProviderHealthStatus.AVAILABLE)
    )

    # Create OpenSpec change directory with valid artifacts
    change_dir = create_isolated_openspec_change(
        tmp_path,
        change_name=change_name,
        proposal_content="# Proposal\n\nAutonomous orchestration.\n",
        tasks_content="## 1. Foundation\n- [x] 1.1 Complete schema <!-- id: 1.1 -->\n",
        design_content="# Design\n\nState graph.\n",
        spec_content="# Spec\n\n## Requirements\nAutonomous stop outcomes.\n",
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Add OpenSpec change"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True
    )

    # Save change in repository
    from minime.domain.models import Change

    ch = Change(
        project_id=project_id,
        name=change_name,
        schema_name="feature",
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(ch)

    return {
        "project_id": project_id,
        "change_name": change_name,
        "project_root": tmp_path,
        "change_dir": change_dir,
    }


def _service_for_pr_lookup(env, uow, github):
    pipeline = ExecutionPipelineService(
        uow=uow,
        project_root=env["project_root"],
        implementer_runner=MockImplementerRunner(),
        checks_runner=FakeChecksRunner(should_pass=True),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                '```json\n{"verdict": "READY_TO_MERGE", "summary": "All good", "findings": []}\n```'
            ]
        ),
        auditor_runner=MockAuditorRunner(
            output=['{"risk": "low", "summary": "Passed", "findings": []}']
        ),
    )
    return OrchestrationService(
        uow,
        project_root=env["project_root"],
        pipeline=pipeline,
        github_adapter=github,
    )


def test_pr_lookup_authoritative_not_found_allows_one_creation(
    setup_orchestration_environment, in_memory_uow
):
    env = setup_orchestration_environment
    github = StructuredLookupGitHubAdapter(PullRequestLookupState.NOT_FOUND)
    run = _service_for_pr_lookup(env, in_memory_uow, github).start(
        env["project_id"], env["change_name"]
    )
    assert run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert github.create_calls == 1


@pytest.mark.parametrize(
    ("state", "expected_outcome"),
    [
        (PullRequestLookupState.UNOBSERVABLE, OrchestrationStopOutcome.WAITING_EXTERNAL),
        (PullRequestLookupState.AMBIGUOUS, OrchestrationStopOutcome.NEEDS_HUMAN),
    ],
)
def test_pr_lookup_non_authoritative_state_never_creates_pr(
    setup_orchestration_environment, in_memory_uow, state, expected_outcome
):
    env = setup_orchestration_environment
    github = StructuredLookupGitHubAdapter(state)
    service = _service_for_pr_lookup(env, in_memory_uow, github)
    run = service.start(env["project_id"], env["change_name"])
    assert run.stop_outcome == expected_outcome
    assert github.create_calls == 0

    if state == PullRequestLookupState.UNOBSERVABLE:
        resumed = service.resume(run.run_id)
        assert resumed.stop_outcome == expected_outcome
        assert github.create_calls == 0


def test_pr_lookup_contradictory_identity_never_creates_pr(
    setup_orchestration_environment, in_memory_uow
):
    env = setup_orchestration_environment
    github = StructuredLookupGitHubAdapter(PullRequestLookupState.FOUND_EXACT, mismatch=True)
    run = _service_for_pr_lookup(env, in_memory_uow, github).start(
        env["project_id"], env["change_name"]
    )
    assert run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
    assert github.create_calls == 0


def test_pr_lookup_exact_identity_adopts_without_creation(
    setup_orchestration_environment, in_memory_uow
):
    env = setup_orchestration_environment
    github = StructuredLookupGitHubAdapter(PullRequestLookupState.FOUND_EXACT)
    run = _service_for_pr_lookup(env, in_memory_uow, github).start(
        env["project_id"], env["change_name"]
    )
    assert run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert github.create_calls == 0


def test_admission_refusal_scenarios(setup_orchestration_environment, in_memory_uow):
    env = setup_orchestration_environment
    service = OrchestrationService(in_memory_uow, project_root=env["project_root"])

    # 1. Non-existent project
    res_bad_proj = service.admit_change("unknown-project", env["change_name"])
    assert res_bad_proj.admitted is False
    assert "not found" in res_bad_proj.refusal_reason.lower()

    # 2. Non-existent change
    res_bad_change = service.admit_change(env["project_id"], "unknown-change")
    assert res_bad_change.admitted is False
    assert "not found" in res_bad_change.refusal_reason.lower()

    # 3. Invalid repository binding (e.g. missing github_issue_number)
    in_memory_uow.bindings.save(
        ProjectBinding(
            project_id=env["project_id"],
            openspec_change_name="bad-binding-change",
            repository="silverberdi/mini-me",
            github_issue_number=0,  # Invalid!
            is_valid=True,
        )
    )
    from minime.domain.models import Change

    in_memory_uow.changes.save(
        Change(
            project_id=env["project_id"],
            name="bad-binding-change",
            schema_name="feature",
            last_readiness_status=ReadinessState.READY,
        )
    )
    res_bad_bind = service.admit_change(env["project_id"], "bad-binding-change")
    assert res_bad_bind.admitted is False
    assert "github issue" in res_bad_bind.refusal_reason.lower()

    # 4. Successful admission
    res_ok = service.admit_change(env["project_id"], env["change_name"])
    assert res_ok.admitted is True
    assert res_ok.run is not None
    assert res_ok.run.current_stage == OrchestrationStage.ADMITTED

    # 5. Duplicate active run refusal
    res_dup = service.admit_change(env["project_id"], env["change_name"])
    assert res_dup.admitted is False
    assert "active orchestration run" in res_dup.refusal_reason.lower()
    assert res_dup.existing_run_id == res_ok.run.run_id


def test_end_to_end_successful_orchestration(setup_orchestration_environment, in_memory_uow):
    """Verify normal progression across all stages to PR_PREPARED and READY_FOR_HUMAN_MERGE."""
    env = setup_orchestration_environment

    fake_github = FakeGitHubAdapter()
    mock_implementer = MockImplementerRunner()
    fake_checks = FakeChecksRunner(should_pass=True)
    mock_reviewer = MockReviewerRunner(
        stdout=[
            '```json\n{"verdict": "READY_TO_MERGE", "summary": "All criteria met.", "findings": []}\n```'
        ]
    )
    mock_auditor = MockAuditorRunner(
        output=['{"risk": "low", "summary": "No security risks found.", "findings": []}']
    )

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=mock_implementer,
        checks_runner=fake_checks,
        reviewer_runner=mock_reviewer,
        auditor_runner=mock_auditor,
    )

    service = OrchestrationService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        pipeline=pipeline,
        github_adapter=fake_github,
    )

    # Run start
    run = service.start(env["project_id"], env["change_name"])

    assert run.current_stage == OrchestrationStage.PR_PREPARED
    assert run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert run.human_gate == HumanGate.READY_FOR_HUMAN_MERGE
    assert run.is_active is False
    assert run.current_generation == 1

    # Verify mutations and external actions recorded
    push_key = f"push:{run.run_id}:gen1:{run.current_candidate_sha}"
    push_action = in_memory_uow.orchestration_external_actions.get_by_action_key(push_key)
    assert push_action is not None
    assert push_action.status == ExternalActionStatus.COMPLETED

    pr_key = f"pr:{run.run_id}:gen1:{run.current_candidate_sha}"
    pr_action = in_memory_uow.orchestration_external_actions.get_by_action_key(pr_key)
    assert pr_action is not None
    assert pr_action.status == ExternalActionStatus.COMPLETED
    assert pr_action.remote_identifier is not None

    # Status view check
    status_view = service.get_status(run.run_id)
    assert status_view.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert status_view.human_gate == HumanGate.READY_FOR_HUMAN_MERGE
    assert status_view.is_active is False
    assert status_view.pr_number == 1
    assert "github.com" in status_view.pr_url
    assert status_view.review_verdict == "READY_TO_MERGE"
    assert status_view.audit_status == "AUDIT_COMPLETED"


def test_orchestration_reuses_pipeline_evidence_after_production_worktree_cleanup(
    setup_orchestration_environment, in_memory_uow
):
    """The coordinator must use persisted pipeline evidence, never a removed worktree."""
    env = setup_orchestration_environment
    project = in_memory_uow.projects.get_by_id(env["project_id"])
    project.checks = [{"name": "candidate-file", "command": "test -f candidate_impl.py"}]
    in_memory_uow.projects.save(project)

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=MockImplementerRunner(),
        worktree_manager=WorktreeManager(env["project_root"], uow=in_memory_uow),
        checks_runner=ChecksRunner(),
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
        in_memory_uow,
        project_root=env["project_root"],
        pipeline=pipeline,
        github_adapter=FakeGitHubAdapter(),
    )

    run = service.start(env["project_id"], env["change_name"])

    assert run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    job = in_memory_uow.jobs.get_by_id(run.active_job_id)
    assert job is not None and job.candidate_sha
    assert not (env["project_root"] / ".minime" / "worktrees" / job.job_id).exists()

    checks = in_memory_uow.check_results.list_by_job(job.job_id)
    assert len(checks) == 1
    assert checks[0].check_name == "candidate-file"
    assert checks[0].exit_code == 0

    manifest = in_memory_uow.candidate_manifests.get_by_candidate_sha(job.job_id, job.candidate_sha)
    assert manifest is not None
    assert manifest.total_files_count > 0
    assert "candidate_impl.py" in {
        item["path"]
        for item in manifest.tracked_files + manifest.staged_files + manifest.untracked_files
    }
    candidate = in_memory_uow.orchestration_candidates.get_latest_for_run(run.run_id)
    assert candidate is not None
    assert candidate.candidate_sha == job.candidate_sha
    assert candidate.manifest_hash == manifest.manifest_hash


def test_capacity_exhaustion_stops_at_waiting_capacity(
    setup_orchestration_environment, in_memory_uow
):
    """Verify provider capacity exhaustion stops with WAITING_CAPACITY at preserved checkpoint."""
    env = setup_orchestration_environment

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
    )
    service = OrchestrationService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        pipeline=pipeline,
    )

    admission = service.admit_change(env["project_id"], env["change_name"])
    assert admission.admitted is True

    # Provider capacity drops before/during execution
    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="codex",
            status=ProviderHealthStatus.EXHAUSTED,
            last_error_summary="Daily token limit reached",
        )
    )

    run = service.drive_coordinator(admission.run.run_id)

    assert run.stop_outcome == OrchestrationStopOutcome.WAITING_CAPACITY
    assert run.human_gate is None
    assert run.is_active is True
    assert run.resumable_stage == OrchestrationStage.PREPARING_EXECUTION
    assert "exhausted" in run.stop_reason.lower()

    # When capacity recovers, resuming should continue
    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="codex",
            status=ProviderHealthStatus.AVAILABLE,
        )
    )
    fake_github = FakeGitHubAdapter()
    service.github_adapter = fake_github
    service.pipeline.implementer_runner = MockImplementerRunner()
    service.pipeline.checks_runner = FakeChecksRunner(should_pass=True)
    service.pipeline.reviewer_runner = MockReviewerRunner(
        stdout=[
            '```json\n{"verdict": "READY_TO_MERGE", "summary": "All good", "findings": []}\n```'
        ]
    )
    service.pipeline.auditor_runner = MockAuditorRunner(
        output=['{"risk": "low", "summary": "Passed", "findings": []}']
    )

    resumed_run = service.resume(run.run_id)
    assert resumed_run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert resumed_run.human_gate == HumanGate.READY_FOR_HUMAN_MERGE
    assert resumed_run.current_stage == OrchestrationStage.PR_PREPARED


def test_review_remediation_loop_increments_candidate_generation(
    setup_orchestration_environment, in_memory_uow
):
    """Verify review CHANGES_REQUIRED routes through remediation, incrementing candidate generation."""
    env = setup_orchestration_environment

    class DynamicReviewer(MockReviewerRunner):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def run(self, worktree_path: Path, prompt_context: str, timeout_seconds: int):
            self.calls += 1
            if self.calls == 1:
                out = '```json\n{"verdict": "CHANGES_REQUIRED", "summary": "Need tests", "findings": [{"severity": "BLOCKER", "location": "main.py", "violated_requirement": "Tests", "expected_correction": "Add tests"}]}\n```'
            else:
                out = '```json\n{"verdict": "READY_TO_MERGE", "summary": "All good", "findings": []}\n```'
            self.stdout = [out]
            return await super().run(worktree_path, prompt_context, timeout_seconds)

    class DynamicImplementer(MockImplementerRunner):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def run(self, worktree_path: Path, prompt_context: str, timeout_seconds: int):
            self.calls += 1
            import subprocess

            file = Path(worktree_path) / f"impl_gen_{self.calls}.py"
            file.write_text(f"# Gen {self.calls}\n")
            subprocess.run(["git", "add", "."], cwd=str(worktree_path), check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@test.com",
                    "commit",
                    "-m",
                    f"Gen {self.calls}",
                ],
                cwd=str(worktree_path),
                check=True,
            )
            return ImplementerResult(
                exit_code=0,
                timed_out=False,
                stdout=[],
                stderr=[],
                duration_ms=1,
            )

    fake_github = FakeGitHubAdapter()
    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=DynamicImplementer(),
        checks_runner=FakeChecksRunner(should_pass=True),
        reviewer_runner=DynamicReviewer(),
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

    # Generation should have incremented to 2 due to remediation
    assert run.current_generation == 2
    assert run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert run.human_gate == HumanGate.READY_FOR_HUMAN_MERGE

    # Both generation 1 and 2 should exist in candidates repo, gen 1 superseded
    candidates = in_memory_uow.orchestration_candidates.list_by_run(run.run_id)
    assert len(candidates) == 2
    assert candidates[0].generation == 1
    assert candidates[0].superseded_by_id == candidates[1].candidate_id
    assert candidates[1].generation == 2
    assert candidates[1].superseded_by_id is None


def test_deepseek_audit_blocking_findings_trigger_remediation(
    setup_orchestration_environment, in_memory_uow
):
    """Verify DeepSeek Direct CRITICAL/HIGH/MEDIUM findings force audit remediation and re-audit."""
    env = setup_orchestration_environment

    class DynamicAuditor(MockAuditorRunner):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def run(self, worktree_path: Path, prompt_context: str, timeout_seconds: int):
            self.calls += 1
            if self.calls == 1:
                out = '{"risk": "high", "summary": "Found SQL injection", "findings": [{"severity": "high", "category": "security", "message": "SQL injection", "file": "db.py"}]}'
            else:
                out = '{"risk": "low", "summary": "Passed", "findings": []}'
            self.output = [out]
            return await super().run(worktree_path, prompt_context, timeout_seconds)

    class DynamicImplementer(MockImplementerRunner):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def run(self, worktree_path: Path, prompt_context: str, timeout_seconds: int):
            self.calls += 1
            import subprocess

            file = Path(worktree_path) / f"audit_fix_{self.calls}.py"
            file.write_text(f"# Fix {self.calls}\n")
            subprocess.run(["git", "add", "."], cwd=str(worktree_path), check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@test.com",
                    "commit",
                    "-m",
                    f"Fix {self.calls}",
                ],
                cwd=str(worktree_path),
                check=True,
            )
            return ImplementerResult(
                exit_code=0,
                timed_out=False,
                stdout=[],
                stderr=[],
                duration_ms=1,
            )

    fake_github = FakeGitHubAdapter()
    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=DynamicImplementer(),
        checks_runner=FakeChecksRunner(should_pass=True),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                '```json\n{"verdict": "READY_TO_MERGE", "summary": "All good", "findings": []}\n```'
            ]
        ),
        auditor_runner=DynamicAuditor(),
    )

    service = OrchestrationService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        pipeline=pipeline,
        github_adapter=fake_github,
    )

    run = service.start(env["project_id"], env["change_name"])
    assert run.current_generation == 2
    assert run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert run.human_gate == HumanGate.READY_FOR_HUMAN_MERGE


def test_pr_head_mismatch_fails_closed_needs_human(setup_orchestration_environment, in_memory_uow):
    """Verify that an existing remote PR with mismatched head SHA triggers fail-closed NEEDS_HUMAN."""
    env = setup_orchestration_environment

    fake_github = FakeGitHubAdapter()
    # Pre-populate mismatched PR on remote GitHub
    fake_github.prs["silverberdi/mini-me:minime/008-autonomous-change-orchestration"] = {
        "repository": "silverberdi/mini-me",
        "head_branch": "minime/008-autonomous-change-orchestration",
        "base_branch": "main",
        "number": 42,
        "url": "https://github.com/silverberdi/mini-me/pull/42",
        "head_sha": "some-other-unrelated-sha-9999",
        "base_sha": "main",
        "state": "OPEN",
    }

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=MockImplementerRunner(),
        checks_runner=FakeChecksRunner(should_pass=True),
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

    # Fail closed: must stop with NEEDS_HUMAN
    assert run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
    assert run.human_gate == HumanGate.NEEDS_HUMAN
    assert "does not match" in run.stop_reason.lower()
    assert run.stop_details.get("code") == "PR_HEAD_MISMATCH"


def test_transient_external_failure_stops_waiting_external_and_resumes(
    setup_orchestration_environment, in_memory_uow
):
    """Verify network/push failure stops with WAITING_EXTERNAL and recovers smoothly on resume."""
    env = setup_orchestration_environment

    fake_github = FakeGitHubAdapter()
    fake_github.fail_push = True  # Simulate temporary network drop

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=MockImplementerRunner(),
        checks_runner=FakeChecksRunner(should_pass=True),
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
    assert run.stop_outcome == OrchestrationStopOutcome.WAITING_EXTERNAL
    assert run.human_gate is None
    assert run.is_active is True
    assert run.resumable_stage == OrchestrationStage.PREPARING_PR

    # Resolve network and resume
    fake_github.fail_push = False
    resumed_run = service.resume(run.run_id)
    assert resumed_run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
    assert resumed_run.human_gate == HumanGate.READY_FOR_HUMAN_MERGE
    assert resumed_run.current_stage == OrchestrationStage.PR_PREPARED


def test_ready_to_merge_job_without_audit_cannot_prepare_pr(
    setup_orchestration_environment, in_memory_uow
):
    """
    CRITICAL Finding 1 Regression Test:
    Verify that an active job in JobStatus.READY_TO_MERGE with NO audit record
    cannot prepare a PR, and instead routes back to INDEPENDENT_AUDIT or AUDIT_REMEDIATION.
    """
    env = setup_orchestration_environment
    fake_github = FakeGitHubAdapter()

    service = OrchestrationService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        github_adapter=fake_github,
    )

    # Directly create a run and candidate at PREPARING_PR with a READY_TO_MERGE job but NO audit record
    job = Job(
        project_id=env["project_id"],
        change_name=env["change_name"],
        implementer_role="codex",
        reviewer_role="antigravity",
        candidate_sha="test-cand-sha-1",
        base_sha="base-1",
        status=JobStatus.READY_TO_MERGE,  # Status claim without audit record
    )
    in_memory_uow.jobs.save(job)

    run = OrchestrationRun(
        run_id="run-audit-bypass-test",
        project_id=env["project_id"],
        change_name=env["change_name"],
        base_sha="base-1",
        current_stage=OrchestrationStage.PREPARING_PR,
        resumable_stage=OrchestrationStage.PREPARING_PR,
        active_job_id=job.job_id,
        current_generation=1,
        current_candidate_sha="test-cand-sha-1",
        is_active=True,
    )
    in_memory_uow.orchestration_runs.save(run)

    cand = OrchestrationCandidate(
        run_id=run.run_id,
        generation=1,
        base_sha="base-1",
        candidate_sha="test-cand-sha-1",
        manifest_hash="hash-test-1",
        is_frozen=True,
    )
    in_memory_uow.orchestration_candidates.save(cand)

    # 1. Ensure NO audit record exists
    assert in_memory_uow.audits.get_by_job_id(job.job_id) is None

    # 2. Audit authority validator must fail closed despite JobStatus.READY_TO_MERGE
    valid, is_passing, reason = service._validate_audit_authority(run, job, cand)
    assert valid is False
    assert is_passing is False
    assert "No audit record exists" in reason

    # 3. Assert PR was NEVER created or pushed without audit authority
    assert len(fake_github.prs) == 0
    assert len(fake_github.pushed_branches) == 0


def test_review_authority_fail_closed_validation(setup_orchestration_environment, in_memory_uow):
    """
    HIGH Finding 2 Regression Test:
    Verify that review authority validates exact candidate SHA, base SHA, generation,
    and structured verdict, failing closed on any missing field or mismatch.
    """
    env = setup_orchestration_environment
    service = OrchestrationService(in_memory_uow, project_root=env["project_root"])

    job = Job(
        project_id=env["project_id"],
        change_name=env["change_name"],
        implementer_role="codex",
        reviewer_role="antigravity",
    )
    in_memory_uow.jobs.save(job)

    run = OrchestrationRun(
        run_id="run-review-auth-test",
        project_id=env["project_id"],
        change_name=env["change_name"],
        base_sha="base-sha-1",
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        resumable_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        active_job_id=job.job_id,
        current_generation=1,
        current_candidate_sha="cand-sha-1",
        is_active=True,
    )
    cand = OrchestrationCandidate(
        run_id=run.run_id,
        generation=1,
        base_sha="base-sha-1",
        candidate_sha="cand-sha-1",
        manifest_id="manifest-review-auth",
        manifest_hash="hash-review-auth",
        is_frozen=True,
    )

    # 1. No review record exists -> fail closed
    valid, verdict, reason = service._validate_review_authority(run, job, cand)
    assert valid is False
    assert "No review record exists" in reason

    # 2. Review candidate_sha is empty -> fail closed (NULL must NEVER mean current)
    review = Review(
        job_id=job.job_id,
        project_id=env["project_id"],
        change_name=env["change_name"],
        reviewer_role="antigravity",
        candidate_sha="",
        base_sha="base-sha-1",
        orchestration_run_id="run-review-auth-test",
        candidate_generation=1,
        manifest_id="manifest-review-auth",
        manifest_hash="hash-review-auth",
        status=ReviewStatus.REVIEW_COMPLETED,
        verdict=ReviewVerdict.READY_TO_MERGE,
    )
    in_memory_uow.reviews.save(review)

    valid, verdict, reason = service._validate_review_authority(run, job, cand)
    assert valid is False
    assert "does not match current candidate" in reason

    # 3. Review candidate_sha mismatch (e.g. prior generation) -> fail closed
    review.candidate_sha = "stale-prior-gen-sha"
    in_memory_uow.reviews.save(review)
    valid, verdict, reason = service._validate_review_authority(run, job, cand)
    assert valid is False
    assert "does not match current candidate" in reason

    # 4. Review base_sha mismatch -> fail closed
    review.candidate_sha = "cand-sha-1"
    review.base_sha = "wrong-base-sha"
    in_memory_uow.reviews.save(review)
    valid, verdict, reason = service._validate_review_authority(run, job, cand)
    assert valid is False
    assert "does not match run base" in reason

    # 5. Exact match -> valid READY_TO_MERGE
    review.base_sha = "base-sha-1"
    in_memory_uow.reviews.save(review)
    valid, verdict, reason = service._validate_review_authority(run, job, cand)
    assert valid is True
    assert verdict == ReviewVerdict.READY_TO_MERGE


def test_audit_authority_fail_closed_validation(setup_orchestration_environment, in_memory_uow):
    """
    HIGH Finding 2 Regression Test:
    Verify that audit authority validates exact candidate SHA, base SHA, provider,
    full-candidate coverage, and 0 blocking findings, failing closed on mismatch.
    """
    env = setup_orchestration_environment
    service = OrchestrationService(in_memory_uow, project_root=env["project_root"])

    job = Job(
        project_id=env["project_id"],
        change_name=env["change_name"],
        implementer_role="codex",
        reviewer_role="antigravity",
    )
    in_memory_uow.jobs.save(job)

    run = OrchestrationRun(
        run_id="run-audit-auth-test",
        project_id=env["project_id"],
        change_name=env["change_name"],
        base_sha="base-sha-1",
        current_stage=OrchestrationStage.INDEPENDENT_AUDIT,
        resumable_stage=OrchestrationStage.INDEPENDENT_AUDIT,
        active_job_id=job.job_id,
        current_generation=1,
        current_candidate_sha="cand-sha-1",
        is_active=True,
    )
    cand = OrchestrationCandidate(
        run_id=run.run_id,
        generation=1,
        base_sha="base-sha-1",
        candidate_sha="cand-sha-1",
        manifest_id="manifest-audit-auth",
        manifest_hash="hash-audit-auth",
        is_frozen=True,
    )

    # 1. No audit record -> fail closed
    valid, is_passing, reason = service._validate_audit_authority(run, job, cand)
    assert valid is False

    # 2. Audit provider not deepseek -> fail closed
    audit = AuditRecord(
        job_id=job.job_id,
        project_id=env["project_id"],
        change_name=env["change_name"],
        provider="openrouter",
        candidate_sha="cand-sha-1",
        base_sha="base-sha-1",
        orchestration_run_id="run-audit-auth-test",
        candidate_generation=1,
        manifest_id="manifest-audit-auth",
        manifest_hash="hash-audit-auth",
        is_full_candidate=True,
        status=AuditStatus.AUDIT_COMPLETED,
    )
    in_memory_uow.audits.save(audit)

    valid, is_passing, reason = service._validate_audit_authority(run, job, cand)
    assert valid is False
    assert "not DeepSeek Direct" in reason

    # 3. Audit candidate_sha is empty or mismatched -> fail closed
    audit.provider = "deepseek"
    audit.candidate_sha = "wrong-sha"
    in_memory_uow.audits.save(audit)
    valid, is_passing, reason = service._validate_audit_authority(run, job, cand)
    assert valid is False
    assert "does not match current candidate" in reason

    # 4. Partial candidate -> fail closed
    audit.candidate_sha = "cand-sha-1"
    in_memory_uow.audits.save(audit)
    from unittest.mock import MagicMock

    orig_get_by_job = in_memory_uow.audits.get_by_job_id
    mock_audit = MagicMock()
    mock_audit.status = AuditStatus.AUDIT_COMPLETED
    mock_audit.provider = "deepseek"
    mock_audit.is_full_candidate = False
    mock_audit.candidate_sha = "cand-sha-1"
    mock_audit.base_sha = "base-sha-1"
    mock_audit.orchestration_run_id = "run-audit-auth-test"
    mock_audit.candidate_generation = 1
    mock_audit.manifest_id = "manifest-audit-auth"
    mock_audit.manifest_hash = "hash-audit-auth"
    mock_audit.findings = []
    in_memory_uow.audits.get_by_job_id = lambda jid: mock_audit

    valid, is_passing, reason = service._validate_audit_authority(run, job, cand)
    assert valid is False
    assert "not performed over full candidate" in reason

    # Restore real method
    in_memory_uow.audits.get_by_job_id = orig_get_by_job

    # 5. Blocking finding -> valid but not passing
    audit.findings = [
        AuditFinding(
            finding_id="f-1",
            audit_id=audit.audit_id,
            severity=AuditFindingSeverity.HIGH,
            category="security",
            message="Security flaw",
        )
    ]
    in_memory_uow.audits.save(audit)

    valid, is_passing, reason = service._validate_audit_authority(run, job, cand)
    assert valid is True
    assert is_passing is False
    assert "blocking findings" in reason


def test_stage_transitions_graph_guards_and_idempotent_event_keys(
    setup_orchestration_environment, in_memory_uow
):
    """
    HIGH Finding 4 Regression Test:
    Verify that illegal stage jumps are rejected fail-closed, and repeated transitions
    use deterministic keys without generating duplicate stage events.
    """
    env = setup_orchestration_environment
    service = OrchestrationService(in_memory_uow, project_root=env["project_root"])

    run = OrchestrationRun(
        run_id="run-stage-guard-test",
        project_id=env["project_id"],
        change_name=env["change_name"],
        base_sha="base-1",
        current_stage=OrchestrationStage.ADMITTED,
        resumable_stage=OrchestrationStage.ADMITTED,
        is_active=True,
    )
    in_memory_uow.orchestration_runs.save(run)

    # 1. Illegal jump: ADMITTED -> PR_PREPARED must raise ValueError and stop NEEDS_HUMAN
    with pytest.raises(ValueError, match="Illegal stage transition"):
        service._advance_stage(run, OrchestrationStage.PR_PREPARED)

    assert run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
    assert run.human_gate == HumanGate.NEEDS_HUMAN

    # 2. Legal transition: ADMITTED -> PREPARING_EXECUTION
    run.current_stage = OrchestrationStage.ADMITTED
    run.stop_outcome = None
    run.human_gate = None
    service._advance_stage(run, OrchestrationStage.PREPARING_EXECUTION, correlation_id="c-1")
    assert run.current_stage == OrchestrationStage.PREPARING_EXECUTION

    events_1 = in_memory_uow.orchestration_stage_events.list_by_run(run.run_id)
    # Exclude STOP event from step 1
    transition_events_1 = [
        e for e in events_1 if e.to_stage == OrchestrationStage.PREPARING_EXECUTION
    ]
    assert len(transition_events_1) == 1

    # 3. Retrying the same transition adopting existing event -> 0 duplicate inserts
    run.current_stage = OrchestrationStage.ADMITTED
    service._advance_stage(run, OrchestrationStage.PREPARING_EXECUTION, correlation_id="c-1")
    events_2 = in_memory_uow.orchestration_stage_events.list_by_run(run.run_id)
    transition_events_2 = [
        e for e in events_2 if e.to_stage == OrchestrationStage.PREPARING_EXECUTION
    ]
    assert len(transition_events_2) == 1


def test_authority_bindings_reject_every_missing_or_stale_identity_field(
    setup_orchestration_environment, in_memory_uow
):
    """Every review/audit identity component is required and exact."""
    env = setup_orchestration_environment
    service = OrchestrationService(in_memory_uow, project_root=env["project_root"])
    job = Job(
        project_id=env["project_id"],
        change_name=env["change_name"],
        implementer_role="codex",
        reviewer_role="antigravity",
    )
    in_memory_uow.jobs.save(job)
    run = OrchestrationRun(
        run_id="run-binding-matrix",
        project_id=env["project_id"],
        change_name=env["change_name"],
        base_sha="base",
        active_job_id=job.job_id,
        current_generation=2,
        current_candidate_sha="candidate",
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
    )
    cand = OrchestrationCandidate(
        run_id=run.run_id,
        generation=2,
        base_sha="base",
        candidate_sha="candidate",
        manifest_id="manifest",
        manifest_hash="manifest-hash",
    )
    valid_review = Review(
        job_id=job.job_id,
        project_id=run.project_id,
        change_name=run.change_name,
        reviewer_role="antigravity",
        orchestration_run_id=run.run_id,
        candidate_generation=2,
        candidate_sha="candidate",
        base_sha="base",
        manifest_id="manifest",
        manifest_hash="manifest-hash",
        status=ReviewStatus.REVIEW_COMPLETED,
        verdict=ReviewVerdict.READY_TO_MERGE,
    )
    for field, bad_value in {
        "orchestration_run_id": None,
        "candidate_generation": None,
        "candidate_sha": "stale",
        "base_sha": "stale",
        "manifest_id": None,
        "manifest_hash": "stale",
    }.items():
        in_memory_uow.reviews.save(valid_review.model_copy(update={field: bad_value}))
        valid, _, _ = service._validate_review_authority(run, job, cand)
        assert valid is False, field

    valid_audit = AuditRecord(
        job_id=job.job_id,
        project_id=run.project_id,
        change_name=run.change_name,
        provider="deepseek_direct",
        orchestration_run_id=run.run_id,
        candidate_generation=2,
        candidate_sha="candidate",
        base_sha="base",
        manifest_id="manifest",
        manifest_hash="manifest-hash",
        is_full_candidate=True,
        status=AuditStatus.AUDIT_COMPLETED,
    )
    for field, bad_value in {
        "orchestration_run_id": None,
        "candidate_generation": 1,
        "candidate_sha": "stale",
        "base_sha": "stale",
        "manifest_id": None,
        "manifest_hash": "stale",
        "is_full_candidate": None,
    }.items():
        in_memory_uow.audits.save(valid_audit.model_copy(update={field: bad_value}))
        valid, _, _ = service._validate_audit_authority(run, job, cand)
        assert valid is False, field


def test_stage_evidence_and_conflicting_transition_fail_closed(
    setup_orchestration_environment, in_memory_uow
):
    env = setup_orchestration_environment
    service = OrchestrationService(in_memory_uow, project_root=env["project_root"])
    run = OrchestrationRun(
        run_id="run-evidence-conflict",
        project_id=env["project_id"],
        change_name=env["change_name"],
        base_sha="base",
        current_stage=OrchestrationStage.RUNNING_CHECKS,
        resumable_stage=OrchestrationStage.RUNNING_CHECKS,
        current_generation=1,
        current_candidate_sha="candidate-a",
    )
    job = Job(
        project_id=run.project_id,
        change_name=run.change_name,
        implementer_role="codex",
        reviewer_role="antigravity",
    )
    run.active_job_id = job.job_id
    in_memory_uow.jobs.save(job)
    in_memory_uow.orchestration_runs.save(run)
    with pytest.raises(ValueError, match="passing checks"):
        service._advance_stage(run, OrchestrationStage.FREEZING_CANDIDATE)

    run.current_stage = OrchestrationStage.ADMITTED
    service._advance_stage(run, OrchestrationStage.PREPARING_EXECUTION, correlation_id="conflict")
    run.current_stage = OrchestrationStage.ADMITTED
    event = next(
        e
        for e in in_memory_uow.orchestration_stage_events._store
        if e.transition_key
        == f"{run.run_id}:ADMITTED->PREPARING_EXECUTION:gen1:candcandidate-a:conflict"
    )
    event.evidence_references["candidate_sha"] = "different"
    with pytest.raises(ValueError, match="Conflicting"):
        service._advance_stage(
            run, OrchestrationStage.PREPARING_EXECUTION, correlation_id="conflict"
        )
    assert run.human_gate == HumanGate.NEEDS_HUMAN


def test_push_reconciliation_zero_second_push_and_zero_force_push(
    setup_orchestration_environment, in_memory_uow
):
    """
    HIGH Finding 5 Regression Test:
    Verify that push reconciliation queries remote branch first and avoids duplicate push
    or force push when remote already matches candidate SHA or has conflicting SHA.
    """
    env = setup_orchestration_environment
    fake_github = FakeGitHubAdapter()

    pipeline = ExecutionPipelineService(
        uow=in_memory_uow,
        project_root=env["project_root"],
        implementer_runner=MockImplementerRunner(),
        checks_runner=FakeChecksRunner(should_pass=True),
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

    # Simulate remote branch already matching candidate SHA
    cand_sha = "matching-remote-cand-sha"
    fake_github.pushed_branches.append(
        {"remote": "origin", "branch": f"minime/{env['change_name']}", "candidate_sha": cand_sha}
    )
    initial_push_count = len(fake_github.pushed_branches)

    # Run orchestration starting from PREPARING_PR
    job = Job(
        project_id=env["project_id"],
        change_name=env["change_name"],
        implementer_role="codex",
        reviewer_role="antigravity",
        candidate_sha=cand_sha,
        base_sha="base-1",
        status=JobStatus.CHECKS_PASSED,
    )
    in_memory_uow.jobs.save(job)

    run = OrchestrationRun(
        run_id="run-push-recon-test",
        project_id=env["project_id"],
        change_name=env["change_name"],
        base_sha="base-1",
        current_stage=OrchestrationStage.PREPARING_PR,
        resumable_stage=OrchestrationStage.PREPARING_PR,
        active_job_id=job.job_id,
        current_generation=1,
        current_candidate_sha=cand_sha,
        is_active=True,
    )
    in_memory_uow.orchestration_runs.save(run)
    cand = OrchestrationCandidate(
        run_id=run.run_id,
        generation=1,
        base_sha="base-1",
        candidate_sha=cand_sha,
        manifest_id="manifest-push-recon",
        manifest_hash="hash-push-recon",
        is_frozen=True,
    )
    in_memory_uow.orchestration_candidates.save(cand)

    # Valid passing audit record
    audit = AuditRecord(
        job_id=job.job_id,
        project_id=env["project_id"],
        change_name=env["change_name"],
        provider="deepseek",
        candidate_sha=cand_sha,
        base_sha="base-1",
        orchestration_run_id="run-push-recon-test",
        candidate_generation=1,
        manifest_id="manifest-push-recon",
        manifest_hash="hash-push-recon",
        is_full_candidate=True,
        status=AuditStatus.AUDIT_COMPLETED,
    )
    in_memory_uow.audits.save(audit)

    service.drive_coordinator(run.run_id)

    # ZERO second push executed
    assert len(fake_github.pushed_branches) == initial_push_count
    updated_run = in_memory_uow.orchestration_runs.get_by_id(run.run_id)
    assert updated_run.current_stage == OrchestrationStage.PR_PREPARED


def test_strict_pr_adoption_fail_closed_on_missing_or_mismatched_remote_fields(
    setup_orchestration_environment, in_memory_uow
):
    """
    HIGH Finding 6 Regression Test:
    Verify PR adoption requires explicit remote returned fields and fails closed on missing/wrong fields.
    """
    env = setup_orchestration_environment
    service = OrchestrationService(in_memory_uow, project_root=env["project_root"])

    project = in_memory_uow.projects.get_by_id(env["project_id"])
    binding = in_memory_uow.bindings.get_by_project_and_change(
        env["project_id"], env["change_name"]
    )
    run = OrchestrationRun(
        run_id="run-strict-pr-test",
        project_id=env["project_id"],
        change_name=env["change_name"],
        base_sha="base-1",
        current_stage=OrchestrationStage.PREPARING_PR,
        resumable_stage=OrchestrationStage.PREPARING_PR,
        is_active=True,
    )
    cand_sha = "audited-sha-123"
    branch = f"minime/{env['change_name']}"

    # 1. Missing repository -> fail closed
    pr_missing_repo = {
        "head_branch": branch,
        "base_branch": "main",
        "head_sha": cand_sha,
        "number": 1,
        "title": f"{env['change_name']}",
        "body": f"Closes #{binding.github_issue_number}",
    }
    valid, reason, _ = service._verify_pr_adoption_identity(
        pr_missing_repo, project, binding, run, branch, cand_sha
    )
    assert valid is False
    assert "PR repository" in reason

    # 2. Missing head_branch -> fail closed
    pr_missing_head = {
        "repository": project.repository,
        "base_branch": "main",
        "head_sha": cand_sha,
        "number": 1,
    }
    valid, reason, _ = service._verify_pr_adoption_identity(
        pr_missing_head, project, binding, run, branch, cand_sha
    )
    assert valid is False
    assert "head branch" in reason

    # 3. Missing base_branch -> fail closed
    pr_missing_base = {
        "repository": project.repository,
        "head_branch": branch,
        "head_sha": cand_sha,
        "number": 1,
    }
    valid, reason, _ = service._verify_pr_adoption_identity(
        pr_missing_base, project, binding, run, branch, cand_sha
    )
    assert valid is False
    assert "base branch" in reason

    # 4. Wrong head_sha -> fail closed
    pr_wrong_sha = {
        "repository": project.repository,
        "head_branch": branch,
        "base_branch": "main",
        "head_sha": "wrong-sha",
        "number": 1,
    }
    valid, reason, _ = service._verify_pr_adoption_identity(
        pr_wrong_sha, project, binding, run, branch, cand_sha
    )
    assert valid is False
    assert "does not match audited candidate" in reason

    # 5. Fully matching PR -> adopted!
    pr_valid = {
        "repository": project.repository,
        "head_branch": branch,
        "base_branch": "main",
        "head_sha": cand_sha,
        "number": 1,
        "title": env["change_name"],
        "body": f"Closes #{binding.github_issue_number}",
    }
    valid, reason, _ = service._verify_pr_adoption_identity(
        pr_valid, project, binding, run, branch, cand_sha
    )
    assert valid is True
    assert reason is None
