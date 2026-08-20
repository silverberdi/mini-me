"""Tests for 003 complementary review pipeline, policy, runner, verdict parser, and observability."""

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from minime.api.app import app, get_uow
from minime.cli.main import app as cli_app
from minime.domain.enums import (
    ChangeStatus,
    EventType,
    FindingSeverity,
    JobStatus,
    ReadinessState,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.models import Change, CheckResult, Job, Project, Review, ReviewFinding
from minime.services.candidate_integrity import (
    resolve_base_branch_sha,
    validate_post_review_integrity,
    validate_pre_review_integrity,
)
from minime.services.complementary_policy import validate_complementary_pair
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.implementer_runner import MockImplementerRunner
from minime.services.review_verdict_parser import (
    MalformedReviewOutputError,
    parse_review_verdict,
)
from minime.services.reviewer_contract import build_reviewer_prompt
from minime.services.reviewer_runner import MockReviewerRunner
from minime.services.reviewer_view import ReviewerViewManager, SymlinkInCandidateError
from minime.services.worktree_manager import WorktreeInfo


class GitFakeWorktreeManager:
    def __init__(self, root: Path):
        self.root = root
        self.created_paths: dict[str, Path] = {}
        self.cleaned: list[str] = []

    async def create_worktree(
        self, job_id: str, change_name: str, base_branch: str
    ) -> WorktreeInfo:
        del change_name, base_branch
        path = self.root / ".minime" / "worktrees" / job_id
        path.mkdir(parents=True, exist_ok=True)
        if (self.root / "openspec").exists():
            shutil.copytree(self.root / "openspec", path / "openspec")
        else:
            (path / "openspec").mkdir(parents=True, exist_ok=True)

        subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(path), check=True, capture_output=True)
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
            cwd=str(path),
            check=True,
            capture_output=True,
        )
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            check=True,
            capture_output=True,
            text=True,
        )
        head_sha = proc.stdout.strip()
        self.created_paths[job_id] = path
        return WorktreeInfo(
            path=path, branch_name=f"minime/test-{job_id}", base_sha=head_sha
        )

    async def current_sha(self, worktree_path: str | Path) -> str:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree_path),
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    async def cleanup_worktree(self, job_id: str) -> None:
        self.cleaned.append(job_id)


def setup_project_and_change(
    uow,
    tmp_path: Path,
    implementer: str = "codex",
    reviewer: str = "antigravity",
    change_name: str = "synthetic-review-change",
) -> None:
    change_dir = tmp_path / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
    (change_dir / "tasks.md").write_text("# Tasks\n- [x] 1.1 Done\n", encoding="utf-8")
    (change_dir / "design.md").write_text("# Design\n", encoding="utf-8")
    (change_dir / "specs" / "feature").mkdir(parents=True, exist_ok=True)
    (change_dir / "specs" / "feature" / "spec.md").write_text(
        "# Spec\n", encoding="utf-8"
    )

    project = Project(
        project_id="review-test-project",
        display_name="Review Test",
        repository="silverberdi/review-test",
        base_branch="main",
        openspec_path="openspec",
        implementer=implementer,
        reviewer=reviewer,
        checks=[{"name": "test-check", "command": f"{sys.executable} -c 'print(1)'"}],
    )
    change = Change(
        project_id="review-test-project",
        name=change_name,
        status=ChangeStatus.READY,
        last_readiness_status=ReadinessState.READY,
    )
    uow.projects.save(project)
    uow.changes.save(change)


# ==============================================================================
# Finding 1 Tests: Read-Only Reviewer Execution Boundary & Symlink Safety
# ==============================================================================


