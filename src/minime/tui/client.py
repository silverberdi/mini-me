"""TUI read-model query client for mini me console."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.logging import redact_secrets
from minime.services.dashboard_service import (
    DashboardChangeDetailResponse,
    DashboardOverviewResponse,
    OperationsDashboardService,
    SystemStatusDTO,
)

logger = logging.getLogger(__name__)


class TuiQueryClient:
    """Async query client providing safe, secret-redacted operational read models for the TUI."""

    def __init__(
        self,
        uow_factory: Callable[[], PersistenceUnitOfWork] | None = None,
    ) -> None:
        self._uow_factory = uow_factory

    def _get_uow(self) -> PersistenceUnitOfWork:
        if self._uow_factory is not None:
            return self._uow_factory()
        # Default: PostgresPersistenceUnitOfWork from db_manager
        session = db_manager.sessionmaker()
        return PostgresPersistenceUnitOfWork(session)

    async def get_overview(self) -> DashboardOverviewResponse:
        """Fetch high-level operational overview asynchronously without blocking UI loop."""
        return await asyncio.to_thread(self._sync_get_overview)

    def _sync_get_overview(self) -> DashboardOverviewResponse:
        try:
            uow = self._get_uow()
            try:
                service = OperationsDashboardService(uow)
                return service.get_overview()
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.warning(f"Error fetching dashboard overview for TUI: {exc}")
            # Degraded / Disconnected state response
            err_msg = redact_secrets(str(exc))
            return DashboardOverviewResponse(
                system_status=SystemStatusDTO(
                    healthy=False,
                    database_engine="PostgreSQL",
                    database_healthy=False,
                    database_message=f"Database unreachable: {err_msg}",
                    scheduler_mode="WAIT",
                    queue_depth=0,
                    github_app_health="UNKNOWN",
                    active_runs_count=0,
                    total_changes_count=0,
                    attention_runs_count=0,
                    providers=[],
                ),
                attention_items=[],
                active_executions=[],
                recent_completions=[],
                changes=[],
            )

    async def get_change_detail(
        self, project_id: str, change_name: str
    ) -> DashboardChangeDetailResponse | None:
        """Fetch detail response for a specific change asynchronously."""
        return await asyncio.to_thread(self._sync_get_change_detail, project_id, change_name)

    def _sync_get_change_detail(
        self, project_id: str, change_name: str
    ) -> DashboardChangeDetailResponse | None:
        try:
            uow = self._get_uow()
            try:
                service = OperationsDashboardService(uow)
                return service.get_change_detail(project_id, change_name)
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.warning(f"Error fetching detail for {project_id}/{change_name}: {exc}")
            return None
