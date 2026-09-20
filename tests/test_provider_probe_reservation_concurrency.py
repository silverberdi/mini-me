"""PostgreSQL-backed regression proving cross-session atomicity of expensive-probe reservation.

Multiple independent ``SchedulerService`` / ``ProviderHealthService`` instances
each own a separate PostgreSQL session, so the instance-local ``asyncio.Lock``
cannot serialize them. This suite proves that the ``SELECT ... FOR UPDATE``
reservation makes the eligibility check + cooldown/backoff + max-per-window
decision + reservation atomic across sessions: exactly the policy-authorized
number of probes dispatches and the persisted per-window counter/timestamps are
correct.
"""

import asyncio
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from minime.adapters.provider_adapter import FakeProviderAdapter
from minime.config import ProbeConfig
from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import EventType, ProviderHealthStatus, QueuePriority, ReadinessState
from minime.domain.models import Project, ProviderHealth, WorkQueueItem, utc_now
from minime.services.provider_health_service import ProviderHealthService


def _ensure_pg_server() -> str | None:
    """Return a reachable PostgreSQL test URL, starting a local instance if needed."""
    candidate_urls = [
        os.environ.get("MINIME_TEST_DATABASE_URL"),
        "postgresql+psycopg://testuser@localhost:54333/minime_test",
    ]
    for url in candidate_urls:
        if not url:
            continue
        try:
            eng = create_engine(url, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            eng.dispose()
            return url
        except Exception:
            continue

    pg_ctl = Path("/Library/PostgreSQL/17/bin/pg_ctl")
    initdb = Path("/Library/PostgreSQL/17/bin/initdb")
    psql = Path("/Library/PostgreSQL/17/bin/psql")
    data_dir = Path("/tmp/minime_pg_test_data")

    if pg_ctl.exists() and initdb.exists():
        if not data_dir.exists():
            subprocess.run(
                [str(initdb), "-D", str(data_dir), "-U", "testuser", "-A", "trust"],
                check=False,
                capture_output=True,
            )
        subprocess.run(
            [
                str(pg_ctl),
                "-D",
                str(data_dir),
                "-o",
                "-p 54333 -k /tmp",
                "-l",
                "/tmp/minime_pg_test.log",
                "start",
            ],
            check=False,
            capture_output=True,
        )
        time.sleep(0.5)
        if psql.exists():
            subprocess.run(
                [
                    str(psql),
                    "-h",
                    "localhost",
                    "-p",
                    "54333",
                    "-U",
                    "testuser",
                    "-d",
                    "postgres",
                    "-c",
                    "CREATE DATABASE minime_test;",
                ],
                check=False,
                capture_output=True,
            )
        try:
            test_url = "postgresql+psycopg://testuser@localhost:54333/minime_test"
            eng = create_engine(test_url, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            eng.dispose()
            return test_url
        except Exception:
            pass
    return None


PG_TEST_URL = _ensure_pg_server()


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    if not PG_TEST_URL:
        pytest.skip("PostgreSQL test database server is not reachable.")
    engine = create_engine(PG_TEST_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    Base.metadata.create_all(engine)
    yield engine
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


class _ExpensiveCountingFake(FakeProviderAdapter):
    @property
    def probe_is_expensive(self) -> bool:
        return True


def _seed_exhausted_provider(session_factory: sessionmaker[Session], provider: str) -> None:
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        p = Project(project_id="test-p", display_name="Test", repository="owner/repo", implementer=provider)
        uow.projects.save(p)
        w = WorkQueueItem(
            project_id="test-p",
            change_name="test-c",
            priority=QueuePriority.NORMAL,
            readiness_state=ReadinessState.READY,
            discovered_at=utc_now(),
        )
        uow.work_queue.save(w)
        uow.provider_health.save(
            ProviderHealth(
                health_id=f"ph-{provider}",
                provider=provider,
                status=ProviderHealthStatus.EXHAUSTED,
            )
        )
        uow.commit()


def _run_contending_probes(
    session_factory: sessionmaker[Session],
    provider: str,
    cfg: ProbeConfig,
    adapter: _ExpensiveCountingFake,
    num_workers: int,
) -> tuple[list[bool | None], list[BaseException]]:
    """Run ``num_workers`` independent sessions/services contending on one provider."""
    results: list[bool | None] = [None] * num_workers
    errors: list[BaseException | None] = [None] * num_workers
    start_gate = threading.Event()

    def worker(idx: int) -> None:
        try:
            with session_factory() as session:
                uow = PostgresPersistenceUnitOfWork(session)
                service = ProviderHealthService(uow, probe_config=cfg)
                start_gate.wait()
                results[idx] = asyncio.run(service.check_and_probe_provider(provider))
        except BaseException as exc:  # noqa: BLE001 - capture thread failure truthfully
            errors[idx] = exc

    threads = [
        threading.Thread(target=worker, args=(i,), name=f"probe-worker-{i}")
        for i in range(num_workers)
    ]
    for t in threads:
        t.start()
    # Release all workers at the same eligibility boundary.
    time.sleep(0.3)
    start_gate.set()
    for t in threads:
        t.join(timeout=30)

    return results, errors


def test_two_sessions_single_expensive_probe_reservation(
    pg_session_factory: sessionmaker[Session], monkeypatch
):
    """Two independent PostgreSQL sessions/services contend; exactly one reserves.

    max_per_hour=1 and cooldown=0 so the loser passes the cooldown check but must
    observe the winner's committed reservation and be suppressed at the per-window
    maximum rather than dispatching a second probe.
    """
    provider = "codex"
    cfg = ProbeConfig(
        cooldown_seconds=0, backoff_base_seconds=0, backoff_max_seconds=0, max_per_hour=1
    )
    adapter = _ExpensiveCountingFake(name=provider, available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    _seed_exhausted_provider(pg_session_factory, provider)

    results, errors = _run_contending_probes(
        pg_session_factory, provider, cfg, adapter, num_workers=2
    )

    assert errors == [None, None], f"worker raised: {errors}"
    assert adapter.probe_call_count == 1, (
        f"exactly one probe must dispatch, got {adapter.probe_call_count}"
    )
    assert all(r is False for r in results), (
        "every caller must return a truthful False (suppressed/not eligible), got "
        f"{results}"
    )

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        health = uow.provider_health.get_by_provider(provider)
        assert health is not None
        assert health.probe_count_in_window == 1
        assert health.last_probe_at is not None
        assert health.probe_window_started_at is not None
        assert (
            uow.events.count_events(EventType.PROVIDER_PROBE_EXECUTED.value, provider=provider)
            == 1
        )
        assert (
            uow.events.count_events(
                EventType.PROVIDER_PROBE_SUPPRESSED.value, provider=provider
            )
            == 1
        )


def test_multi_worker_expensive_probe_no_oversubscription(
    pg_session_factory: sessionmaker[Session], monkeypatch
):
    """Five independent sessions/services racing cannot oversubscribe max_per_hour=1."""
    provider = "antigravity"
    cfg = ProbeConfig(
        cooldown_seconds=0, backoff_base_seconds=0, backoff_max_seconds=0, max_per_hour=1
    )
    adapter = _ExpensiveCountingFake(name=provider, available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    _seed_exhausted_provider(pg_session_factory, provider)

    num_workers = 5
    results, errors = _run_contending_probes(
        pg_session_factory, provider, cfg, adapter, num_workers=num_workers
    )

    assert errors == [None] * num_workers, f"worker raised: {errors}"
    assert adapter.probe_call_count == 1, (
        f"exactly one probe must dispatch across {num_workers} sessions, got "
        f"{adapter.probe_call_count}"
    )

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        health = uow.provider_health.get_by_provider(provider)
        assert health is not None
        assert health.probe_count_in_window == 1
        assert health.last_probe_at is not None
        assert health.probe_window_started_at is not None
        # Suppression evidence is bounded to one event per provider per hour.
        assert (
            uow.events.count_events(EventType.PROVIDER_PROBE_EXECUTED.value, provider=provider)
            == 1
        )
        assert (
            uow.events.count_events(
                EventType.PROVIDER_PROBE_SUPPRESSED.value, provider=provider
            )
            == 1
        )
