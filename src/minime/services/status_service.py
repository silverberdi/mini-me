"""Status and observability service for mini me."""

from __future__ import annotations

from typing import Any

from minime.adapters.github import GitHubAppAuth
from minime.db.session import db_manager
from minime.domain.enums import ExternalActionStatus, ExternalActionType
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.logging import get_logger
from minime.services.efficiency_telemetry_service import EfficiencyTelemetryService

logger = get_logger("services.status")


class StatusService:
    """Service providing aggregate status and health across persistence and projects."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def get_self_hosting_diagnostic(self) -> dict[str, Any]:
        """Return static runtime capability facts for the self-hosting pilot."""
        return {
            "runtime_engine": "mini-me-runtime",
            "status": "SELF_HOSTING_READY",
            "autonomous_queue": True,
        }

    def get_efficiency_summary(self, project_id: str | None = None) -> dict[str, Any]:
        """Return project efficiency telemetry, defaulting to the primary active project."""
        if project_id is None:
            projects = self.uow.projects.list_all()
            project = next((p for p in projects if p.status.value == "ACTIVE"), None)
            if project is None:
                raise LookupError("No active registered project is available")
            project_id = project.project_id
        return EfficiencyTelemetryService(self.uow).get_project_efficiency_summary(project_id)

    def get_pipeline_diagnostic(self, run_id: str | None = None) -> dict[str, Any] | None:
        """Return a compact operational snapshot for an orchestration run."""
        if run_id:
            run = self.uow.orchestration_runs.get_by_id(run_id)
        else:
            runs = self.uow.orchestration_runs.list_runs()
            run = max(runs, key=lambda item: (item.updated_at, item.created_at), default=None)
        if run is None:
            return None

        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        candidate_sha = run.current_candidate_sha
        if candidate_sha is None:
            candidate = self.uow.orchestration_candidates.get_latest_for_run(run.run_id)
            candidate_sha = candidate.candidate_sha if candidate else None

        review = self.uow.reviews.get_by_job_id(job.job_id) if job else None
        audit = self.uow.audits.get_by_job_id(job.job_id) if job else None

        pr_url = None
        for action in reversed(self.uow.orchestration_external_actions.list_by_run(run.run_id)):
            if (
                action.action_type == ExternalActionType.PR_CREATE
                and action.status == ExternalActionStatus.COMPLETED
            ):
                pr_url = action.remote_identifier or action.result_payload.get("pr_url")
                if pr_url is None:
                    pr_url = action.result_payload.get("url")
                break

        return {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "change_name": run.change_name,
            "stage": run.current_stage.value,
            "candidate_sha": candidate_sha,
            "pr_url": pr_url,
            "review_verdict": review.verdict.value if review and review.verdict else None,
            "audit_risk": audit.risk.value if audit and audit.risk else None,
        }

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
        github_auth = GitHubAppAuth()
        github_configured = bool(
            github_auth.app_id and github_auth.installation_id and github_auth.private_key_path
        )

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
            "self_hosting": self.get_self_hosting_diagnostic(),
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
