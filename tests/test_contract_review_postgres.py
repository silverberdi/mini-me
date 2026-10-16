"""Disposable-PostgreSQL persistence and uniqueness evidence for contract review."""

from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    ReviewStatus,
    ReviewVerdict,
)
from minime.domain.models import (
    BudgetReservation,
    Job,
    OpenRouterPricingSnapshot,
    OperatorActionRecord,
    OrchestrationRun,
    Project,
    Review,
)
from minime.services.contract_review_service import _review_reservation_key

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)


def test_contract_review_identity_and_single_spend_authorization_persist_in_postgres():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    # Several durable identities use UUID-sized VARCHAR columns.
    project_id = str(uuid4())
    job_id = str(uuid4())
    run_id = str(uuid4())
    action_id = str(uuid4())
    snapshot_id = str(uuid4())
    review_id = str(uuid4())
    reservation_id = str(uuid4())
    contract_hash = "a" * 64
    account_fingerprint = "b" * 64
    reservation_key = _review_reservation_key(
        run_id=run_id,
        job_id=job_id,
        stage="CONTRACT_REVIEW",
        contract_hash=contract_hash,
    )

    try:
        with engine.connect() as connection:
            assert (
                connection.execute(text("select current_database()")).scalar()
                == "minime_contract_review_test"
            )
            assert (
                connection.execute(text("select version_num from alembic_version")).scalar()
                == "r02_contract_review_budget_identity"
            )

        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            project = Project(
                project_id=project_id,
                display_name="Disposable contract review persistence test",
                repository="test/contract-review",
            )
            job = Job(
                job_id=job_id,
                project_id=project_id,
                change_name="review-change",
                implementer_role="codex",
            )
            run = OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name="review-change",
                base_sha="base-test-sha",
                active_job_id=job_id,
                current_stage=OrchestrationStage.ADMITTED,
            )
            snapshot = OpenRouterPricingSnapshot(
                id=snapshot_id,
                canonical_model_identity="deepseek-chat",
                routed_model_identity="deepseek-chat",
                prompt_price_per_token=Decimal("0.000001"),
                output_price_per_token=Decimal("0.000001"),
                source="deepseek_official_pricing",
                provider="deepseek",
                account_fingerprint=account_fingerprint,
                billing_origin="deepseek_direct",
            )
            action = OperatorActionRecord(
                action_request_id=action_id,
                project_id=project_id,
                change_name=run.change_name,
                run_id=run_id,
                job_id=job_id,
                action_type=OperatorActionType.AUTHORIZE_DEEPSEEK_REVIEW,
                status=OperatorActionStatus.COMPLETED,
                result_payload_json={
                    "authorization": {
                        "provider": "deepseek",
                        "account_fingerprint": account_fingerprint,
                        "model": "deepseek-chat",
                        "stage": "CONTRACT_REVIEW",
                        "billing_origin": "deepseek_direct",
                        "pricing_snapshot_id": snapshot_id,
                        "run_id": run_id,
                        "job_id": job_id,
                        "max_spend_usd": "0.50",
                    }
                },
            )
            reservation = BudgetReservation(
                reservation_id=reservation_id,
                project_id=project_id,
                job_id=job_id,
                run_id=run_id,
                change_id=run.change_name,
                role="reviewer",
                canonical_model_identity="deepseek-chat",
                reserved_amount_usd=Decimal("0.01"),
                status="RESERVED",
                pricing_snapshot_id=snapshot_id,
                provider="deepseek",
                account_fingerprint=account_fingerprint,
                stage="CONTRACT_REVIEW",
                billing_origin="deepseek_direct",
                authorization_id=action_id,
                idempotency_key=reservation_key,
            )
            review = Review(
                review_id=review_id,
                job_id=job_id,
                project_id=project_id,
                change_name=run.change_name,
                reviewer_role="deepseek",
                reviewer_model="deepseek-chat",
                review_stage="CONTRACT_REVIEW",
                contract_hash=contract_hash,
                provider="deepseek",
                account_fingerprint=account_fingerprint,
                budget_authorization_id=action_id,
                budget_reservation_id=reservation_id,
                billing_origin="deepseek_direct",
                orchestration_run_id=run_id,
                candidate_generation=1,
                candidate_sha=contract_hash,
                base_sha=run.base_sha,
                manifest_id=contract_hash,
                manifest_hash=contract_hash,
                status=ReviewStatus.REVIEW_COMPLETED,
                verdict=ReviewVerdict.CONTRACT_ACCEPTED,
            )
            uow.projects.save(project)
            uow.jobs.save(job)
            uow.orchestration_runs.save(run)
            uow.pricing_snapshots.save(snapshot)
            uow.operator_actions.save(action)
            # The repositories share one SQLAlchemy session but do not define
            # ORM relationships for flush ordering; materialize FK parents first.
            uow.flush()
            uow.budget_reservations.save(reservation)
            uow.reviews.save(review)
            uow.commit()

        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            persisted_review = uow.reviews.get_by_job_stage(job_id, "CONTRACT_REVIEW")
            persisted_reservation = uow.budget_reservations.get_by_idempotency_key(reservation_key)
            assert persisted_review is not None
            assert persisted_review.contract_hash == contract_hash
            assert persisted_review.provider == "deepseek"
            assert persisted_review.account_fingerprint == account_fingerprint
            assert persisted_review.budget_authorization_id == action_id
            assert persisted_reservation is not None
            assert persisted_reservation.stage == "CONTRACT_REVIEW"
            assert persisted_reservation.billing_origin == "deepseek_direct"

        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            uow.budget_reservations.save(
                BudgetReservation(
                    project_id=project_id,
                    job_id=job_id,
                    run_id=run_id,
                    change_id="review-change",
                    role="reviewer",
                    canonical_model_identity="deepseek-chat",
                    reserved_amount_usd=Decimal("0.01"),
                    status="RESERVED",
                    pricing_snapshot_id=snapshot_id,
                    provider="deepseek",
                    account_fingerprint=account_fingerprint,
                    stage="CONTRACT_REVIEW",
                    billing_origin="deepseek_direct",
                    authorization_id=action_id,
                    idempotency_key=f"second:{uuid4().hex}",
                )
            )
            with pytest.raises(IntegrityError):
                uow.commit()
            session.rollback()
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("delete from reviews where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from budget_reservations where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from operator_action_records where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from orchestration_runs where project_id = :project_id"),
                {"project_id": project_id},
            )
            connection.execute(
                text("delete from jobs where project_id = :project_id"), {"project_id": project_id}
            )
            connection.execute(
                text("delete from openrouter_pricing_snapshots where id = :snapshot_id"),
                {"snapshot_id": snapshot_id},
            )
            connection.execute(
                text("delete from projects where id = :project_id"), {"project_id": project_id}
            )
        engine.dispose()
