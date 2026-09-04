"""SQLAlchemy models for PostgreSQL operational persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    repository: Mapped[str] = mapped_column(String(255), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(128), default="main", nullable=False)
    openspec_path: Mapped[str] = mapped_column(String(255), default="openspec", nullable=False)
    implementer: Mapped[str] = mapped_column(String(64), default="codex", nullable=False)
    reviewer: Mapped[str] = mapped_column(String(64), default="antigravity", nullable=False)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    external_providers_allowed: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["codex", "antigravity", "deepseek"], nullable=False
    )
    openrouter_drain_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deployment_preview: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    deployment_production: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    changes: Mapped[list[ChangeModel]] = relationship(
        "ChangeModel", back_populates="project", cascade="all, delete-orphan"
    )
    bindings: Mapped[list[ProjectBindingModel]] = relationship(
        "ProjectBindingModel", back_populates="project", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[JobModel]] = relationship(
        "JobModel", back_populates="project", cascade="all, delete-orphan"
    )


class ProjectBindingModel(Base):
    __tablename__ = "project_bindings"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "openspec_change_name", name="uq_project_bindings_project_change"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repository: Mapped[str] = mapped_column(String(255), nullable=False)
    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_project_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    github_pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_pr_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    openspec_change_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mismatch_reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped[ProjectModel] = relationship("ProjectModel", back_populates="bindings")


class ChangeModel(Base):
    __tablename__ = "changes"

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_changes_project_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERED", nullable=False)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_name: Mapped[str] = mapped_column(String(64), default="spec-driven", nullable=False)
    proposal_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    tasks_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    design_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    specs_paths: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    last_readiness_status: Mapped[str] = mapped_column(
        String(32), default="NOT_READY", nullable=False
    )
    last_readiness_reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped[ProjectModel] = relationship("ProjectModel", back_populates="changes")


class EventModel(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    change_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class MetricFactModel(Base):
    __tablename__ = "metric_facts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    change_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fact_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class JobModel(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    implementer_role: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    waiting_provider: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    capacity_block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovery_blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    reassignment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_executor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_progress: Mapped[str | None] = mapped_column(String(64), nullable=True)
    continuation_decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_mixed_authorship: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped[ProjectModel] = relationship("ProjectModel", back_populates="jobs")
    logs: Mapped[list[JobLogModel]] = relationship(
        "JobLogModel", back_populates="job", cascade="all, delete-orphan"
    )
    check_results: Mapped[list[CheckResultModel]] = relationship(
        "CheckResultModel", back_populates="job", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[ReviewModel]] = relationship(
        "ReviewModel", back_populates="job", cascade="all, delete-orphan"
    )
    audits: Mapped[list[AuditModel]] = relationship(
        "AuditModel", back_populates="job", cascade="all, delete-orphan"
    )
    attempts: Mapped[list[JobAttemptModel]] = relationship(
        "JobAttemptModel", back_populates="job", cascade="all, delete-orphan"
    )
    blocker_claims: Mapped[list[BlockerClaimModel]] = relationship(
        "BlockerClaimModel", back_populates="job", cascade="all, delete-orphan"
    )
    handoffs: Mapped[list[JobHandoffModel]] = relationship(
        "JobHandoffModel", back_populates="job", cascade="all, delete-orphan"
    )
    manifests: Mapped[list[CandidateManifestModel]] = relationship(
        "CandidateManifestModel", back_populates="job", cascade="all, delete-orphan"
    )
    authorships: Mapped[list[CandidateAuthorshipModel]] = relationship(
        "CandidateAuthorshipModel", back_populates="job", cascade="all, delete-orphan"
    )
    diagnostics: Mapped[list[EvidenceDiagnosticModel]] = relationship(
        "EvidenceDiagnosticModel", back_populates="job", cascade="all, delete-orphan"
    )


class JobAttemptModel(Base):
    __tablename__ = "job_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    executor_role: Mapped[str] = mapped_column(String(64), nullable=False)
    model_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    start_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    end_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_outcome: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    progress_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    continuation_decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    corrective_retries_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    same_outcome_streak: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    same_blocker_fingerprint_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corrective_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_class: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    productivity_class: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    premium_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_same_sha_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    job: Mapped[JobModel] = relationship("JobModel", back_populates="attempts")
    blocker_claims: Mapped[list[BlockerClaimModel]] = relationship(
        "BlockerClaimModel", back_populates="attempt", cascade="all, delete-orphan"
    )


class BlockerClaimModel(Base):
    __tablename__ = "blocker_claims"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("job_attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    blocker_type: Mapped[str] = mapped_column(String(64), nullable=False)
    blocker_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    affected_requirement: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failing_invariant: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    attempted_remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_agent_solvable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    validation_verdict: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    validation_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    available_integration_points: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    job: Mapped[JobModel] = relationship("JobModel", back_populates="blocker_claims")
    attempt: Mapped[JobAttemptModel] = relationship(
        "JobAttemptModel", back_populates="blocker_claims"
    )


class JobHandoffModel(Base):
    __tablename__ = "job_handoffs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_attempt_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("job_attempts.id", ondelete="CASCADE"), nullable=False
    )
    to_attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("job_attempts.id", ondelete="SET NULL"), nullable=True
    )
    from_executor: Mapped[str] = mapped_column(String(64), nullable=False)
    to_executor: Mapped[str] = mapped_column(String(64), nullable=False)
    worktree_path: Mapped[str] = mapped_column(String(512), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_tasks: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    remaining_tasks: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    manifest_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    checks_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    blockers_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    architectural_notes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    do_not_redo_guidance: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    authorship_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    is_consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    job: Mapped[JobModel] = relationship("JobModel", back_populates="handoffs")


class CandidateManifestModel(Base):
    __tablename__ = "candidate_manifests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("job_attempts.id", ondelete="SET NULL"), nullable=True
    )
    candidate_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    tracked_files: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    staged_files: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    untracked_files: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    deleted_files: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    total_files_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    job: Mapped[JobModel] = relationship("JobModel", back_populates="manifests")


class CandidateAuthorshipModel(Base):
    __tablename__ = "candidate_authorships"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False)
    model_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    files_touched: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_primary_author: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    job: Mapped[JobModel] = relationship("JobModel", back_populates="authorships")


class EvidenceDiagnosticModel(Base):
    __tablename__ = "evidence_diagnostics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("job_attempts.id", ondelete="SET NULL"), nullable=True
    )
    stage_type: Mapped[str] = mapped_column(String(64), nullable=False)
    check_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    diagnostic_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    environment_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    candidate_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_reference: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    job: Mapped[JobModel] = relationship("JobModel", back_populates="diagnostics")


class ProviderHealthModel(Base):
    __tablename__ = "provider_health"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="available", nullable=False, index=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_result_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class CapacityWindowModel(Base):
    __tablename__ = "capacity_windows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quota_exhausted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    capacity_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_signal: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class GitOperationModel(Base):
    __tablename__ = "git_operations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    worktree_path: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING", nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobLogModel(Base):
    __tablename__ = "job_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stream: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    job: Mapped[JobModel] = relationship("JobModel", back_populates="logs")


class CheckResultModel(Base):
    __tablename__ = "check_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    check_name: Mapped[str] = mapped_column(String(128), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    output_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_sha: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    candidate_generation: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    job: Mapped[JobModel] = relationship("JobModel", back_populates="check_results")


class ReviewModel(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reviewer_role: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    orchestration_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    candidate_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_mixed_authorship: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.false()
    )
    authorship_evidence: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    job: Mapped[JobModel] = relationship("JobModel", back_populates="reviews")
    findings: Mapped[list[ReviewFindingModel]] = relationship(
        "ReviewFindingModel", back_populates="review", cascade="all, delete-orphan"
    )


class ReviewFindingModel(Base):
    __tablename__ = "review_findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    violated_requirement: Mapped[str] = mapped_column(Text, nullable=False)
    expected_correction: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    review: Mapped[ReviewModel] = relationship("ReviewModel", back_populates="findings")


class AuditModel(Base):
    __tablename__ = "audits"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), default="deepseek", nullable=False)
    model: Mapped[str] = mapped_column(String(128), default="deepseek-chat", nullable=False)
    orchestration_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    candidate_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_full_candidate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    review_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("reviews.id", ondelete="SET NULL"), nullable=True, index=True
    )
    review_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    job: Mapped[JobModel] = relationship("JobModel", back_populates="audits")
    findings: Mapped[list[AuditFindingModel]] = relationship(
        "AuditFindingModel", back_populates="audit", cascade="all, delete-orphan"
    )


class AuditFindingModel(Base):
    __tablename__ = "audit_findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    audit: Mapped[AuditModel] = relationship("AuditModel", back_populates="findings")


class OpenRouterBudgetPolicyModel(Base):
    __tablename__ = "openrouter_budget_policies"

    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    daily_cap_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    monthly_cap_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class OpenRouterPricingSnapshotModel(Base):
    __tablename__ = "openrouter_pricing_snapshots"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    canonical_model_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    routed_model_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_price_per_token: Mapped[Decimal] = mapped_column(Numeric(14, 10), nullable=False)
    output_price_per_token: Mapped[Decimal] = mapped_column(Numeric(14, 10), nullable=False)
    additional_cost_per_request: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=Decimal("0.0"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class BudgetReservationModel(Base):
    __tablename__ = "budget_reservations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    change_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_model_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    reserved_amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    pricing_snapshot_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("openrouter_pricing_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class BudgetLedgerModel(Base):
    __tablename__ = "budget_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reservation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("budget_reservations.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    change_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="openrouter", nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_model_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class OrchestrationRunModel(Base):
    __tablename__ = "orchestration_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    current_stage: Mapped[str] = mapped_column(
        String(32), default="ADMITTED", nullable=False, index=True
    )
    resumable_stage: Mapped[str] = mapped_column(String(32), default="ADMITTED", nullable=False)
    stop_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    human_gate: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    active_job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    current_generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_candidate_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    project: Mapped[ProjectModel] = relationship("ProjectModel")
    active_job: Mapped[JobModel | None] = relationship("JobModel")
    stage_events: Mapped[list[OrchestrationStageEventModel]] = relationship(
        "OrchestrationStageEventModel", back_populates="run", cascade="all, delete-orphan"
    )
    candidates: Mapped[list[OrchestrationCandidateModel]] = relationship(
        "OrchestrationCandidateModel", back_populates="run", cascade="all, delete-orphan"
    )
    external_actions: Mapped[list[OrchestrationExternalActionModel]] = relationship(
        "OrchestrationExternalActionModel", back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_active_orchestration_run",
            "project_id",
            "change_name",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
    )


class OrchestrationStageEventModel(Base):
    __tablename__ = "orchestration_stage_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), default="STAGE_TRANSITION", nullable=False)
    transition_key: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True, index=True
    )
    evidence_references: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    actor: Mapped[str] = mapped_column(String(64), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    run: Mapped[OrchestrationRunModel] = relationship(
        "OrchestrationRunModel", back_populates="stage_events"
    )


class OrchestrationCandidateModel(Base):
    __tablename__ = "orchestration_candidates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manifest_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("candidate_manifests.id", ondelete="SET NULL"), nullable=True
    )
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorship_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    superseded_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    run: Mapped[OrchestrationRunModel] = relationship(
        "OrchestrationRunModel", back_populates="candidates"
    )
    manifest: Mapped[CandidateManifestModel | None] = relationship("CandidateManifestModel")

    __table_args__ = (
        UniqueConstraint("run_id", "generation", name="uq_orchestration_candidate_generation"),
    )


class CandidateRemediationModel(Base):
    __tablename__ = "candidate_remediations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    source_candidate_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    source_base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authorized_paths: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tree_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_candidate_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_generation",
            "source_candidate_sha",
            "contract_hash",
            name="uq_candidate_remediation_identity",
        ),
    )


class OrchestrationExternalActionModel(Base):
    __tablename__ = "orchestration_external_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="RESERVED", nullable=False, index=True)
    remote_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    run: Mapped[OrchestrationRunModel] = relationship(
        "OrchestrationRunModel", back_populates="external_actions"
    )


class PreviewSessionModel(Base):
    __tablename__ = "preview_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("orchestration_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    candidate_generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    image_digest: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="REQUESTED", nullable=False, index=True)
    container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    container_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    allocated_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[ProjectModel] = relationship("ProjectModel")
    run: Mapped[OrchestrationRunModel | None] = relationship("OrchestrationRunModel")


class ValidationRunModel(Base):
    __tablename__ = "validation_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    preview_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("preview_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("orchestration_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    candidate_generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    image_digest: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(32), default="PASS", nullable=False, index=True)
    scenario_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    project: Mapped[ProjectModel] = relationship("ProjectModel")
    preview: Mapped[PreviewSessionModel | None] = relationship("PreviewSessionModel")


class OperatorActionRecordModel(Base):
    __tablename__ = "operator_action_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_request_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("orchestration_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_identity: Mapped[str] = mapped_column(String(128), default="operator", nullable=False)
    source_interface: Mapped[str] = mapped_column(String(64), default="tui", nullable=False)
    precondition_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    precondition_gate: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACCEPTED", nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    resulting_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resulting_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resulting_gate: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    project: Mapped[ProjectModel] = relationship("ProjectModel")
    run: Mapped[OrchestrationRunModel | None] = relationship("OrchestrationRunModel")


class WorkQueueSnapshotModel(Base):
    __tablename__ = "work_queue_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "change_name", name="uq_work_queue_snapshots_project_change"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_issue_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    github_project_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    priority: Mapped[str] = mapped_column(String(32), default="NORMAL", nullable=False)
    roadmap_stage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    readiness_state: Mapped[str] = mapped_column(String(32), default="NOT_READY", nullable=False)
    unmet_readiness_reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    admission_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    last_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    project: Mapped[ProjectModel] = relationship("ProjectModel")


class SchedulerDecisionRecordModel(Base):
    __tablename__ = "scheduler_decision_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reason_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    selected_implementer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    concurrency_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    capacity_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("orchestration_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    project: Mapped[ProjectModel] = relationship("ProjectModel")
    run: Mapped[OrchestrationRunModel | None] = relationship("OrchestrationRunModel")


class ProviderEfficiencyMetricsModel(Base):
    __tablename__ = "provider_efficiency_metrics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    attempts_by_provider: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    duration_by_provider_ms: Mapped[dict[str, int]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    productive_attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    no_progress_attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    same_sha_retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    same_sha_retry_suppressed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    corrective_retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reassignments_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reassignment_reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    provider_exhaustion_events: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    drain_transitions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    premium_provider_assignments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    premium_provider_reason_codes: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    candidate_generations_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    time_to_candidate_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_to_checks_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_to_review_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_to_pr_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_cycle_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    human_gates_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    operator_actions_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    self_hosting_native_phases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    self_hosting_total_phases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    self_hosting_percentage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    project: Mapped[ProjectModel] = relationship("ProjectModel")
    run: Mapped[OrchestrationRunModel] = relationship("OrchestrationRunModel")


class AuthorizedOperatorModel(Base):
    __tablename__ = "authorized_operators"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AuthSessionModel(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_token_hash: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    operator_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuthAuditEventModel(Base):
    __tablename__ = "auth_audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    operator_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
