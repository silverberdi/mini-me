"""Strict parser for DeepSeek Direct audit results."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from minime.domain.enums import AuditFindingSeverity, AuditRiskLevel
from minime.domain.models import AuditResult


class MalformedAuditOutputError(ValueError):
    """Raised when audit output is missing, invalid, or ambiguous."""

    pass


def parse_audit_result(raw_output: str | list[str]) -> AuditResult:
    """Parse exactly one authoritative audit JSON payload.

    Allows a single optional markdown code fence wrapping the entire payload.
    Does not scan prose for JSON fragments or accept multiple payloads.
    """
    text = (
        "\n".join(raw_output).strip() if isinstance(raw_output, list) else str(raw_output).strip()
    )
    if not text:
        raise MalformedAuditOutputError("Audit output is empty.")

    fence_pattern = re.compile(r"^```(?:json)?\s*\n?([\s\S]*?)\n?```\s*$", re.IGNORECASE)
    fence_match = fence_pattern.match(text)
    if fence_match:
        payload_text = fence_match.group(1).strip()
        if re.search(r"```", payload_text):
            raise MalformedAuditOutputError("Audit output contains nested markdown fences.")
    else:
        payload_text = text

    if not payload_text.startswith("{") or not payload_text.endswith("}"):
        raise MalformedAuditOutputError(
            "Audit output must be exactly one JSON object, optionally wrapped in a single code fence."
        )

    try:
        data = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise MalformedAuditOutputError(f"Audit output is malformed JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise MalformedAuditOutputError("Audit output must be a JSON object.")

    try:
        result = AuditResult.model_validate(data)
    except ValidationError as exc:
        raise MalformedAuditOutputError(f"Audit output failed schema validation: {exc}") from exc

    if not result.summary.strip():
        raise MalformedAuditOutputError("Audit output summary must be non-empty.")

    for finding in result.findings:
        if finding.severity not in {
            AuditFindingSeverity.LOW,
            AuditFindingSeverity.MEDIUM,
            AuditFindingSeverity.HIGH,
            AuditFindingSeverity.CRITICAL,
        }:
            raise MalformedAuditOutputError(f"Unsupported finding severity: {finding.severity}")
        if not finding.category.strip():
            raise MalformedAuditOutputError("Audit finding category must be non-empty.")
        if not finding.message.strip():
            raise MalformedAuditOutputError("Audit finding message must be non-empty.")

    if result.risk not in {
        AuditRiskLevel.LOW,
        AuditRiskLevel.MEDIUM,
        AuditRiskLevel.HIGH,
        AuditRiskLevel.CRITICAL,
    }:
        raise MalformedAuditOutputError(f"Unsupported audit risk: {result.risk}")

    return result
