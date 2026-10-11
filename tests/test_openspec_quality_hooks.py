"""Comprehensive tests for OpenSpec Lifecycle Quality Hooks V1 with adversarial verification."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from minime.quality_hooks.analyzers.regression_pr139 import analyze_pr139_regressions
from minime.quality_hooks.cli import cli_app
from minime.quality_hooks.engine import (
    evaluate_archive,
    evaluate_post_apply,
    evaluate_pre_apply,
    evaluate_verify,
)
from minime.quality_hooks.models import (
    FindingSeverity,
    HookVerdict,
    HumanApprovalEvidence,
    MergeEvidence,
    QualityHookStage,
    ReviewEvidence,
    ReviewSpecialty,
    VerificationResult,
)
from minime.quality_hooks.specialties import (
    select_specialties_for_files,
)

runner = CliRunner()

BASE_SHA = "1111111111111111111111111111111111111111"
CANDIDATE_SHA = "2222222222222222222222222222222222222222"
ANOTHER_SHA = "8888888888888888888888888888888888888888"


def test_dynamic_specialty_selection():
    """Verify changed file paths map deterministically to required review specialties."""
    files = [
        "src/minime/services/auth_service.py",
        "alembic/versions/001_initial.py",
        "src/minime/services/restart_recovery_service.py",
        "tests/test_auth_service.py",
        "docker-compose.yml",
    ]
    specialties = select_specialties_for_files(files)
    assert ReviewSpecialty.SECURITY_AUTH in specialties
    assert ReviewSpecialty.DATA_MIGRATIONS in specialties
    assert ReviewSpecialty.RELIABILITY_RECOVERY in specialties
    assert ReviewSpecialty.TESTS_COVERAGE in specialties
    assert ReviewSpecialty.OPERATIONAL_DELIVERY in specialties

    # Single unmatched file falls back to general architecture
    unmatched_specs = select_specialties_for_files(["README.md"])
    assert unmatched_specs == [ReviewSpecialty.GENERAL_ARCHITECTURE]


def test_pre_apply_hook_readiness(tmp_path: Path):
    """Verify PRE-APPLY hook validates OpenSpec change artifacts and SHA formatting."""
    change_id = "test-feature"
    openspec_dir = tmp_path / "openspec" / "changes" / change_id
    openspec_dir.mkdir(parents=True)
    (openspec_dir / "proposal.md").write_text("# Proposal\nValue.", encoding="utf-8")
    (openspec_dir / "tasks.md").write_text("# Tasks\n- [ ] Task 1", encoding="utf-8")
    (openspec_dir / "design.md").write_text("# Design\nDetails.", encoding="utf-8")

    # Evaluate with valid artifacts
    report = evaluate_pre_apply(
        change_id=change_id,
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        repo_root=tmp_path,
    )
    assert report.hook_id == QualityHookStage.PRE_APPLY
    assert report.final_verdict == HookVerdict.PASS
    assert "passed" in report.verdict_reason.lower()

    # Missing change directory -> BLOCKED
    report_missing = evaluate_pre_apply(
        change_id="nonexistent-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        repo_root=tmp_path,
    )
    assert report_missing.final_verdict == HookVerdict.BLOCKED
    assert "not found" in report_missing.verdict_reason.lower()


def test_adversarial_post_apply_rejection(tmp_path: Path):
    """Adversarial POST-APPLY tests: reject invented reviews and unverified JSON."""
    # Adversarial 1: Invented review JSON with untrusted provenance -> MUST be BLOCKED
    untrusted_review = ReviewEvidence(
        candidate_sha=CANDIDATE_SHA,
        reviewer_identity="antigravity",
        reviewer_model_identity="google/gemini-2.5-pro",
        verdict="approve",
        summary="Fabricated review summary",
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH],
        evidence_source="scratch/fake-review.json",
        provenance="untrusted-local-file",  # Not a canonical authority!
    )
    report_untrusted = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=untrusted_review,
        _override_changed_files=["src/minime/services/auth_service.py"],
        _override_diff_text="def test(): pass",
        repo_root=tmp_path,
    )
    assert report_untrusted.final_verdict == HookVerdict.BLOCKED
    assert "not a trusted canonical review authority" in report_untrusted.verdict_reason.lower()

    # Adversarial 2: Review claiming candidate SHA of another commit -> MUST be BLOCKED
    another_commit_review = ReviewEvidence(
        candidate_sha=ANOTHER_SHA,  # Another commit!
        reviewer_identity="antigravity",
        reviewer_model_identity="google/gemini-2.5-pro",
        verdict="approve",
        summary="Review for another commit",
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH],
        evidence_source="canonical-review.json",
        provenance="canonical-uow-review",
    )
    report_another = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=another_commit_review,
        _override_changed_files=["src/minime/services/auth_service.py"],
        _override_diff_text="def test(): pass",
        repo_root=tmp_path,
    )
    assert report_another.final_verdict == HookVerdict.BLOCKED
    assert "does not match candidate sha" in report_another.verdict_reason.lower()

    # Adversarial 3: Same model family self-review in canonical evidence -> MUST be BLOCKED
    same_model_review = ReviewEvidence(
        candidate_sha=CANDIDATE_SHA,
        reviewer_identity="antigravity",
        reviewer_model_identity="openai/gpt-4o",  # Same as implementer!
        verdict="approve",
        summary="Self review",
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH],
        evidence_source="canonical-review.json",
        provenance="canonical-uow-review",
    )
    report_same_model = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=same_model_review,
        _override_changed_files=["src/minime/services/auth_service.py"],
        _override_diff_text="def test(): pass",
        repo_root=tmp_path,
    )
    assert report_same_model.final_verdict == HookVerdict.BLOCKED
    assert "independence" in report_same_model.verdict_reason.lower()

    # Legitimate canonical review with independent reviewer covering specialties -> PASS
    legit_review = ReviewEvidence(
        candidate_sha=CANDIDATE_SHA,
        reviewer_identity="antigravity",
        reviewer_model_identity="google/gemini-2.5-pro",
        verdict="approve",
        summary="Authoritative independent review passed",
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH],
        evidence_source="canonical-review.json",
        provenance="canonical-uow-review",
    )
    report_legit = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=legit_review,
        _override_changed_files=["src/minime/services/auth_service.py"],
        _override_diff_text="def test(): pass",
        repo_root=tmp_path,
    )
    assert report_legit.final_verdict == HookVerdict.PASS


def test_adversarial_verify_rejection(tmp_path: Path):
    """Adversarial VERIFY tests: reject fabricated results, SHA mismatch, and unverified schemas."""
    # Adversarial 1: Fabricated verification result with untrusted provenance -> MUST be BLOCKED
    untrusted_res = VerificationResult(
        candidate_sha=CANDIDATE_SHA,
        deterministic_checks_passed=True,
        tests_passed=True,
        linters_passed=True,
        schemas_passed=True,
        evidence_source="scratch/fake-test-run.log",
        provenance="untrusted-self-claimed-result",  # Untrusted!
    )
    report_untrusted = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=untrusted_res,
        repo_root=tmp_path,
    )
    assert report_untrusted.final_verdict == HookVerdict.BLOCKED
    assert "not a trusted canonical authority" in report_untrusted.verdict_reason.lower()

    # Adversarial 2: Verification result with candidate SHA of another commit -> MUST be BLOCKED
    mismatched_sha_res = VerificationResult(
        candidate_sha=ANOTHER_SHA,  # Wrong SHA!
        deterministic_checks_passed=True,
        tests_passed=True,
        linters_passed=True,
        schemas_passed=True,
        evidence_source="ci-run-123",
        provenance="canonical-ci-runner",
    )
    report_mismatched = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=mismatched_sha_res,
        repo_root=tmp_path,
    )
    assert report_mismatched.final_verdict == HookVerdict.BLOCKED
    assert "does not match candidate sha" in report_mismatched.verdict_reason.lower()

    # Adversarial 3: Fictitious test result where schemas_passed was not run/failed -> MUST be FAIL
    schema_failed_res = VerificationResult(
        candidate_sha=CANDIDATE_SHA,
        deterministic_checks_passed=True,
        tests_passed=True,
        linters_passed=True,
        schemas_passed=False,  # Schemas failed or unverified!
        evidence_source="ci-run-123",
        provenance="canonical-ci-runner",
    )
    report_schema_fail = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=schema_failed_res,
        repo_root=tmp_path,
    )
    assert report_schema_fail.final_verdict == HookVerdict.FAIL
    assert "schema validation checks failed" in report_schema_fail.verdict_reason.lower()

    # Adversarial 4: Canonical worktree runner on non-git dir -> MUST be BLOCKED
    worktree_res = VerificationResult(
        candidate_sha=CANDIDATE_SHA,
        deterministic_checks_passed=True,
        tests_passed=True,
        linters_passed=True,
        schemas_passed=True,
        evidence_source="local-run",
        provenance="canonical-worktree-runner",
    )
    report_nongit = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=worktree_res,
        repo_root=tmp_path,
    )
    assert report_nongit.final_verdict == HookVerdict.BLOCKED
    assert "not a valid git repository" in report_nongit.verdict_reason.lower()

    # Adversarial 5: Canonical worktree runner on git repo with mismatched HEAD
    git_repo = tmp_path / "repo"
    git_repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(git_repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(git_repo), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(git_repo), check=True)
    (git_repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=str(git_repo), check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(git_repo), check=True)
    report_worktree_mismatch = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=worktree_res,
        repo_root=git_repo,
    )
    assert report_worktree_mismatch.final_verdict == HookVerdict.BLOCKED
    assert "working tree head" in report_worktree_mismatch.verdict_reason.lower()

    # Legitimate canonical verification with all checks passed -> PASS
    legit_res = VerificationResult(
        candidate_sha=CANDIDATE_SHA,
        deterministic_checks_passed=True,
        tests_passed=True,
        linters_passed=True,
        schemas_passed=True,
        evidence_source="ci-run-124",
        provenance="canonical-ci-runner",
    )
    report_legit = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=legit_res,
        findings=[],
        repo_root=tmp_path,
    )
    assert report_legit.final_verdict == HookVerdict.PASS


def test_adversarial_archive_rejection(tmp_path: Path):
    """Adversarial ARCHIVE tests: reject fake merge and fake human approval."""
    valid_approval = HumanApprovalEvidence(
        candidate_head_sha=CANDIDATE_SHA,
        base_sha=BASE_SHA,
        decision="approve",
        approver_identity="operator",
        evidence_source="validation_runs_table",
        provenance="canonical-validation-authority",
    )
    valid_merge = MergeEvidence(
        candidate_sha=CANDIDATE_SHA,
        target_branch="main",
        is_merged=True,
        merged_by="silverberdi",
        merged_by_type="User",
        evidence_source="github_api",
        provenance="canonical-github-pr",
    )

    # Adversarial 1: Fabricated merge JSON with untrusted provenance -> MUST be BLOCKED
    fake_merge = MergeEvidence(
        candidate_sha=CANDIDATE_SHA,
        target_branch="main",
        is_merged=True,
        merged_by="silverberdi",
        evidence_source="scratch/fake-merge.json",
        provenance="untrusted-self-claimed-merge",  # Untrusted!
    )
    report_fake_merge = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        merge_evidence=fake_merge,
        human_approval_evidence=valid_approval,
        repo_root=tmp_path,
    )
    assert report_fake_merge.final_verdict == HookVerdict.BLOCKED
    assert "not a trusted canonical authority" in report_fake_merge.verdict_reason.lower()

    # Adversarial 2: Fabricated human approval JSON with untrusted provenance -> MUST be BLOCKED
    fake_approval = HumanApprovalEvidence(
        candidate_head_sha=CANDIDATE_SHA,
        base_sha=BASE_SHA,
        decision="approve",
        approver_identity="fake-operator",
        evidence_source="scratch/fake-approval.json",
        provenance="untrusted-self-claimed-approval",  # Untrusted!
    )
    report_fake_approval = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        merge_evidence=valid_merge,
        human_approval_evidence=fake_approval,
        repo_root=tmp_path,
    )
    assert report_fake_approval.final_verdict == HookVerdict.BLOCKED
    assert "not a trusted canonical authority" in report_fake_approval.verdict_reason.lower()

    # Adversarial 3: Merge evidence with candidate SHA of another commit -> MUST be BLOCKED
    another_merge = MergeEvidence(
        candidate_sha=ANOTHER_SHA,  # Another commit!
        target_branch="main",
        is_merged=True,
        merged_by="silverberdi",
        merged_by_type="User",
        evidence_source="github_api",
        provenance="canonical-github-pr",
    )
    report_another_merge = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        merge_evidence=another_merge,
        human_approval_evidence=valid_approval,
        repo_root=tmp_path,
    )
    assert report_another_merge.final_verdict == HookVerdict.BLOCKED
    assert "does not match candidate" in report_another_merge.verdict_reason.lower()

    # Adversarial 4: Automated bot merge -> MUST be FAIL (human merge mandatory in MVP)
    bot_merge = MergeEvidence(
        candidate_sha=CANDIDATE_SHA,
        target_branch="main",
        is_merged=True,
        merged_by="github-actions[bot]",
        merged_by_type="Bot",
        evidence_source="github_api",
        provenance="canonical-github-pr",
    )
    report_bot_merge = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        merge_evidence=bot_merge,
        human_approval_evidence=valid_approval,
        repo_root=tmp_path,
    )
    assert report_bot_merge.final_verdict == HookVerdict.FAIL
    assert any(f.finding_id == "ARCHIVE-NO-HUMAN-MERGE" for f in report_bot_merge.findings)

    # Legitimate canonical merge and approval -> PASS
    report_legit = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        merge_evidence=valid_merge,
        human_approval_evidence=valid_approval,
        repo_root=tmp_path,
    )
    assert report_legit.final_verdict == HookVerdict.PASS


def test_pr139_regression_fixture():
    """Verify static analyzer catches PR #139 auth swallowing and secret leakage patterns."""
    buggy_code = """
def _get_git_auth_bundle(self):
    try:
        token = self._fetch_token()
    except Exception as e:
        logger.warning(f"Token fetch failed: {e}")
        return {}
"""
    findings = analyze_pr139_regressions("intake_service.py", buggy_code)
    assert len(findings) == 1
    assert findings[0].finding_id.startswith("PR139-AUTH-SWALLOW")
    assert findings[0].severity == FindingSeverity.CRITICAL

    secret_leak_code = """
raise ValueError(f"Authorization token: {secret_token} rejected")
"""
    leak_findings = analyze_pr139_regressions("intake_service.py", secret_leak_code)
    assert len(leak_findings) == 1
    assert leak_findings[0].finding_id.startswith("PR139-SECRET-LEAK")
    assert leak_findings[0].severity == FindingSeverity.CRITICAL

    # Verify that evaluating POST-APPLY with this diff results in FAIL
    review_ev = ReviewEvidence(
        candidate_sha=CANDIDATE_SHA,
        reviewer_identity="antigravity",
        reviewer_model_identity="google/gemini-2.5-pro",
        verdict="approve",
        summary="Testing diff scan",
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH, ReviewSpecialty.RELIABILITY_RECOVERY],
        evidence_source="canonical-review.json",
        provenance="canonical-uow-review",
    )
    report = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=review_ev,
        _override_changed_files=["src/minime/services/intake_service.py"],
        _override_diff_text=buggy_code,
        repo_root=Path("/tmp"),
    )
    assert report.final_verdict == HookVerdict.FAIL
    assert any("PR139-AUTH-SWALLOW" in f.finding_id for f in report.findings)


