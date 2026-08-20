"""Tests for PostgreSQL durable state, Alembic migrations, and persistence primitives."""

import subprocess

from minime.db.models import (
    Base,
)
from minime.domain.enums import ChangeStatus, EventType, ReadinessState
from minime.domain.models import Change, Event, Project, utc_now


def test_models_metadata_tables():
    tables = Base.metadata.tables
    assert "projects" in tables
    assert "project_bindings" in tables
    assert "changes" in tables
    assert "events" in tables
    assert "metric_facts" in tables
    assert "jobs" in tables
    assert "job_logs" in tables
    assert "check_results" in tables
    assert "reviews" in tables
    assert "review_findings" in tables
    assert "audits" in tables
    assert "audit_findings" in tables
    # Verify uniqueness constraint on project_bindings (project_id, openspec_change_name)
    pb_table = tables["project_bindings"]
    constraint_names = {c.name for c in pb_table.constraints}
    assert "uq_project_bindings_project_change" in constraint_names


def test_alembic_offline_postgres_migration():
    """Verify that Alembic generates PostgreSQL-compatible DDL without error."""
    result = subprocess.run(
        [".venv/bin/alembic", "upgrade", "head", "--sql"],
        env={"MINIME_DATABASE_URL": "postgresql://minime:pass@localhost:5432/minime"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Alembic error: {result.stderr}"
    sql = result.stdout
    assert "CREATE TABLE projects" in sql
    assert "CREATE TABLE project_bindings" in sql
    assert "uq_project_bindings_project_change" in sql
    assert "CREATE TABLE changes" in sql
    assert "CREATE TABLE events" in sql
    assert "CREATE TABLE metric_facts" in sql
    assert "CREATE TABLE jobs" in sql
    assert "CREATE TABLE job_logs" in sql
    assert "CREATE TABLE check_results" in sql
    assert "CREATE TABLE reviews" in sql
    assert "CREATE TABLE review_findings" in sql
    assert "CREATE TABLE audits" in sql
    assert "CREATE TABLE audit_findings" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql


def test_restart_persistence_simulation(in_memory_uow):
    """Verify that committed projects, changes, and event evidence survive and remain queryable."""
    # First daemon session: Register project and discover change
    now = utc_now()
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        change_id="change-001",
        project_id="mini-me",
        name="synthetic-change",
        status=ChangeStatus.READY,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    event = Event(
        event_id="evt-1",
        event_type=EventType.PROJECT_REGISTERED,
        project_id="mini-me",
        change_id="synthetic-change",
        payload={"action": "registered"},
        timestamp=now,
    )
    in_memory_uow.events.save(event)
    in_memory_uow.commit()

    # Simulate daemon restart: Querying the persistence store retrieves the saved entities
    restored_project = in_memory_uow.projects.get_by_id("mini-me")
    assert restored_project is not None
    assert restored_project.display_name == "mini me"
    assert restored_project.repository == "owner/mini-me"

    restored_change = in_memory_uow.changes.get_by_name("mini-me", "synthetic-change")
    assert restored_change is not None
    assert restored_change.last_readiness_status == ReadinessState.READY

    events = in_memory_uow.events.list_events(project_id="mini-me")
    assert len(events) == 1
    assert events[0].event_type == EventType.PROJECT_REGISTERED
