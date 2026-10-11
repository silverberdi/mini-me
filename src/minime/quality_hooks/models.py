"""Pydantic models for OpenSpec Lifecycle Quality Hooks V1."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return timezone-aware UTC current time."""
    return datetime.now(timezone.utc)


class QualityHookStage(str, Enum):
    PRE_APPLY = "PRE-APPLY"
    POST_APPLY = "POST-APPLY"
    VERIFY = "VERIFY"
    ARCHIVE = "ARCHIVE"


class HookVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class ReviewSpecialty(str, Enum):
    SECURITY_AUTH = "security_auth"
    DATA_MIGRATIONS = "data_migrations"
    RELIABILITY_RECOVERY = "reliability_recovery"
    TESTS_COVERAGE = "tests_coverage"
    OPERATIONAL_DELIVERY = "operational_delivery"
    GENERAL_ARCHITECTURE = "general_architecture"

    @property
    def label(self) -> str:
        descriptions = {
            ReviewSpecialty.SECURITY_AUTH: "Security & Authorization",
            ReviewSpecialty.DATA_MIGRATIONS: "Data & Migrations",
            ReviewSpecialty.RELIABILITY_RECOVERY: "Reliability & Recovery",
            ReviewSpecialty.TESTS_COVERAGE: "Tests & Functional Coverage",
            ReviewSpecialty.OPERATIONAL_DELIVERY: "Operational Delivery",
            ReviewSpecialty.GENERAL_ARCHITECTURE: "General Architecture & Scope",
        }
        return descriptions.get(self, self.value)


class QualityHookFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(description="Unique identifier for finding, e.g. FIND-001")
    specialty: ReviewSpecialty = Field(description="Associated review specialty")
    severity: FindingSeverity = Field(description="Severity level")
    file_path: str | None = Field(default=None, description="Affected file path if applicable")
    line_number: int | str | None = Field(default=None, description="Line number or range if applicable")
    requirement_reference: str = Field(description="OpenSpec requirement, spec item, or canonical decision reference")
    observed_evidence: str = Field(description="Concrete evidence observed")
    expected_behavior: str = Field(description="Expected compliant behavior")
    suggested_remediation: str = Field(description="Actionable suggestion to resolve issue")
    status: FindingStatus = Field(default=FindingStatus.UNRESOLVED, description="Status of finding")


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_checks_passed: bool = Field(default=True)
    tests_passed: bool = Field(default=True)
    linters_passed: bool = Field(default=True)
    schemas_passed: bool = Field(default=True)
    check_details: dict[str, Any] = Field(default_factory=dict)


class QualityHookReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_id: QualityHookStage = Field(description="Lifecycle stage for hook execution")
    contract_version: str = Field(default="1.0.0", description="Contract version")
    change_id: str = Field(description="OpenSpec change name/id")
    repository_identity: str = Field(description="Bound repository identity, e.g. silverberdi/mini-me")
    base_sha: str = Field(description="Base commit SHA")
    candidate_sha: str = Field(description="Candidate commit SHA")
    implementer_identity: str | None = Field(default=None, description="Implementer role/agent identity")
    implementer_model_identity: str | None = Field(default=None, description="Implementer model identity")
    reviewer_identity: str | None = Field(default=None, description="Reviewer role/agent identity")
    reviewer_model_identity: str | None = Field(default=None, description="Reviewer model identity")
    required_specialties: list[ReviewSpecialty] = Field(default_factory=list, description="Required review specialties for candidate")
    evaluated_specialties: list[ReviewSpecialty] = Field(default_factory=list, description="Evaluated review specialties")
    findings: list[QualityHookFinding] = Field(default_factory=list, description="Recorded findings")
    verification_result: VerificationResult | None = Field(default=None, description="Verification result breakdown")
    final_verdict: HookVerdict = Field(description="Explicit final verdict: PASS, FAIL, or BLOCKED")
    verdict_reason: str = Field(description="Detailed explanation of the verdict decision")
    evaluated_at: datetime = Field(default_factory=utc_now, description="Timestamp of evaluation")
