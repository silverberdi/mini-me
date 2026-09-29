"""Regression test suite verifying Stage D saga resume command row locking preservation."""

from __future__ import annotations

from unittest.mock import MagicMock

from minime.domain.enums import SagaStatus, SagaType
from minime.domain.models import DurableSaga
from minime.services.saga_engine import SagaEngine


def test_saga_resume_retains_get_for_update_command_locking(in_memory_uow):
    uow = in_memory_uow

    # Seed a saga
    saga = DurableSaga(
        id="saga-test-locking-1",
        saga_type=SagaType.INTAKE,
        project_id="test-proj",
        work_item_key="test-change",
        change_name="test-change",
        status=SagaStatus.IN_PROGRESS,
        current_phase="INTAKE_CREATED",
    )
    uow.durable_sagas.save(saga)
    uow.commit()

    # Wrap uow.durable_sagas.get_for_update with spy mock
    original_get_for_update = uow.durable_sagas.get_for_update
    get_for_update_spy = MagicMock(side_effect=original_get_for_update)
    uow.durable_sagas.get_for_update = get_for_update_spy

    engine = SagaEngine(uow)
    resumed = engine.resume_saga("saga-test-locking-1")

    # Assert get_for_update was called by resume_saga
    assert get_for_update_spy.called
    assert get_for_update_spy.call_args[0][0] == "saga-test-locking-1"
    assert resumed.id == "saga-test-locking-1"
