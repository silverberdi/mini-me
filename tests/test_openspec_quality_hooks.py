"""Comprehensive tests for OpenSpec Lifecycle Quality Hooks V1 with adversarial verification."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
from minime.domain.models import ExternalActionResult
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


def _git_repo_with_two_commits(repo: Path) -> tuple[str, str]:
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    source = repo / "tracked.txt"
    source.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    source.write_text("candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "candidate"], cwd=repo, check=True, capture_output=True)
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    return base_sha, candidate_sha


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
        repo_root=tmp_path,
    )
    assert report_untrusted.final_verdict == HookVerdict.BLOCKED
    assert (
        "canonical specialty-aware reviewer evidence is unavailable"
        in report_untrusted.verdict_reason.lower()
    )
    assert report_untrusted.reviewer_identity is None

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
        repo_root=tmp_path,
    )
    assert report_another.final_verdict == HookVerdict.BLOCKED
    assert (
        "canonical specialty-aware reviewer evidence is unavailable"
        in report_another.verdict_reason.lower()
    )

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
        repo_root=tmp_path,
    )
    assert report_same_model.final_verdict == HookVerdict.BLOCKED
    assert report_same_model.reviewer_model_identity is None

    # Even plausible identity, specialties and provenance claims are not authenticated authority.
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
        repo_root=tmp_path,
    )
    assert report_legit.final_verdict == HookVerdict.BLOCKED
    assert (
        "canonical specialty-aware reviewer evidence is unavailable"
        in report_legit.verdict_reason.lower()
    )


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
    assert (
        "caller-supplied verification payload is not authoritative"
        in report_untrusted.verdict_reason.lower()
    )

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
    assert (
        "caller-supplied verification payload is not authoritative"
        in report_mismatched.verdict_reason.lower()
    )

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
    assert report_schema_fail.final_verdict == HookVerdict.BLOCKED
    assert (
        "caller-supplied verification payload is not authoritative"
        in report_schema_fail.verdict_reason.lower()
    )

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
    assert (
        "caller-supplied verification payload is not authoritative"
        in report_nongit.verdict_reason.lower()
    )

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
    from minime.quality_hooks.engine import _run_checks_for_candidate

    _, mismatch_reason = _run_checks_for_candidate(git_repo, CANDIDATE_SHA)
    assert mismatch_reason and "does not match candidate sha" in mismatch_reason.lower()

    # A plausible provenance string in a JSON-shaped payload is still not execution evidence.
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
    assert report_legit.final_verdict == HookVerdict.BLOCKED
    assert (
        "caller-supplied verification payload is not authoritative"
        in report_legit.verdict_reason.lower()
    )


def test_verify_refuses_untracked_candidate_tree_even_with_exact_head(tmp_path: Path):
    from minime.quality_hooks.engine import _run_checks_for_candidate

    repo = tmp_path / "candidate"
    _, candidate_sha = _git_repo_with_two_commits(repo)
    (repo / "tests").mkdir()
    (repo / "tests" / "untracked_test.py").write_text("def test_extra(): pass\n", encoding="utf-8")

    result, reason = _run_checks_for_candidate(repo, candidate_sha)
    assert result is None
    assert reason and "untracked changes" in reason.lower()


def test_archive_queries_github_and_still_requires_canonical_dod(tmp_path: Path):
    repo = tmp_path / "candidate"
    base_sha, candidate_sha = _git_repo_with_two_commits(repo)

    class GitHubAuthority:
        def __init__(self):
            self.pr_calls = 0
            self.review_calls = 0
            self.reviews = [
                {
                    "state": "APPROVED",
                    "commit_id": candidate_sha,
                    "user_type": "User",
                    "user_login": "human-reviewer",
                    "submitted_at": "2026-10-11T12:00:00Z",
                }
            ]

        def get_pull_request_details(self, repository, pr_number):
            self.pr_calls += 1
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data={
                    "number": pr_number,
                    "head_sha": candidate_sha,
                    "base_branch": "main",
                    "is_merged": True,
                    "merged_at": "2026-10-11T10:00:00Z",
                    "merge_commit_sha": "a" * 40,
                    "merged_by_type": "User",
                    "merged_by_login": "human-operator",
                },
            )

        def get_pull_request_reviews(self, repository, pr_number):
            self.review_calls += 1
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github_rest",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=self.reviews,
            )

    authority = GitHubAuthority()
    report = evaluate_archive(
        change_id="test-change",
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        pull_request_number=42,
        github_adapter=authority,
        repo_root=repo,
    )
    assert authority.pr_calls == authority.review_calls == 1
    assert not any(
        finding.finding_id in {"ARCHIVE-NO-HUMAN-MERGE", "ARCHIVE-MISSING-HUMAN-APPROVAL"}
        for finding in report.findings
    )
    assert report.final_verdict == HookVerdict.BLOCKED
    assert "full definition-of-done evidence is not available" in report.verdict_reason.lower()

    authority.reviews.append(
        {
            "state": "CHANGES_REQUESTED",
            "commit_id": candidate_sha,
            "user_type": "User",
            "user_login": "human-reviewer",
            "submitted_at": "2026-10-11T13:00:00Z",
        }
    )
    stale_approval = evaluate_archive(
        change_id="test-change",
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        pull_request_number=42,
        github_adapter=authority,
        repo_root=repo,
    )
    assert any(
        finding.finding_id == "ARCHIVE-MISSING-HUMAN-APPROVAL"
        for finding in stale_approval.findings
    )


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
    assert (
        "caller-supplied merge/approval payloads are not accepted"
        in report_fake_merge.verdict_reason.lower()
    )

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
    assert (
        "caller-supplied merge/approval payloads are not accepted"
        in report_fake_approval.verdict_reason.lower()
    )

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
    assert (
        "caller-supplied merge/approval payloads are not accepted"
        in report_another_merge.verdict_reason.lower()
    )

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
    assert report_bot_merge.final_verdict == HookVerdict.BLOCKED
    assert (
        "caller-supplied merge/approval payloads are not accepted"
        in report_bot_merge.verdict_reason.lower()
    )

    # Even matching provenance strings do not replace direct GitHub and DoD evidence.
    report_legit = evaluate_archive(
        change_id="test-change",
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        merge_evidence=valid_merge,
        human_approval_evidence=valid_approval,
        repo_root=tmp_path,
    )
    assert report_legit.final_verdict == HookVerdict.BLOCKED
    assert (
        "caller-supplied merge/approval payloads are not accepted"
        in report_legit.verdict_reason.lower()
    )


def test_pr139_regression_fixture(tmp_path: Path):
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
    repo = tmp_path / "quality-hooks-pr139-fixture"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    source = repo / "src" / "minime" / "services" / "intake_service.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def safe():\n    return None\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    source.write_text(buggy_code, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "introduce regression"], cwd=repo, check=True, capture_output=True
    )
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    report = evaluate_post_apply(
        change_id="test-change",
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        implementer_identity="codex",
        implementer_model_identity="openai/gpt-4o",
        review_evidence=review_ev,
        repo_root=repo,
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
            "-c",
            "test-change",
            "--base-sha",
            BASE_SHA,
            "--candidate-sha",
            CANDIDATE_SHA,
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert verify_fail.exit_code == 1
    verify_report = json.loads(verify_fail.output)
    assert verify_report["final_verdict"] == "BLOCKED"

    declared_checks = tmp_path / "claimed-checks.json"
    declared_checks.write_text(
        VerificationResult(
            candidate_sha=CANDIDATE_SHA,
            deterministic_checks_passed=True,
            tests_passed=True,
            linters_passed=True,
            schemas_passed=True,
            evidence_source="ci-run-pretend",
            provenance="canonical-ci-runner",
        ).model_dump_json(),
        encoding="utf-8",
    )
    forged_verify = runner.invoke(
        cli_app,
        [
            "evaluate-verify",
            "-c",
            "test-change",
            "--base-sha",
            BASE_SHA,
            "--candidate-sha",
            CANDIDATE_SHA,
            "--evidence-file",
            str(declared_checks),
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert forged_verify.exit_code == 1
    assert json.loads(forged_verify.output)["final_verdict"] == "BLOCKED"

    # 3. evaluate-archive fails closed without evidence
    archive_fail = runner.invoke(
        cli_app,
        [
            "evaluate-archive",
            "-c",
            "test-change",
            "--base-sha",
            BASE_SHA,
            "--candidate-sha",
            CANDIDATE_SHA,
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert archive_fail.exit_code == 1
    archive_report = json.loads(archive_fail.output)
    assert archive_report["final_verdict"] == "BLOCKED"

    # 4. A JSON review with trusted-looking provenance is ignored by the CLI.
    claimed_review = tmp_path / "claimed-review.json"
    claimed_review.write_text(
        ReviewEvidence(
            candidate_sha=CANDIDATE_SHA,
            reviewer_identity="invented-reviewer",
            reviewer_model_identity="invented-model",
            verdict="approve",
            summary="claimed approval",
            evaluated_specialties=[ReviewSpecialty.GENERAL_ARCHITECTURE],
            evidence_source="local",
            provenance="canonical-uow-review",
        ).model_dump_json(),
        encoding="utf-8",
    )
    post_apply_fail = runner.invoke(
        cli_app,
        [
            "evaluate-post-apply",
            "-c",
            "test-change",
            "--base-sha",
            BASE_SHA,
            "--candidate-sha",
            CANDIDATE_SHA,
            "--review-evidence-file",
            str(claimed_review),
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert post_apply_fail.exit_code == 1
    post_report = json.loads(post_apply_fail.output)
    assert post_report["final_verdict"] == "BLOCKED"
    assert post_report["reviewer_identity"] is None
