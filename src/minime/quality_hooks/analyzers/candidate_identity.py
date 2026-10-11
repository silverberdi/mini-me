"""Candidate Identity and Git Integrity Quality Analyzer."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from minime.quality_hooks.models import (
    FindingSeverity,
    FindingStatus,
    QualityHookFinding,
    ReviewSpecialty,
)

_SHA_REGEX = re.compile(r"^[0-9a-fA-F]{40}$")


def analyze_candidate_identity(
    repo_root: str | Path,
    base_sha: str,
    candidate_sha: str,
    expected_repo_identity: str = "silverberdi/mini-me",
) -> list[QualityHookFinding]:
    """Verify candidate SHA, base SHA, and repository binding integrity."""
    findings: list[QualityHookFinding] = []

    # 1. Validate Base SHA format
    if not base_sha or not _SHA_REGEX.match(base_sha):
        findings.append(
            QualityHookFinding(
                finding_id="CANDIDATE-INVALID-BASE-SHA",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.CRITICAL,
                file_path=None,
                requirement_reference="CANONICAL-DECISIONS#candidate-identity",
                observed_evidence=f"Base SHA '{base_sha}' is missing or not a valid 40-character hex SHA.",
                expected_behavior="Base SHA must be a valid 40-character commit SHA.",
                suggested_remediation="Provide valid base_sha commit hash for candidate evaluation.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    # 2. Validate Candidate SHA format
    if not candidate_sha or not _SHA_REGEX.match(candidate_sha):
        findings.append(
            QualityHookFinding(
                finding_id="CANDIDATE-INVALID-CANDIDATE-SHA",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.CRITICAL,
                file_path=None,
                requirement_reference="CANONICAL-DECISIONS#candidate-identity",
                observed_evidence=f"Candidate SHA '{candidate_sha}' is missing or not a valid 40-character hex SHA.",
                expected_behavior="Candidate SHA must be a valid 40-character commit SHA.",
                suggested_remediation="Provide valid candidate_sha commit hash for candidate evaluation.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    # 3. Check git repo commit existence if directory exists
    repo_path = Path(repo_root)
    if repo_path.exists() and (repo_path / ".git").exists():
        if _SHA_REGEX.match(candidate_sha):
            res = subprocess.run(
                ["git", "cat-file", "-e", f"{candidate_sha}^{{commit}}"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                findings.append(
                    QualityHookFinding(
                        finding_id="CANDIDATE-SHA-NOT-FOUND",
                        specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                        severity=FindingSeverity.CRITICAL,
                        file_path=None,
                        requirement_reference="CANONICAL-DECISIONS#candidate-identity",
                        observed_evidence=f"Candidate SHA '{candidate_sha}' does not exist in local repository object storage.",
                        expected_behavior="Candidate SHA must be a committed, reachable git object in the target worktree.",
                        suggested_remediation="Commit candidate changes or fetch candidate ref before running quality evaluation.",
                        status=FindingStatus.UNRESOLVED,
                    )
                )

    return findings
