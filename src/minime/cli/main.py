"""Small operator CLI retained after F1 legacy retirement."""

from __future__ import annotations

import asyncio
import json
from typing import NoReturn

import typer
import uvicorn

from minime.config import discover_and_load_env_file, load_config
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.models import ProjectConfigurationInput, ProjectConfigurationPatch
from minime.logging import configure_logging
from minime.services.budget_service import BudgetService
from minime.services.context_discovery_service import ContextDiscoveryService
from minime.services.greenfield_bootstrap import GreenfieldBootstrapCoordinator
from minime.services.legacy_unavailable import unavailable_payload
from minime.services.project_catalog_service import ProjectCatalogService
from minime.services.project_connection_service import ProjectConnectionService
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
project_catalog_app = typer.Typer(help="Read-only provider and agent capability catalogs.")
scheduler_app = typer.Typer(help="Retired in F1; F3 owns its replacement.")
queue_app = typer.Typer(help="Retired in F1; F3 owns its replacement.")
orchestrate_app = typer.Typer(help="Retired in F1; F3 owns its replacement.")
action_app = typer.Typer(help="Retired in F1; F3 owns its replacement.")
providers_app = typer.Typer(help="Read-only provider diagnostics.")
budget_app = typer.Typer(help="Read-only budget diagnostics.")
app.add_typer(project_app, name="project")
project_app.add_typer(project_catalog_app, name="catalog")
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
        typer.echo(
            json.dumps(
                [ProjectService.public_project_payload(project) for project in projects],
                indent=2,
                default=str,
            )
        )
        return
    for project in projects:
        typer.echo(f"{project.project_id} {project.repository} [{project.status.value}]")


@project_catalog_app.command("providers")
def list_project_provider_catalog() -> None:
    """Show provider metadata without project connections or credential values."""
    catalog = ProjectCatalogService().provider_catalog()
    typer.echo(json.dumps(catalog, indent=2))


