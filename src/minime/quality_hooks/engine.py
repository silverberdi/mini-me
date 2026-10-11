"""Core evaluation engine for OpenSpec Lifecycle Quality Hooks."""

from __future__ import annotations

from pathlib import Path

from minime.quality_hooks.analyzers.archive_analyzer import analyze_archive_integrity
from minime.quality_hooks.analyzers.candidate_identity import analyze_candidate_identity
from minime.quality_hooks.analyzers.model_independence import analyze_model_independence
from minime.quality_hooks.analyzers.pre_apply_analyzer import analyze_pre_apply_readiness
from minime.quality_hooks.analyzers.regression_pr139 import analyze_pr139_regressions
from minime.quality_hooks.models import (
    FindingSeverity,
    FindingStatus,
    HookVerdict,
    QualityHookFinding,
    QualityHookReport,
    QualityHookStage,
    ReviewSpecialty,
    VerificationResult,
    utc_now,
)
from minime.quality_hooks.specialties import (
    select_specialties_for_diff,
)


def resolve_final_verdict(
    findings: list[QualityHookFinding],
    *,
    is_blocked: bool = False,
    blocked_reasons: list[str] | None = None,
    verification_result: VerificationResult | None = None,
    require_verification_evidence: bool = False,
) -> tuple[HookVerdict, str]:
    """Determine final verdict (PASS, FAIL, BLOCKED) and comprehensive reason."""
    if is_blocked:
        reasons = blocked_reasons or ["Evaluation blocked by unmet lifecycle preconditions."]
        return HookVerdict.BLOCKED, "; ".join(reasons)

    if require_verification_evidence and verification_result is None:
        return HookVerdict.BLOCKED, "Mandatory verification evidence is missing; evaluation is BLOCKED."

    if verification_result is not None and not verification_result.deterministic_checks_passed:
        return HookVerdict.FAIL, "Deterministic checks (tests/linters/schemas) failed."

    unresolved_blocking = [
        f for f in findings
        if f.status == FindingStatus.UNRESOLVED and f.severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH)
    ]

    if unresolved_blocking:
        summary = f"{len(unresolved_blocking)} unresolved CRITICAL/HIGH finding(s): " + ", ".join(
            f"[{f.severity}] {f.finding_id}: {f.observed_evidence[:60]}" for f in unresolved_blocking[:3]
        )
        return HookVerdict.FAIL, summary

    return HookVerdict.PASS, "All deterministic checks and quality rules passed with zero unresolved blocking findings."


def evaluate_pre_apply(
    *,
    change_id: str,
    repository_identity: str = "silverberdi/mini-me",
    base_sha: str,
    candidate_sha: str,
    repo_root: str | Path = ".",
    openspec_path: str = "openspec",
) -> QualityHookReport:
    """Evaluate PRE-APPLY stage: Implementation Readiness & Boundary Checks."""
    findings: list[QualityHookFinding] = []
    blocked_reasons: list[str] = []

    # 1. Candidate and Base SHA validation
    id_findings = analyze_candidate_identity(repo_root, base_sha, candidate_sha, repository_identity)
    findings.extend(id_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in id_findings):
        blocked_reasons.append("Base or Candidate SHA is invalid or unreachable in repository.")

    # 2. Artifact and OpenSpec readiness
    pre_findings = analyze_pre_apply_readiness(repo_root, change_id, openspec_path)
    findings.extend(pre_findings)
    if any(f.finding_id == "PREAPPLY-CHANGE-NOT-FOUND" for f in pre_findings):
        blocked_reasons.append(f"OpenSpec change directory for '{change_id}' not found.")

    is_blocked = len(blocked_reasons) > 0
    verdict, reason = resolve_final_verdict(
        findings,
        is_blocked=is_blocked,
        blocked_reasons=blocked_reasons,
    )

    return QualityHookReport(
        hook_id=QualityHookStage.PRE_APPLY,
        contract_version="1.0.0",
        change_id=change_id,
        repository_identity=repository_identity,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        required_specialties=[ReviewSpecialty.GENERAL_ARCHITECTURE],
        evaluated_specialties=[ReviewSpecialty.GENERAL_ARCHITECTURE],
        findings=findings,
        final_verdict=verdict,
        verdict_reason=reason,
        evaluated_at=utc_now(),
    )


