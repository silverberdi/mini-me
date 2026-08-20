"""Command line interface for mini me."""

from __future__ import annotations

import json

import typer
import uvicorn

from minime.adapters.openspec import OpenSpecAdapter
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.logging import configure_logging, get_logger
from minime.services.project_service import ProjectService
from minime.services.readiness_service import ReadinessService
from minime.services.status_service import StatusService

app = typer.Typer(
    name="minime",
    help="mini me — personal orchestration system for spec-driven development.",
    add_completion=False,
)
project_app = typer.Typer(help="Manage registered projects.")
app.add_typer(project_app, name="project")

logger = get_logger("cli")


@app.callback()
def main_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose log output"),
    json_logs: bool = typer.Option(False, "--json-logs", help="Output logs in JSON format"),
) -> None:
    """Global configuration callback."""
    log_level = 10 if verbose else 20  # DEBUG vs INFO
    configure_logging(level=log_level, json_output=json_logs)


@app.command("status")
def status_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output status as JSON"),
) -> None:
    """Show operational system status, database health, and registered projects."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = StatusService(uow)
            status_data = service.get_system_status()

            if json_output:
                typer.echo(json.dumps(status_data, indent=2))
                return

            typer.secho("=== mini me Operational Status ===", fg=typer.colors.CYAN, bold=True)
            db_status = status_data["database"]
            if db_status["healthy"]:
                typer.secho(f"Database: {db_status['message']}", fg=typer.colors.GREEN)
            else:
                typer.secho(f"Database: {db_status['message']}", fg=typer.colors.RED)

            typer.echo(f"\nRegistered Projects: {status_data['projects_count']}")
            for p in status_data["projects"]:
                typer.echo(
                    f"  • {p['project_id']} ({p['display_name']}) -> {p['repository']} [{p['status']}]"
                )
                if p["changes"]:
                    typer.echo("    Changes:")
                    for c in p["changes"]:
                        readiness_color = (
                            typer.colors.GREEN if c["readiness"] == "READY" else typer.colors.YELLOW
                        )
                        typer.secho(
                            f"      - {c['name']} [{c['status']}] -> Readiness: {c['readiness']}",
                            fg=readiness_color,
                        )
                        if c["unmet_reasons"]:
                            for r in c["unmet_reasons"]:
                                typer.secho(f"        * {r}", fg=typer.colors.RED)
                else:
                    typer.echo("    (No changes discovered yet)")

    except Exception as e:
        typer.secho(f"Error fetching status: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@project_app.command("list")
def list_projects_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output projects as JSON"),
) -> None:
    """List all registered projects."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = ProjectService(uow)
            projects = service.list_projects()

            if json_output:
                typer.echo(json.dumps([p.model_dump() for p in projects], indent=2, default=str))
                return

            if not projects:
                typer.echo("No registered projects found.")
                return

            typer.secho("=== Registered Projects ===", fg=typer.colors.CYAN, bold=True)
            for p in projects:
                typer.echo(
                    f"ID: {p.project_id}\n"
                    f"  Name: {p.display_name}\n"
                    f"  Repository: {p.repository}\n"
                    f"  Base Branch: {p.base_branch}\n"
                    f"  OpenSpec Path: {p.openspec_path}\n"
                    f"  Roles: Implementer={p.implementer}, Reviewer={p.reviewer}\n"
                    f"  Status: {p.status.value}\n"
                )
    except Exception as e:
        typer.secho(f"Error listing projects: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@project_app.command("register")
def register_project_cmd(
    project_id: str = typer.Argument(..., help="Immutable project identifier (e.g. mini-me)"),
    display_name: str = typer.Argument(..., help="Human-readable project display name"),
    repository: str = typer.Argument(
        ..., help="Canonical repository identity (owner/repo or path)"
    ),
    base_branch: str = typer.Option("main", "--base-branch", help="Target base branch"),
    openspec_path: str = typer.Option("openspec", "--openspec-path", help="Path to OpenSpec root"),
    implementer: str = typer.Option("codex", "--implementer", help="Primary implementer agent"),
    reviewer: str = typer.Option("antigravity", "--reviewer", help="Complementary reviewer agent"),
) -> None:
    """Register a new project with immutable project_id and complementary roles."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = ProjectService(uow)
            project = service.register_project(
                project_id=project_id,
                display_name=display_name,
                repository=repository,
                base_branch=base_branch,
                openspec_path=openspec_path,
                implementer=implementer,
                reviewer=reviewer,
            )
            typer.secho(
                f"Successfully registered project '{project.project_id}' for repo '{project.repository}'",
                fg=typer.colors.GREEN,
            )
    except Exception as e:
        typer.secho(f"Registration failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command("discover")
def discover_cmd(
    project_id: str = typer.Argument(..., help="Project identifier"),
    project_root: str = typer.Option(".", "--path", "-p", help="Filesystem path to project root"),
) -> None:
    """Discover OpenSpec changes in project root and persist them."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            project_service = ProjectService(uow)
            project = project_service.get_project(project_id)
            if not project:
                typer.secho(f"Project '{project_id}' not found.", fg=typer.colors.RED)
                raise typer.Exit(code=1)

            adapter = OpenSpecAdapter()
            changes = adapter.discover_changes(project, project_root)
            for c in changes:
                uow.changes.save(c)
            uow.commit()

            typer.secho(
                f"Discovered {len(changes)} active change(s) for project '{project_id}':",
                fg=typer.colors.GREEN,
            )
            for c in changes:
                typer.echo(f"  • {c.name} (schema: {c.schema_name})")
    except Exception as e:
        typer.secho(f"Discovery error: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command("readiness")
def readiness_cmd(
    project_id: str = typer.Argument(..., help="Project identifier"),
    change_name: str = typer.Argument(..., help="OpenSpec change name"),
    project_root: str = typer.Option(".", "--path", "-p", help="Filesystem path to project root"),
    current_active_change: str | None = typer.Option(
        None, "--active-change", help="Designated active change for roadmap gating"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output readiness as JSON"),
) -> None:
    """Evaluate Definition of Ready (DoR) for an OpenSpec change."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = ReadinessService(uow)
            result = service.evaluate_change_readiness(
                project_id=project_id,
                change_name=change_name,
                project_root=project_root,
                current_active_change=current_active_change,
            )

            if json_output:
                typer.echo(json.dumps(result.model_dump(), indent=2, default=str))
                return

            status_color = typer.colors.GREEN if result.is_ready else typer.colors.RED
            typer.secho(
                f"\n=== Readiness Evaluation for '{change_name}' in '{project_id}' ===",
                fg=typer.colors.CYAN,
                bold=True,
            )
            typer.secho(f"Status: {result.status.value}", fg=status_color, bold=True)

            typer.echo("\nChecks:")
            for check in result.checks:
                c_color = typer.colors.GREEN if check.passed else typer.colors.RED
                symbol = "✓" if check.passed else "✗"
                typer.secho(f"  {symbol} {check.name}", fg=c_color)
                if check.reason:
                    typer.secho(f"      Reason: {check.reason}", fg=typer.colors.YELLOW)

            if result.unmet_reasons:
                typer.secho("\nUnmet Reasons:", fg=typer.colors.RED, bold=True)
                for reason in result.unmet_reasons:
                    typer.secho(f"  - {reason}", fg=typer.colors.RED)
            else:
                typer.secho("\nAll Definition of Ready criteria met!", fg=typer.colors.GREEN)

    except Exception as e:
        typer.secho(f"Readiness check failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8787, "--port", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
) -> None:
    """Start the mini me FastAPI daemon."""
    uvicorn.run("minime.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