def test_cli_quality_hooks_fails_closed_without_evidence(tmp_path: Path):
    """Verify quality-hooks CLI commands fail closed as BLOCKED without evidence."""
    # 1. select-specialties
    result = runner.invoke(
        cli_app,
        ["select-specialties", "-f", "src/minime/services/auth_service.py"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "security_auth" in data["required_specialties"]

    # 2. evaluate-verify fails closed without evidence
    verify_fail = runner.invoke(
        cli_app,
        [
            "evaluate-verify",
            "-c", "test-change",
            "--base-sha", BASE_SHA,
            "--candidate-sha", CANDIDATE_SHA,
            "--repo-root", str(tmp_path),
        ],
    )
    assert verify_fail.exit_code == 1
    verify_report = json.loads(verify_fail.output)
    assert verify_report["final_verdict"] == "BLOCKED"

    # 3. evaluate-archive fails closed without evidence
    archive_fail = runner.invoke(
        cli_app,
        [
            "evaluate-archive",
            "-c", "test-change",
            "--base-sha", BASE_SHA,
            "--candidate-sha", CANDIDATE_SHA,
            "--repo-root", str(tmp_path),
        ],
    )
    assert archive_fail.exit_code == 1
    archive_report = json.loads(archive_fail.output)
    assert archive_report["final_verdict"] == "BLOCKED"

    # 4. evaluate-post-apply fails closed without review evidence file
    post_apply_fail = runner.invoke(
        cli_app,
        [
            "evaluate-post-apply",
            "-c", "test-change",
            "--base-sha", BASE_SHA,
            "--candidate-sha", CANDIDATE_SHA,
            "--repo-root", str(tmp_path),
        ],
    )
    assert post_apply_fail.exit_code == 1
    post_report = json.loads(post_apply_fail.output)
    assert post_report["final_verdict"] == "BLOCKED"
