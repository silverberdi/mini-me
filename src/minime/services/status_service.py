"""Status and observability service for mini me."""

from __future__ import annotations

from typing import Any

from minime.db.session import db_manager
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.logging import get_logger

logger = get_logger("services.status")


class StatusService:
    """Service providing aggregate status and health across persistence and projects."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def get_system_status(self) -> dict[str, Any]:
        """Aggregate operational system status."""
        db_healthy, db_message = db_manager.check_health()
        projects = self.uow.projects.list_all()

        project_summaries: list[dict[str, Any]] = []
        for proj in projects:
            changes = self.uow.changes.list_by_project(proj.project_id)
            project_summaries.append(
                {
                    "project_id": proj.project_id,
                    "display_name": proj.display_name,
                    "repository": proj.repository,
                    "base_branch": proj.base_branch,
                    "status": proj.status.value,
                    "changes_count": len(changes),
                    "changes": [
                        {
                            "name": c.name,
                            "status": c.status.value,
                            "readiness": c.last_readiness_status.value,
                            "unmet_reasons": c.last_readiness_reasons,
                        }
                        for c in changes
                    ],
                }
            )

        recent_events = self.uow.events.list_events(limit=10)

        return {
            "status": "healthy" if db_healthy else "degraded",
            "database": {
                "engine": "PostgreSQL",
                "healthy": db_healthy,
                "message": db_message,
            },
            "projects_count": len(projects),
            "projects": project_summaries,
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
