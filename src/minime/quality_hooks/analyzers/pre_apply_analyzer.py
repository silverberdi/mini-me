"""PRE-APPLY Implementation Readiness Quality Analyzer."""

from __future__ import annotations

from pathlib import Path

from minime.quality_hooks.models import (
    FindingSeverity,
    FindingStatus,
    QualityHookFinding,
    ReviewSpecialty,
)


def analyze_pre_apply_readiness(
    repo_root: str | Path,
    change_id: str,
    openspec_path: str = "openspec",
) -> list[QualityHookFinding]:
    """Validate OpenSpec artifacts and scope boundaries before apply begins."""
    findings: list[QualityHookFinding] = []
    root = Path(repo_root)
    change_dir = root / openspec_path / "changes" / change_id

    if not change_dir.exists():
        findings.append(
            QualityHookFinding(
                finding_id="PREAPPLY-CHANGE-NOT-FOUND",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.CRITICAL,
                file_path=str(change_dir),
                requirement_reference="OPENSPEC-SPEC-DRIVEN#change-directory",
                observed_evidence=f"OpenSpec change directory '{change_dir}' does not exist.",
                expected_behavior="Target OpenSpec change directory must exist before implementation.",
                suggested_remediation=f"Create OpenSpec change '{change_id}' using openspec new or propose.",
                status=FindingStatus.UNRESOLVED,
            )
        )
        return findings

    # Required artifacts in spec-driven schema
    proposal_file = change_dir / "proposal.md"
    tasks_file = change_dir / "tasks.md"
    design_file = change_dir / "design.md"
    specs_dir = change_dir / "specs"

    if not proposal_file.exists():
        findings.append(
            QualityHookFinding(
                finding_id="PREAPPLY-MISSING-PROPOSAL",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.HIGH,
                file_path=str(proposal_file),
                requirement_reference="OPENSPEC-SPEC-DRIVEN#proposal",
                observed_evidence="proposal.md artifact is missing in change directory.",
                expected_behavior="proposal.md must define value, scope, and non-goals.",
                suggested_remediation="Generate proposal.md for change before starting apply.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    if not design_file.exists():
        findings.append(
            QualityHookFinding(
                finding_id="PREAPPLY-MISSING-DESIGN",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.MEDIUM,
                file_path=str(design_file),
                requirement_reference="OPENSPEC-SPEC-DRIVEN#design",
                observed_evidence="design.md artifact is missing in change directory.",
                expected_behavior="design.md should document architectural decisions and technical approach.",
                suggested_remediation="Generate design.md for change if architectural decisions are required.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    if not specs_dir.exists():
        findings.append(
            QualityHookFinding(
                finding_id="PREAPPLY-MISSING-SPECS",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.MEDIUM,
                file_path=str(specs_dir),
                requirement_reference="OPENSPEC-SPEC-DRIVEN#specs",
                observed_evidence="specs directory is missing in change directory.",
                expected_behavior="specs directory should define observable requirements and scenarios.",
                suggested_remediation="Create specs directory with delta specs if capability specs are affected.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    if not tasks_file.exists():
        findings.append(
            QualityHookFinding(
                finding_id="PREAPPLY-MISSING-TASKS",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.CRITICAL,
                file_path=str(tasks_file),
                requirement_reference="OPENSPEC-SPEC-DRIVEN#tasks",
                observed_evidence="tasks.md artifact is missing in change directory.",
                expected_behavior="tasks.md must define ordered, testable tasks for the change.",
                suggested_remediation="Create tasks.md artifact with actionable task checklist.",
                status=FindingStatus.UNRESOLVED,
            )
        )
    else:
        # Inspect tasks content
        content = tasks_file.read_text(encoding="utf-8")
        if "- [ ]" not in content and "- [x]" not in content:
            findings.append(
                QualityHookFinding(
                    finding_id="PREAPPLY-EMPTY-TASKS",
                    specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                    severity=FindingSeverity.HIGH,
                    file_path=str(tasks_file),
                    requirement_reference="OPENSPEC-SPEC-DRIVEN#tasks-format",
                    observed_evidence="tasks.md does not contain any checklist tasks ('- [ ]').",
                    expected_behavior="tasks.md must contain concrete checklist items for apply.",
                    suggested_remediation="Add structured task items to tasks.md.",
                    status=FindingStatus.UNRESOLVED,
                )
            )

    return findings
