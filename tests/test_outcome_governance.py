"""Tests for OutcomeGovernanceService outcome classification and progress evaluation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from minime.domain.enums import (
    BlockerValidationVerdict,
    ExecutionOutcome,
    ProgressClassification,
    ProviderResultClass,
)
from minime.domain.models import (
    BlockerClaim,
    CheckResult,
    NormalizedProviderResult,
)
from minime.services.openspec_tasks import OpenSpecTask, OpenSpecTaskTracker
from minime.services.outcome_governance import (
    CompletionVerificationResult,
    OutcomeGovernanceService,
    ProgressSignals,
)


def test_verify_completion_incomplete_tasks(tmp_path: Path):
    tracker = MagicMock(spec=OpenSpecTaskTracker)
    tracker.incomplete_tasks.return_value = [
        OpenSpecTask(task_id="1.1", text="Task 1", section="Phase 1", complete=False)
    ]
    service = OutcomeGovernanceService(task_tracker=tracker)

    res = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007-continuation",
        base_sha="abc123",
    )

    assert not res.is_complete
    assert "OpenSpec tasks incomplete" in (res.reason or "")
    assert len(res.incomplete_tasks) == 1


def test_verify_completion_no_modifications(tmp_path: Path):
    tracker = MagicMock(spec=OpenSpecTaskTracker)
    tracker.incomplete_tasks.return_value = []
    service = OutcomeGovernanceService(task_tracker=tracker)

    # Empty tmp directory has no git changes
    res = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007-continuation",
        base_sha="abc123",
    )

    assert not res.is_complete
    assert "No candidate file modifications" in (res.reason or "")


def test_verify_completion_failing_checks(tmp_path: Path):
    tracker = MagicMock(spec=OpenSpecTaskTracker)
    tracker.incomplete_tasks.return_value = []
    service = OutcomeGovernanceService(task_tracker=tracker)

    check_fail = CheckResult(
        result_id="chk-1",
        job_id="job-1",
        check_name="pytest",
        command="pytest",
        exit_code=1,
        duration_ms=100,
        output_snippet="FAILED",
    )

    res = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007-continuation",
        base_sha="abc123",
        check_results=[check_fail],
    )

    assert not res.is_complete


def test_verify_completion_candidate_sha_omitted_success_binds_actual_head(tmp_path: Path):
    """Test A: candidate_sha omitted + valid Git worktree HEAD -> completion succeeds, result.candidate_sha == actual HEAD."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "mod.py").write_text("hello")
    subprocess.run(["git", "add", "mod.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()

    tracker = MagicMock(spec=OpenSpecTaskTracker)
    tracker.incomplete_tasks.return_value = []
    service = OutcomeGovernanceService(task_tracker=tracker)

    res = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007-continuation",
        base_sha="abc123",
        candidate_sha=None,
    )
    assert res.is_complete
    assert res.candidate_sha == head_sha


def test_verify_completion_candidate_sha_omitted_head_resolution_failure_rejected(tmp_path: Path):
    """Test B: candidate_sha omitted + HEAD resolution failure -> completion rejected, candidate_sha=None."""
    # Non-git directory (tmp_path without git init)
    (tmp_path / "mod.py").write_text("hello")

    tracker = MagicMock(spec=OpenSpecTaskTracker)
    tracker.incomplete_tasks.return_value = []
    service = OutcomeGovernanceService(task_tracker=tracker)

    res = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007-continuation",
        base_sha="abc123",
        candidate_sha=None,
    )
    assert not res.is_complete
    assert res.candidate_sha is None
    assert "Worktree HEAD resolution failure" in (res.reason or "")


