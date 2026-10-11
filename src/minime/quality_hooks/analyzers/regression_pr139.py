"""Deterministic static analyzer for PR #139 regression pattern.

Defect pattern:
1. Swallowing authentication / token retrieval exceptions on HTTPS operations and returning
   empty credentials/dict `{}` instead of raising explicit authorization errors (silent unauthenticated fallback).
2. Unsanitized exception / log formatting that interpolates raw credentials, tokens, or headers.
3. Swallowing failure in git auth bundle when authenticated remote is required (fail-closed violation).
"""

from __future__ import annotations

import re

from minime.quality_hooks.models import (
    FindingSeverity,
    FindingStatus,
    QualityHookFinding,
    ReviewSpecialty,
)

_TRY_EXCEPT_EMPTY_DICT_PATTERN = re.compile(
    r"try:\s*\n(?P<try_body>.*?)\n\s*except\s+(?P<exc>[^:]*):\s*\n(?P<exc_body>.*?)(?:return\s*\{\s*\})",
    re.IGNORECASE | re.DOTALL,
)

_SECRET_LEAK_IN_EXCEPTION_PATTERN = re.compile(
    r"(?:raise\s+[A-Za-z0-9_]*Error\s*\(\s*f?[\"'].*?(?:token|secret|password|api_key|authorization)\s*[:=]\s*\{[a-zA-Z0-9_]+)",
    re.IGNORECASE,
)


def analyze_pr139_regressions(
    file_path: str,
    content: str,
) -> list[QualityHookFinding]:
    """Scan file content for PR #139 auth failure swallowing and secret leakage patterns."""
    findings: list[QualityHookFinding] = []

    # Check for empty auth fallback in exception handlers
    for match in _TRY_EXCEPT_EMPTY_DICT_PATTERN.finditer(content):
        combined_context = match.group("try_body") + "\n" + match.group("exc_body")
        if re.search(r"\b(?:token|auth|credential|secret|httpx|bearer)\b", combined_context, re.IGNORECASE):
            line_num = content[:match.start()].count("\n") + 1
            findings.append(
                QualityHookFinding(
                    finding_id=f"PR139-AUTH-SWALLOW-{line_num}",
                    specialty=ReviewSpecialty.SECURITY_AUTH,
                    severity=FindingSeverity.CRITICAL,
                    file_path=file_path,
                    line_number=line_num,
                    requirement_reference="CANONICAL-DECISIONS#auth-fail-closed",
                    observed_evidence=f"Exception handler returns empty credentials/dict: {match.group(0)[:80]}...",
                    expected_behavior="Propagate explicit authorization error fail-closed without silent unauthenticated fallback.",
                    suggested_remediation="Raise explicit sanitized authorization exception when token or credentials retrieval fails.",
                    status=FindingStatus.UNRESOLVED,
                )
            )

    # Check for secret or token leakage in raised exception strings
    for match in _SECRET_LEAK_IN_EXCEPTION_PATTERN.finditer(content):
        line_num = content[:match.start()].count("\n") + 1
        findings.append(
            QualityHookFinding(
                finding_id=f"PR139-SECRET-LEAK-{line_num}",
                specialty=ReviewSpecialty.SECURITY_AUTH,
                severity=FindingSeverity.CRITICAL,
                file_path=file_path,
                line_number=line_num,
                requirement_reference="CANONICAL-DECISIONS#secret-sanitization",
                observed_evidence=f"Exception message interpolates credential or secret variable: {match.group(0)[:80]}...",
                expected_behavior="Sanitize exceptions; never expose raw credentials, tokens, or auth headers in error messages.",
                suggested_remediation="Log sanitized error messages and omit raw secret/token values from exception messages.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    return findings