def test_readonly_reviewer_view_denies_writes_and_cleans_up(tmp_path):
    source_dir = tmp_path / "candidate_worktree"
    source_dir.mkdir()
    (source_dir / "src").mkdir()
    (source_dir / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    (source_dir / "README.md").write_text("# Title", encoding="utf-8")

    view_mgr = ReviewerViewManager(tmp_path)
    view_path = view_mgr.create_readonly_view(source_dir, "view-job-1")

    assert view_path.exists()
    # 1. Verify read access works
    assert (view_path / "src" / "main.py").read_text(encoding="utf-8") == "print('hello')"
    assert (view_path / "README.md").read_text(encoding="utf-8") == "# Title"

    # 2. Verify write attempts to existing file fail
    with pytest.raises((PermissionError, OSError)):
        (view_path / "src" / "main.py").write_text("malicious mutation", encoding="utf-8")

    # 3. Verify write attempts to create new file fail
    with pytest.raises((PermissionError, OSError)):
        (view_path / "new_file.txt").write_text("new file", encoding="utf-8")

    # 4. Verify directory creation fails
    with pytest.raises((PermissionError, OSError)):
        (view_path / "new_dir").mkdir()

    # 5. Verify source worktree remains untouched
    assert (source_dir / "src" / "main.py").read_text(encoding="utf-8") == "print('hello')"
    assert not (source_dir / "new_file.txt").exists()

    # 6. Verify deterministic cleanup
    view_mgr.cleanup_readonly_view("view-job-1")
    assert not view_path.exists()


def test_symlink_in_candidate_file_rejected(tmp_path):
    source = tmp_path / "candidate_with_file_symlink"
    source.mkdir()
    (source / "real.txt").write_text("real", encoding="utf-8")
    os.symlink(source / "real.txt", source / "link.txt")

    view_mgr = ReviewerViewManager(tmp_path)
    with pytest.raises(SymlinkInCandidateError, match="prohibited symlink"):
        view_mgr.create_readonly_view(source, "v-file-symlink")


def test_symlink_in_candidate_directory_rejected(tmp_path):
    source = tmp_path / "candidate_with_dir_symlink"
    source.mkdir()
    (source / "real_dir").mkdir()
    os.symlink(source / "real_dir", source / "link_dir", target_is_directory=True)

    view_mgr = ReviewerViewManager(tmp_path)
    with pytest.raises(SymlinkInCandidateError, match="prohibited symlink"):
        view_mgr.create_readonly_view(source, "v-dir-symlink")


def test_symlink_to_tmp_rejected(tmp_path):
    source = tmp_path / "candidate_with_tmp_symlink"
    source.mkdir()
    os.symlink("/tmp", source / "escape_tmp", target_is_directory=True)

    view_mgr = ReviewerViewManager(tmp_path)
    with pytest.raises(SymlinkInCandidateError, match="prohibited symlink"):
        view_mgr.create_readonly_view(source, "v-tmp-symlink")


def test_broken_symlink_rejected(tmp_path):
    source = tmp_path / "candidate_with_broken_symlink"
    source.mkdir()
    os.symlink(source / "nonexistent_target.txt", source / "broken_link.txt")

    view_mgr = ReviewerViewManager(tmp_path)
    with pytest.raises(SymlinkInCandidateError, match="prohibited symlink"):
        view_mgr.create_readonly_view(source, "v-broken-symlink")


@pytest.mark.asyncio
async def test_reviewer_never_starts_if_symlink_detected(in_memory_uow, tmp_path):
    setup_project_and_change(in_memory_uow, tmp_path)

    # Worktree manager that plants a symlink before review
    class WorktreeWithSymlink(GitFakeWorktreeManager):
        async def create_worktree(self, job_id, change_name, base_branch):
            info = await super().create_worktree(job_id, change_name, base_branch)
            os.symlink("/tmp", info.path / "tmp_escape", target_is_directory=True)
            return info

    reviewer_called = False

    class SpyReviewerRunner(MockReviewerRunner):
        async def run(self, worktree_path, prompt, timeout_seconds=3600):
            nonlocal reviewer_called
            reviewer_called = True
            return await super().run(worktree_path, prompt, timeout_seconds)

    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=SpyReviewerRunner(),
        worktree_manager=WorktreeWithSymlink(tmp_path),
    )

    job = await service.run_job("review-test-project", "synthetic-review-change")

    assert job.status == JobStatus.FAILED
    assert "prohibited symlink" in (job.error_message or "")
    assert reviewer_called is False


# ==============================================================================
# Finding 2 Tests: Authoritative Base Ref Precedence (origin/<base_branch>)
# ==============================================================================


def test_base_sha_origin_main_matching_allowed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=str(repo), check=True, capture_output=True)
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True)
    base_sha = proc.stdout.strip()

    # Set origin/main
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", base_sha], cwd=str(repo), check=True, capture_output=True)

    ok, err = validate_pre_review_integrity(
        worktree_path=repo,
        expected_candidate_sha=base_sha,
        expected_base_sha=base_sha,
        base_branch="main",
        repo_root_path=repo,
        checks_passed=True,
    )
    assert ok is True
    assert err is None


