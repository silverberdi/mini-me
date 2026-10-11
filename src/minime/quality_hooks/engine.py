"""Core evaluation engine for OpenSpec Lifecycle Quality Hooks with authoritative canonical evidence enforcement."""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from minime.domain.interfaces import GitHubAdapterInterface
from minime.quality_hooks.analyzers.archive_analyzer import analyze_archive_integrity
from minime.quality_hooks.analyzers.candidate_identity import analyze_candidate_identity
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
from minime.quality_hooks.specialties import select_specialties_for_diff


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
            return (
                HookVerdict.BLOCKED,
                "Mandatory verification evidence is missing; evaluation is BLOCKED.",
            )
        if not verification_result.deterministic_checks_passed:
            return (
                HookVerdict.FAIL,
                "Deterministic checks (tests/linters/schemas) failed in verified evidence.",
            )
        if not verification_result.schemas_passed:
            return HookVerdict.FAIL, "Schema validation checks failed or were not executed."

    unresolved_blocking = [
        f
        for f in findings
        if f.status == FindingStatus.UNRESOLVED
        and f.severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH)
    ]

    if unresolved_blocking:
        summary = f"{len(unresolved_blocking)} unresolved CRITICAL/HIGH finding(s): " + ", ".join(
            f"[{f.severity}] {f.finding_id}: {f.observed_evidence[:60]}"
            for f in unresolved_blocking[:3]
        )
        return HookVerdict.FAIL, summary

    return (
        HookVerdict.PASS,
        "All deterministic checks and quality rules passed with zero unresolved blocking findings.",
    )


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
    id_findings = analyze_candidate_identity(
        repo_root, base_sha, candidate_sha, repository_identity
    )
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
) -> QualityHookReport:
    """Evaluate POST-APPLY stage: Expert Review, Dynamic Specialties, and Independence.

    Authoritative constraints:
    1. Obtains changed files and real diff directly from Git (base_sha..candidate_sha).
    2. Requires a canonical persisted review carrying specialty-level evidence.
    3. ReviewEvidence is only a report payload; its provenance string is not authority.
    """
    findings: list[QualityHookFinding] = []
    blocked_reasons: list[str] = []

    # 1. Candidate Identity
    id_findings = analyze_candidate_identity(
        repo_root, base_sha, candidate_sha, repository_identity
    )
    findings.extend(id_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in id_findings):
        blocked_reasons.append("Candidate SHA validation failed.")

    # 2. Authoritative Git diff and changed files extraction
    changed_files: list[str] = []
    diff_text: str = ""

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

    # 4. No existing durable review source records authenticated identities plus specialty coverage.
    # ReviewEvidence is intentionally not projected into the report: its fields are caller claims.
    blocked_reasons.append(
        "Canonical specialty-aware reviewer evidence is unavailable; reviewer identity, independence, "
        "candidate binding, and evaluated specialties cannot be authenticated."
    )

    # 5. Scan the final candidate blobs (not diff-prefixed lines) for PR #139 regressions.
    for changed_file in changed_files:
        blob = subprocess.run(
            ["git", "show", f"{candidate_sha}:{changed_file}"],
            cwd=root_path,
            capture_output=True,
            text=True,
        )
        if blob.returncode == 0:
            findings.extend(analyze_pr139_regressions(changed_file, blob.stdout))

    has_blocking_findings = any(
        f.status == FindingStatus.UNRESOLVED
        and f.severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH)
        for f in findings
    )
    is_blocked = len(blocked_reasons) > 0 and not has_blocking_findings
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
        reviewer_identity=None,
        reviewer_model_identity=None,
        required_specialties=required_specialties,
        evaluated_specialties=[],
        findings=findings,
        final_verdict=verdict,
        verdict_reason=reason,
        evaluated_at=utc_now(),
    )


