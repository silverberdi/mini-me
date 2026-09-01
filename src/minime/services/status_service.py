"""Status and observability service for mini me."""

from __future__ import annotations

from typing import Any

from minime.adapters.github import GitHubAppAuth
from minime.db.session import db_manager
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.logging import get_logger

logger = get_logger("services.status")


class StatusService:
    """Service providing aggregate status and health across persistence and projects."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

        return {
            "status": "healthy" if db_healthy else "degraded",
            "database": {
                "engine": "PostgreSQL",
                "healthy": db_healthy,
                "message": db_message,
            },
            "projects_count": len(projects),
            "projects": project_summaries,
            "github_runtime": {
                "authentication_mode": github_auth.mode,
                "configured": github_configured,
                "health": "configured" if github_configured else "not_configured",
            },
            "recent_events": [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type.value,
                    "project_id": e.project_id,
                    "change_id": e.change_id,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in recent_events
            ],
        }
