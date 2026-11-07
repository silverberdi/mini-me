"""Deterministic database seeder for Playwright browser E2E test suite."""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from minime.db.models import ProjectModel, ProviderModelRegistryModel
from minime.db.session import db_manager

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed_e2e_data")


def seed_e2e_state() -> None:
    session_factory = db_manager.sessionmaker()
    with session_factory() as session:
        # 1. Seed or reset E2E project
        project = session.execute(
            select(ProjectModel).where(ProjectModel.id == "e2e-project")
        ).scalar_one_or_none()

        profiles = {
            role: {
                "agent_id": "opencode" if role in ("thinking", "execution") else "codex",
                "provider_id": "deepseek" if role == "thinking" else "codex",
                "harness_id": "opencode" if role in ("thinking", "execution") else "codex",
                "model_id": "deepseek/deepseek-flash" if role == "thinking" else "codex-v1",
                "effort": "medium",
            }
            for role in ("thinking", "execution", "independent_review", "fallback")
        }

        if project is None:
            logger.info("Creating e2e-project in database...")
            project = ProjectModel(
                id="e2e-project",
                display_name="E2E Test Project",
                repository="test-owner/e2e-project",
                project_type="BROWNFIELD",
                base_branch="main",
                provider_connections={"tickets": {}, "git_pr": {}},
                agent_profiles=profiles,
                execution_policy={"effective_pause": False},
                status="ACTIVE",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(project)
        else:
            logger.info("Resetting e2e-project to active state...")
            project.status = "ACTIVE"
            project.execution_policy = {"effective_pause": False}
            project.agent_profiles = profiles
            project.updated_at = datetime.now(UTC)

        # 2. Ensure deepseek-chat provider model is active and enabled
        model = session.execute(
            select(ProviderModelRegistryModel).where(
                ProviderModelRegistryModel.id == "static-deepseek-chat"
            )
        ).scalar_one_or_none()

        if model is None:
            logger.info("Creating static-deepseek-chat model in registry...")
            model = ProviderModelRegistryModel(
                id="static-deepseek-chat",
                provider_id="deepseek",
                harness_id="direct",
                canonical_model_id="deepseek-chat",
                origin="static",
                capabilities={"model_route": "direct", "thinking": True},
                discovery_status="available",
                diagnostic_code="ok",
                diagnostic_summary="Static compatibility metadata for E2E",
                is_enabled=True,
                version=1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(model)
        else:
            logger.info("Resetting static-deepseek-chat to enabled state...")
            model.is_enabled = True
            model.discovery_status = "available"
            model.updated_at = datetime.now(UTC)

        session.commit()
        logger.info("E2E database seeding completed successfully.")


if __name__ == "__main__":
    seed_e2e_state()