def test_verify_completion_candidate_sha_supplied_correctly_succeeds(tmp_path: Path):
    """Test C: candidate_sha supplied correctly -> succeeds, result uses actual verified HEAD."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "mod.py").write_text("hello")
    subprocess.run(["git", "add", "mod.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()

    tracker = MagicMock(spec=OpenSpecTaskTracker)
    tracker.incomplete_tasks.return_value = []
    service = OutcomeGovernanceService(task_tracker=tracker)

    res = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007-continuation",
        base_sha="abc123",
        candidate_sha=head_sha,
    )
    assert res.is_complete
    assert res.candidate_sha == head_sha


def test_verify_completion_candidate_sha_supplied_stale_rejected(tmp_path: Path):
    """Test D: candidate_sha supplied stale -> rejected."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "mod.py").write_text("hello")
    subprocess.run(["git", "add", "mod.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()

    tracker = MagicMock(spec=OpenSpecTaskTracker)
    tracker.incomplete_tasks.return_value = []
    service = OutcomeGovernanceService(task_tracker=tracker)

    stale_sha = "1111222233334444555566667777888899990000"
    res = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007-continuation",
        base_sha="abc123",
        candidate_sha=stale_sha,
    )
    assert not res.is_complete
    assert "Candidate SHA mismatch" in (res.reason or "")
    assert res.candidate_sha == head_sha


def test_verify_completion_candidate_sha_malformed_rejected(tmp_path: Path):
    """Test E: candidate_sha malformed -> rejected."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "mod.py").write_text("hello")
    subprocess.run(["git", "add", "mod.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True)

    tracker = MagicMock(spec=OpenSpecTaskTracker)
    tracker.incomplete_tasks.return_value = []
    service = OutcomeGovernanceService(task_tracker=tracker)

    res = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007-continuation",
        base_sha="abc123",
        candidate_sha="not-a-valid-sha!",
    )
    assert not res.is_complete
    assert "Malformed candidate SHA" in (res.reason or "")


def test_verify_completion_require_candidate_sha_omitted_rejected(tmp_path: Path):
    """Test F: require_candidate_sha=True + candidate_sha omitted -> rejected."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "mod.py").write_text("hello")
    subprocess.run(["git", "add", "mod.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True)

    tracker = MagicMock(spec=OpenSpecTaskTracker)
    tracker.incomplete_tasks.return_value = []
    service = OutcomeGovernanceService(task_tracker=tracker)

    res = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007-continuation",
        base_sha="abc123",
        candidate_sha=None,
        require_candidate_sha=True,
    )
    assert not res.is_complete
    assert "Missing required candidate SHA" in (res.reason or "")


def test_verify_completion_successful_result_must_never_have_none_sha_invariant(tmp_path: Path):
    """Test G: Invariant test ensuring NO successful CompletionVerificationResult ever has candidate_sha=None."""
    tracker = MagicMock(spec=OpenSpecTaskTracker)
    tracker.incomplete_tasks.return_value = []
    service = OutcomeGovernanceService(task_tracker=tracker)

    # 1. Non-git path: must fail closed, cannot return is_complete=True
    (tmp_path / "f.py").write_text("ok")
    res_non_git = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007",
        base_sha="base",
        candidate_sha=None,
    )
    assert not res_non_git.is_complete
    if res_non_git.is_complete:
        assert res_non_git.candidate_sha is not None  # Invariant

    # 2. Valid git path: if is_complete is True, candidate_sha must be non-None string
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "f.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True)

    res_git = service.verify_completion(
        worktree_path=tmp_path,
        openspec_path="openspec",
        change_name="007",
        base_sha="base",
        candidate_sha=None,
    )
    assert res_git.is_complete
    assert res_git.candidate_sha is not None
    assert len(res_git.candidate_sha) >= 7


def test_classify_outcome_provider_exhausted():
    service = OutcomeGovernanceService()
    ver_res = CompletionVerificationResult(is_complete=False)
    prov_res = NormalizedProviderResult(
        result_class=ProviderResultClass.QUOTA_LIMIT,
        provider="openrouter",
        role="implementer",
    )

    outcome = service.classify_outcome(ver_res, provider_result=prov_res)
    assert outcome == ExecutionOutcome.PROVIDER_EXHAUSTED


def test_classify_outcome_provider_failure():
    service = OutcomeGovernanceService()
    ver_res = CompletionVerificationResult(is_complete=False)
    prov_res = NormalizedProviderResult(
        result_class=ProviderResultClass.AUTH_ERROR,
        provider="codex",
        role="implementer",
    )

    outcome = service.classify_outcome(ver_res, provider_result=prov_res)
    assert outcome == ExecutionOutcome.PROVIDER_FAILURE


def test_classify_outcome_policy_violation():
    service = OutcomeGovernanceService()
    ver_res = CompletionVerificationResult(is_complete=False)

    outcome = service.classify_outcome(ver_res, has_policy_violation=True)
    assert outcome == ExecutionOutcome.POLICY_VIOLATION


def test_classify_outcome_blocker_claim_verdicts():
    service = OutcomeGovernanceService()
    ver_res = CompletionVerificationResult(is_complete=False)

    real_claim = BlockerClaim(
        claim_id="b1",
        job_id="j1",
        attempt_id="a1",
        blocker_type="MISSING_REQUIREMENT",
        blocker_fingerprint="fp1",
        validation_verdict=BlockerValidationVerdict.REAL_BLOCKER,
    )
    assert (
        service.classify_outcome(ver_res, blocker_claim=real_claim) == ExecutionOutcome.REAL_BLOCKER
    )

    false_claim = BlockerClaim(
        claim_id="b2",
        job_id="j1",
        attempt_id="a1",
        blocker_type="MISSING_FILE",
        blocker_fingerprint="fp2",
        validation_verdict=BlockerValidationVerdict.FALSE_BLOCKER,
    )
    assert (
        service.classify_outcome(ver_res, blocker_claim=false_claim)
        == ExecutionOutcome.FALSE_BLOCKER
    )


def test_classify_outcome_premature_stop_and_changes_required():
    service = OutcomeGovernanceService()

    ver_premature = CompletionVerificationResult(
        is_complete=False,
        incomplete_tasks=[OpenSpecTask("1", "T", None, False)],
        modified_files=["file1.py"],
    )
    assert service.classify_outcome(ver_premature) == ExecutionOutcome.PREMATURE_STOP

    ver_changes = CompletionVerificationResult(
        is_complete=False,
        failing_checks=[
            CheckResult(
                result_id="c1",
                job_id="j1",
                check_name="test",
                command="pytest",
                exit_code=1,
                duration_ms=10,
                output_snippet="fail",
            )
        ],
        modified_files=["file1.py"],
    )
    assert service.classify_outcome(ver_changes) == ExecutionOutcome.CHANGES_REQUIRED


def test_evaluate_progress_determinism():
    service = OutcomeGovernanceService()

    # Regression
    assert (
        service.evaluate_progress(ProgressSignals(regression_detected=True))
        == ProgressClassification.REGRESSION
    )
    assert (
        service.evaluate_progress(ProgressSignals(checks_fail_delta=1))
        == ProgressClassification.REGRESSION
    )

    # Good progress
    assert (
        service.evaluate_progress(ProgressSignals(completed_task_delta=1))
        == ProgressClassification.GOOD_PROGRESS
    )
    assert (
        service.evaluate_progress(ProgressSignals(checks_pass_delta=1))
        == ProgressClassification.GOOD_PROGRESS
    )
    assert (
        service.evaluate_progress(ProgressSignals(acceptance_evidence_delta=1))
        == ProgressClassification.GOOD_PROGRESS
    )

    # Partial progress
    assert (
        service.evaluate_progress(ProgressSignals(candidate_file_delta=2))
        == ProgressClassification.PARTIAL_PROGRESS
    )

    # No progress
    assert service.evaluate_progress(ProgressSignals()) == ProgressClassification.NO_PROGRESS