def _run_checks_for_candidate(
    repo_root: str | Path, candidate_sha: str
) -> tuple[VerificationResult | None, str | None]:
    """Run checks against an isolated export of the exact clean candidate commit."""
    root_path = Path(repo_root).resolve()
    if not (root_path / ".git").exists():
        return None, f"Repository path '{root_path}' is not a Git worktree."

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root_path, capture_output=True, text=True
    )
    if head.returncode or head.stdout.strip() != candidate_sha:
        return (
            None,
            f"Worktree HEAD '{head.stdout.strip()}' does not match candidate SHA '{candidate_sha}'.",
        )

    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root_path,
        capture_output=True,
        text=True,
    )
    if status.returncode or status.stdout.strip():
        return (
            None,
            "Candidate worktree has tracked or untracked changes; execution identity is not provable.",
        )

    with tempfile.TemporaryDirectory(prefix="minime-quality-verify-") as temp_dir:
        archive_path = Path(temp_dir) / "candidate.tar"
        extracted = Path(temp_dir) / "candidate"
        extracted.mkdir()
        archive = subprocess.run(
            ["git", "archive", "--format=tar", "--output", str(archive_path), candidate_sha],
            cwd=root_path,
            capture_output=True,
            text=True,
        )
        if archive.returncode:
            return None, f"Cannot materialize candidate Git tree: {archive.stderr.strip()}"
        try:
            with tarfile.open(archive_path) as candidate_tar:
                candidate_tar.extractall(extracted, filter="data")
        except (OSError, tarfile.TarError, ValueError) as exc:
            return None, f"Cannot safely materialize candidate Git tree: {exc}"

        def run(args: list[str]) -> subprocess.CompletedProcess[str]:
            try:
                return subprocess.run(
                    args, cwd=extracted, capture_output=True, text=True, timeout=3600
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return subprocess.CompletedProcess(args, 127, "", str(exc))

        tests = run([sys.executable, "-m", "pytest", "-q"])
        lint = run([sys.executable, "-m", "ruff", "check", "src", "tests"])
        openspec = run(["openspec", "validate", "--all", "--strict"])

        for name, proc in (("pytest", tests), ("Ruff", lint), ("OpenSpec", openspec)):
            if proc.returncode == 127 and (
                "No such file" in proc.stderr or "not found" in proc.stderr
            ):
                return None, f"{name} executable is unavailable; candidate verification is BLOCKED."

        schema_files = sorted((extracted / "schemas").glob("*.json"))
        schema_ok = bool(schema_files)
        schema_error = None
        try:
            from jsonschema.validators import validator_for
        except ImportError:
            return None, "JSON Schema validator is unavailable; candidate verification is BLOCKED."
        try:
            for schema_file in schema_files:
                schema = json.loads(schema_file.read_text(encoding="utf-8"))
                validator_for(schema).check_schema(schema)
        except Exception as exc:
            schema_ok = False
            schema_error = str(exc)

        checks_ok = (
            tests.returncode == 0
            and lint.returncode == 0
            and openspec.returncode == 0
            and schema_ok
        )
        result = VerificationResult(
            candidate_sha=candidate_sha,
            deterministic_checks_passed=checks_ok,
            tests_passed=tests.returncode == 0,
            linters_passed=lint.returncode == 0,
            schemas_passed=openspec.returncode == 0 and schema_ok,
            evidence_source="isolated-git-archive-runner",
            provenance="canonical-worktree-runner",
            check_details={
                "pytest_returncode": tests.returncode,
                "ruff_returncode": lint.returncode,
                "openspec_strict_returncode": openspec.returncode,
                "json_schemas_validated": len(schema_files),
                "json_schema_error": schema_error,
                "execution_tree": "git archive of exact candidate commit",
            },
        )
        return result, None


def evaluate_verify(
    *,
    change_id: str,
    repository_identity: str = "silverberdi/mini-me",
    base_sha: str,
    candidate_sha: str,
    verification_result: VerificationResult | None = None,
    run_checks: bool = False,
    findings: list[QualityHookFinding] | None = None,
    repo_root: str | Path = ".",
) -> QualityHookReport:
    """Evaluate VERIFY stage: Quality & Acceptance Gate (strictly evidence-based).

    Authoritative constraints:
    1. Zero assumed PASS results.
    2. Checks run in-process against a clean Git archive of the exact candidate commit.
    3. Caller-supplied result objects are not accepted as evidence.
    """
    all_findings = list(findings or [])
    blocked_reasons: list[str] = []

    # 1. Candidate Identity
    id_findings = analyze_candidate_identity(
        repo_root, base_sha, candidate_sha, repository_identity
    )
    all_findings.extend(id_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in id_findings):
        blocked_reasons.append("Candidate SHA validation failed.")

    # 2. Execute checks here; a serialized result or caller-built model is not an authority.
    if run_checks:
        verification_result, run_error = _run_checks_for_candidate(repo_root, candidate_sha)
        if run_error:
            blocked_reasons.append(run_error)
    elif verification_result is not None:
        blocked_reasons.append(
            "Caller-supplied verification payload is not authoritative; use --run-checks to execute checks on the candidate tree."
        )
    else:
        blocked_reasons.append("Mandatory deterministic verification checks were not executed.")

    if verification_result is not None and run_checks:
        if verification_result.candidate_sha != candidate_sha:
            blocked_reasons.append(
                "Executed verification is not bound to the requested candidate SHA."
            )
        if verification_result.provenance != "canonical-worktree-runner":
            blocked_reasons.append("Internal verification runner identity is unavailable.")

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
    pull_request_number: int | None = None,
    target_branch: str = "main",
    github_adapter: GitHubAdapterInterface | None = None,
    merge_evidence: MergeEvidence | None = None,
    human_approval_evidence: HumanApprovalEvidence | None = None,
    findings: list[QualityHookFinding] | None = None,
    repo_root: str | Path = ".",
) -> QualityHookReport:
    """Evaluate ARCHIVE from GitHub observations; serialized evidence is never authority."""
    all_findings = list(findings or [])
    blocked_reasons: list[str] = []

    # 1. Candidate Identity
    id_findings = analyze_candidate_identity(
        repo_root, base_sha, candidate_sha, repository_identity
    )
    all_findings.extend(id_findings)
    if any(f.severity == FindingSeverity.CRITICAL for f in id_findings):
        blocked_reasons.append("Candidate SHA validation failed.")

    # Supplied evidence models are untrusted payloads, regardless of provenance labels.
    if merge_evidence is not None or human_approval_evidence is not None:
        blocked_reasons.append(
            "Caller-supplied merge/approval payloads are not accepted as authority."
        )

    # 2. Observe the actual PR through the configured GitHub adapter.
    pr_merged_by_human = False
    human_approval_recorded = False
    if pull_request_number is None or pull_request_number <= 0:
        blocked_reasons.append(
            "A pull-request number is required for direct GitHub merge verification."
        )
    else:
        if github_adapter is None:
            from minime.adapters.github import GitHubAdapter

            github_adapter = GitHubAdapter()
        try:
            pr_result = github_adapter.get_pull_request_details(
                repository_identity, pull_request_number
            )
        except Exception as exc:
            pr_result = None
            blocked_reasons.append(f"GitHub pull-request lookup failed closed: {exc}")
        pr = pr_result.data if pr_result is not None and pr_result.is_success else None
        if not isinstance(pr, dict):
            blocked_reasons.append("GitHub pull-request state is unavailable; ARCHIVE is BLOCKED.")
        else:
            merged_by_type = pr.get("merged_by_type")
            merged_by_login = pr.get("merged_by_login")
            pr_merged_by_human = bool(
                pr.get("number") == pull_request_number
                and pr.get("head_sha") == candidate_sha
                and pr.get("base_branch") == target_branch
                and pr.get("is_merged") is True
                and pr.get("merged_at")
                and pr.get("merge_commit_sha")
                and merged_by_type == "User"
                and merged_by_login
                and not str(merged_by_login).endswith("[bot]")
            )
            if not pr_merged_by_human:
                blocked_reasons.append(
                    "GitHub PR does not prove a human merge of the exact candidate SHA into the requested target branch."
                )

            try:
                reviews_result = github_adapter.get_pull_request_reviews(
                    repository_identity, pull_request_number
                )
            except Exception as exc:
                reviews_result = None
                blocked_reasons.append(f"GitHub review lookup failed closed: {exc}")
            reviews = (
                reviews_result.data
                if reviews_result is not None and reviews_result.is_success
                else None
            )
            if reviews is None:
                blocked_reasons.append(
                    "GitHub pull-request approvals are unavailable; ARCHIVE is BLOCKED."
                )
            else:
                latest_by_reviewer: dict[str, tuple[datetime, dict]] = {}
                invalid_review_time = False
                for row in reviews:
                    reviewer = row.get("user_login")
                    if reviewer and row.get("user_type") == "User":
                        try:
                            reviewed_at = datetime.fromisoformat(
                                row.get("submitted_at", "").replace("Z", "+00:00")
                            )
                            if reviewed_at.tzinfo is None:
                                raise ValueError(
                                    "Review timestamp is missing timezone information."
                                )
                        except (AttributeError, TypeError, ValueError):
                            invalid_review_time = True
                            continue
                        current = latest_by_reviewer.get(reviewer)
                        if current is None or reviewed_at > current[0]:
                            latest_by_reviewer[reviewer] = (reviewed_at, row)
                human_approval_recorded = any(
                    row.get("state") == "APPROVED"
                    and row.get("commit_id") == candidate_sha
                    and not reviewer.endswith("[bot]")
                    for reviewer, (_, row) in latest_by_reviewer.items()
                )
                if invalid_review_time:
                    blocked_reasons.append(
                        "GitHub review timestamps are incomplete or invalid; approval ordering cannot be verified."
                    )
                    human_approval_recorded = False
                elif not human_approval_recorded:
                    blocked_reasons.append(
                        "No authenticated human GitHub approval is bound to the exact candidate SHA."
                    )

    # GitHub review binds to the immutable head. Confirm the supplied base is an ancestor.
    base_relation = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_sha, candidate_sha],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if base_relation.returncode != 0:
        blocked_reasons.append(
            "Candidate/base ancestry could not be verified in the local Git object database."
        )

    # 4. Check unresolved findings
    has_unresolved_crit_high = any(
        f.status == FindingStatus.UNRESOLVED
        and f.severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH)
        for f in all_findings
    )

    # 5. Analyze Archive Integrity
    archive_findings = analyze_archive_integrity(
        pr_merged_by_human=pr_merged_by_human,
        human_approval_recorded=human_approval_recorded,
        has_unresolved_critical_high=has_unresolved_crit_high,
    )
    all_findings.extend(archive_findings)

    # No canonical aggregate Definition-of-Done authority is currently wired to this gate.
    blocked_reasons.append(
        "Full Definition-of-Done evidence is not available from a canonical lifecycle authority; closure cannot be declared."
    )

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