def test_base_sha_local_main_stale_origin_main_correct_allowed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "commit 1"], cwd=str(repo), check=True, capture_output=True)
    proc1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True)
    sha1 = proc1.stdout.strip()
    subprocess.run(["git", "branch", "-M", "main"], cwd=str(repo), check=True, capture_output=True)

    # Make a second commit for origin/main
    subprocess.run(["git", "commit", "--allow-empty", "-m", "commit 2"], cwd=str(repo), check=True, capture_output=True)
    proc2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True)
    sha2 = proc2.stdout.strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", sha2], cwd=str(repo), check=True, capture_output=True)

    # Reset local main back to sha1 (stale local main)
    subprocess.run(["git", "reset", "--hard", sha1], cwd=str(repo), check=True, capture_output=True)

    # Expected base SHA is sha2 (origin/main) -> should be allowed based on authoritative origin/main
    ok, err = validate_pre_review_integrity(
        worktree_path=repo,
        expected_candidate_sha=sha1,
        expected_base_sha=sha2,
        base_branch="main",
        repo_root_path=repo,
        checks_passed=True,
    )
    assert ok is True
    assert err is None


def test_base_sha_local_main_only_blocked_when_origin_main_differs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "commit 1"], cwd=str(repo), check=True, capture_output=True)
    proc1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True)
    sha1 = proc1.stdout.strip()
    subprocess.run(["git", "branch", "-M", "main"], cwd=str(repo), check=True, capture_output=True)

    subprocess.run(["git", "commit", "--allow-empty", "-m", "commit 2"], cwd=str(repo), check=True, capture_output=True)
    proc2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True)
    sha2 = proc2.stdout.strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", sha2], cwd=str(repo), check=True, capture_output=True)

    # If expected_base_sha matches only local main (sha1), it MUST be blocked because origin/main (sha2) is authoritative
    ok, err = validate_pre_review_integrity(
        worktree_path=repo,
        expected_candidate_sha=sha2,
        expected_base_sha=sha1,
        base_branch="main",
        repo_root_path=repo,
        checks_passed=True,
    )
    assert ok is False
    assert "Base SHA mismatch" in (err or "")


def test_base_sha_missing_origin_main_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(repo), check=True, capture_output=True)
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True)
    current_sha = proc.stdout.strip()

    # No origin/main created
    ok, err = validate_pre_review_integrity(
        worktree_path=repo,
        expected_candidate_sha=current_sha,
        expected_base_sha=current_sha,
        base_branch="main",
        repo_root_path=repo,
        checks_passed=True,
    )
    assert ok is False
    assert "Pre-review base ref resolution failure" in (err or "")


def test_resolve_base_branch_sha_direct(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # Missing origin/main
    sha, err = resolve_base_branch_sha(repo, "main")
    assert sha is None
    assert "Failed to resolve authoritative base ref" in (err or "")

    nonexistent = tmp_path / "nonexistent"
    sha, err = resolve_base_branch_sha(nonexistent, "main")
    assert sha is None
    assert "does not exist" in (err or "")


def test_post_review_integrity_direct(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(repo), check=True, capture_output=True)
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True)
    current_sha = proc.stdout.strip()

    # Clean
    ok, err = validate_post_review_integrity(repo, current_sha)
    assert ok is True
    assert err is None

    # Dirty worktree
    (repo / "dirty.txt").write_text("modified", encoding="utf-8")
    ok, err = validate_post_review_integrity(repo, current_sha)
    assert ok is False
    assert "Unauthorized reviewer mutation" in (err or "")

    # Nonexistent path
    ok, err = validate_post_review_integrity(tmp_path / "nonexistent", current_sha)
    assert ok is False
    assert "does not exist" in (err or "")


# ==============================================================================
# Finding 3 Tests: Ambiguous Structured Review Output & Strict Parsing
# ==============================================================================


def test_review_verdict_parser_success_ready_to_merge():
    output = """
Some thinking...
```json
{
  "verdict": "READY_TO_MERGE",
  "summary": "All acceptance criteria verified and checks passed.",
  "findings": []
}
```
Final comment.
"""
    result = parse_review_verdict(output)
    assert result.verdict == ReviewVerdict.READY_TO_MERGE
    assert result.summary == "All acceptance criteria verified and checks passed."
    assert result.findings == []


