"""Seed and remove the isolated structured Human Gate browser fixture."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import HumanGate, OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import (
    OrchestrationRun,
    Project,
    ProjectAgentProfile,
    ProjectManagedRepositoryBinding,
)

PROJECT_ID = "e2e-human-gate-project"
RUN_ID = "e2e-human-gate-run"


def _engine():
    database_url = os.environ.get("MINIME_TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("MINIME_TEST_DATABASE_URL is required")
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        database_name = str(connection.execute(text("SELECT current_database()")).scalar_one())
    if "test" not in database_name.lower():
        engine.dispose()
        raise RuntimeError("Refusing to seed a non-test database")
    return engine


def cleanup(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM operator_action_records WHERE project_id = :project_id"),
            {"project_id": PROJECT_ID},
        )
        connection.execute(
            text("DELETE FROM orchestration_runs WHERE id = :run_id"), {"run_id": RUN_ID}
        )
        connection.execute(
            text("DELETE FROM project_managed_repository_bindings WHERE project_id = :project_id"),
            {"project_id": PROJECT_ID},
        )
        connection.execute(
            text("DELETE FROM projects WHERE id = :project_id"), {"project_id": PROJECT_ID}
        )


def create(engine) -> None:
    cleanup(engine)
    with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(Project(
            project_id=PROJECT_ID,
            display_name="Structured Human Gate E2E",
            repository="test/structured-human-gate",
            agent_profiles={
                role: ProjectAgentProfile(
                    agent_id="codex",
                    model_id="gpt-5.6-luna",
                    effort="medium",
                ).model_dump()
                for role in ("thinking", "execution", "independent_review", "fallback")
            },
        ))
        uow.project_managed_repository_bindings.save(ProjectManagedRepositoryBinding(
            project_id=PROJECT_ID,
            canonical_repository_identity="github.com/test/structured-human-gate",
            managed_repository_root="/tmp/structured-human-gate-repository",
            worktree_parent_dir="/tmp/structured-human-gate-worktrees",
        ))
        run = OrchestrationRun(
            run_id=RUN_ID,
            project_id=PROJECT_ID,
            change_name="structured-human-gate-e2e",
            base_sha="a" * 40,
            current_stage=OrchestrationStage.PROPOSING,
            resumable_stage=OrchestrationStage.PROPOSING,
            human_gate=HumanGate.NEEDS_HUMAN,
            stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
            is_active=True,
            stop_details={
                "human_payload": {
                    "gate_id": f"{RUN_ID}-gate",
                    "gate": "proposal_feasibility",
                    "stage": OrchestrationStage.PROPOSING.value,
                    "question": "Choose CONTINUE_CANDIDATE or preserve the candidate.",
                    "question_es": "Elige cómo continuar con el candidato.",
                    "summary_es": "La propuesta está detenida hasta confirmar cómo continuar.",
                    "pending_items": ["Falta confirmar la validación del candidato"],
                    "options": [
                        {"id": "continue", "label": "Continue candidate", "response_text": "CONTINUE_CANDIDATE"},
                        {"id": "preserve", "label": "Preserve candidate", "response_text": "PRESERVE_CANDIDATE"},
                    ],
                    "options_es": ["Continuar con la validación", "Conservar el candidato"],
                    "option_explanations": [
                        {"consequence": "Reintenta la validación del candidato."},
                        {"consequence": "Mantiene el Run detenido para revisión."},
                    ],
                    "description": "The proposal needs an explicit operator decision.",
                    "diff": {"status": "NOT_APPLICABLE"},
                }
            },
        )
        uow.orchestration_runs.save(run)
        uow.commit()


def main(action: str) -> None:
    engine = _engine()
    try:
        if action == "create":
            create(engine)
        elif action == "cleanup":
            cleanup(engine)
        else:
            raise ValueError(f"Unknown fixture action: {action}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main(sys.argv[1])
