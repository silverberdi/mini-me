"""SQLAlchemy models for PostgreSQL operational persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
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


class ProjectBindingModel(Base):
    __tablename__ = "project_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "openspec_change_name", name="uq_project_bindings_project_change"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repository: Mapped[str] = mapped_column(String(255), nullable=False)
    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_project_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