def test_review_verdict_parser_success_changes_required():
    output = """
```json
{
  "verdict": "CHANGES_REQUIRED",
  "summary": "Found one blocker and one minor issue.",
  "findings": [
    {
      "severity": "BLOCKER",
      "location": "src/auth.py:45",
      "violated_requirement": "Password hashing must use Argon2",
      "expected_correction": "Replace SHA256 with Argon2 password hasher"
    },
    {
      "severity": "MINOR",
      "location": "README.md",
      "violated_requirement": "Docs update",
      "expected_correction": "Add command example"
    }
  ]
}
```
"""
    result = parse_review_verdict(output)
    assert result.verdict == ReviewVerdict.CHANGES_REQUIRED
    assert len(result.findings) == 2
    assert result.findings[0].severity == FindingSeverity.BLOCKER
    assert result.findings[0].location == "src/auth.py:45"
    assert result.findings[1].severity == FindingSeverity.MINOR


def test_review_verdict_parser_conflicting_verdicts_rejected():
    output = """
```json
{
  "verdict": "READY_TO_MERGE",
  "summary": "All looks good at first glance.",
  "findings": []
}
```
Wait, I found an issue:
```json
{
  "verdict": "CHANGES_REQUIRED",
  "summary": "Actually broken.",
  "findings": [
    {
      "severity": "BLOCKER",
      "location": "src/main.py",
      "violated_requirement": "Must not fail",
      "expected_correction": "Fix it"
    }
  ]
}
```
"""
    with pytest.raises(MalformedReviewOutputError, match="Ambiguous reviewer output"):
        parse_review_verdict(output)


def test_review_verdict_parser_duplicate_verdicts_rejected():
    output = """
```json
{
  "verdict": "READY_TO_MERGE",
  "summary": "First block.",
  "findings": []
}
```
```json
{
  "verdict": "READY_TO_MERGE",
  "summary": "Duplicate block.",
  "findings": []
}
```
"""
    with pytest.raises(MalformedReviewOutputError, match="Ambiguous reviewer output"):
        parse_review_verdict(output)


def test_review_verdict_parser_valid_plus_malformed_attempt_rejected():
    output = """
```json
{
  "verdict": "READY_TO_MERGE",
  "summary": "First valid block.",
  "findings": []
}
```
```json
{
  "verdict": "MALFORMED_JSON_ATTEMPT",
  "summary":
}
```
"""
    with pytest.raises(MalformedReviewOutputError, match="Ambiguous reviewer output"):
        parse_review_verdict(output)


def test_review_verdict_parser_prose_only_rejected():
    output = "Overall assessment: The code is ready and we should set verdict to READY_TO_MERGE."
    with pytest.raises(MalformedReviewOutputError, match="No structured"):
        parse_review_verdict(output)


def test_review_verdict_parser_unsupported_severity_rejected():
    output = json.dumps(
        {
            "verdict": "CHANGES_REQUIRED",
            "summary": "Has findings",
            "findings": [
                {
                    "severity": "CRITICAL_UNSUPPORTED",
                    "location": "src/app.py",
                    "violated_requirement": "Req A",
                    "expected_correction": "Fix A",
                }
            ],
        }
    )
    with pytest.raises(MalformedReviewOutputError):
        parse_review_verdict(f"```json\n{output}\n```")


def test_review_verdict_parser_missing_required_fields_rejected():
    output = json.dumps(
        {
            "verdict": "CHANGES_REQUIRED",
            "summary": "Has findings",
            "findings": [
                {
                    "severity": "BLOCKER",
                    "location": "src/app.py",
                    "violated_requirement": "",
                    "expected_correction": "Fix A",
                }
            ],
        }
    )
    with pytest.raises(MalformedReviewOutputError):
        parse_review_verdict(f"```json\n{output}\n```")


# ==============================================================================
# End-to-End Pipeline & Observability Tests
# ==============================================================================


def test_complementary_policy_validation():
    ok, err = validate_complementary_pair("codex", "antigravity")
    assert ok is True
    assert err is None

    ok, err = validate_complementary_pair("antigravity", "codex")
    assert ok is True
    assert err is None

    ok, err = validate_complementary_pair("codex", "codex")
    assert ok is False
    assert "Self-review is prohibited" in (err or "")

    ok, err = validate_complementary_pair("antigravity", "antigravity")
    assert ok is False
    assert "Self-review is prohibited" in (err or "")

    ok, err = validate_complementary_pair("unknown", "antigravity")
    assert ok is False
    assert "Unsupported implementer" in (err or "")


