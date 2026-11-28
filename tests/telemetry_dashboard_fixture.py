"""Seed and remove one deterministic proportional-autonomy browser observation."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import OrchestrationRun, OrchestrationStageEvent, Project


def main(action: str, suffix: str) -> None:
    database_url = os.environ.get("MINIME_TEST_DATABASE_URL")
    if not database_url or "test" not in database_url.rsplit("/", 1)[-1].lower():
        raise RuntimeError("Refusing to seed anything except the configured test database")
    run_id = f"telemetry-dashboard-{suffix}"
    empty_project_id = f"telemetry-empty-{suffix}"
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        if action == "cleanup":
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM orchestration_stage_events WHERE run_id = :run_id"), {"run_id": run_id})
                connection.execute(text("DELETE FROM orchestration_runs WHERE id = :run_id"), {"run_id": run_id})
                connection.execute(text("DELETE FROM projects WHERE id = :project_id"), {"project_id": empty_project_id})
            return
        now = datetime.now(UTC)
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            uow.projects.save(Project(
                project_id=empty_project_id,
                display_name="Telemetry empty E2E",
                repository=f"test/{empty_project_id}",
            ))
            run = OrchestrationRun(
                run_id=run_id,
                project_id="e2e-project",
                change_name=f"telemetry-dashboard-{suffix}",
                base_sha="a" * 40,
                current_stage=OrchestrationStage.COMPLETED,
                stop_outcome=OrchestrationStopOutcome.COMPLETED,
                is_active=False,
                updated_at=now,
                stop_details={"resolved_human_gates": [{
                    "gate_id": "telemetry-scope",
                    "response": "approved",
                    "type": "governance",
                    "stage": "PROPOSING",
                }]},
            )
            uow.orchestration_runs.save(run)
            stages = [OrchestrationStage.EXPLORING, OrchestrationStage.PROPOSING,
                      OrchestrationStage.IMPLEMENTING, OrchestrationStage.VERIFYING,
                      OrchestrationStage.CODE_REVIEW, OrchestrationStage.COMPLETED]
            for stage in stages:
                uow.orchestration_stage_events.save(OrchestrationStageEvent(
                    run_id=run_id,
                    from_stage=stage,
                    to_stage=stage,
                    event_type="STAGE_INVOCATION_COMPLETED",
                    created_at=now,
                    evidence_references={"status": "COMPLETE"},
                ))
            uow.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
