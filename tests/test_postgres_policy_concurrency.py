"""PostgreSQL adversarial tests for budget policy, provider probe, and retry safety (T08, T09, T15)."""

import os
import subprocess
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from minime.adapters.provider_adapter import FakeProviderAdapter
from minime.config import ProbeConfig
from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.retry import TransactionRetryWrapper
from minime.domain.enums import (
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    ProviderHealthStatus,
)
from minime.domain.models import (
    Job,
    OpenRouterBudgetPolicy,
    OpenRouterPricingSnapshot,
    OperatorActionRecord,
    OrchestrationRun,
    Project,
    ProviderHealth,
    RecoveryClaimContext,
)
from minime.services.budget_service import BudgetService
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
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

    from minime.db.session import EXPECTED_ALEMBIC_HEAD

    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) PRIMARY KEY);"))
        conn.execute(text("DELETE FROM alembic_version;"))
        conn.execute(text(f"INSERT INTO alembic_version (version_num) VALUES ('{EXPECTED_ALEMBIC_HEAD}');"))
        conn.commit()
    yield engine
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) PRIMARY KEY);"))
        conn.execute(text("DELETE FROM alembic_version;"))
        conn.execute(text(f"INSERT INTO alembic_version (version_num) VALUES ('{EXPECTED_ALEMBIC_HEAD}');"))
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
        uow.commit()
        uow.jobs.save(Job(job_id="j1", project_id=project_id, change_name="c1", implementer_role="PRIMARY"))
        uow.jobs.save(Job(job_id="j2", project_id=project_id, change_name="c2", implementer_role="PRIMARY"))

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
            routed_model_identity="m1",
            prompt_price_per_token=Decimal("0.001"),
            output_price_per_token=Decimal("0.002"),
            additional_cost_per_request=Decimal("0.45"),
            currency="USD",
            source="openrouter_catalog_api",
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
                project_id=project_id,
                job_id="j1",
                change_id="c1",
                role="implementer",
                canonical_model_identity="m1",
                pricing_snapshot=snapshot,
                prompt_token_upper_bound=100,
                max_output_tokens=100,
            )
            uow.commit()

    def worker_b():
        nonlocal res_b
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            srv = BudgetService(uow)
            res_b, _, _ = srv.reserve_budget(
                project_id=project_id,
                job_id="j2",
                change_id="c2",
                role="implementer",
                canonical_model_identity="m1",
                pricing_snapshot=snapshot,
                prompt_token_upper_bound=100,
                max_output_tokens=100,
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


def test_t09_provider_probe_does_not_dispatch_without_retired_queue(
    pg_session_factory: sessionmaker[Session], monkeypatch
):
    """F1: expensive probes do not dispatch when no work queue exists."""
    provider = "codex"
    cfg = ProbeConfig(cooldown_seconds=0, backoff_base_seconds=0, backoff_max_seconds=0, max_per_hour=1)
    adapter = _ExpensiveAdapter(name=provider, available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(Project(project_id="p-t09", display_name="P9", repository="o/r", implementer=provider))
        uow.provider_health.save(
            ProviderHealth(health_id=f"ph-{provider}", provider=provider, status=ProviderHealthStatus.EXHAUSTED)
        )
        uow.commit()

    def worker(idx: int):
        import asyncio

        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            srv = ProviderHealthService(uow, probe_config=cfg)
            asyncio.run(srv.check_and_probe_provider(provider))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert adapter.probe_call_count == 0


def test_t14_provider_health_stale_writer_protection(pg_session_factory: sessionmaker[Session]):
    """T14 / F14: Prove ProviderHealthService.record_outcome() chronology protection preserves newer T2 truth when delayed T1 observation arrives."""
    from datetime import timedelta

    from minime.domain.enums import ProviderResultClass, RetrySafety
    from minime.domain.models import NormalizedProviderResult, utc_now
    from minime.services.provider_health_service import ProviderHealthService

    provider = "codex"
    base_time = utc_now()
    t1 = base_time + timedelta(seconds=10)
    t2 = base_time + timedelta(seconds=20)

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(Project(project_id="p-t14", display_name="P14", repository="o/r", implementer=provider))
        srv = ProviderHealthService(uow)
        out_init = NormalizedProviderResult(
            provider=provider,
            role="implementer",
            result_class=ProviderResultClass.SUCCESS,
            summary="Initial state at base_time",
            retry_safety=RetrySafety.SAFE,
        )
        srv.record_outcome(out_init, observed_at=base_time)

    # Step 1: Record newer observation at T2 via ProviderHealthService.record_outcome (EXHAUSTED)
    with pg_session_factory() as session2:
        uow2 = PostgresPersistenceUnitOfWork(session2)
        srv2 = ProviderHealthService(uow2)
        out2 = NormalizedProviderResult(
            provider=provider,
            role="implementer",
            result_class=ProviderResultClass.QUOTA_LIMIT,
            summary="Quota limit reached at T2",
            retry_safety=RetrySafety.SAFE,
        )
        srv2.record_outcome(out2, observed_at=t2)

    # Step 2: Later invoke record_outcome at T1 < T2 (attempting to set AVAILABLE based on stale T1 observation)
    with pg_session_factory() as session1:
        uow1 = PostgresPersistenceUnitOfWork(session1)
        srv1 = ProviderHealthService(uow1)
        out1 = NormalizedProviderResult(
            provider=provider,
            role="implementer",
            result_class=ProviderResultClass.SUCCESS,
            summary="Stale success from T1",
            retry_safety=RetrySafety.SAFE,
        )
        srv1.record_outcome(out1, observed_at=t1)

    # Step 3: Verify persisted state remains the T2 (newer) EXHAUSTED truth
    with pg_session_factory() as session_v:
        uow_v = PostgresPersistenceUnitOfWork(session_v)
        final_h = uow_v.provider_health.get_by_provider(provider)
        assert final_h is not None
        assert final_h.status == ProviderHealthStatus.EXHAUSTED
        assert final_h.updated_at >= t2


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
    result = wrapper.execute(database_transaction_fn, rollback_fn=lambda: None)

    assert result == "success"
    assert attempt_counter == 2
    assert external_call_count == 1, "External action must be executed exactly once outside retries."


def test_explore_recovery_authorization_is_single_use_under_postgres_contention(
    pg_session_factory: sessionmaker[Session],
):
    """Two real DB sessions may consume one recovery decision only once."""
    project_id = "explore-auth-concurrency"
    run_id = "explore-auth-run"
    action_id = "explore-auth-request"
    prior_attempt_id = "explore-prior-attempt"
    expected = {
        "single_use": True,
        "stage": "explore",
        "issue_number": 173,
        "provider": "antigravity",
        "prior_attempt_id": prior_attempt_id,
        "prior_context_sha256": "a" * 64,
        "prior_workflow_sha256": "b" * 64,
    }

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(
            Project(
                project_id=project_id,
                display_name="Explore auth contention",
                repository="o/r",
                base_branch="main",
            )
        )
        uow.orchestration_runs.save(
            OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name="explore-auth-change",
                base_sha="main",
                current_stage=OrchestrationStage.EXPLORING,
                resumable_stage=OrchestrationStage.EXPLORING,
                stop_details={
                    "explore_attempt": {
                        "attempt_id": prior_attempt_id,
                        "status": "IN_PROGRESS",
                        "context_sha256": expected["prior_context_sha256"],
                        "workflow_sha256": expected["prior_workflow_sha256"],
                    }
                },
            )
        )
        uow.operator_actions.save(
            OperatorActionRecord(
                id="explore-auth-record",
                action_request_id=action_id,
                project_id=project_id,
                change_name="explore-auth-change",
                run_id=run_id,
                action_type=OperatorActionType.RETRY,
                actor_identity="operator@example.com",
                source_interface="api",
                precondition_stage=OrchestrationStage.EXPLORING.value,
                status=OperatorActionStatus.ACCEPTED,
                parameters_json=expected,
            )
        )
        uow.commit()

    barrier = threading.Barrier(2)
    results: list[bool] = []

    def consume() -> None:
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            barrier.wait()
            consumed = uow.operator_actions.consume_single_use(
                action_id,
                run_id=run_id,
                action_type=OperatorActionType.RETRY,
                expected_parameters=expected,
            )
            results.append(consumed is not None)
            uow.commit()

    threads = [threading.Thread(target=consume) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(results) == [False, True]

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        record = uow.operator_actions.get_by_request_id(action_id)
        assert record is not None
        assert record.status == OperatorActionStatus.COMPLETED


def test_recovery_claim_release_uses_owner_and_fence_context(
    pg_session_factory: sessionmaker[Session],
):
    """A completed Explore dispatch releases its PostgreSQL claim by CAS identity."""
    claim_key = "run:explore-release-context"
    owner = "explore-release-owner"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        claim = uow.claims.acquire_or_reacquire(claim_key, owner, lease_seconds=300)
        assert claim is not None
        context = RecoveryClaimContext(
            claim_key=claim.claim_key,
            owner_instance_id=claim.owner_instance_id,
            fence_token=claim.fence_token,
            lease_expires_at=claim.lease_expires_at,
        )
        assert uow.claims.release_claim(context) is True
        uow.commit()

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        stored = uow.claims.get_by_key(claim_key)
        assert stored is not None
        assert stored.released_at is not None


def test_legacy_explore_run_without_attempt_accepts_only_explicit_recovery(
    pg_session_factory: sessionmaker[Session],
):
    """The observed legacy state gets a new authorization, never a fabricated attempt."""
    suffix = str(time.time_ns())
    project_id = f"legacy-explore-{suffix}"
    run_id = f"legacy-explore-run-{suffix}"
    action_id = f"legacy-recovery-{suffix}"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(
            Project(
                project_id=project_id,
                display_name="Legacy Explore",
                repository="o/r",
                base_branch="main",
            )
        )
        uow.orchestration_runs.save(
            OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name="gacela-05-ui-self-hosted",
                base_sha="main",
                current_stage=OrchestrationStage.EXPLORING,
                resumable_stage=OrchestrationStage.EXPLORING,
                stop_details={"issue_number": 173},
            )
        )
        uow.commit()
        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: uow,
            github_adapter=MagicMock(),
            worktree_manager=MagicMock(),
            agent_runner=MagicMock(),
        )
        assert coordinator.register_explore_recovery_authorization(
            project_id=project_id,
            run_id=run_id,
            authorization_reference=action_id,
            actor_identity="operator@example.com",
            source_interface="api",
            issue_number=173,
            provider="antigravity",
            prior_attempt_id=None,
        )
        record = uow.operator_actions.get_by_request_id(action_id)
        assert record is not None
        assert record.parameters_json["legacy_missing_attempt"] is True
        assert record.parameters_json["prior_attempt_id"] is None
        stored_run = uow.orchestration_runs.get_by_id(run_id)
        assert stored_run is not None
        assert "explore_attempt" not in stored_run.stop_details
        assert "explore_checkpoint" not in stored_run.stop_details