def evaluate_post_apply(
    *,
    change_id: str,
    repository_identity: str = "silverberdi/mini-me",
    base_sha: str,
    candidate_sha: str,
    implementer_identity: str | None = None,
    implementer_model_identity: str | None = None,
    reviewer_identity: str | None = None,
    reviewer_model_identity: str | None = None,
    changed_files: list[str] | None = None,
    diff_text: str = "",
    evaluated_specialties: list[ReviewSpecialty] | None = None,
    custom_findings: list[QualityHookFinding] | None = None,
    repo_root: str | Path = ".",
) -> QualityHookReport:
    """Evaluate POST-APPLY stage: Expert Review, Dynamic Specialties, and Independence."""
    findings: list[QualityHookFinding] = list(custom_findings or [])
    blocked_reasons: list[str] = []

    # 1. Candidate Identity
    id_findings = analyze_candidate_identity(repo_root, base_sha, candidate_sha, repository_identity)
    findings.extend(id_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in id_findings):
        blocked_reasons.append("Candidate SHA validation failed.")

    # 2. Reviewer Independence
    indep_findings = analyze_model_independence(
        implementer_identity=implementer_identity,
        implementer_model_identity=implementer_model_identity,
        reviewer_identity=reviewer_identity,
        reviewer_model_identity=reviewer_model_identity,
    )
    findings.extend(indep_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in indep_findings):
        blocked_reasons.append("Reviewer independence violated (same agent or same model family).")

    # 3. Dynamic Specialty Selection
    files = list(changed_files or [])
    required_specialties = select_specialties_for_diff(diff_text, files)
    evaluated = list(evaluated_specialties or [])

    # Check unfulfilled specialties
    missing_specialties = [s for s in required_specialties if s not in evaluated]
    if missing_specialties:
        blocked_reasons.append(
            f"Required review specialties unfulfilled: {', '.join(s.label for s in missing_specialties)}"
        )

    # 4. PR #139 Regression Pattern Checks on changed code
    if diff_text:
        reg_findings = analyze_pr139_regressions("diff", diff_text)
        findings.extend(reg_findings)

    is_blocked = len(blocked_reasons) > 0
    verdict, reason = resolve_final_verdict(
        findings,
        is_blocked=is_blocked,
        blocked_reasons=blocked_reasons,
    )

    return QualityHookReport(
        hook_id=QualityHookStage.POST_APPLY,
        contract_version="1.0.0",
        change_id=change_id,
        repository_identity=repository_identity,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        implementer_identity=implementer_identity,
        implementer_model_identity=implementer_model_identity,
        reviewer_identity=reviewer_identity,
        reviewer_model_identity=reviewer_model_identity,
        required_specialties=required_specialties,
        evaluated_specialties=evaluated,
        findings=findings,
        final_verdict=verdict,
        verdict_reason=reason,
        evaluated_at=utc_now(),
    )


def evaluate_verify(
    *,
    change_id: str,
    repository_identity: str = "silverberdi/mini-me",
    base_sha: str,
    candidate_sha: str,
    verification_result: VerificationResult | None,
    findings: list[QualityHookFinding] | None = None,
    repo_root: str | Path = ".",
) -> QualityHookReport:
    """Evaluate VERIFY stage: Quality & Acceptance Gate (evidence mandatory)."""
    all_findings = list(findings or [])
    blocked_reasons: list[str] = []

    # 1. Candidate Identity
    id_findings = analyze_candidate_identity(repo_root, base_sha, candidate_sha, repository_identity)
    all_findings.extend(id_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in id_findings):
        blocked_reasons.append("Candidate SHA validation failed.")

    # 2. Missing Evidence Check -> BLOCKED
    if verification_result is None:
        blocked_reasons.append("Mandatory deterministic verification evidence is missing.")

    is_blocked = len(blocked_reasons) > 0
    verdict, reason = resolve_final_verdict(
        all_findings,
        is_blocked=is_blocked,
        blocked_reasons=blocked_reasons,
        verification_result=verification_result,
        require_verification_evidence=True,
    )

    return QualityHookReport(
        hook_id=QualityHookStage.VERIFY,
        contract_version="1.0.0",
        change_id=change_id,
        repository_identity=repository_identity,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        findings=all_findings,
        verification_result=verification_result,
        final_verdict=verdict,
        verdict_reason=reason,
        evaluated_at=utc_now(),
    )


def evaluate_archive(
    *,
    change_id: str,
    repository_identity: str = "silverberdi/mini-me",
    base_sha: str,
    candidate_sha: str,
    pr_merged_by_human: bool,
    pr_number: int | None = None,
    human_approval_recorded: bool = True,
    findings: list[QualityHookFinding] | None = None,
    repo_root: str | Path = ".",
) -> QualityHookReport:
    """Evaluate ARCHIVE stage: Delivery Integrity and DoD Validation."""
    all_findings = list(findings or [])
    blocked_reasons: list[str] = []

    # 1. Candidate Identity
    id_findings = analyze_candidate_identity(repo_root, base_sha, candidate_sha, repository_identity)
    all_findings.extend(id_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in id_findings):
        blocked_reasons.append("Candidate SHA validation failed.")

    has_unresolved_crit_high = any(
        f.status == FindingStatus.UNRESOLVED and f.severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH)
        for f in all_findings
    )

    # 2. Archive DoD Integrity
    archive_findings = analyze_archive_integrity(
        pr_merged_by_human=pr_merged_by_human,
        pr_number=pr_number,
        human_approval_recorded=human_approval_recorded,
        has_unresolved_critical_high=has_unresolved_crit_high,
    )
    all_findings.extend(archive_findings)

    is_blocked = len(blocked_reasons) > 0
    verdict, reason = resolve_final_verdict(
        all_findings,
        is_blocked=is_blocked,
        blocked_reasons=blocked_reasons,
    )

    return QualityHookReport(
        hook_id=QualityHookStage.ARCHIVE,
        contract_version="1.0.0",
        change_id=change_id,
        repository_identity=repository_identity,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        findings=all_findings,
        final_verdict=verdict,
        verdict_reason=reason,
        evaluated_at=utc_now(),
    )
