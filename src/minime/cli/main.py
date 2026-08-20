"""Command line interface for mini me."""

from __future__ import annotations

import asyncio
import json

import typer
import uvicorn

from minime.adapters.openspec import OpenSpecAdapter
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.enums import ReviewVerdict
from minime.logging import configure_logging, get_logger
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.project_service import ProjectService
from minime.services.readiness_service import ReadinessService
from minime.services.status_service import StatusService

app = typer.Typer(
    name="minime",
    help="mini me — personal orchestration system for spec-driven development.",
    add_completion=False,
)
project_app = typer.Typer(help="Manage registered projects.")
jobs_app = typer.Typer(help="Inspect execution jobs.")
app.add_typer(project_app, name="project")
app.add_typer(jobs_app, name="jobs")

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


@app.command("run")
def run_cmd(
    project_id: str = typer.Argument(..., help="Project identifier"),
    change_name: str = typer.Argument(..., help="OpenSpec change name"),
    project_root: str = typer.Option(".", "--path", "-p", help="Filesystem path to project root"),
) -> None:
    """Run a READY OpenSpec implementation job and stream final status."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = ExecutionPipelineService(uow, project_root=project_root)
            job = asyncio.run(service.run_job(project_id, change_name))
            typer.echo(f"Job: {job.job_id}")
            typer.echo(f"Status: {job.status.value}")
            if job.candidate_sha:
                typer.echo(f"Candidate SHA: {job.candidate_sha}")
            if job.error_message:
                typer.echo(f"Error: {job.error_message}")
    except Exception as e:
        typer.secho(f"Run failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@jobs_app.command("list")
def jobs_list_cmd(
    project_id: str = typer.Argument(..., help="Project identifier"),
    json_output: bool = typer.Option(False, "--json", help="Output jobs as JSON"),
) -> None:
    """List execution jobs for a project."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            jobs = uow.jobs.list_by_project(project_id)
            if json_output:
                typer.echo(json.dumps([j.model_dump() for j in jobs], indent=2, default=str))
                return
            if not jobs:
                typer.echo("No jobs found.")
                return
            for job in jobs:
                checks = uow.check_results.list_by_job(job.job_id)
                check_summary = ",".join(f"{c.check_name}:{c.exit_code}" for c in checks) or "-"
                review = uow.reviews.get_by_job_id(job.job_id)
                verdict_summary = f"verdict={review.verdict.value}" if review and review.verdict else f"review={review.status.value}" if review else ""
                typer.echo(
                    f"{job.job_id}  {job.change_name}  {job.status.value}  "
                    f"candidate={job.candidate_sha or '-'}  checks={check_summary}  {verdict_summary}".strip()
                )
    except Exception as e:
        typer.secho(f"Error listing jobs: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@jobs_app.command("show")
def jobs_show_cmd(
    job_id: str = typer.Argument(..., help="Execution job identifier"),
    logs: bool = typer.Option(False, "--logs", help="Include redacted job logs"),
    json_output: bool = typer.Option(False, "--json", help="Output job as JSON"),
) -> None:
    """Show execution job details."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            job = uow.jobs.get_by_id(job_id)
            if not job:
                typer.secho(f"Job '{job_id}' not found.", fg=typer.colors.RED)
                raise typer.Exit(code=1)
            check_results = uow.check_results.list_by_job(job_id)
            review = uow.reviews.get_by_job_id(job_id)
            findings = uow.review_findings.list_by_review(review.review_id) if review else []
            payload = {
                "job": job.model_dump(),
                "checks": [c.model_dump() for c in check_results],
                "review": review.model_dump() if review else None,
                "findings": [f.model_dump() for f in findings],
                "logs": [log.model_dump() for log in uow.job_logs.list_by_job(job_id)] if logs else [],
            }
            if json_output:
                typer.echo(json.dumps(payload, indent=2, default=str))
                return
            typer.echo(f"Job: {job.job_id}")
            typer.echo(f"Project: {job.project_id}")
            typer.echo(f"Change: {job.change_name}")
            typer.echo(f"Status: {job.status.value}")
            typer.echo(f"Implementer: {job.implementer_role}")
            typer.echo(f"Base SHA: {job.base_sha or '-'}")
            typer.echo(f"Candidate SHA: {job.candidate_sha or '-'}")
            if job.error_message:
                typer.echo(f"Error: {job.error_message}")
            if check_results:
                typer.echo("Checks:")
                for check in check_results:
                    typer.echo(f"  {check.check_name}: exit={check.exit_code} ({check.duration_ms}ms)")
            if review:
                typer.echo("Review:")
                typer.echo(f"  Reviewer: {review.reviewer_role}")
                typer.echo(f"  Status: {review.status.value}")
                if review.verdict:
                    typer.echo(f"  Verdict: {review.verdict.value}")
                if review.summary:
                    typer.echo(f"  Summary: {review.summary}")
                if findings:
                    typer.echo(f"  Findings: {len(findings)} finding(s)")
            if logs:
                typer.echo("Logs:")
                for log in payload["logs"]:
                    typer.echo(f"  [{log['stream']}] {log['message']}")
    except Exception as e:
        typer.secho(f"Error showing job: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@jobs_app.command("review")
def jobs_review_cmd(
    job_id: str = typer.Argument(..., help="Execution job identifier"),
    json_output: bool = typer.Option(False, "--json", help="Output review details as JSON"),
) -> None:
    """Show complementary review details and findings for an execution job."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            review = uow.reviews.get_by_job_id(job_id)
            if not review:
                typer.secho(f"No review found for job '{job_id}'.", fg=typer.colors.RED)
                raise typer.Exit(code=1)
            findings = uow.review_findings.list_by_review(review.review_id)
            payload = {
                "review": review.model_dump(),
                "findings": [f.model_dump() for f in findings],
            }
            if json_output:
                typer.echo(json.dumps(payload, indent=2, default=str))
                return

            typer.echo(f"Review ID: {review.review_id}")
            typer.echo(f"Job ID: {review.job_id}")
            typer.echo(f"Project: {review.project_id}")
            typer.echo(f"Change: {review.change_name}")
            typer.echo(f"Reviewer: {review.reviewer_role}")
            typer.echo(f"Status: {review.status.value}")
            verdict_str = review.verdict.value if review.verdict else "None"
            v_color = (
                typer.colors.GREEN
                if review.verdict == ReviewVerdict.READY_TO_MERGE
                else typer.colors.RED
            )
            typer.secho(f"Verdict: {verdict_str}", fg=v_color, bold=True)
            if review.summary:
                typer.echo(f"Summary: {review.summary}")
            if review.error_message:
                typer.secho(f"Error: {review.error_message}", fg=typer.colors.RED)
            typer.echo(f"Candidate SHA: {review.candidate_sha}")
            typer.echo(f"Base SHA: {review.base_sha}")

            if findings:
                typer.secho(f"\nFindings ({len(findings)}):", fg=typer.colors.YELLOW, bold=True)
                for f in findings:
                    sev_color = (
                        typer.colors.RED
                        if f.severity == "BLOCKER" or f.severity.value == "BLOCKER"
                        else typer.colors.YELLOW
                    )
                    typer.secho(f"  • [{f.severity.value}] {f.location or 'general'}", fg=sev_color, bold=True)
                    typer.echo(f"    Violated: {f.violated_requirement}")
                    typer.echo(f"    Correction: {f.expected_correction}")
            else:
                typer.echo("\nNo findings recorded.")
    except Exception as e:
        typer.secho(f"Error showing review: {e}", fg=typer.colors.RED)
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
