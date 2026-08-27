"""Regression coverage for logical OpenSpec change identity."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from minime.db.models import Base, ChangeModel, ProjectModel
from minime.db.repository import PostgresChangeRepository
from minime.domain.enums import ChangeStatus, ProjectStatus, ReadinessState
from minime.domain.models import Change


def make_change(**kwargs):
    now = datetime.now(UTC)
    values = {
        "project_id": "mini-me",
        "name": "010-logical-identity",
        "discovered_at": now,
        "updated_at": now,
    }
    values.update(kwargs)
    return Change(**values)


def test_in_memory_rediscovery_is_logical_upsert_and_preserves_ready(in_memory_uow):
    first = make_change(
        change_id="stable-id",
        status=ChangeStatus.READY,
        last_readiness_status=ReadinessState.READY,
        proposal_path="old/proposal.md",
    )
    in_memory_uow.changes.save(first)
    rediscovered = make_change(
        change_id="new-discovery-id",
        status=ChangeStatus.DISCOVERED,
        last_readiness_status=ReadinessState.NOT_READY,
        proposal_path="new/proposal.md",
        discovered_at=first.discovered_at + timedelta(days=1),
    )
    in_memory_uow.changes.save(rediscovered)

    saved = in_memory_uow.changes.get_by_name("mini-me", "010-logical-identity")
    assert saved is not None
    assert saved.change_id == "stable-id"
    assert saved.discovered_at == first.discovered_at
    assert saved.proposal_path == "new/proposal.md"
    assert saved.status == ChangeStatus.READY
    assert saved.last_readiness_status == ReadinessState.READY


def test_in_memory_attached_entity_can_regress_readiness(in_memory_uow):
    first = make_change(
        change_id="attached-id",
        status=ChangeStatus.READY,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(first)
    loaded = in_memory_uow.changes.get_by_name(first.project_id, first.name)
    loaded.status = ChangeStatus.DISCOVERED
    loaded.last_readiness_status = ReadinessState.NOT_READY
    loaded.last_readiness_reasons = ["synthetic failure"]
    in_memory_uow.changes.save(loaded)

    saved = in_memory_uow.changes.get_by_id(first.change_id)
    assert saved.status == ChangeStatus.DISCOVERED
    assert saved.last_readiness_status == ReadinessState.NOT_READY
    assert saved.last_readiness_reasons == ["synthetic failure"]


def test_in_memory_get_by_name_fails_closed_on_corruption(in_memory_uow):
    first = make_change(change_id="one")
    second = make_change(change_id="two")
    in_memory_uow.changes._store[first.change_id] = first
    in_memory_uow.changes._store[second.change_id] = second

    with pytest.raises(ValueError, match="Ambiguous logical Change identity"):
        in_memory_uow.changes.get_by_name("mini-me", "010-logical-identity")


def test_postgres_repository_logical_upsert_and_ambiguity():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            ProjectModel(
                id="mini-me",
                display_name="Mini Me",
                repository="silverberdi/mini-me",
                checks=[],
                external_providers_allowed=[],
                deployment_preview={},
                deployment_production={},
                status=ProjectStatus.ACTIVE.value,
            )
        )
        session.commit()
        repo = PostgresChangeRepository(session)
        assert repo.get_by_name("mini-me", "missing") is None
        first = make_change(
            change_id="stable-id",
            status=ChangeStatus.READY,
            last_readiness_status=ReadinessState.READY,
            proposal_path="old/proposal.md",
        )
        repo.save(first)
        session.commit()
        repo.save(make_change(change_id="new-id", proposal_path="new/proposal.md"))
        session.commit()

        saved = repo.get_by_name("mini-me", "010-logical-identity")
        assert saved is not None
        assert saved.change_id == "stable-id"
        assert saved.discovered_at.replace(tzinfo=UTC) == first.discovered_at
        assert saved.proposal_path == "new/proposal.md"
        assert saved.status == ChangeStatus.READY
        loaded = repo.get_by_name("mini-me", "010-logical-identity")
        loaded.status = ChangeStatus.DISCOVERED
        loaded.last_readiness_status = ReadinessState.NOT_READY
        loaded.last_readiness_reasons = ["synthetic failure"]
        repo.save(loaded)
        session.commit()
        regressed = repo.get_by_name("mini-me", "010-logical-identity")
        assert regressed.status == ChangeStatus.DISCOVERED
        assert regressed.last_readiness_status == ReadinessState.NOT_READY
        assert regressed.last_readiness_reasons == ["synthetic failure"]
        assert session.scalar(
            select(func.count()).select_from(ChangeModel).where(ChangeModel.project_id == "mini-me")
        ) == 1

def test_change_model_declares_stable_unique_constraint():
    constraint = next(
        c for c in ChangeModel.__table__.constraints if c.name == "uq_changes_project_name"
    )
    assert [column.name for column in constraint.columns] == ["project_id", "name"]
