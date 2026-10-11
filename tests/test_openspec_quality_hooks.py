"""Comprehensive tests for OpenSpec Lifecycle Quality Hooks V1 with fail-closed evidence enforcement."""

from __future__ import annotations

import json
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
    FindingStatus,
    HookVerdict,
    HumanApprovalEvidence,
    MergeEvidence,
    QualityHookFinding,
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


def test_post_apply_fails_closed_without_review_evidence(tmp_path: Path):
    """POST-APPLY Defect 2 Remediation: verify failure when review evidence is missing or stale."""
    # Negative test 1: Self-declared identities without review evidence -> MUST be BLOCKED
    report_no_evidence = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=None,
        _override_changed_files=["src/minime/services/auth_service.py"],
        _override_diff_text="def test(): pass",
        repo_root=tmp_path,
    )
    assert report_no_evidence.final_verdict == HookVerdict.BLOCKED
    assert "review evidence is missing" in report_no_evidence.verdict_reason.lower()

    # Negative test 2: Stale review evidence bound to different SHA -> MUST be BLOCKED
    stale_evidence = ReviewEvidence(
        candidate_sha="3333333333333333333333333333333333333333",  # Mismatched SHA
        reviewer_identity="antigravity",
        reviewer_model_identity="google/gemini-2.5-pro",
        verdict="approve",
        summary="Looks good",
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH],
        evidence_source="reviews/review-001.json",
    )
    report_stale = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=stale_evidence,
        _override_changed_files=["src/minime/services/auth_service.py"],
        _override_diff_text="def test(): pass",
        repo_root=tmp_path,
    )
    assert report_stale.final_verdict == HookVerdict.BLOCKED
    assert "stale review" in report_stale.verdict_reason.lower()

    # Negative test 3: Same model identity in review evidence -> MUST be BLOCKED
    same_model_evidence = ReviewEvidence(
        candidate_sha=CANDIDATE_SHA,
        reviewer_identity="antigravity",
        reviewer_model_identity="openai/gpt-4o",  # Same as implementer!
        verdict="approve",
        summary="Self review attempt",
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH],
        evidence_source="reviews/review-002.json",
    )
    report_same_model = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=same_model_evidence,
        _override_changed_files=["src/minime/services/auth_service.py"],
        _override_diff_text="def test(): pass",
        repo_root=tmp_path,
    )
    assert report_same_model.final_verdict == HookVerdict.BLOCKED
    assert "independence" in report_same_model.verdict_reason.lower()

    # Negative test 4: Missing required specialty in review evidence -> MUST be BLOCKED
    missing_spec_evidence = ReviewEvidence(
        candidate_sha=CANDIDATE_SHA,
        reviewer_identity="antigravity",
        reviewer_model_identity="google/gemini-2.5-pro",
        verdict="approve",
        summary="Missed security specialty",
        evaluated_specialties=[ReviewSpecialty.GENERAL_ARCHITECTURE],  # Missing SECURITY_AUTH
        evidence_source="reviews/review-003.json",
    )
    report_missing_spec = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=missing_spec_evidence,
        _override_changed_files=["src/minime/services/auth_service.py"],
        _override_diff_text="def test(): pass",
        repo_root=tmp_path,
    )
    assert report_missing_spec.final_verdict == HookVerdict.BLOCKED
    assert "unfulfilled" in report_missing_spec.verdict_reason.lower()

    # Positive test: Valid, independent review evidence covering required specialty -> PASS
    valid_evidence = ReviewEvidence(
        candidate_sha=CANDIDATE_SHA,
        reviewer_identity="antigravity",
        reviewer_model_identity="google/gemini-2.5-pro",
        verdict="approve",
        summary="Full review passed",
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH],
        evidence_source="reviews/review-004.json",
    )
    report_valid = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=valid_evidence,
        _override_changed_files=["src/minime/services/auth_service.py"],
        _override_diff_text="def test(): pass",
        repo_root=tmp_path,
    )
    assert report_valid.final_verdict == HookVerdict.PASS


