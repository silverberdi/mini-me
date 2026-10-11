"""Model and Agent Independence Quality Analyzer."""

from __future__ import annotations

from minime.quality_hooks.models import (
    FindingSeverity,
    FindingStatus,
    QualityHookFinding,
    ReviewSpecialty,
)


def normalize_model_family(model_name: str | None) -> str | None:
    """Normalize model string to family identifier for comparison."""
    if not model_name:
        return None
    name = model_name.strip().lower()
    if "/" in name:
        name = name.split("/")[-1]

    # Strip common version/date tags or qualifiers
    if "codex" in name or "gpt-4" in name or "gpt-5" in name:
        return "openai-codex"
    if "antigravity" in name or "gemini" in name:
        return "google-antigravity"
    if "claude" in name:
        return "anthropic-claude"
    if "deepseek" in name:
        return "deepseek"
    if "qwen" in name:
        return "qwen"
    return name


def analyze_model_independence(
    implementer_identity: str | None,
    implementer_model_identity: str | None,
    reviewer_identity: str | None,
    reviewer_model_identity: str | None,
) -> list[QualityHookFinding]:
    """Verify that the reviewer is distinct and complementary to the implementer."""
    findings: list[QualityHookFinding] = []

    # 1. Check primary agent identity pairing
    if (
        implementer_identity
        and reviewer_identity
        and implementer_identity.strip().lower() == reviewer_identity.strip().lower()
    ):
        findings.append(
            QualityHookFinding(
                finding_id="INDEP-SAME-PRIMARY-AGENT",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.CRITICAL,
                file_path=None,
                requirement_reference="CANONICAL-DECISIONS#agent-roles",
                observed_evidence=f"Implementer '{implementer_identity}' matches reviewer '{reviewer_identity}'.",
                expected_behavior="Primary implementer and reviewer must be complementary distinct roles.",
                suggested_remediation="Assign an independent complementary reviewer for this candidate.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    # 2. Check model identity pairing (especially under fallback or multi-model executions)
    norm_impl = normalize_model_family(implementer_model_identity)
    norm_rev = normalize_model_family(reviewer_model_identity)

    if norm_impl and norm_rev and norm_impl == norm_rev:
        findings.append(
            QualityHookFinding(
                finding_id="INDEP-SAME-MODEL-IDENTITY",
                specialty=ReviewSpecialty.GENERAL_ARCHITECTURE,
                severity=FindingSeverity.CRITICAL,
                file_path=None,
                requirement_reference="CANONICAL-DECISIONS#model-independence",
                observed_evidence=f"Implementer model '{implementer_model_identity}' and reviewer model '{reviewer_model_identity}' share family '{norm_impl}'.",
                expected_behavior="The same model identity must not perform substantive implementation and authoritative review.",
                suggested_remediation="Reassign candidate review to a distinct model identity.",
                status=FindingStatus.UNRESOLVED,
            )
        )

    return findings
