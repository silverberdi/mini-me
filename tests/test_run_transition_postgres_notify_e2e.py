from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from uuid import uuid4

import pytest
from psycopg import AsyncConnection
from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from minime.db.models import (
    AuthSessionModel,
    AuthorizedOperatorModel,
    OrchestrationRunModel,
    ProjectModel,
)
from minime.db.notifications import RUN_TRANSITION_CHANNEL
from minime.db.repository import (
    PostgresOrchestrationRunRepository,
    PostgresPersistenceUnitOfWork,
)
from minime.domain.enums import OrchestrationStage
from minime.domain.models import AuthorizedOperator, OrchestrationRun, Project
from minime.api import app as api_module
from minime.services.event_broker import EventBroker
from minime.services.postgres_run_event_listener import PostgresRunEventListener
from minime.services.auth_service import SessionManager, hash_token
from starlette.requests import Request

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)


async def _collect_notifications(
    connection: AsyncConnection, notifications: asyncio.Queue
) -> None:
    async for notification in connection.notifies():
        await notifications.put(notification)


async def _expect_no_notification(notifications: asyncio.Queue) -> None:
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(notifications.get(), timeout=0.15)


@pytest.mark.asyncio
async def test_run_transition_notification_is_transactional_and_only_for_stage_changes():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, run_id = str(uuid4()), str(uuid4())
    listener_url = make_url(DATABASE_URL).set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    listener = await AsyncConnection.connect(listener_url, autocommit=True)
    await listener.execute(f"LISTEN {RUN_TRANSITION_CHANNEL}")
    notifications: asyncio.Queue = asyncio.Queue()
    notification_task = asyncio.create_task(_collect_notifications(listener, notifications))
    session = None
    try:
        with engine.connect() as connection:
            database_name = connection.execute(text("select current_database()")).scalar_one()
            assert "test" in database_name.lower(), "Refusing to write outside a test database"

        session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        runs = PostgresOrchestrationRunRepository(session)
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(
            Project(project_id=project_id, display_name="SSE E2E", repository="test/sse")
        )
        uow.orchestration_runs.save(
            OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name="issue-366-sse-e2e",
                base_sha="test-base",
                current_stage=OrchestrationStage.ADMITTED,
                resumable_stage=OrchestrationStage.ADMITTED,
                is_active=True,
            )
        )
        uow.commit()
        await _expect_no_notification(notifications)

        run = runs.get_by_id(run_id)
        assert run is not None
        run.current_stage = OrchestrationStage.IMPLEMENTING
        runs.save(run)
        session.rollback()
        await _expect_no_notification(notifications)

        run = runs.get_by_id(run_id)
        assert run is not None
        run.stop_reason = "metadata-only update"
        runs.save(run)
        session.commit()
        await _expect_no_notification(notifications)

        run = runs.get_by_id(run_id)
        assert run is not None
        run.current_stage = OrchestrationStage.IMPLEMENTING
        runs.save(run)
        session.commit()
        notification = await asyncio.wait_for(notifications.get(), timeout=2)
        assert notification.channel == RUN_TRANSITION_CHANNEL
        assert json.loads(notification.payload) == {
            "project_id": project_id,
            "run_id": run_id,
            "stage": OrchestrationStage.IMPLEMENTING.value,
        }
    finally:
        if session is not None:
            session.rollback()
            session.execute(
                delete(OrchestrationRunModel).where(OrchestrationRunModel.id == run_id)
            )
            session.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
            session.commit()
            session.close()
        notification_task.cancel()
        with suppress(asyncio.CancelledError):
            await notification_task
        await listener.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_postgres_listener_relays_committed_stage_and_projection_is_authoritative(
    monkeypatch,
):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, run_id = str(uuid4()), str(uuid4())
    operator_email = f"issue366-{uuid4()}@example.test"
    database_url = make_url(DATABASE_URL).set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    session = None
    listener = None
    stream = None
    raw_token = None
    try:
        with engine.connect() as connection:
            database_name = connection.execute(text("select current_database()")).scalar_one()
            assert "test" in database_name.lower(), "Refusing to write outside a test database"

        session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        session = session_factory()
        uow = PostgresPersistenceUnitOfWork(session)
        uow.authorized_operators.save(
            AuthorizedOperator(email=operator_email, display_name="Issue 366 E2E")
        )
        uow.projects.save(
            Project(project_id=project_id, display_name="SSE relay E2E", repository="test/sse-relay")
        )
        uow.orchestration_runs.save(
            OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name="issue-366-listener-e2e",
                base_sha="test-base",
                current_stage=OrchestrationStage.ADMITTED,
                resumable_stage=OrchestrationStage.ADMITTED,
                is_active=True,
            )
        )
        uow.commit()

        raw_token, _ = SessionManager(uow).create_session(operator_email)
        request = Request(
            {
                "type": "http",
                "headers": [(b"cookie", f"minime_session={raw_token}".encode("ascii"))],
            }
        )
        authenticated_operator = api_module.get_current_operator(request, uow)

        broker = EventBroker()
        monkeypatch.setattr(api_module, "event_broker", broker)
        response = await api_module.stream_events(authenticated_operator)
        stream = response.body_iterator
        assert await anext(stream) == ": connected\n\n"
        listener = PostgresRunEventListener(database_url, broker.publish)
        await listener.start()
        # The listener's initial resync is emitted only after LISTEN is established.
        initial_resync = await asyncio.wait_for(anext(stream), timeout=5)
        assert initial_resync.startswith("event: run.resync\n")

        # A second database session simulates the independent scheduler process.
        writer = session_factory()
        try:
            run = PostgresOrchestrationRunRepository(writer).get_by_id(run_id)
            assert run is not None
            run.current_stage = OrchestrationStage.IMPLEMENTING
            PostgresOrchestrationRunRepository(writer).save(run)
            writer.commit()
        finally:
            writer.close()

        transition_event = await asyncio.wait_for(anext(stream), timeout=5)
        assert transition_event.startswith("event: run.transition\n")
        payload = json.loads(transition_event.split("data: ", 1)[1])
        assert payload == {
            "project_id": project_id,
            "run_id": run_id,
            "stage": OrchestrationStage.IMPLEMENTING.value,
        }

        projection_session = session_factory()
        try:
            projection = api_module.list_orchestration_runs(
                PostgresPersistenceUnitOfWork(projection_session), project_id=project_id
            )
            assert projection[0]["run_id"] == run_id
            assert projection[0]["current_stage"] == OrchestrationStage.IMPLEMENTING.value
        finally:
            projection_session.close()
    finally:
        if stream is not None:
            await stream.aclose()
        if listener is not None:
            await listener.stop()
        if session is not None:
            session.rollback()
            session.execute(
                delete(OrchestrationRunModel).where(OrchestrationRunModel.id == run_id)
            )
            if raw_token is not None:
                session.execute(
                    delete(AuthSessionModel).where(
                        AuthSessionModel.session_token_hash == hash_token(raw_token)
                    )
                )
            session.execute(
                delete(AuthorizedOperatorModel).where(
                    AuthorizedOperatorModel.email == operator_email
                )
            )
            session.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
            session.commit()
            session.close()
        engine.dispose()
