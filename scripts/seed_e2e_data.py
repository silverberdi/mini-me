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
    OrchestrationRunModel,
    ProjectManagedRepositoryBindingModel,
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

        # 3.b Ensure managed repository binding exists for e2e-project
        os.makedirs("/tmp/e2e-project-repo", exist_ok=True)
        os.makedirs("/tmp/e2e-project-worktrees", exist_ok=True)
        binding = session.execute(
            select(ProjectManagedRepositoryBindingModel).where(
                ProjectManagedRepositoryBindingModel.project_id == "e2e-project"
            )
        ).scalar_one_or_none()
        if binding is None:
            logger.info("Creating e2e-project repository binding...")
            binding = ProjectManagedRepositoryBindingModel(
                id="e2e-project-binding",
                project_id="e2e-project",
                canonical_repository_identity="github.com/test-owner/e2e-project",
                remote_name="origin",
                managed_repository_root="/tmp/e2e-project-repo",
                worktree_parent_dir="/tmp/e2e-project-worktrees",
                default_base_branch="main",
                ownership_marker_filename=".minime-managed-project.json",
                is_valid=True,
                mismatch_reasons=[],
                created_at=now,
                updated_at=now,
            )
            session.add(binding)
        else:
            logger.info("Resetting e2e-project repository binding...")
            binding.managed_repository_root = "/tmp/e2e-project-repo"
            binding.worktree_parent_dir = "/tmp/e2e-project-worktrees"
            binding.is_valid = True
            binding.updated_at = now

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

        # 5. Ensure an active OrchestrationRun with HUMAN_REQUIRED exists for human-gate E2E test
        e2e_run = session.execute(
            select(OrchestrationRunModel).where(
                OrchestrationRunModel.id == "e2e-human-gate-run"
            )
        ).scalar_one_or_none()

        human_payload = {
            "gate": "explore_clarification",
            "stage": "EXPLORING",
            "question": "¿Desea persistir los datos en PostgreSQL o en memoria local?",
            "options": [
                {"id": "postgres", "label": "PostgreSQL"},
                {"id": "memory", "label": "Memoria local"},
            ],
            "explanation_es": "El agente en etapa Explore requiere aclarar la estrategia de persistencia.",
        }

        if e2e_run is None:
            logger.info("Creating e2e-human-gate-run in database...")
            e2e_run = OrchestrationRunModel(
                id="e2e-human-gate-run",
                project_id="e2e-project",
                change_name="issue-321-human-gate-test",
                base_sha="0274272890abcdef1234567890abcdef12345678",
                current_stage="EXPLORING",
                resumable_stage="EXPLORING",
                stop_outcome="NEEDS_HUMAN",
                human_gate="NEEDS_HUMAN",
                stop_reason="Clarification required",
                stop_details={"human_payload": human_payload},
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(e2e_run)
        else:
            logger.info("Resetting e2e-human-gate-run to initial HUMAN_REQUIRED state...")
            e2e_run.current_stage = "EXPLORING"
            e2e_run.resumable_stage = "EXPLORING"
            e2e_run.stop_outcome = "NEEDS_HUMAN"
            e2e_run.human_gate = "NEEDS_HUMAN"
            e2e_run.stop_details = {"human_payload": human_payload}
            e2e_run.is_active = True
            e2e_run.updated_at = now

        session.commit()
        logger.info("E2E database seeding completed successfully.")


if __name__ == "__main__":
    seed_e2e_state()