def test_verify_fails_closed_without_candidate_evidence(tmp_path: Path):
    """VERIFY Defect 1 Remediation: verify failure when verification evidence is missing, unbound, or failing."""
    # Negative test 1: verification_result is None -> MUST be BLOCKED
    report_no_evidence = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=None,
        repo_root=tmp_path,
    )
    assert report_no_evidence.final_verdict == HookVerdict.BLOCKED
    assert "missing" in report_no_evidence.verdict_reason.lower()

    # Negative test 2: verification_result candidate_sha mismatch -> MUST be BLOCKED
    mismatched_evidence = VerificationResult(
        candidate_sha="9999999999999999999999999999999999999999",  # Wrong SHA
        deterministic_checks_passed=True,
        tests_passed=True,
        linters_passed=True,
        schemas_passed=True,
        evidence_source="pytest-run-log",
    )
    report_mismatch = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=mismatched_evidence,
        repo_root=tmp_path,
    )
    assert report_mismatch.final_verdict == HookVerdict.BLOCKED
    assert "does not match" in report_mismatch.verdict_reason.lower()

    # Negative test 3: Failed deterministic checks in evidence -> MUST be FAIL
    failed_checks_evidence = VerificationResult(
        candidate_sha=CANDIDATE_SHA,
        deterministic_checks_passed=False,
        tests_passed=False,
        linters_passed=True,
        schemas_passed=True,
        evidence_source="pytest-run-log",
    )
    report_checks_fail = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=failed_checks_evidence,
        repo_root=tmp_path,
    )
    assert report_checks_fail.final_verdict == HookVerdict.FAIL
    assert "failed" in report_checks_fail.verdict_reason.lower()

    # Negative test 4: Unresolved CRITICAL finding -> MUST be FAIL
    crit_finding = QualityHookFinding(
        finding_id="FIND-001",
        specialty=ReviewSpecialty.SECURITY_AUTH,
        severity=FindingSeverity.CRITICAL,
        requirement_reference="CANONICAL#auth",
        observed_evidence="Unauthenticated fallback",
        expected_behavior="Fail-closed",
        suggested_remediation="Raise error",
        status=FindingStatus.UNRESOLVED,
    )
    valid_checks_evidence = VerificationResult(
        candidate_sha=CANDIDATE_SHA,
        deterministic_checks_passed=True,
        tests_passed=True,
        linters_passed=True,
        schemas_passed=True,
        evidence_source="pytest-run-log",
    )
    report_finding_fail = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=valid_checks_evidence,
        findings=[crit_finding],
        repo_root=tmp_path,
    )
    assert report_finding_fail.final_verdict == HookVerdict.FAIL

    # Positive test: Valid evidence bound to candidate SHA with zero unresolved issues -> PASS
    report_pass = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=valid_checks_evidence,
        findings=[],
        repo_root=tmp_path,
    )
    assert report_pass.final_verdict == HookVerdict.PASS


def test_archive_fails_closed_without_authoritative_sources(tmp_path: Path):
    """ARCHIVE Defect 3 Remediation: verify failure when merge or human approval evidence is absent or invalid."""
    # Negative test 1: Both merge and approval evidence missing -> MUST be BLOCKED
    report_no_evidence = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        merge_evidence=None,
        human_approval_evidence=None,
        repo_root=tmp_path,
    )
    assert report_no_evidence.final_verdict == HookVerdict.BLOCKED
    assert "merge verification evidence is missing" in report_no_evidence.verdict_reason.lower()

    # Negative test 2: Merge evidence present but human approval missing -> MUST be BLOCKED
    valid_merge = MergeEvidence(
        candidate_sha=CANDIDATE_SHA,
        target_branch="main",
        is_merged=True,
        merged_by="silverberdi",
        merged_by_type="User",
        evidence_source="github_api_pr_details",
    )
    report_missing_approval = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        merge_evidence=valid_merge,
        human_approval_evidence=None,
        repo_root=tmp_path,
    )
    assert report_missing_approval.final_verdict == HookVerdict.BLOCKED
    assert "human approval evidence is missing" in report_missing_approval.verdict_reason.lower()

    # Negative test 3: Merge was executed by a Bot -> MUST be FAIL (human merge mandatory in MVP)
    bot_merge = MergeEvidence(
        candidate_sha=CANDIDATE_SHA,
        target_branch="main",
        is_merged=True,
        merged_by="github-actions[bot]",
        merged_by_type="Bot",
        evidence_source="github_api_pr_details",
    )
    valid_approval = HumanApprovalEvidence(
        candidate_head_sha=CANDIDATE_SHA,
        base_sha=BASE_SHA,
        decision="approve",
        approver_identity="operator",
        evidence_source="human-validation-report.json",
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

    # Negative test 4: Human approval decision was "reject" -> MUST be FAIL
    rejected_approval = HumanApprovalEvidence(
        candidate_head_sha=CANDIDATE_SHA,
        base_sha=BASE_SHA,
        decision="reject",
        approver_identity="operator",
        evidence_source="human-validation-report.json",
    )
    report_rejected_approval = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        merge_evidence=valid_merge,
        human_approval_evidence=rejected_approval,
        repo_root=tmp_path,
    )
    assert report_rejected_approval.final_verdict == HookVerdict.FAIL
    assert any(f.finding_id == "ARCHIVE-MISSING-HUMAN-APPROVAL" for f in report_rejected_approval.findings)

    # Positive test: Valid human merge + approved human validation -> PASS
    report_archive_pass = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        merge_evidence=valid_merge,
        human_approval_evidence=valid_approval,
        repo_root=tmp_path,
    )
    assert report_archive_pass.final_verdict == HookVerdict.PASS


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
        evidence_source="reviews/review.json",
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


def test_cli_quality_hooks(tmp_path: Path):
    """Verify quality-hooks CLI commands work as expected and fail closed without evidence."""
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