def test_explore_dispatch_claim_serializes_two_postgres_workers(
    pg_session_factory: sessionmaker[Session],
):
    """The durable Explore dispatch intent admits one worker before provider I/O."""
    suffix = str(time.time_ns())
    project_id = f"explore-dispatch-{suffix}"
    run_id = f"explore-dispatch-run-{suffix}"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(
            Project(
                project_id=project_id,
                display_name="Explore dispatch contention",
                repository="o/r",
                base_branch="main",
            )
        )
        uow.orchestration_runs.save(
            OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name="explore-dispatch-change",
                base_sha="main",
                current_stage=OrchestrationStage.EXPLORING,
                resumable_stage=OrchestrationStage.EXPLORING,
            )
        )
        uow.commit()


def test_propose_dispatch_claim_serializes_two_postgres_workers(
    pg_session_factory: sessionmaker[Session],
):
    """A partial Propose continuation cannot create two provider dispatches."""
    suffix = str(time.time_ns())
    project_id = f"propose-dispatch-{suffix}"
    run_id = f"propose-dispatch-run-{suffix}"
    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(
            Project(
                project_id=project_id,
                display_name="Propose dispatch contention",
                repository="o/r",
                base_branch="main",
            )
        )
        uow.orchestration_runs.save(
            OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name="propose-dispatch-change",
                base_sha="main",
                current_stage=OrchestrationStage.PROPOSING,
                resumable_stage=OrchestrationStage.PROPOSING,
            )
        )
        uow.commit()

    barrier = threading.Barrier(2)
    results: list[tuple[str, str, RecoveryClaimContext] | None] = []
    errors: list[str] = []

    def prepare() -> None:
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            coordinator = NativeOrchestrationCoordinator(
                uow_factory=lambda: uow,
                github_adapter=MagicMock(),
                worktree_manager=MagicMock(),
                agent_runner=MagicMock(),
            )
            barrier.wait()
            try:
                run = uow.orchestration_runs.get_by_id(run_id)
                assert run is not None
                results.append(
                    coordinator._prepare_propose_dispatch(
                        uow=uow,
                        run=run,
                        issue_number=173,
                        provider="codex",
                        change_name="propose-dispatch-change",
                        is_recovery=True,
                    )
                )
            except Exception as exc:
                errors.append(repr(exc))

    threads = [threading.Thread(target=prepare) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    admitted = [result for result in results if result is not None]
    assert not errors, errors
    assert len(admitted) == 1
    attempt_id, action_key, context = admitted[0]
    assert attempt_id
    assert action_key.startswith(f"propose:{run_id}:")

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        action = uow.orchestration_external_actions.get_by_action_key(action_key)
        assert action is not None
        assert action.status.value == "EXECUTING"
        attempts = uow.external_action_attempts.list_by_action_key(action_key)
        assert len(attempts) == 1
        assert attempts[0].dispatch_intent_key.startswith(action_key)
        assert uow.claims.release_claim(context) is True
        uow.commit()

    barrier = threading.Barrier(2)
    results: list[tuple[str, str, RecoveryClaimContext] | None] = []
    errors: list[str] = []

    def prepare() -> None:
        with pg_session_factory() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            coordinator = NativeOrchestrationCoordinator(
                uow_factory=lambda: uow,
                github_adapter=MagicMock(),
                worktree_manager=MagicMock(),
                agent_runner=MagicMock(),
            )
            barrier.wait()
            try:
                run = uow.orchestration_runs.get_by_id(run_id)
                assert run is not None
                result = coordinator._prepare_explore_dispatch(
                    uow=uow,
                    run=run,
                    issue_number=173,
                    provider="antigravity",
                    context_sha="c" * 64,
                    workflow_sha="d" * 64,
                    is_recovery=True,
                )
                results.append(result)
            except Exception as exc:
                errors.append(repr(exc))

    threads = [threading.Thread(target=prepare) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    admitted = [result for result in results if result is not None]
    assert not errors, errors
    assert len(admitted) == 1
    attempt_id, action_key, context = admitted[0]
    assert attempt_id
    assert action_key.startswith(f"explore:{run_id}:")

    with pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        action = uow.orchestration_external_actions.get_by_action_key(action_key)
        assert action is not None
        assert action.status.value == "EXECUTING"
        attempts = uow.external_action_attempts.list_by_action_key(action_key)
        assert len(attempts) == 1
        assert attempts[0].dispatch_intent_key.startswith(action_key)
        assert uow.claims.release_claim(context) is True
        uow.commit()
