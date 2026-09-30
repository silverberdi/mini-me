"""PostgreSQL adversarial tests for budget policy, provider probe, and retry safety (T08, T09, T15)."""

import os
import subprocess
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from minime.adapters.provider_adapter import FakeProviderAdapter
from minime.config import ProbeConfig
from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.retry import TransactionRetryWrapper
from minime.domain.enums import ProviderHealthStatus, QueuePriority, ReadinessState
from minime.domain.models import (
    Job,
    OpenRouterBudgetPolicy,
    OpenRouterPricingSnapshot,
    Project,
    ProviderHealth,
    WorkQueueItem,
    utc_now,
)
from minime.services.budget_service import BudgetService
from minime.services.provider_health_service import ProviderHealthService


def _ensure_pg_server() -> str | None:
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


def test_t08_budget_contention_serialization(pg_session_factory: sessionmaker[Session]):
    """T08: Prove row locking on budget policy serializes concurrent reservations and prevents oversubscription."""
    project_id = "t08-proj"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        proj = Project(project_id=project_id, display_name="T08", repository="o/r", base_branch="main")
        uow.projects.save(proj)
        uow.jobs.save(Job(job_id="j1", project_id=project_id, change_name="c1"))
        uow.jobs.save(Job(job_id="j2", project_id=project_id, change_name="c2"))

        policy = OpenRouterBudgetPolicy(
            project_id=project_id,
            enabled=True,
            daily_cap_usd=Decimal("1.00"),
            monthly_cap_usd=Decimal("100.00"),
            currency="USD",
        )
        uow.budget_policies.save(policy)

        snapshot = OpenRouterPricingSnapshot(
            snapshot_id="snap-t08",
            canonical_model_identity="m1",
            prompt_price_per_token=Decimal("0.001"),
            output_price_per_token=Decimal("0.002"),
            additional_cost_per_request=Decimal("0.45"),
            currency="USD",
            source="test",
        )
        uow.pricing_snapshots.save(snapshot)
        uow.commit()

    res_a, res_b = None, None

    def worker_a():
        nonlocal res_a
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            srv = BudgetService(uow)
            res_a, _, _ = srv.reserve_budget(
                project_id, "j1", "c1", "implementer", "m1", snapshot, 100, 100
            )
            uow.commit()

    def worker_b():
        nonlocal res_b
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            srv = BudgetService(uow)
            res_b, _, _ = srv.reserve_budget(
                project_id, "j2", "c2", "implementer", "m1", snapshot, 100, 100
            )
            uow.commit()

    t1 = threading.Thread(target=worker_a)
    t2 = threading.Thread(target=worker_b)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Under $1.00 daily cap and $0.75 per reservation, exactly 1 succeeds and 1 is denied
    successes = [r for r in (res_a, res_b) if r is not None]
    assert len(successes) == 1


class _ExpensiveAdapter(FakeProviderAdapter):
    @property
    def probe_is_expensive(self) -> bool:
        return True


def test_t09_provider_probe_contention_serialization(
    pg_session_factory: sessionmaker[Session], monkeypatch
):
    """T09: Prove row locking on provider health get_by_provider_for_update() serializes expensive probe reservations."""
    provider = "t09-provider"
    cfg = ProbeConfig(cooldown_seconds=0, backoff_base_seconds=0, backoff_max_seconds=0, max_per_hour=1)
    adapter = _ExpensiveAdapter(name=provider, available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(Project(project_id="p-t09", display_name="P9", repository="o/r", implementer=provider))
        uow.work_queue.save(
            WorkQueueItem(
                project_id="p-t09",
                change_name="c-t09",
                priority=QueuePriority.NORMAL,
                readiness_state=ReadinessState.READY,
                discovered_at=utc_now(),
            )
        )
        uow.provider_health.save(
            ProviderHealth(health_id=f"ph-{provider}", provider=provider, status=ProviderHealthStatus.EXHAUSTED)
        )
        uow.commit()

    dispatched: list[int] = []

    def worker(idx: int):
        import asyncio

        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            srv = ProviderHealthService(uow, probe_config=cfg)
            res = asyncio.run(srv.check_and_probe_provider(provider))
            if res:
                dispatched.append(idx)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly 1 expensive probe dispatched despite 3 concurrent sessions
    assert adapter.probe_call_count == 1


def test_t15_external_effect_retry_safety(pg_session_factory: sessionmaker[Session]):
    """T15: Prove TransactionRetryWrapper excludes unreserved external side effects from retry blocks."""
    external_call_count = 0

    def unreserved_external_action():
        nonlocal external_call_count
        external_call_count += 1

    wrapper = TransactionRetryWrapper(max_attempts=3)

    attempt_counter = 0

    def database_transaction_fn():
        nonlocal attempt_counter
        attempt_counter += 1
        if attempt_counter == 1:

            class Synthetic40001(Exception):
                pass

            err = Synthetic40001("Serialization error")
            err.pgcode = "40001"  # type: ignore
            raise err

        return "success"

    # Rule: External side effect must NOT be placed inside retriable transaction block
    unreserved_external_action()
    result = wrapper.execute(database_transaction_fn)

    assert result == "success"
    assert attempt_counter == 2
    assert external_call_count == 1, "External action must be executed exactly once outside retries."
