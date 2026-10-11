"""Core evaluation engine for OpenSpec Lifecycle Quality Hooks with authoritative evidence enforcement."""

from __future__ import annotations

import subprocess
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
    HumanApprovalEvidence,
    MergeEvidence,
    QualityHookFinding,
    QualityHookReport,
    QualityHookStage,
    ReviewEvidence,
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

    if require_verification_evidence:
        if verification_result is None:
            return HookVerdict.BLOCKED, "Mandatory verification evidence is missing; evaluation is BLOCKED."
        if not verification_result.deterministic_checks_passed:
            return HookVerdict.FAIL, "Deterministic checks (tests/linters/schemas) failed in verified evidence."

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
    review_evidence: ReviewEvidence | None = None,
    repo_root: str | Path = ".",
    # Fallbacks only allowed for testing with mock git
    _override_changed_files: list[str] | None = None,
    _override_diff_text: str | None = None,
) -> QualityHookReport:
    """Evaluate POST-APPLY stage: Expert Review, Dynamic Specialties, and Independence.

    Authoritative constraints:
    1. Obtains changed files and real diff directly from Git (base_sha..candidate_sha).
    2. Requires verifiable ReviewEvidence bound strictly to candidate_sha.
    3. Self-declared reviewer identity or specialties without review evidence is BLOCKED.
    """
    findings: list[QualityHookFinding] = []
    blocked_reasons: list[str] = []

    # 1. Candidate Identity
    id_findings = analyze_candidate_identity(repo_root, base_sha, candidate_sha, repository_identity)
    findings.extend(id_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in id_findings):
        blocked_reasons.append("Candidate SHA validation failed.")

    # 2. Authoritative Git diff and changed files extraction
    changed_files: list[str] = []
    diff_text: str = ""

    if _override_changed_files is not None and _override_diff_text is not None:
        changed_files = list(_override_changed_files)
        diff_text = _override_diff_text
    else:
        root_path = Path(repo_root)
        if not (root_path / ".git").exists():
            blocked_reasons.append(f"Repository at '{repo_root}' is not a valid Git worktree.")
        else:
            diff_files_proc = subprocess.run(
                ["git", "diff", "--name-only", f"{base_sha}..{candidate_sha}"],
                cwd=str(root_path),
                capture_output=True,
                text=True,
            )
            diff_proc = subprocess.run(
                ["git", "diff", f"{base_sha}..{candidate_sha}"],
                cwd=str(root_path),
                capture_output=True,
                text=True,
            )
            if diff_files_proc.returncode != 0 or diff_proc.returncode != 0:
                blocked_reasons.append(
                    f"Failed to obtain authoritative git diff for {base_sha}..{candidate_sha}: {diff_files_proc.stderr or diff_proc.stderr}"
                )
            else:
                changed_files = [f.strip() for f in diff_files_proc.stdout.splitlines() if f.strip()]
                diff_text = diff_proc.stdout

    # 3. Dynamic Specialty Selection from authoritative diff
    required_specialties = select_specialties_for_diff(diff_text, changed_files)

    # 4. Enforce Verifiable Review Evidence (FAIL-CLOSED: cannot just declare reviewer)
    reviewer_identity: str | None = None
    reviewer_model_identity: str | None = None
    evaluated_specialties: list[ReviewSpecialty] = []

    if review_evidence is None:
        blocked_reasons.append(
            "Verifiable review evidence is missing. Self-declared specialties or reviewer models without authoritative review evidence are rejected."
        )
    else:
        # Candidate binding check
        if review_evidence.candidate_sha != candidate_sha:
            blocked_reasons.append(
                f"Review evidence is bound to SHA '{review_evidence.candidate_sha}', which does not match candidate SHA '{candidate_sha}' (stale review)."
            )

        reviewer_identity = review_evidence.reviewer_identity
        reviewer_model_identity = review_evidence.reviewer_model_identity
        evaluated_specialties = list(review_evidence.evaluated_specialties)
        findings.extend(review_evidence.findings)

        # Reviewer Independence check
        indep_findings = analyze_model_independence(
            implementer_identity=implementer_identity,
            implementer_model_identity=implementer_model_identity,
            reviewer_identity=reviewer_identity,
            reviewer_model_identity=reviewer_model_identity,
        )
        findings.extend(indep_findings)
        if any(f.severity == FindingSeverity.CRITICAL for f in indep_findings):
            blocked_reasons.append("Reviewer independence violated (same agent or same model family).")

        # Specialty fulfillment check
        missing_specialties = [s for s in required_specialties if s not in evaluated_specialties]
        if missing_specialties:
            blocked_reasons.append(
                f"Required review specialties unfulfilled by review evidence: {', '.join(s.label for s in missing_specialties)}"
            )

        # Review verdict check
        if review_evidence.verdict.lower() in ("changes_requested", "reject"):
            findings.append(
                QualityHookFinding(
                    finding_id="REVIEW-VERDICT-REJECTED",
                    specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                    severity=FindingSeverity.HIGH,
                    file_path=None,
                    requirement_reference="REVIEWER-CONTRACT#verdict",
                    observed_evidence=f"Reviewer rendered negative verdict: {review_evidence.verdict} ({review_evidence.summary})",
                    expected_behavior="Candidate must receive approval from authoritative reviewer.",
                    suggested_remediation="Address reviewer feedback and request re-review.",
                    status=FindingStatus.UNRESOLVED,
                )
            )

    # 5. Scan git diff for PR #139 regression pattern
    if diff_text:
        reg_findings = analyze_pr139_regressions("git_diff", diff_text)
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
        evaluated_specialties=evaluated_specialties,
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
    """Evaluate VERIFY stage: Quality & Acceptance Gate (strictly evidence-based).

    Authoritative constraints:
    1. Zero assumed PASS results.
    2. Verification evidence MUST exist and be bound strictly to candidate_sha.
    3. Missing or unbound evidence fails closed as BLOCKED.
    """
    all_findings = list(findings or [])
    blocked_reasons: list[str] = []

    # 1. Candidate Identity
    id_findings = analyze_candidate_identity(repo_root, base_sha, candidate_sha, repository_identity)
    all_findings.extend(id_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in id_findings):
        blocked_reasons.append("Candidate SHA validation failed.")

    # 2. Strict evidence requirement
    if verification_result is None:
        blocked_reasons.append("Mandatory deterministic verification evidence is missing; evaluation is BLOCKED.")
    else:
        if verification_result.candidate_sha != candidate_sha:
            blocked_reasons.append(
                f"Verification evidence candidate SHA '{verification_result.candidate_sha}' does not match candidate SHA '{candidate_sha}'."
            )
        if not verification_result.evidence_source:
            blocked_reasons.append("Verification evidence lacks a verifiable source or log reference.")

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
    merge_evidence: MergeEvidence | None = None,
    human_approval_evidence: HumanApprovalEvidence | None = None,
    findings: list[QualityHookFinding] | None = None,
    repo_root: str | Path = ".",
) -> QualityHookReport:
    """Evaluate ARCHIVE stage: Delivery Integrity and DoD Validation.

    Authoritative constraints:
    1. No self-claim flags (--merged-by-human) or default approval values.
    2. Must verify merge and human approval from authoritative evidence bound to candidate SHA.
    3. Missing authoritative query mechanism or evidence returns BLOCKED, never PASS.
    """
    all_findings = list(findings or [])
    blocked_reasons: list[str] = []

    # 1. Candidate Identity
    id_findings = analyze_candidate_identity(repo_root, base_sha, candidate_sha, repository_identity)
    all_findings.extend(id_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in id_findings):
        blocked_reasons.append("Candidate SHA validation failed.")

    # 2. Check Merge Evidence
    pr_merged_by_human = False
    if merge_evidence is None:
        blocked_reasons.append(
            "Authoritative merge verification evidence is missing; failing closed as BLOCKED."
        )
    else:
        if merge_evidence.candidate_sha != candidate_sha:
            blocked_reasons.append(
                f"Merge evidence candidate SHA '{merge_evidence.candidate_sha}' does not match candidate '{candidate_sha}'."
            )
        else:
            is_bot = (
                merge_evidence.merged_by_type.lower() == "bot"
                or merge_evidence.merged_by.endswith("[bot]")
            )
            if merge_evidence.is_merged and not is_bot:
                pr_merged_by_human = True
            else:
                pr_merged_by_human = False

    # 3. Check Human Approval Evidence
    human_approval_recorded = False
    if human_approval_evidence is None:
        blocked_reasons.append(
            "Authoritative human approval evidence is missing; failing closed as BLOCKED."
        )
    else:
        if human_approval_evidence.candidate_head_sha != candidate_sha:
            blocked_reasons.append(
                f"Human approval evidence candidate SHA '{human_approval_evidence.candidate_head_sha}' does not match candidate '{candidate_sha}'."
            )
        elif human_approval_evidence.base_sha != base_sha:
            blocked_reasons.append(
                f"Human approval evidence base SHA '{human_approval_evidence.base_sha}' does not match base '{base_sha}'."
            )
        else:
            if human_approval_evidence.decision.lower() == "approve":
                human_approval_recorded = True
            else:
                human_approval_recorded = False

    # 4. Check unresolved findings
    has_unresolved_crit_high = any(
        f.status == FindingStatus.UNRESOLVED and f.severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH)
        for f in all_findings
    )

    # 5. Analyze Archive Integrity
    archive_findings = analyze_archive_integrity(
        pr_merged_by_human=pr_merged_by_human,
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