def test_reviewer_prompt_builder(tmp_path):
    project = Project(
        project_id="p1",
        display_name="Project 1",
        repository="silverberdi/p1",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )
    change_dir = tmp_path / "openspec" / "changes" / "change-abc"
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text("# Feature Why", encoding="utf-8")
    (change_dir / "tasks.md").write_text("- [x] 1.1 Do something", encoding="utf-8")

    check_res = [
        CheckResult(
            job_id="j1",
            check_name="lint",
            command="ruff check",
            exit_code=0,
            duration_ms=50,
            output_snippet="clean",
        )
    ]
    prompt = build_reviewer_prompt(
        project=project,
        change_name="change-abc",
        job_id="j1",
        candidate_sha="cand-sha-123",
        base_sha="base-sha-456",
        candidate_worktree_path=tmp_path,
        checks_results=check_res,
    )

    assert "change-abc" in prompt
    assert "cand-sha-123" in prompt
    assert "base-sha-456" in prompt
    assert "silverberdi/p1" in prompt
    assert "READY_TO_MERGE" in prompt
    assert "CHANGES_REQUIRED" in prompt
    assert "READ-ONLY" in prompt


@pytest.mark.asyncio
async def test_review_pipeline_ready_to_merge_flow(in_memory_uow, tmp_path):
    setup_project_and_change(in_memory_uow, tmp_path)
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(stdout=["implementation done"]),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                '```json\n{"verdict": "READY_TO_MERGE", "summary": "All good", "findings": []}\n```'
            ]
        ),
        worktree_manager=GitFakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("review-test-project", "synthetic-review-change")

    assert job.status == JobStatus.READY_TO_MERGE
    review = in_memory_uow.reviews.get_by_job_id(job.job_id)
    assert review is not None
    assert review.status == ReviewStatus.REVIEW_COMPLETED
    assert review.verdict == ReviewVerdict.READY_TO_MERGE
    assert review.reviewer_role == "antigravity"
    assert review.candidate_sha == job.candidate_sha
    events = in_memory_uow.events.list_events(
        project_id="review-test-project", change_id="synthetic-review-change"
    )
    event_types = [e.event_type for e in events]
    assert EventType.JOB_REVIEW_RUNNING in event_types
    assert EventType.JOB_READY_TO_MERGE in event_types


@pytest.mark.asyncio
async def test_review_pipeline_changes_required_flow(in_memory_uow, tmp_path):
    setup_project_and_change(in_memory_uow, tmp_path)
    reviewer_output = json.dumps(
        {
            "verdict": "CHANGES_REQUIRED",
            "summary": "Found broken spec requirement.",
            "findings": [
                {
                    "severity": "BLOCKER",
                    "location": "src/main.py:10",
                    "violated_requirement": "Must return exit 0",
                    "expected_correction": "Fix returncode handling",
                }
            ],
        }
    )
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=MockReviewerRunner(stdout=[f"```json\n{reviewer_output}\n```"]),
        worktree_manager=GitFakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("review-test-project", "synthetic-review-change")

    assert job.status == JobStatus.CHANGES_REQUIRED
    review = in_memory_uow.reviews.get_by_job_id(job.job_id)
    assert review is not None
    assert review.status == ReviewStatus.REVIEW_COMPLETED
    assert review.verdict == ReviewVerdict.CHANGES_REQUIRED
    findings = in_memory_uow.review_findings.list_by_review(review.review_id)
    assert len(findings) == 1
    assert findings[0].severity == FindingSeverity.BLOCKER
    assert findings[0].location == "src/main.py:10"
    events = in_memory_uow.events.list_events(
        project_id="review-test-project", change_id="synthetic-review-change"
    )
    assert any(e.event_type == EventType.JOB_CHANGES_REQUIRED for e in events)


@pytest.mark.asyncio
async def test_review_pipeline_timeout_fails_safely(in_memory_uow, tmp_path):
    setup_project_and_change(in_memory_uow, tmp_path)
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=MockReviewerRunner(timed_out=True),
        worktree_manager=GitFakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("review-test-project", "synthetic-review-change")

    assert job.status == JobStatus.FAILED
    review = in_memory_uow.reviews.get_by_job_id(job.job_id)
    assert review is not None
    assert review.status == ReviewStatus.REVIEW_TIMED_OUT
    events = in_memory_uow.events.list_events(
        project_id="review-test-project", change_id="synthetic-review-change"
    )
    assert any(e.event_type == EventType.REVIEW_TIMEOUT for e in events)


