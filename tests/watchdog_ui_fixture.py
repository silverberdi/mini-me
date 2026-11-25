"""Seed and remove isolated browser-test records in the disposable test database."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import OrchestrationRun, OrchestrationStageEvent, Project
from minime.db.models import ProviderModelRegistryModel


def main(action: str, suffix: str) -> None:
    database_url = os.environ.get("MINIME_TEST_DATABASE_URL")
    if not database_url or "test" not in database_url.rsplit("/", 1)[-1].lower():
        raise RuntimeError("Refusing to seed anything except the configured test database")
    engine = create_engine(database_url, pool_pre_ping=True)
    prefix = f"watchdog-ui-{suffix}-"
    projects = [f"{prefix}one", f"{prefix}two"]
    runs = [f"{prefix}active", f"{prefix}complete-one", f"{prefix}complete-two"]
    model_id = f"watchdog-ui-gemini-{suffix}"
    model_backup = Path(tempfile.gettempdir()) / f"{model_id}.json"
    try:
        if action == "cleanup":
            if model_backup.exists():
                backup = json.loads(model_backup.read_text())
                with engine.begin() as connection:
                    if backup["created"]:
                        connection.execute(
                            text("DELETE FROM provider_model_registry WHERE id = :id"),
                            {"id": model_id},
                        )
                    else:
                        connection.execute(
                            text("""UPDATE provider_model_registry
                                SET discovery_status = :status, is_enabled = :enabled,
                                    version = :version, updated_at = :updated_at
                                WHERE id = :id"""),
                            {
                                "status": backup["discovery_status"],
                                "enabled": backup["is_enabled"],
                                "version": backup["version"],
                                "updated_at": datetime.fromisoformat(backup["updated_at"])
                                if backup["updated_at"] else None,
                                "id": backup["id"],
                            },
                        )
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM watchdog_diagnoses WHERE project_id LIKE :prefix"), {"prefix": f"{prefix}%"})
                connection.execute(text("DELETE FROM orchestration_stage_events WHERE run_id LIKE :prefix"), {"prefix": f"{prefix}%"})
                connection.execute(text("DELETE FROM orchestration_runs WHERE id LIKE :prefix"), {"prefix": f"{prefix}%"})
                connection.execute(text("DELETE FROM projects WHERE id LIKE :prefix"), {"prefix": f"{prefix}%"})
            model_backup.unlink(missing_ok=True)
            return

        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            model = session.execute(
                select(ProviderModelRegistryModel).where(
                    ProviderModelRegistryModel.provider_id == "antigravity",
                    ProviderModelRegistryModel.harness_id == "antigravity",
                    ProviderModelRegistryModel.canonical_model_id == "gemini-3.8-flash-medium",
                )
            ).scalar_one_or_none()
            backup = {"created": model is None}
            if model is None:
                model = ProviderModelRegistryModel(
                    id=model_id,
                    provider_id="antigravity",
                    harness_id="antigravity",
                    canonical_model_id="gemini-3.8-flash-medium",
                    origin="discovered",
                    capabilities={"workflow": True, "file_edit": True},
                    discovery_status="available",
                    is_enabled=True,
                    version=1,
                )
                session.add(model)
            else:
                backup.update({
                    "id": model.id,
                    "discovery_status": model.discovery_status,
                    "is_enabled": model.is_enabled,
                    "version": model.version,
                    "updated_at": model.updated_at.isoformat() if model.updated_at else None,
                })
                model.discovery_status = "available"
                model.is_enabled = True
            model_backup.write_text(json.dumps(backup))
            session.commit()

        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            uow.projects.save(Project(project_id=projects[0], display_name="Watchdog UI E2E One", repository="test/watchdog-ui-one"))
            uow.projects.save(Project(project_id=projects[1], display_name="Watchdog UI E2E Two", repository="test/watchdog-ui-two"))
            now = datetime.now(UTC)
            active = OrchestrationRun(
                run_id=runs[0], project_id=projects[0], change_name="ui-e2e-active",
                base_sha="a" * 40, current_candidate_sha="b" * 40,
                current_stage=OrchestrationStage.IMPLEMENTING, is_active=True,
                updated_at=now - timedelta(minutes=20),
            )
            completed_clean = OrchestrationRun(
                run_id=runs[1], project_id=projects[0], change_name="ui-e2e-complete-one",
                base_sha="a" * 40, current_stage=OrchestrationStage.COMPLETED,
                stop_outcome=OrchestrationStopOutcome.COMPLETED, is_active=False,
                stop_details={"resolved_human_gates": []}, updated_at=now - timedelta(minutes=2),
            )
            completed_assisted = OrchestrationRun(
                run_id=runs[2], project_id=projects[1], change_name="ui-e2e-complete-two",
                base_sha="a" * 40, current_stage=OrchestrationStage.COMPLETED,
                stop_outcome=OrchestrationStopOutcome.COMPLETED, is_active=False,
                stop_details={"resolved_human_gates": [{"gate_id": "gate-e2e"}]}, updated_at=now - timedelta(minutes=1),
            )
            for run in (active, completed_clean, completed_assisted):
                uow.orchestration_runs.save(run)
                uow.orchestration_stage_events.save(OrchestrationStageEvent(
                    run_id=run.run_id, from_stage=OrchestrationStage.IMPLEMENTING,
                    to_stage=run.current_stage, event_type="RUN_COMPLETED" if not run.is_active else "STAGE_ACTIVITY",
                    created_at=now - timedelta(minutes=20 if run.is_active else 2),
                    evidence_references={"status": "COMPLETE"},
                ))
            uow.commit()
            diagnoses = [
                (runs[0], projects[0], "pending", "Una sugerencia pendiente para prueba"),
                (runs[0], projects[0], "pending", "Otra sugerencia del mismo proyecto"),
                (runs[2], projects[1], "pending", "Sugerencia de otro proyecto"),
            ]
            for index, (run_id, project_id, _status, suggestion) in enumerate(diagnoses):
                values = {
                    "project_id": project_id, "run_id": run_id,
                    "change_name": "ui-e2e-change", "stage": "IMPLEMENTING" if index == 0 else f"STAGE_{index}",
                    "candidate_sha": "b" * 40, "candidate_generation": 1,
                    "status": "OBSERVED", "root_cause": f"e2e_cause_{index}",
                    "affected_component": "apply", "summary": "Resumen de diagnóstico E2E",
                    "evidence": {"inactive_seconds": 1200}, "action": None,
                    "action_result": {"status": "NOT_ATTEMPTED"},
                    "improvement_suggestion": suggestion,
                }
                uow.watchdog.save_diagnosis(values)
            uow.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
