"""Comprehensive tests for OpenSpec Lifecycle Quality Hooks V1."""

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
    QualityHookFinding,
    QualityHookStage,
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


def test_post_apply_expert_review_and_independence(tmp_path: Path):
    """Verify POST-APPLY evaluates model independence, specialties, and findings."""
    # Case 1: Same model identity -> BLOCKED
    report_same_model = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        reviewer_identity="antigravity",
        reviewer_model_identity="openai/gpt-4o",
        changed_files=["src/minime/services/auth_service.py"],
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH],
        repo_root=tmp_path,
    )
    assert report_same_model.final_verdict == HookVerdict.BLOCKED
    assert "independence" in report_same_model.verdict_reason.lower()

    # Case 2: Required specialty missing -> BLOCKED
    report_missing_spec = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        reviewer_identity="antigravity",
        reviewer_model_identity="google/gemini-2.5-pro",
        changed_files=["src/minime/services/auth_service.py"],
        evaluated_specialties=[],  # Missing SECURITY_AUTH
        repo_root=tmp_path,
    )
    assert report_missing_spec.final_verdict == HookVerdict.BLOCKED
    assert "unfulfilled" in report_missing_spec.verdict_reason.lower()

    # Case 3: Fully compliant review -> PASS
    report_compliant = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        reviewer_identity="antigravity",
        reviewer_model_identity="google/gemini-2.5-pro",
        changed_files=["src/minime/services/auth_service.py"],
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH],
        repo_root=tmp_path,
    )
    assert report_compliant.final_verdict == HookVerdict.PASS


def test_verify_hook_gate(tmp_path: Path):
    """Verify VERIFY gate requires evidence and zero unresolved CRITICAL/HIGH findings."""
    # Missing verification result -> BLOCKED
    report_no_evidence = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=None,
        repo_root=tmp_path,
    )
    assert report_no_evidence.final_verdict == HookVerdict.BLOCKED
    assert "missing" in report_no_evidence.verdict_reason.lower()

    # Failed deterministic checks -> FAIL
    failed_res = VerificationResult(
        deterministic_checks_passed=False,
        tests_passed=False,
        linters_passed=True,
        schemas_passed=True,
    )
    report_check_fail = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=failed_res,
        repo_root=tmp_path,
    )
    assert report_check_fail.final_verdict == HookVerdict.FAIL

    # Unresolved CRITICAL finding -> FAIL
    crit_finding = QualityHookFinding(
        finding_id="FIND-001",
        specialty=ReviewSpecialty.SECURITY_AUTH,
        severity=FindingSeverity.CRITICAL,
        requirement_reference="SPEC-01",
        observed_evidence="Security leak detected",
        expected_behavior="Sanitized output",
        suggested_remediation="Fix leak",
        status=FindingStatus.UNRESOLVED,
    )
    passed_res = VerificationResult(
        deterministic_checks_passed=True,
        tests_passed=True,
        linters_passed=True,
        schemas_passed=True,
    )
    report_finding_fail = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=passed_res,
        findings=[crit_finding],
        repo_root=tmp_path,
    )
    assert report_finding_fail.final_verdict == HookVerdict.FAIL

    # Clean verification -> PASS
    report_pass = evaluate_verify(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        verification_result=passed_res,
        findings=[],
        repo_root=tmp_path,
    )
    assert report_pass.final_verdict == HookVerdict.PASS


def test_archive_hook_delivery_integrity(tmp_path: Path):
    """Verify ARCHIVE hook enforces DoD and mandatory human merge."""
    # Not merged by human -> FAIL
    report_auto_merge = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        pr_merged_by_human=False,
        repo_root=tmp_path,
    )
    assert report_auto_merge.final_verdict == HookVerdict.FAIL
    assert any(f.finding_id == "ARCHIVE-NO-HUMAN-MERGE" for f in report_auto_merge.findings)

    # Valid human merge and approval -> PASS
    report_archive_pass = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        pr_merged_by_human=True,
        pr_number=140,
        human_approval_recorded=True,
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
    report = evaluate_post_apply(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        reviewer_identity="antigravity",
        reviewer_model_identity="google/gemini-2.5-pro",
        changed_files=["src/minime/services/intake_service.py"],
        diff_text=buggy_code,
        evaluated_specialties=[ReviewSpecialty.SECURITY_AUTH, ReviewSpecialty.RELIABILITY_RECOVERY],
        repo_root=Path("/tmp"),
    )
    assert report.final_verdict == HookVerdict.FAIL
    assert any("PR139-AUTH-SWALLOW" in f.finding_id for f in report.findings)


def test_cli_quality_hooks(tmp_path: Path):
    """Verify quality-hooks CLI commands work as expected."""
    # 1. select-specialties
    result = runner.invoke(
        cli_app,
        ["select-specialties", "-f", "src/minime/services/auth_service.py"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "security_auth" in data["required_specialties"]

    # 2. validate-report
    report = evaluate_pre_apply(
        change_id="cli-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        repo_root=tmp_path,
    )
    report_file = tmp_path / "report.json"
    report_file.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    val_res = runner.invoke(cli_app, ["validate-report", "-r", str(report_file)])
    assert val_res.exit_code == 0
    assert "Valid report" in val_res.output
