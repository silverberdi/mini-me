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
    """Verifiable deterministic checks result bound strictly to candidate SHA."""
    model_config = ConfigDict(extra="forbid")

    candidate_sha: str = Field(description="Exact candidate SHA that was verified")
    deterministic_checks_passed: bool = Field(description="Strict boolean whether all checks passed")
    tests_passed: bool = Field(description="Strict boolean whether test suite passed")
    linters_passed: bool = Field(description="Strict boolean whether linters passed")
    schemas_passed: bool = Field(description="Strict boolean whether schema validations passed")
    evidence_source: str = Field(description="Verifiable source of execution logs or diagnostic report")
    check_details: dict[str, Any] = Field(default_factory=dict, description="Detailed check breakdown")


class ReviewEvidence(BaseModel):
    """Verifiable independent review evidence bound strictly to candidate SHA."""
    model_config = ConfigDict(extra="forbid")

    candidate_sha: str = Field(description="Exact candidate SHA that was reviewed")
    reviewer_identity: str = Field(description="Authoritative reviewer role/agent identity")
    reviewer_model_identity: str = Field(description="Authoritative reviewer model identity")
    verdict: str = Field(description="Review verdict: approve, changes_requested, needs_human")
    summary: str = Field(description="Substantive review summary")
    evaluated_specialties: list[ReviewSpecialty] = Field(description="Specialties verified during review")
    findings: list[QualityHookFinding] = Field(default_factory=list, description="Findings reported by reviewer")
    evidence_source: str = Field(description="Authoritative artifact path or execution reference")
    details: dict[str, Any] = Field(default_factory=dict)


class HumanApprovalEvidence(BaseModel):
    """Verifiable human approval record bound strictly to candidate tuple."""
    model_config = ConfigDict(extra="forbid")

    candidate_head_sha: str = Field(description="Exact candidate head SHA approved")
    base_sha: str = Field(description="Base SHA approved against")
    decision: str = Field(description="Decision: approve, request_changes, reject")
    approver_identity: str = Field(description="Authorized human operator identity")
    evidence_source: str = Field(description="Authoritative source (e.g. human validation report or DB)")
    notes: str | None = Field(default=None)


class MergeEvidence(BaseModel):
    """Verifiable delivery/merge evidence bound strictly to candidate SHA."""
    model_config = ConfigDict(extra="forbid")

    candidate_sha: str = Field(description="Exact candidate SHA merged")
    target_branch: str = Field(description="Target base branch merged into")
    is_merged: bool = Field(description="Whether pull request or commit was merged")
    merged_by: str = Field(description="Identity that performed merge (must be human, not bot)")
    merged_by_type: str = Field(default="User", description="Identity type (User vs Bot)")
    merge_commit_sha: str | None = Field(default=None, description="Resulting merge commit SHA")
    evidence_source: str = Field(description="Authoritative source (GitHub API details or git ancestry)")


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
