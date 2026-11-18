"""Create and mutate one isolated Run for the real browser SSE integration test."""

from __future__ import annotations

import json
import os
import sys
import time

from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from minime.db.models import (
    AuthSessionModel,
    AuthorizedOperatorModel,
    OrchestrationRunModel,
    ProjectModel,
)
from minime.db.repository import PostgresOrchestrationRunRepository, PostgresPersistenceUnitOfWork
from minime.domain.enums import HumanGate, OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import AuthorizedOperator, OrchestrationRun, Project
from minime.services.auth_service import SessionManager, hash_token


def _engine():
    database_url = os.environ.get("MINIME_DATABASE_URL")
    if not database_url:
        raise RuntimeError("MINIME_DATABASE_URL is required for the PostgreSQL browser E2E")
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        database_name = connection.execute(text("SELECT current_database()")).scalar_one()
    normalized_name = database_name.lower()
    if "test" not in normalized_name and not normalized_name.startswith("minime_f3_e2e_"):
        engine.dispose()
        raise RuntimeError("Refusing to use a database not identified as test or dedicated F3 E2E")
    return engine


def main() -> None:
    engine = _engine()
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    command = sys.argv[1]
    project_id, run_id = sys.argv[2:4]
    session = session_factory()
    try:
        uow = PostgresPersistenceUnitOfWork(session)
        if command == "create":
            operator_email = f"{project_id}@example.test"
            uow.projects.save(
                Project(project_id=project_id, display_name="Realtime SSE E2E", repository="test/realtime-sse")
            )
            uow.authorized_operators.save(
                AuthorizedOperator(email=operator_email, display_name="Realtime E2E")
            )
            uow.orchestration_runs.save(
                OrchestrationRun(
                    run_id=run_id,
                    project_id=project_id,
                    change_name="issue-366-realtime-e2e",
                    base_sha="test-base",
                    current_stage=OrchestrationStage.ADMITTED,
                    resumable_stage=OrchestrationStage.ADMITTED,
                    is_active=True,
                )
            )
            token, _ = SessionManager(uow).create_session(operator_email)
            print(json.dumps({"token": token}))
        elif command == "transition":
            stage = OrchestrationStage(sys.argv[4])
            listener_ready = False
            for _ in range(100):
                with engine.connect() as connection:
                    listener_ready = bool(
                        connection.execute(
                            text(
                                "SELECT 1 FROM pg_stat_activity "
                                "WHERE datname = current_database() "
                                "AND application_name = 'minime-api-run-event-listener' "
                                "AND pid <> pg_backend_pid() LIMIT 1"
                            )
                        ).scalar_one_or_none()
                    )
                if listener_ready:
                    break
                time.sleep(0.1)
            if not listener_ready:
                raise RuntimeError("API PostgreSQL event listener did not become ready")
            run = uow.orchestration_runs.get_by_id(run_id)
            if run is None or run.project_id != project_id:
                raise RuntimeError("E2E Run was not found in the expected project")
            run.current_stage = stage
            run.resumable_stage = stage
            uow.orchestration_runs.save(run)
            uow.commit()
        elif command == "gate-create":
            run = uow.orchestration_runs.get_by_id(run_id)
            if run is None or run.project_id != project_id:
                raise RuntimeError("E2E Run was not found in the expected project")
            uow.orchestration_runs.update_stop_outcome(
                run_id,
                OrchestrationStopOutcome.NEEDS_HUMAN,
                HumanGate.NEEDS_HUMAN,
                "Choose CONTINUE_CANDIDATE or preserve the candidate.",
                {
                    "human_payload": {
                        "gate_id": f"{run_id}-gate-1",
                        "gate": "e2e_native_choice",
                        "stage": run.current_stage.value,
                        "question": "Choose CONTINUE_CANDIDATE or preserve the candidate.",
                        "question_es": "Elige CONTINUE_CANDIDATE o conserva el candidato.",
                        "options": [
                            {"id": "continue", "label": "Continue candidate", "response_text": "CONTINUE_CANDIDATE"},
                            {"id": "preserve", "label": "Preserve candidate", "response_text": "PRESERVE_CANDIDATE"},
                        ],
                        "options_es": ["Continuar con el candidato", "Conservar el candidato"],
                        "options_source": "native",
                    }
                },
                is_active=True,
            )
            uow.commit()
        elif command == "gate-resolve":
            run = uow.orchestration_runs.get_by_id(run_id)
            if run is None or run.project_id != project_id:
                raise RuntimeError("E2E Run was not found in the expected project")
            details = dict(run.stop_details or {})
            details.pop("human_payload", None)
            details["resolved_human_gates"] = [
                {"gate_id": f"{run_id}-gate-1", "response": "CONTINUE_CANDIDATE"}
            ]
            uow.orchestration_runs.update_stop_outcome(
                run_id, None, None, None, details, is_active=True
            )
            uow.commit()
        elif command == "recover-listener":
            with engine.begin() as connection:
                pid = connection.execute(
                    text(
                        "SELECT pid FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND application_name = 'minime-api-run-event-listener' "
                        "AND pid <> pg_backend_pid() LIMIT 1"
                    )
                ).scalar_one_or_none()
                if pid is None:
                    raise RuntimeError("API PostgreSQL event listener is not connected")
                terminated = connection.execute(
                    text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
                ).scalar_one()
                if not terminated:
                    raise RuntimeError("PostgreSQL refused to terminate the test listener")
        elif command == "cleanup":
            session.rollback()
            session.execute(
                delete(OrchestrationRunModel).where(OrchestrationRunModel.id == run_id)
            )
            session.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
            session.execute(
                delete(AuthSessionModel).where(
                    AuthSessionModel.operator_email == f"{project_id}@example.test"
                )
            )
            session.execute(
                delete(AuthorizedOperatorModel).where(
                    AuthorizedOperatorModel.email == f"{project_id}@example.test"
                )
            )
            session.commit()
        else:
            raise ValueError(f"Unknown fixture command: {command}")
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
