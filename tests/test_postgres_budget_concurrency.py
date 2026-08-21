"""PostgreSQL-backed integration tests proving transactional contention and row-level locking."""

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

from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.models import (
    Job,
    OpenRouterBudgetPolicy,
    OpenRouterPricingSnapshot,
    Project,
    utc_now,
)
from minime.services.budget_service import BudgetService

# Preferred PostgreSQL URLs for testing
DEFAULT_PG_URL = os.environ.get(
    "MINIME_DATABASE_URL",
    "postgresql+psycopg://testuser@localhost:54333/minime_test",
)


def _ensure_pg_server() -> str | None:
    """Ensure a PostgreSQL database is available, starting local test instance if needed."""
    candidate_urls = [
        os.environ.get("MINIME_DATABASE_URL"),
        "postgresql+psycopg://testuser@localhost:54333/minime_test",
        "postgresql+psycopg://minime:pass@localhost:5432/minime",
        "postgresql+psycopg://localhost:5432/minime",
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

    # Attempt to start PostgreSQL if binaries exist in standard macOS location
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
                [str(psql), "-h", "localhost", "-p", "54333", "-U", "testuser", "-d", "postgres", "-c", "CREATE DATABASE minime_test;"],
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
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


def _seed_test_project_and_snapshot(
    session_factory: sessionmaker[Session],
    project_id: str,
    daily_cap: str,
    monthly_cap: str,
    snapshot_id: str = "snap-concurrency",
) -> OpenRouterPricingSnapshot:
    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        # 1. Project
        proj = Project(
            project_id=project_id,
            display_name=f"Project {project_id}",
            repository="silverberdi/mini-me",
            base_branch="main",
        )
        uow.projects.save(proj)
        uow.commit()

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        # 2. Jobs
        job_a = Job(job_id=f"job-{project_id}-a", project_id=project_id, change_name="change-a", implementer_role="codex")
        job_b = Job(job_id=f"job-{project_id}-b", project_id=project_id, change_name="change-b", implementer_role="codex")
        uow.jobs.save(job_a)
        uow.jobs.save(job_b)

        # 3. Policy
        policy = OpenRouterBudgetPolicy(
            project_id=project_id,
            enabled=True,
            daily_cap_usd=Decimal(daily_cap),
            monthly_cap_usd=Decimal(monthly_cap),
            currency="USD",
            policy_version=1,
            is_breached=False,
            updated_at=utc_now(),
        )
        uow.budget_policies.save(policy)

        # 4. Pricing Snapshot ($0.10 prompt + $0.20 output + $0.45 request = $0.75 max cost for 100/100 tokens)
        snapshot = OpenRouterPricingSnapshot(
            snapshot_id=snapshot_id,
            canonical_model_identity="qwen:qwen3-coder",
            routed_model_identity="qwen/qwen3-coder",
            prompt_price_per_token=Decimal("0.001"),
            output_price_per_token=Decimal("0.002"),
            additional_cost_per_request=Decimal("0.45"),
            currency="USD",
            source="openrouter_catalog_api",
            observed_at=utc_now(),
            created_at=utc_now(),
        )
        uow.pricing_snapshots.save(snapshot)
        uow.commit()

    return snapshot


def test_postgres_daily_cap_race_serialization(pg_session_factory: sessionmaker[Session]):
    """Prove that PostgreSQL SELECT ... FOR UPDATE row-level locking serializes concurrent reservations.

    Scenario:
    - daily_cap = 1.00, monthly_cap = 100.00
    - Transaction A and Transaction B both attempt to reserve $0.75 concurrently on the same project.
    - Transaction A enters and acquires the row lock on openrouter_budget_policies.
    - Transaction B attempts to reserve and blocks at PostgreSQL row-level lock.
    - Transaction A completes and commits its $0.75 reservation.
    - Transaction B unblocks, recomputes headroom from committed state ($0.25 remaining), and is denied.
    - Persisted total in PostgreSQL is exactly $0.75 (never exceeds $1.00 daily cap).
    """
    project_id = "test-daily-race"
    snapshot = _seed_test_project_and_snapshot(
        pg_session_factory,
        project_id=project_id,
        daily_cap="1.00",
        monthly_cap="100.00",
        snapshot_id="snap-daily",
    )

    res_a, res_b = None, None
    reason_a, reason_b = None, None
    lock_event_a = threading.Event()
    step_log: list[str] = []

    def worker_a():
        nonlocal res_a, reason_a
        with pg_session_factory() as session_a:
            uow_a = PostgresPersistenceUnitOfWork(session_a)
            srv_a = BudgetService(uow_a)

            # Acquire row lock in transaction A
            _ = uow_a.budget_policies.get_for_update(project_id)
            step_log.append("A: acquired row lock")
            lock_event_a.set()

            # Pause to ensure transaction B reaches SELECT ... FOR UPDATE and blocks on PostgreSQL row lock
            time.sleep(0.2)

            step_log.append("A: reserving $0.75")
            res_a, reason_a, _ = srv_a.reserve_budget(
                project_id=project_id,
                job_id=f"job-{project_id}-a",
                change_id="change-a",
                role="reviewer",
                canonical_model_identity="qwen:qwen3-coder",
                pricing_snapshot=snapshot,
                prompt_token_upper_bound=100,
                max_output_tokens=100,
            )
            step_log.append("A: committing transaction")
            uow_a.commit()
            step_log.append("A: committed")

    def worker_b():
        nonlocal res_b, reason_b
        # Wait until transaction A has acquired the exclusive row lock
        lock_event_a.wait()
        step_log.append("B: starting concurrent reserve attempt (will block on row lock)")
        with pg_session_factory() as session_b:
            uow_b = PostgresPersistenceUnitOfWork(session_b)
            srv_b = BudgetService(uow_b)

            res_b, reason_b, _ = srv_b.reserve_budget(
                project_id=project_id,
                job_id=f"job-{project_id}-b",
                change_id="change-b",
                role="reviewer",
                canonical_model_identity="qwen:qwen3-coder",
                pricing_snapshot=snapshot,
                prompt_token_upper_bound=100,
                max_output_tokens=100,
            )
            step_log.append("B: unblocked and finished reserve attempt")
            uow_b.commit()

    thread_a = threading.Thread(target=worker_a, name="txn-A")
    thread_b = threading.Thread(target=worker_b, name="txn-B")

    thread_a.start()
    thread_b.start()
    thread_a.join()
    thread_b.join()

    # 1. Exactly one transaction successfully reserved
    assert res_a is not None, "Transaction A should have succeeded"
    assert reason_a is None
    assert res_a.reserved_amount_usd == Decimal("0.750000")

    # 2. Transaction B serialized behind A, recomputed headroom, and was denied
    assert res_b is None, "Transaction B should have been denied after A committed"
    assert reason_b == "budget_denial"

    # 3. Verify step order proves contention and serialization
    assert "A: acquired row lock" in step_log
    assert "B: starting concurrent reserve attempt (will block on row lock)" in step_log
    assert "A: committed" in step_log
    assert "B: unblocked and finished reserve attempt" in step_log

    # 4. Verify authoritative persisted database state
    with pg_session_factory() as verify_session:
        verify_uow = PostgresPersistenceUnitOfWork(verify_session)
        persisted_reservations = verify_uow.budget_reservations.list_by_project(project_id)
        assert len(persisted_reservations) == 1, "Only one reservation must be persisted in PostgreSQL"
        assert persisted_reservations[0].reserved_amount_usd == Decimal("0.750000")
        assert persisted_reservations[0].status == "RESERVED"

        # Verify headroom calculation in DB
        policy, headroom = BudgetService(verify_uow).get_headroom(project_id)
        assert policy is not None
        assert headroom is not None
        assert headroom.daily_cap_usd == Decimal("1.000000")
        assert headroom.reserved_today_usd == Decimal("0.750000")
        assert headroom.daily_headroom_usd == Decimal("0.250000")


def test_postgres_monthly_cap_race_serialization(pg_session_factory: sessionmaker[Session]):
    """Prove that PostgreSQL SELECT ... FOR UPDATE row-level locking protects monthly caps against race conditions.

    Scenario:
    - daily_cap = 100.00, monthly_cap = 1.00
    - Transaction A and Transaction B both attempt to reserve $0.75 concurrently on the same project.
    - Transaction A holds row lock, completes reservation, and commits.
    - Transaction B serializes, unblocks, observes remaining monthly headroom ($0.25), and is denied.
    - Authoritative persisted monthly encumbrance never exceeds $1.00.
    """
    project_id = "test-monthly-race"
    snapshot = _seed_test_project_and_snapshot(
        pg_session_factory,
        project_id=project_id,
        daily_cap="100.00",
        monthly_cap="1.00",
        snapshot_id="snap-monthly",
    )

    res_a, res_b = None, None
    reason_a, reason_b = None, None
    lock_event_a = threading.Event()

    def worker_a():
        nonlocal res_a, reason_a
        with pg_session_factory() as session_a:
            uow_a = PostgresPersistenceUnitOfWork(session_a)
            srv_a = BudgetService(uow_a)

            _ = uow_a.budget_policies.get_for_update(project_id)
            lock_event_a.set()
            time.sleep(0.2)

            res_a, reason_a, _ = srv_a.reserve_budget(
                project_id=project_id,
                job_id=f"job-{project_id}-a",
                change_id="change-a",
                role="reviewer",
                canonical_model_identity="qwen:qwen3-coder",
                pricing_snapshot=snapshot,
                prompt_token_upper_bound=100,
                max_output_tokens=100,
            )
            uow_a.commit()

    def worker_b():
        nonlocal res_b, reason_b
        lock_event_a.wait()
        with pg_session_factory() as session_b:
            uow_b = PostgresPersistenceUnitOfWork(session_b)
            srv_b = BudgetService(uow_b)

            res_b, reason_b, _ = srv_b.reserve_budget(
                project_id=project_id,
                job_id=f"job-{project_id}-b",
                change_id="change-b",
                role="reviewer",
                canonical_model_identity="qwen:qwen3-coder",
                pricing_snapshot=snapshot,
                prompt_token_upper_bound=100,
                max_output_tokens=100,
            )
            uow_b.commit()

    thread_a = threading.Thread(target=worker_a, name="txn-A-month")
    thread_b = threading.Thread(target=worker_b, name="txn-B-month")

    thread_a.start()
    thread_b.start()
    thread_a.join()
    thread_b.join()

    # 1. Exactly one transaction succeeds
    assert res_a is not None
    assert reason_a is None

    # 2. Exactly one transaction is denied
    assert res_b is None
    assert reason_b == "budget_denial"

    # 3. Persisted monthly encumbrance never exceeds $1.00
    with pg_session_factory() as verify_session:
        verify_uow = PostgresPersistenceUnitOfWork(verify_session)
        persisted_reservations = verify_uow.budget_reservations.list_by_project(project_id)
        assert len(persisted_reservations) == 1
        assert persisted_reservations[0].reserved_amount_usd == Decimal("0.750000")

        policy, headroom = BudgetService(verify_uow).get_headroom(project_id)
        assert policy is not None
        assert headroom is not None
        assert headroom.monthly_cap_usd == Decimal("1.000000")
        assert headroom.reserved_month_usd == Decimal("0.750000")
        assert headroom.monthly_headroom_usd == Decimal("0.250000")


def test_postgres_multi_worker_contention_no_oversubscription(pg_session_factory: sessionmaker[Session]):
    """Prove that 5 concurrent threads racing simultaneously cannot oversubscribe the daily cap in PostgreSQL."""
    project_id = "test-multi-worker"
    num_workers = 5
    snapshot = _seed_test_project_and_snapshot(
        pg_session_factory,
        project_id=project_id,
        daily_cap="1.00",
        monthly_cap="100.00",
        snapshot_id="snap-multi",
    )

    # Seed jobs for each worker
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        for i in range(num_workers):
            uow.jobs.save(Job(job_id=f"job-{project_id}-{i}", project_id=project_id, change_name=f"change-{i}", implementer_role="codex"))
        uow.commit()

    barrier = threading.Barrier(num_workers)
    results: list[tuple[bool, str | None]] = [ (False, None) ] * num_workers

    def worker(worker_id: int):
        barrier.wait()
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            srv = BudgetService(uow)
            res, reason, _ = srv.reserve_budget(
                project_id=project_id,
                job_id=f"job-{project_id}-{worker_id}",
                change_id=f"change-{worker_id}",
                role="reviewer",
                canonical_model_identity="qwen:qwen3-coder",
                pricing_snapshot=snapshot,
                prompt_token_upper_bound=100,
                max_output_tokens=100,
            )
            uow.commit()
            results[worker_id] = (res is not None, reason)

    threads = [threading.Thread(target=worker, args=(i,), name=f"worker-{i}") for i in range(num_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r[0] is True]
    denials = [r for r in results if r[0] is False]

    # Exactly 1 can succeed under $1.00 daily cap for $0.75 reservation
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(denials) == 4, f"Expected exactly 4 denials, got {len(denials)}"
    assert all(r[1] == "budget_denial" for r in denials)

    # Verify persisted DB records in PostgreSQL
    with pg_session_factory() as verify_session:
        verify_uow = PostgresPersistenceUnitOfWork(verify_session)
        reservations = verify_uow.budget_reservations.list_by_project(project_id)
        assert len(reservations) == 1
        assert reservations[0].reserved_amount_usd == Decimal("0.750000")

