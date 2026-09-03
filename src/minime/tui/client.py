"""TUI read-model query client for mini me console."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

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

    async def get_available_actions(self, run_id: str) -> list[Any]:
        """Discover available operator actions for a run asynchronously."""
        return await asyncio.to_thread(self._sync_get_available_actions, run_id)

    def _sync_get_available_actions(self, run_id: str) -> list[Any]:
        from minime.services.control_plane_service import ControlPlaneService

        try:
            uow = self._get_uow()
            try:
                service = ControlPlaneService(uow)
                return service.get_available_actions(run_id)
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.warning(f"Error discovering actions for run {run_id}: {exc}")
            return []

    async def execute_action(self, request: Any) -> Any:
        """Execute a governed operator action asynchronously."""
        return await asyncio.to_thread(self._sync_execute_action, request)

    def _sync_execute_action(self, request: Any) -> Any:
        from minime.services.control_plane_service import ControlPlaneService

        try:
            uow = self._get_uow()
            try:
                service = ControlPlaneService(uow)
                return service.execute_action(request)
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.error(f"Error executing action via TUI client: {exc}")
            from minime.domain.enums import OperatorActionErrorCode, OperatorActionStatus
            from minime.domain.models import OperatorActionResult

            return OperatorActionResult(
                action_request_id=getattr(request, "action_request_id", "unknown"),
                action_type=getattr(request, "action_type", "UNKNOWN"),
                status=OperatorActionStatus.FAILED,
                error_code=OperatorActionErrorCode.ACTION_EXECUTION_FAILED,
                summary=f"TUI client execution error: {exc}",
            )

    async def get_action_history(self, run_id: str, limit: int = 50) -> list[Any]:
        """Fetch operator action audit trail asynchronously."""
        return await asyncio.to_thread(self._sync_get_action_history, run_id, limit)

    def _sync_get_action_history(self, run_id: str, limit: int = 50) -> list[Any]:
        from minime.services.control_plane_service import ControlPlaneService

        try:
            uow = self._get_uow()
            try:
                service = ControlPlaneService(uow)
                return service.list_action_history(run_id, limit=limit)
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.warning(f"Error fetching action history for run {run_id}: {exc}")
            return []

    async def get_latest_run_id_for_change(self, project_id: str, change_name: str) -> str | None:
        """Find the latest run ID for a project and change."""
        return await asyncio.to_thread(self._sync_get_latest_run_id, project_id, change_name)

    def _sync_get_latest_run_id(self, project_id: str, change_name: str) -> str | None:
        try:
            uow = self._get_uow()
            try:
                runs = uow.orchestration_runs.list_runs(
                    project_id=project_id, change_name=change_name
                )
                return runs[0].run_id if runs else None
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.warning(f"Error finding latest run for {project_id}/{change_name}: {exc}")
            return None

    async def get_queue_items(
        self, project_id: str | None = None, ready_only: bool = False
    ) -> list[Any]:
        """Fetch ranked queue items asynchronously."""
        return await asyncio.to_thread(self._sync_get_queue_items, project_id, ready_only)

    def _sync_get_queue_items(
        self, project_id: str | None = None, ready_only: bool = False
    ) -> list[Any]:
        from minime.services.scheduler_service import SchedulerService

        try:
            uow = self._get_uow()
            try:
                scheduler = SchedulerService(uow)
                if ready_only:
                    items = uow.work_queue.list_ready(project_id)
                else:
                    items = uow.work_queue.list_all(project_id)
                return scheduler.rank_candidates(items)
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.warning(f"Error fetching queue items for TUI: {exc}")
            return []

    async def get_queue_explain(self, project_id: str, change_name: str) -> Any | None:
        """Fetch explainability report for a queue item asynchronously."""
        return await asyncio.to_thread(self._sync_get_queue_explain, project_id, change_name)

    def _sync_get_queue_explain(self, project_id: str, change_name: str) -> Any | None:
        from minime.services.scheduler_service import SchedulerService

        try:
            uow = self._get_uow()
            try:
                scheduler = SchedulerService(uow)
                return scheduler.explain_item_priority(project_id, change_name)
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.warning(f"Error fetching explain report for {change_name}: {exc}")
            return None

    async def get_scheduler_status(self, project_id: str | None = None) -> Any | None:
        """Fetch scheduler operational status view asynchronously."""
        return await asyncio.to_thread(self._sync_get_scheduler_status, project_id)

    def _sync_get_scheduler_status(self, project_id: str | None = None) -> Any | None:
        from minime.services.scheduler_service import SchedulerService

        try:
            uow = self._get_uow()
            try:
                scheduler = SchedulerService(uow)
                return scheduler.get_status(project_id)
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.warning(f"Error fetching scheduler status for TUI: {exc}")
            return None

    async def trigger_scheduler_tick(self, project_id: str | None = None) -> list[Any]:
        """Trigger a scheduler tick asynchronously."""
        return await asyncio.to_thread(self._sync_trigger_scheduler_tick, project_id)

    def _sync_trigger_scheduler_tick(self, project_id: str | None = None) -> list[Any]:
        from minime.services.scheduler_service import SchedulerService

        try:
            uow = self._get_uow()
            try:
                scheduler = SchedulerService(uow)
                return scheduler.tick(project_id)
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.error(f"Error triggering scheduler tick for TUI: {exc}")
            return []

    async def get_efficiency_telemetry(self, project_id: str, change_name: str) -> Any | None:
        """Fetch efficiency telemetry for a change asynchronously."""
        return await asyncio.to_thread(self._sync_get_efficiency_telemetry, project_id, change_name)

    def _sync_get_efficiency_telemetry(self, project_id: str, change_name: str) -> Any | None:
        try:
            uow = self._get_uow()
            try:
                service = OperationsDashboardService(uow)
                return service.get_efficiency_telemetry(project_id, change_name)
            finally:
                if hasattr(uow, "session") and hasattr(uow.session, "close"):
                    uow.session.close()
        except Exception as exc:
            logger.warning(f"Error fetching efficiency telemetry for {change_name}: {exc}")
            return None