@pytest.mark.asyncio
async def test_review_pipeline_malformed_output_fails_safely(in_memory_uow, tmp_path):
    setup_project_and_change(in_memory_uow, tmp_path)
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=MockReviewerRunner(
            stdout=["Invalid output without json payload"]
        ),
        worktree_manager=GitFakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("review-test-project", "synthetic-review-change")

    assert job.status == JobStatus.FAILED
    review = in_memory_uow.reviews.get_by_job_id(job.job_id)
    assert review is not None
    assert review.status == ReviewStatus.REVIEW_FAILED
    events = in_memory_uow.events.list_events(
        project_id="review-test-project", change_id="synthetic-review-change"
    )
    assert any(e.event_type == EventType.MALFORMED_REVIEW_OUTPUT for e in events)


@pytest.mark.asyncio
async def test_review_pipeline_secret_redaction(in_memory_uow, tmp_path):
    setup_project_and_change(in_memory_uow, tmp_path)
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=MockReviewerRunner(
            stdout=[
                "Reviewing apiKey=secret_live_key_999",
                '```json\n{"verdict": "READY_TO_MERGE", "summary": "ok", "findings": []}\n```',
            ]
        ),
        worktree_manager=GitFakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("review-test-project", "synthetic-review-change")

    assert job.status == JobStatus.READY_TO_MERGE
    logs = in_memory_uow.job_logs.list_by_job(job.job_id)
    assert any("[REDACTED]" in log.message for log in logs)


def test_fastapi_review_endpoints(in_memory_uow):
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    job = Job(
        job_id="job-123",
        project_id="p1",
        change_name="c1",
        implementer_role="codex",
        status=JobStatus.CHANGES_REQUIRED,
        candidate_sha="cand-sha",
        base_sha="base-sha",
    )
    review = Review(
        review_id="rev-123",
        job_id="job-123",
        project_id="p1",
        change_name="c1",
        reviewer_role="antigravity",
        candidate_sha="cand-sha",
        base_sha="base-sha",
        status=ReviewStatus.REVIEW_COMPLETED,
        verdict=ReviewVerdict.CHANGES_REQUIRED,
        summary="Needs work",
    )
    finding = ReviewFinding(
        finding_id="f-1",
        review_id="rev-123",
        severity=FindingSeverity.BLOCKER,
        location="src/main.py:1",
        violated_requirement="Spec req 1",
        expected_correction="Fix it",
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.reviews.save(review)
    in_memory_uow.review_findings.save(finding)

    res = client.get("/jobs/job-123/review")
    assert res.status_code == 200
    data = res.json()
    assert data["review_id"] == "rev-123"
    assert data["verdict"] == "CHANGES_REQUIRED"
    assert len(data["findings"]) == 1
    assert data["findings"][0]["severity"] == "BLOCKER"

    # Nonexistent review
    res_404 = client.get("/jobs/job-nonexistent/review")
    assert res_404.status_code == 404
    app.dependency_overrides.clear()


def test_cli_jobs_review_command(in_memory_uow, monkeypatch):
    runner = CliRunner()

    @contextmanager
    def mock_session():
        yield None

    monkeypatch.setattr("minime.cli.main.db_manager.session", mock_session)
    monkeypatch.setattr("minime.cli.main.PostgresPersistenceUnitOfWork", lambda session: in_memory_uow)

    job = Job(
        job_id="job-cli",
        project_id="cli-project",
        change_name="cli-change",
        implementer_role="codex",
        status=JobStatus.CHANGES_REQUIRED,
        candidate_sha="sha123",
        base_sha="basesha",
    )
    review = Review(
        review_id="rev-cli",
        job_id="job-cli",
        project_id="cli-project",
        change_name="cli-change",
        reviewer_role="antigravity",
        candidate_sha="sha123",
        base_sha="basesha",
        status=ReviewStatus.REVIEW_COMPLETED,
        verdict=ReviewVerdict.CHANGES_REQUIRED,
        summary="Review findings present",
    )
    finding = ReviewFinding(
        finding_id="f-cli",
        review_id="rev-cli",
        severity=FindingSeverity.BLOCKER,
        location="src/cli.py",
        violated_requirement="Requirement X",
        expected_correction="Fix requirement X",
    )
    in_memory_uow.jobs.save(job)
    in_memory_uow.reviews.save(review)
    in_memory_uow.review_findings.save(finding)

    result = runner.invoke(cli_app, ["jobs", "review", "job-cli"])
    assert result.exit_code == 0
    assert "Review ID: rev-cli" in result.output
    assert "CHANGES_REQUIRED" in result.output
    assert "[BLOCKER] src/cli.py" in result.output
