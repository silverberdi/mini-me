"""Small operator CLI retained after F1 legacy retirement."""

from __future__ import annotations

import json
from typing import NoReturn

import typer
import uvicorn

from minime.config import discover_and_load_env_file
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.logging import configure_logging
from minime.services.budget_service import BudgetService
from minime.services.legacy_unavailable import unavailable_payload
from minime.services.project_service import ProjectService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.status_service import StatusService

discover_and_load_env_file()

app = typer.Typer(
    name="minime",
    help="mini me — configuration and read-only diagnostics.",
    add_completion=False,
)
project_app = typer.Typer(help="Manage retained project configuration.")
scheduler_app = typer.Typer(help="Retired in F1; F3 owns its replacement.")
queue_app = typer.Typer(help="Retired in F1; F3 owns its replacement.")
orchestrate_app = typer.Typer(help="Retired in F1; F3 owns its replacement.")
action_app = typer.Typer(help="Retired in F1; F3 owns its replacement.")
providers_app = typer.Typer(help="Read-only provider diagnostics.")
budget_app = typer.Typer(help="Read-only budget diagnostics.")
app.add_typer(project_app, name="project")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(queue_app, name="queue")
app.add_typer(orchestrate_app, name="orchestrate")
app.add_typer(action_app, name="action")
app.add_typer(providers_app, name="providers")
app.add_typer(budget_app, name="budget")


def _unavailable(operation: str, phase: str = "F3") -> NoReturn:
    typer.echo(json.dumps(unavailable_payload(operation, phase)))
    raise typer.Exit(code=2)


@app.callback()
def main_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    json_logs: bool = typer.Option(False, "--json-logs", help="Emit JSON logs"),
) -> None:
    """Configure only the retained local CLI process."""
    configure_logging(level=10 if verbose else 20, json_output=json_logs)


@app.command("status")
def status_cmd(json_output: bool = typer.Option(False, "--json")) -> None:
    """Show read-only database health and registered projects."""
    try:
        with db_manager.session() as session:
            data = StatusService(PostgresPersistenceUnitOfWork(session)).get_system_status()
    except Exception as exc:
        typer.echo(f"status unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(data, indent=2, default=str))
        return
    typer.echo(f"Database: {data['database']['message']}")
    typer.echo(f"Registered projects: {data['projects_count']}")


@project_app.command("list")
def list_projects(json_output: bool = typer.Option(False, "--json")) -> None:
    """List retained project configuration."""
    try:
        with db_manager.session() as session:
            projects = ProjectService(PostgresPersistenceUnitOfWork(session)).list_projects()
    except Exception as exc:
        typer.echo(f"project listing unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps([project.model_dump() for project in projects], indent=2, default=str))
        return
    for project in projects:
        typer.echo(f"{project.project_id} {project.repository} [{project.status.value}]")


@project_app.command("register")
def register_project(
    project_id: str = typer.Argument(...),
    display_name: str = typer.Argument(...),
    repository: str = typer.Argument(...),
    base_branch: str = typer.Option("main", "--base-branch"),
    openspec_path: str = typer.Option("openspec", "--openspec-path"),
    implementer: str = typer.Option("codex", "--implementer"),
    reviewer: str = typer.Option("antigravity", "--reviewer"),
) -> None:
    """Register configuration required for later F2/F3 work."""
    try:
        with db_manager.session() as session:
            project = ProjectService(PostgresPersistenceUnitOfWork(session)).register_project(
                project_id=project_id,
                display_name=display_name,
                repository=repository,
                base_branch=base_branch,
                openspec_path=openspec_path,
                implementer=implementer,
                reviewer=reviewer,
            )
    except Exception as exc:
        typer.echo(f"project registration failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"registered {project.project_id}")


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the retained FastAPI daemon; it never starts the scheduler."""
    uvicorn.run("minime.api.app:app", host=host, port=port)


@providers_app.command("health")
def providers_health_cmd(json_output: bool = typer.Option(False, "--json")) -> None:
    """Inspect persisted provider health without probing or dispatching."""
    try:
        with db_manager.session() as session:
            health = ProviderHealthService(
                PostgresPersistenceUnitOfWork(session)
            ).list_all_health_with_capacity()
    except Exception as exc:
        typer.echo(f"provider diagnostics unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(
            json.dumps(
                [
                    {"health": entry.model_dump(), "capacity": capacity.model_dump() if capacity else None}
                    for entry, capacity in health
                ],
                indent=2,
                default=str,
            )
        )
        return
    for entry, capacity in health:
        typer.echo(f"{entry.provider}: {entry.status.value}")
        if capacity and capacity.capacity_reset_at:
            typer.echo(f"  Expected Reset: {capacity.capacity_reset_at.isoformat()}")
        if capacity and capacity.retry_after_seconds is not None:
            typer.echo(f"  Retry After: {capacity.retry_after_seconds}s")


@providers_app.command("openrouter")
def providers_openrouter_cmd() -> NoReturn:
    _unavailable("legacy_openrouter_dashboard", "F6")


@budget_app.command("status")
def budget_status_cmd(project_id: str | None = typer.Option(None, "--project-id")) -> None:
    """Inspect retained budget records without reserving or spending."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            projects = uow.projects.list_all()
            resolved_project_id = project_id or (projects[0].project_id if projects else "")
            policy = uow.budget_policies.get_by_project_id(resolved_project_id) if resolved_project_id else None
            headroom = BudgetService(uow)._compute_headroom(resolved_project_id, policy) if policy else None
    except Exception as exc:
        typer.echo(f"budget diagnostics unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps({"project_id": resolved_project_id, "policy": policy.model_dump() if policy else None, "headroom": headroom.__dict__ if headroom else None}, default=str))


@app.command("run")
def run_legacy() -> NoReturn:
    _unavailable("legacy_execution")


@app.command("readiness")
def readiness_legacy() -> NoReturn:
    _unavailable("legacy_readiness", "F2")


@app.command("discover")
def discover_legacy() -> NoReturn:
    _unavailable("legacy_discovery", "F2")


@app.command("tui")
def tui_legacy() -> NoReturn:
    _unavailable("legacy_tui", "F5")


def _legacy_group_command(operation: str, phase: str = "F3"):
    def command(
        json_output: bool = typer.Option(False, "--json", help="Emit the unavailable result as JSON"),
    ) -> NoReturn:
        del json_output
        return _unavailable(operation, phase)

    return command


for _group, _operation, _commands in (
    (scheduler_app, "legacy_scheduler", ("status", "tick", "run")),
    (queue_app, "legacy_queue", ("list", "explain")),
    (orchestrate_app, "legacy_orchestration", ("start", "resume", "status", "list", "cancel", "retry", "reassign")),
    (action_app, "legacy_control_plane", ("list", "execute", "history")),
):
    for _command_name in _commands:
        _group.command(_command_name)(_legacy_group_command(_operation))


if __name__ == "__main__":
    app()