@project_catalog_app.command("agents")
def list_project_agent_catalog(
    project_id: str | None = typer.Option(None, "--project-id"),
) -> None:
    """Discover local capabilities, optionally checking a bound project workspace."""
    try:
        project_root = None
        if project_id:
            with db_manager.session() as session:
                service = ProjectService(PostgresPersistenceUnitOfWork(session))
                if service.get_project(project_id) is None:
                    raise ValueError(f"Project '{project_id}' not found")
                project_root = service.verified_managed_workspace_root(project_id)
                if project_root is None:
                    raise ValueError("Project managed workspace identity is unavailable or invalid")
        catalog = asyncio.run(ProjectCatalogService().agent_catalog(project_root))
    except Exception as exc:
        typer.echo(f"agent catalog unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(catalog, indent=2))


@project_app.command("create")
def create_project(config_path: str = typer.Argument(..., exists=True, readable=True)) -> None:
    """Create a Brownfield project from a non-secret JSON configuration file."""
    try:
        with open(config_path, encoding="utf-8") as stream:
            raw = json.load(stream)
        if "github_app_credentials" in raw:
            raise ValueError(
                "Do not put GitHub App credentials in the configuration file; enter them only at the hidden prompt"
            )
        if any(
            isinstance(value, dict) and value.get("auth_mode") == "project_app"
            for value in raw.get("provider_connections", {}).values()
        ):
            raw["github_app_credentials"] = {
                "app_id": typer.prompt("GitHub App ID"),
                "installation_id": typer.prompt("GitHub installation ID"),
                "private_key": typer.prompt("GitHub App private key", hide_input=True),
            }
        configuration = ProjectConfigurationInput.model_validate(raw)
        asyncio.run(
            ProjectCatalogService().validate_project_profiles(
                configuration.agent_profiles
            )
        )
        with db_manager.session() as session:
            project = ProjectService(PostgresPersistenceUnitOfWork(session)).create_configured_project(
                configuration
            )
    except Exception as exc:
        typer.echo(f"project creation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"created {project.project_id} [{project.onboarding_status.value}]")


@project_app.command("bootstrap")
def bootstrap_greenfield(
    config_path: str = typer.Argument(..., exists=True, readable=True),
    zip_path: str = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Bootstrap a Greenfield project from a ZIP through its first PR."""
    try:
        with open(config_path, encoding="utf-8") as stream:
            raw = json.load(stream)
        if "github_app_credentials" in raw:
            raise ValueError("Do not put GitHub App credentials in the configuration file")
        configuration = ProjectConfigurationInput.model_validate(raw)
        if configuration.project_type.value != "GREENFIELD":
            raise ValueError("project_type must be GREENFIELD")
        asyncio.run(ProjectCatalogService().validate_project_profiles(configuration.agent_profiles))
        with open(zip_path, "rb") as stream:
            archive = stream.read()
        with db_manager.session() as session:
            result = GreenfieldBootstrapCoordinator(
                PostgresPersistenceUnitOfWork(session),
                trusted_managed_root=load_config().paths.repos_root,
            ).bootstrap(configuration, archive)
    except Exception as exc:
        typer.echo(f"project bootstrap failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, indent=2, default=str))


@project_app.command("show")
def show_project(project_id: str = typer.Argument(...), json_output: bool = typer.Option(False, "--json")) -> None:
    try:
        with db_manager.session() as session:
            project = ProjectService(PostgresPersistenceUnitOfWork(session)).get_project(project_id)
    except Exception as exc:
        typer.echo(f"project lookup unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if project is None:
        typer.echo(f"project not found: {project_id}", err=True)
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(json.dumps(ProjectService.public_project_payload(project), indent=2, default=str))
    else:
        typer.echo(
            f"{project.project_id} {project.repository} "
            f"[{project.status.value}/{project.onboarding_status.value}]"
        )


@project_app.command("context")
def show_project_context(project_id: str = typer.Argument(...)) -> None:
    """Read context from the project's verified managed repository binding."""
    try:
        with db_manager.session() as session:
            report = ContextDiscoveryService(
                PostgresPersistenceUnitOfWork(session)
            ).discover_context_pure(project_id)
    except Exception as exc:
        typer.echo(f"project context unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(report.model_dump_json(indent=2))


@project_app.command("onboarding-status")
def onboarding_status(project_id: str = typer.Argument(...)) -> None:
    """Show sanitized, read-only project onboarding progress."""
    try:
        with db_manager.session() as session:
            service = ProjectService(PostgresPersistenceUnitOfWork(session))
            project = service.get_project(project_id)
            if project is None:
                raise ValueError("project not found")
            state = service.public_onboarding_state(project)
    except Exception as exc:
        typer.echo(f"project onboarding status unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(state, indent=2, default=str))


@project_app.command("add-context")
def add_project_context(
    project_id: str = typer.Argument(...),
    zip_path: str = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Publish incremental project context on a separate PR."""
    try:
        with open(zip_path, "rb") as stream:
            archive = stream.read()
        with db_manager.session() as session:
            result = GreenfieldBootstrapCoordinator(
                PostgresPersistenceUnitOfWork(session),
                trusted_managed_root=load_config().paths.repos_root,
            ).add_context(project_id, archive)
    except Exception as exc:
        typer.echo(f"project context update failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, indent=2, default=str))


@project_app.command("observe-bootstrap-merge")
def observe_bootstrap_merge(project_id: str = typer.Argument(...)) -> None:
    """Read the recorded Greenfield PR and update status only on exact merge proof."""
    try:
        with db_manager.session() as session:
            result = ProjectService(
                PostgresPersistenceUnitOfWork(session)
            ).observe_bootstrap_merge(project_id)
    except Exception as exc:
        typer.echo(f"bootstrap merge observation unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, indent=2, default=str))
    if result.get("observed") is False:
        raise typer.Exit(code=2)


@project_app.command("update")
def update_project(
    project_id: str = typer.Argument(...),
    config_path: str = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Update mutable project settings from a non-secret JSON patch."""
    try:
        with open(config_path, encoding="utf-8") as stream:
            raw = json.load(stream)
        if "github_app_credentials" in raw:
            raise ValueError(
                "Do not put GitHub App credentials in the configuration file; enter them only at the hidden prompt"
            )
        if any(
            isinstance(value, dict) and value.get("auth_mode") == "project_app"
            for value in raw.get("provider_connections", {}).values()
        ):
            raw["github_app_credentials"] = {
                "app_id": typer.prompt("GitHub App ID"),
                "installation_id": typer.prompt("GitHub installation ID"),
                "private_key": typer.prompt("GitHub App private key", hide_input=True),
            }
        patch = ProjectConfigurationPatch.model_validate(raw)
        with db_manager.session() as session:
            service = ProjectService(PostgresPersistenceUnitOfWork(session))
            if patch.agent_profiles is not None:
                binding = service.uow.project_managed_repository_bindings.get_by_project_id(
                    project_id
                )
                workspace_root = service.verified_managed_workspace_root(project_id)
                if binding is not None and workspace_root is None:
                    raise ValueError(
                        "Project agent profiles cannot be changed while its managed workspace identity is invalid"
                    )
                asyncio.run(
                    ProjectCatalogService().validate_project_profiles(
                        patch.agent_profiles, project_root=workspace_root
                    )
                )
            project = service.update_configuration(project_id, patch)
    except Exception as exc:
        typer.echo(f"project update failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"updated {project.project_id} [{project.onboarding_status.value}]")


def _set_project_lifecycle(project_id: str, active: bool) -> None:
    try:
        with db_manager.session() as session:
            project = ProjectService(PostgresPersistenceUnitOfWork(session)).set_lifecycle(
                project_id, active=active
            )
    except Exception as exc:
        typer.echo(f"project lifecycle update failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"{project.project_id} [{project.status.value}]")


@project_app.command("pause")
def pause_project(project_id: str = typer.Argument(...)) -> None:
    _set_project_lifecycle(project_id, active=False)


@project_app.command("activate")
def activate_project(project_id: str = typer.Argument(...)) -> None:
    _set_project_lifecycle(project_id, active=True)


@project_app.command("verify-connections")
def verify_project_connections(project_id: str = typer.Argument(...)) -> None:
    """Read-only verify configured GitHub identities and App grants."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            project = uow.projects.get_by_id(project_id)
            if project is None:
                raise ValueError("project not found")
            connections = ProjectConnectionService().verify(project)
    except Exception as exc:
        typer.echo(f"connection verification unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps({"project_id": project_id, "connections": connections}, indent=2))
    if any(not result["verified"] for result in connections.values()):
        raise typer.Exit(code=2)


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
