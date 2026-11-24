from __future__ import annotations

import asyncio
import json
import os

import pytest
from psycopg import AsyncConnection
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from minime.db.models import OperatorActionRecordModel
from minime.db.notifications import (
    SCHEDULER_WAKEUP_CHANNEL,
    notify_scheduler_wakeup,
)
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import OperatorActionStatus, OperatorActionType, OrchestrationStage
from minime.domain.models import OperatorActionRecord, OrchestrationRun, Project
from minime.services.scheduler_wakeup import SchedulerWakeupListener

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
def _pg_url(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)


async def _collect(connection: AsyncConnection, queue: asyncio.Queue) -> None:
    async for notification in connection.notifies():
        await queue.put(notification)


@pytest.mark.asyncio
async def test_scheduler_wakeup_is_delivered_only_after_commit_and_not_rollback():
    assert DATABASE_URL
    listener = await AsyncConnection.connect(_pg_url(DATABASE_URL), autocommit=True)
    await listener.execute(f"LISTEN {SCHEDULER_WAKEUP_CHANNEL}")
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_collect(listener, queue))
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        notify_scheduler_wakeup(
            session,
            project_id="project-e2e",
            run_id="run-e2e",
            action_id="action-rollback",
            reason="accepted_action",
        )
        session.rollback()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.2)

        notify_scheduler_wakeup(
            session,
            project_id="project-e2e",
            run_id="run-e2e",
            action_id="action-commit",
            reason="accepted_action",
        )
        session.commit()
        notification = await asyncio.wait_for(queue.get(), timeout=2)
        assert notification.channel == SCHEDULER_WAKEUP_CHANNEL
        assert json.loads(notification.payload) == {
            "project_id": "project-e2e",
            "run_id": "run-e2e",
            "action_id": "action-commit",
            "reason": "accepted_action",
        }
        assert session.execute(text("select 1")).scalar_one() == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await listener.close()
        session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_accepted_operator_action_wakes_after_commit_and_preserves_identity():
    """Exercise the real durable writer, not only the pg_notify helper."""
    assert DATABASE_URL
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    project_id = "wakeup-writer-project"
    run_id = "wakeup-writer-run"
    listener = await AsyncConnection.connect(_pg_url(DATABASE_URL), autocommit=True)
    await listener.execute(f"LISTEN {SCHEDULER_WAKEUP_CHANNEL}")
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_collect(listener, queue))
    session = sessions()
    try:
        session.execute(text("delete from operator_action_records where project_id = :project_id"), {"project_id": project_id})
        session.execute(text("delete from orchestration_runs where project_id = :project_id"), {"project_id": project_id})
        session.execute(text("delete from projects where id = :project_id"), {"project_id": project_id})
        session.commit()
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(Project(project_id=project_id, display_name="Wake-up writer", repository="test/wakeup"))
        uow.orchestration_runs.save(OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name="wakeup-writer-change",
            base_sha="test-base",
            current_stage=OrchestrationStage.DOC_CLOSING,
            resumable_stage=OrchestrationStage.DOC_CLOSING,
            is_active=True,
        ))
        uow.commit()

        action_id = "wakeup-accepted-action"
        action = OperatorActionRecord(
            action_request_id=action_id,
            project_id=project_id,
            change_name="wakeup-writer-change",
            run_id=run_id,
            action_type=OperatorActionType.RESOLVE_GATE,
            status=OperatorActionStatus.ACCEPTED,
            precondition_stage=OrchestrationStage.DOC_CLOSING.value,
        )
        uow.operator_actions.save(action)
        uow.commit()

        notification = await asyncio.wait_for(queue.get(), timeout=2)
        assert json.loads(notification.payload)["action_id"] == action_id
        persisted = uow.operator_actions.get_by_request_id(action_id)
        assert persisted is not None
        assert persisted.status == OperatorActionStatus.ACCEPTED
        assert persisted.run_id == run_id
        assert persisted.action_type == OperatorActionType.RESOLVE_GATE
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        session.rollback()
        session.execute(text("delete from operator_action_records where project_id = :project_id"), {"project_id": project_id})
        session.execute(text("delete from orchestration_runs where project_id = :project_id"), {"project_id": project_id})
        session.execute(text("delete from projects where id = :project_id"), {"project_id": project_id})
        session.commit()
        session.close()
        await listener.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_rollback_noneligible_and_duplicate_actions_do_not_dispatch():
    """Rollback and actions unable to make scheduler work eligible stay silent."""
    assert DATABASE_URL
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    project_id = "wakeup-negative-project"
    run_id = "wakeup-negative-run"
    listener = await AsyncConnection.connect(_pg_url(DATABASE_URL), autocommit=True)
    await listener.execute(f"LISTEN {SCHEDULER_WAKEUP_CHANNEL}")
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_collect(listener, queue))
    session = sessions()
    try:
        session.execute(text("delete from operator_action_records where project_id = :project_id"), {"project_id": project_id})
        session.execute(text("delete from orchestration_runs where project_id = :project_id"), {"project_id": project_id})
        session.execute(text("delete from projects where id = :project_id"), {"project_id": project_id})
        session.commit()
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(Project(project_id=project_id, display_name="Wake-up negative", repository="test/wakeup"))
        uow.orchestration_runs.save(OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name="wakeup-negative-change",
            base_sha="test-base",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            is_active=True,
        ))
        uow.commit()

        uow.operator_actions.save(OperatorActionRecord(
            action_request_id="wakeup-rolled-back",
            project_id=project_id,
            change_name="wakeup-negative-change",
            run_id=run_id,
            action_type=OperatorActionType.RESOLVE_GATE,
            status=OperatorActionStatus.ACCEPTED,
        ))
        session.rollback()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.2)
        assert session.get(OperatorActionRecordModel, "wakeup-rolled-back") is None

        uow.operator_actions.save(OperatorActionRecord(
            action_request_id="wakeup-cancel",
            project_id=project_id,
            change_name="wakeup-negative-change",
            run_id=run_id,
            action_type=OperatorActionType.CANCEL,
            status=OperatorActionStatus.ACCEPTED,
        ))
        session.commit()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.2)

        duplicate = OperatorActionRecord(
            action_request_id="wakeup-duplicate",
            project_id=project_id,
            change_name="wakeup-negative-change",
            run_id=run_id,
            action_type=OperatorActionType.RETRY,
            status=OperatorActionStatus.ACCEPTED,
        )
        uow.operator_actions.save(duplicate)
        session.commit()
        await asyncio.wait_for(queue.get(), timeout=2)
        uow.operator_actions.save(duplicate)
        session.commit()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        session.rollback()
        session.execute(text("delete from operator_action_records where project_id = :project_id"), {"project_id": project_id})
        session.execute(text("delete from orchestration_runs where project_id = :project_id"), {"project_id": project_id})
        session.execute(text("delete from projects where id = :project_id"), {"project_id": project_id})
        session.commit()
        session.close()
        await listener.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_listener_reconnect_and_poll_fallback_reconcile_without_pending_queue():
    reasons: list[str] = []

    async def reconcile(reason: str) -> None:
        reasons.append(reason)

    listener = SchedulerWakeupListener("postgresql://unused", reconcile)
    await listener.reconcile_startup()
    await listener._handle_notification(SCHEDULER_WAKEUP_CHANNEL, "{\"not\":\"a wake-up\"}")
    await listener._handle_notification(
        SCHEDULER_WAKEUP_CHANNEL,
        json.dumps({
            "project_id": "project-reconnect",
            "run_id": "run-reconnect",
            "action_id": "action-reconnect",
            "reason": "accepted_action",
        }, separators=(",", ":")),
    )
    assert reasons == ["startup", "wake-up"]
    assert await listener.wait_for_wakeup(0) is False
