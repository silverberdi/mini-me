"""Deterministic database seeder for Playwright browser E2E test suite."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from minime.db.models import (
    AuthorizedOperatorModel,
    AuthSessionModel,
    ProjectModel,
    ProviderModelRegistryModel,
)
from minime.db.session import db_manager

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed_e2e_data")

E2E_OPERATOR_EMAIL = "e2e-operator@minime.local"
E2E_SESSION_TOKEN = "e2e-session-token-32-chars-long-xxx"
E2E_TOKEN_HASH = hashlib.sha256(E2E_SESSION_TOKEN.encode("utf-8")).hexdigest()


def seed_e2e_state() -> None:
    now = datetime.now(UTC)
    expires = now + timedelta(days=30)

    with db_manager.sessionmaker() as session:
        # 1. Seed Authorized Operator
        operator = session.execute(
            select(AuthorizedOperatorModel).where(
                AuthorizedOperatorModel.email == E2E_OPERATOR_EMAIL
            )
        ).scalar_one_or_none()

        if operator is None:
            logger.info("Creating E2E authorized operator...")
            operator = AuthorizedOperatorModel(
                id="e2e-operator-id",
                email=E2E_OPERATOR_EMAIL,
                display_name="E2E Operator",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(operator)
        else:
            operator.is_active = True
            operator.updated_at = now

        # 2. Seed Auth Session
        auth_session = session.execute(
            select(AuthSessionModel).where(
                AuthSessionModel.session_token_hash == E2E_TOKEN_HASH
            )
        ).scalar_one_or_none()

        if auth_session is None:
            logger.info("Creating E2E authenticated session...")
            auth_session = AuthSessionModel(
                id="e2e-session-id",
                session_token_hash=E2E_TOKEN_HASH,
                operator_email=E2E_OPERATOR_EMAIL,
                created_at=now,
                expires_at=expires,
                last_seen_at=now,
            )
            session.add(auth_session)
        else:
            auth_session.expires_at = expires
            auth_session.revoked_at = None
            auth_session.last_seen_at = now

        # 3. Seed or reset E2E project
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
                created_at=now,
                updated_at=now,
            )
            session.add(project)
        else:
            logger.info("Resetting e2e-project to active state...")
            project.status = "ACTIVE"
            project.execution_policy = {"effective_pause": False}
            project.agent_profiles = profiles
            project.updated_at = now

        # 4. Ensure deepseek-chat provider model is active and enabled
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
                created_at=now,
                updated_at=now,
            )
            session.add(model)
        else:
            logger.info("Resetting static-deepseek-chat to enabled state...")
            model.is_enabled = True
            model.discovery_status = "available"
            model.updated_at = now

        session.commit()
        logger.info("E2E database seeding completed successfully.")


if __name__ == "__main__":
    seed_e2e_state()
