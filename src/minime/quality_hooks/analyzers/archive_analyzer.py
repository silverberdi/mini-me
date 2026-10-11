"""ARCHIVE Delivery Integrity Quality Analyzer."""

from __future__ import annotations

from minime.quality_hooks.models import (
    FindingSeverity,
    FindingStatus,
    QualityHookFinding,
    ReviewSpecialty,
)


def analyze_archive_integrity(
    pr_merged_by_human: bool,
    pr_number: int | None = None,
    human_approval_recorded: bool = True,
    has_unresolved_critical_high: bool = False,
) -> list[QualityHookFinding]:
    """Validate Definition of Done (DoD) archive requirements."""
    findings: list[QualityHookFinding] = []

    # 1. Mandatory human merge check
    if not pr_merged_by_human:
        findings.append(
            QualityHookFinding(
                finding_id="ARCHIVE-NO-HUMAN-MERGE",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.CRITICAL,
                file_path=None,
                requirement_reference="CANONICAL-DECISIONS#human-merge-mandatory",
                observed_evidence="Candidate has not been merged by human operator.",
                expected_behavior="Human merge is strictly mandatory in MVP before archiving.",
                suggested_remediation="Require human operator to review and merge Pull Request before archiving.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    # 2. Human approval record check
    if not human_approval_recorded:
        findings.append(
            QualityHookFinding(
                finding_id="ARCHIVE-MISSING-HUMAN-APPROVAL",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.HIGH,
                file_path=None,
                requirement_reference="DOR-DOD#definition-of-done",
                observed_evidence="Human approval record is missing for candidate.",
                expected_behavior="Authoritative human approval must be recorded prior to archiving.",
                suggested_remediation="Record explicit human approval for candidate in audit trace.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    # 3. Blocking findings check
    if has_unresolved_critical_high:
        findings.append(
            QualityHookFinding(
                finding_id="ARCHIVE-UNRESOLVED-FINDINGS",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.CRITICAL,
                file_path=None,
                requirement_reference="DOR-DOD#blocking-findings-resolved",
                observed_evidence="Unresolved CRITICAL or HIGH findings remain active on candidate.",
                expected_behavior="All blocking findings must be resolved or explicitly overridden with human reason.",
                suggested_remediation="Resolve all CRITICAL and HIGH findings prior to archive.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    return findings
