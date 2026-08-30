"""Command line interface for mini me."""

from __future__ import annotations

import asyncio
import json

import typer
import uvicorn

from minime.adapters.openspec import OpenSpecAdapter
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.enums import ProviderHealthStatus, ReviewVerdict, SchedulerMode
from minime.logging import configure_logging, get_logger
from minime.services.budget_service import BudgetService
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.orchestration_service import OrchestrationService
from minime.services.project_service import ProjectService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.readiness_service import ReadinessService
from minime.services.status_service import StatusService

app = typer.Typer(
    name="minime",
    help="mini me — personal orchestration system for spec-driven development.",
    add_completion=False,
)
project_app = typer.Typer(help="Manage registered projects.")
jobs_app = typer.Typer(help="Inspect execution jobs.")
scheduler_app = typer.Typer(help="Inspect scheduler capacity mode and admission status.")
providers_app = typer.Typer(help="Inspect primary provider health and capacity windows.")
budget_app = typer.Typer(help="Inspect OpenRouter budget usage and policy state.")
orchestrate_app = typer.Typer(help="Autonomous single-change orchestration commands.")

app.add_typer(project_app, name="project")
app.add_typer(jobs_app, name="jobs")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(providers_app, name="providers")
app.add_typer(budget_app, name="budget")
app.add_typer(orchestrate_app, name="orchestrate")

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
            verdict_summary = (
                f"verdict={review.verdict.value}"
                if review and review.verdict
                else f"review={review.status.value}"
                if review
                else ""
            )
            audit = uow.audits.get_by_job_id(job.job_id)
            audit_summary = (
                f"audit={audit.status.value}/risk={audit.risk.value if audit.risk else '-'}"
                if audit
                else ""
            )
            typer.echo(
                f"{job.job_id}  {job.change_name}  {job.status.value}  "
                f"candidate={job.candidate_sha or '-'}  checks={check_summary}  {verdict_summary}  {audit_summary}".strip()
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
            attempts = uow.job_attempts.list_by_job(job_id)
            handoffs = uow.job_handoffs.list_by_job(job_id)
            manifest = uow.candidate_manifests.get_latest_manifest(job_id)
            diagnostics = uow.evidence_diagnostics.list_by_job(job_id)

            payload = {
                "job": job.model_dump(),
                "attempts": [a.model_dump() for a in attempts],
                "handoffs": [h.model_dump() for h in handoffs],
                "manifest": manifest.model_dump() if manifest else None,
                "diagnostics": [d.model_dump() for d in diagnostics],
                "checks": [c.model_dump() for c in check_results],
                "review": review.model_dump() if review else None,
                "findings": [f.model_dump() for f in findings],
                "logs": [log.model_dump() for log in uow.job_logs.list_by_job(job_id)]
                if logs
                else [],
            }
            if json_output:
                typer.echo(json.dumps(payload, indent=2, default=str))
                return
            typer.echo(f"Job: {job.job_id}")
            typer.echo(f"Project: {job.project_id}")
            typer.echo(f"Change: {job.change_name}")
            typer.echo(f"Status: {job.status.value}")
            typer.echo(f"Implementer: {job.implementer_role}")
            typer.echo(f"Current Executor: {job.current_executor or job.implementer_role}")
            typer.echo(f"Attempt Count: {job.attempt_count}")
            typer.echo(f"Reassignments: {job.reassignment_count}")
            typer.echo(f"Mixed Authorship: {job.is_mixed_authorship}")
            if job.latest_outcome:
                typer.echo(f"Latest Outcome: {job.latest_outcome.value}")
            if job.latest_progress:
                typer.echo(f"Latest Progress: {job.latest_progress.value}")
            if job.continuation_decision:
                typer.echo(f"Continuation Decision: {job.continuation_decision.value}")
            if job.escalation_reason:
                typer.secho(
                    f"Escalation Reason: {job.escalation_reason}", fg=typer.colors.RED, bold=True
                )
            typer.echo(f"Base SHA: {job.base_sha or '-'}")
            typer.echo(f"Candidate SHA: {job.candidate_sha or '-'}")
            if manifest:
                typer.echo(
                    f"Manifest Hash: {manifest.manifest_hash} ({manifest.total_files_count} files)"
                )
            if job.error_message:
                typer.echo(f"Error: {job.error_message}")
            if attempts:
                typer.echo(f"Attempts ({len(attempts)}):")
                for att in attempts:
                    typer.echo(
                        f"  • Attempt #{att.attempt_number} [{att.executor_role}] -> Outcome: {att.normalized_outcome.value} ({att.duration_ms or 0}ms)"
                    )
            if check_results:
                typer.echo("Checks:")
                for check in check_results:
                    typer.echo(
                        f"  {check.check_name}: exit={check.exit_code} ({check.duration_ms}ms)"
                    )
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


@jobs_app.command("attempts")
def jobs_attempts_cmd(
    job_id: str = typer.Argument(..., help="Execution job identifier"),
    json_output: bool = typer.Option(False, "--json", help="Output attempts as JSON"),
) -> None:
    """Show execution attempts history for a job."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            job = uow.jobs.get_by_id(job_id)
            if not job:
                typer.secho(f"Job '{job_id}' not found.", fg=typer.colors.RED)
                raise typer.Exit(code=1)
            attempts = uow.job_attempts.list_by_job(job_id)
            if json_output:
                typer.echo(json.dumps([a.model_dump() for a in attempts], indent=2, default=str))
                return
            typer.secho(f"=== Attempts for Job {job_id} ===", fg=typer.colors.CYAN, bold=True)
            for a in attempts:
                typer.echo(
                    f"Attempt #{a.attempt_number}: Executor={a.executor_role} Model={a.model_identity} "
                    f"Outcome={a.normalized_outcome.value} Progress={a.progress_classification.value if a.progress_classification else '-'} "
                    f"Duration={a.duration_ms or 0}ms"
                )
                if a.corrective_prompt:
                    typer.echo(f"  Corrective Prompt: {a.corrective_prompt[:100]}...")
    except Exception as e:
        typer.secho(f"Error showing attempts: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@jobs_app.command("handoffs")
def jobs_handoffs_cmd(
    job_id: str = typer.Argument(..., help="Execution job identifier"),
    json_output: bool = typer.Option(False, "--json", help="Output handoffs as JSON"),
) -> None:
    """Show handoff records for reassigned attempts in a job."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            job = uow.jobs.get_by_id(job_id)
            if not job:
                typer.secho(f"Job '{job_id}' not found.", fg=typer.colors.RED)
                raise typer.Exit(code=1)
            handoffs = uow.job_handoffs.list_by_job(job_id)
            if json_output:
                typer.echo(json.dumps([h.model_dump() for h in handoffs], indent=2, default=str))
                return
            typer.secho(f"=== Handoffs for Job {job_id} ===", fg=typer.colors.CYAN, bold=True)
            for h in handoffs:
                consumed = f"Consumed by {h.consumed_by_attempt_id}" if h.is_consumed else "Pending"
                typer.echo(
                    f"Handoff {h.handoff_id}: From={h.from_executor} To={h.to_executor} [{consumed}]"
                )
    except Exception as e:
        typer.secho(f"Error showing handoffs: {e}", fg=typer.colors.RED)
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
                    typer.secho(
                        f"  • [{f.severity.value}] {f.location or 'general'}",
                        fg=sev_color,
                        bold=True,
                    )
                    typer.echo(f"    Violated: {f.violated_requirement}")
                    typer.echo(f"    Correction: {f.expected_correction}")
            else:
                typer.echo("\nNo findings recorded.")
    except Exception as e:
        typer.secho(f"Error showing review: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@jobs_app.command("audit")
def jobs_audit_cmd(
    job_id: str = typer.Argument(..., help="Execution job identifier"),
    json_output: bool = typer.Option(False, "--json", help="Output audit details as JSON"),
) -> None:
    """Show DeepSeek Direct audit details and findings for an execution job."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            audit = uow.audits.get_by_job_id(job_id)
            if not audit:
                typer.secho(f"No audit found for job '{job_id}'.", fg=typer.colors.RED)
                raise typer.Exit(code=1)
            findings = uow.audit_findings.list_by_audit(audit.audit_id)
            payload = {
                "audit": audit.model_dump(),
                "findings": [f.model_dump() for f in findings],
            }
            if json_output:
                typer.echo(json.dumps(payload, indent=2, default=str))
                return

            typer.echo(f"Audit ID: {audit.audit_id}")
            typer.echo(f"Job ID: {audit.job_id}")
            typer.echo(f"Project: {audit.project_id}")
            typer.echo(f"Change: {audit.change_name}")
            typer.echo(f"Provider: {audit.provider}")
            typer.echo(f"Model: {audit.model}")
            typer.echo(f"Status: {audit.status.value}")
            typer.echo(f"Risk: {audit.risk.value if audit.risk else 'None'}")
            if audit.summary:
                typer.echo(f"Summary: {audit.summary}")
            if audit.error_message:
                typer.secho(f"Error: {audit.error_message}", fg=typer.colors.RED)
            typer.echo(f"Candidate SHA: {audit.candidate_sha}")
            typer.echo(f"Base SHA: {audit.base_sha}")

            if findings:
                typer.secho(f"\nFindings ({len(findings)}):", fg=typer.colors.YELLOW, bold=True)
                for f in findings:
                    sev_color = (
                        typer.colors.RED
                        if f.severity.value in {"high", "critical"}
                        else typer.colors.YELLOW
                    )
                    loc = f"{f.file or 'general'} {f.location or ''}".strip()
                    typer.secho(
                        f"  • [{f.severity.value}] {f.category}: {loc}",
                        fg=sev_color,
                        bold=True,
                    )
                    typer.echo(f"    {f.message}")
            else:
                typer.echo("\nNo findings recorded.")
    except Exception as e:
        typer.secho(f"Error showing audit: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@scheduler_app.command("status")
def scheduler_status_cmd(
    project_id: str = typer.Option(None, "--project-id", "-p", help="Filter by registered project"),
    json_output: bool = typer.Option(False, "--json", help="Output scheduler status as JSON"),
) -> None:
    """Show current scheduler mode (RUN, DRAIN, WAIT) and admission eligibility."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            lifecycle = CapacityLifecycleService(uow)
            sched_status = lifecycle.get_scheduler_status(project_id=project_id)

            if json_output:
                typer.echo(json.dumps(sched_status.model_dump(), indent=2, default=str))
                return

            mode_color = {
                SchedulerMode.RUN: typer.colors.GREEN,
                SchedulerMode.DRAIN: typer.colors.YELLOW,
                SchedulerMode.WAIT: typer.colors.RED,
            }.get(sched_status.mode, typer.colors.WHITE)

            typer.secho("=== mini me Scheduler Status ===", fg=typer.colors.CYAN, bold=True)
            typer.secho(f"Mode: {sched_status.mode.value}", fg=mode_color, bold=True)
            typer.echo(f"Admission Allowed: {'YES' if sched_status.admission_allowed else 'NO'}")
            typer.echo(
                f"Primary Capacity Available: {'YES' if sched_status.primary_capacity_available else 'NO'}"
            )
            typer.echo(f"Active Jobs: {sched_status.active_jobs_count}")
            if sched_status.reason:
                typer.echo(f"Reason: {sched_status.reason}")
            typer.echo(f"Last Evaluated: {sched_status.updated_at.isoformat()}")

    except Exception as e:
        typer.secho(f"Error fetching scheduler status: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@providers_app.command("health")
def providers_health_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output provider health as JSON"),
) -> None:
    """Show health, availability, and exhaustion state for primary providers (Codex and Antigravity)."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = ProviderHealthService(uow)
            health_list = service.list_all_health_with_capacity()

            if json_output:
                typer.echo(
                    json.dumps(
                        [
                            {
                                "health": h.model_dump(),
                                "capacity_window": w.model_dump() if w else None,
                            }
                            for h, w in health_list
                        ],
                        indent=2,
                        default=str,
                    )
                )
                return

            typer.secho("=== Primary Provider Health ===", fg=typer.colors.CYAN, bold=True)
            for h, window in health_list:
                h_color = {
                    ProviderHealthStatus.AVAILABLE: typer.colors.GREEN,
                    ProviderHealthStatus.EXHAUSTED: typer.colors.RED,
                    ProviderHealthStatus.TEMPORARILY_UNAVAILABLE: typer.colors.YELLOW,
                    ProviderHealthStatus.DEGRADED: typer.colors.YELLOW,
                }.get(h.status, typer.colors.WHITE)

                typer.secho(f"\nProvider: {h.provider.upper()}", fg=typer.colors.CYAN, bold=True)
                typer.secho(f"  Status: {h.status.value}", fg=h_color, bold=True)
                typer.echo(f"  Consecutive Failures: {h.consecutive_failures}")
                if h.last_error_summary:
                    typer.secho(f"  Last Error: {h.last_error_summary}", fg=typer.colors.YELLOW)
                if window and window.capacity_reset_at:
                    typer.echo(f"  Expected Reset: {window.capacity_reset_at.isoformat()}")
                if window and window.retry_after_seconds:
                    typer.echo(f"  Retry After: {window.retry_after_seconds}s")
                typer.echo(f"  Updated At: {h.updated_at.isoformat()}")

    except Exception as e:
        typer.secho(f"Error fetching provider health: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@budget_app.command("status")
def budget_status_cmd(
    project_id: str = typer.Option(None, "--project-id", "-p", help="Filter by project"),
    json_output: bool = typer.Option(False, "--json", help="Output budget status as JSON"),
) -> None:
    """Show OpenRouter budget consumption against caps, headroom, and breach state."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = BudgetService(uow)
            if not project_id:
                projects = uow.projects.list_all()
                project_id = projects[0].project_id if projects else ""
            policy = uow.budget_policies.get_for_update(project_id) if project_id else None
            if not policy:
                typer.echo("No OpenRouter budget policy found.")
                return
            headroom = service._compute_headroom(project_id, policy)
            reservations = uow.budget_reservations.list_by_project(project_id)
            ledger_entries = uow.budget_ledger.list_by_project(project_id)
            payload = {
                "project_id": project_id,
                "policy": policy.model_dump(),
                "headroom": headroom.__dict__,
                "reservations": [r.model_dump() for r in reservations],
                "ledger_count": len(ledger_entries),
            }
            if json_output:
                typer.echo(json.dumps(payload, indent=2, default=str))
                return

            typer.secho("=== OpenRouter Budget Status ===", fg=typer.colors.CYAN, bold=True)
            typer.echo(f"Project: {project_id}")
            typer.echo(f"Enabled: {'YES' if policy.enabled else 'NO'}")
            breach_color = typer.colors.RED if policy.is_breached else typer.colors.GREEN
            typer.secho(
                f"Policy Breach: {'BREACH DETECTED (LOCKED)' if policy.is_breached else 'HEALTHY'}",
                fg=breach_color,
                bold=True,
            )
            typer.echo(f"Daily Cap: ${policy.daily_cap_usd:.2f} {policy.currency}")
            typer.echo(f"Monthly Cap: ${policy.monthly_cap_usd:.2f} {policy.currency}")
            typer.echo(f"Committed Spend Today (UTC): ${headroom.committed_today_usd:.4f}")
            typer.echo(f"Committed Spend Month (UTC): ${headroom.committed_month_usd:.4f}")
            typer.echo(f"Active Reservations (Today): ${headroom.reserved_today_usd:.4f}")
            typer.echo(f"Active Reservations (Month): ${headroom.reserved_month_usd:.4f}")
            if headroom.unresolved_usd > 0:
                typer.secho(
                    f"Unresolved Encumbrance (All-Time): ${headroom.unresolved_usd:.4f} ({headroom.unresolved_count} unresolved)",
                    fg=typer.colors.YELLOW,
                )
            typer.secho(
                f"Daily Headroom: ${headroom.daily_headroom_usd:.4f}",
                fg=typer.colors.GREEN if headroom.daily_headroom_usd > 0 else typer.colors.RED,
            )
            typer.secho(
                f"Monthly Headroom: ${headroom.monthly_headroom_usd:.4f}",
                fg=typer.colors.GREEN if headroom.monthly_headroom_usd > 0 else typer.colors.RED,
            )
    except Exception as e:
        typer.secho(f"Error fetching budget status: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@providers_app.command("openrouter")
def providers_openrouter_cmd(
    project_id: str = typer.Option(None, "--project-id", "-p", help="Filter by project"),
    json_output: bool = typer.Option(False, "--json", help="Output OpenRouter status as JSON"),
) -> None:
    """Show OpenRouter fallback status, allowed models, and policy configuration."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = BudgetService(uow)
            if not project_id:
                projects = uow.projects.list_all()
                project_id = projects[0].project_id if projects else ""
            policy = uow.budget_policies.get_for_update(project_id) if project_id else None
            headroom = service._compute_headroom(project_id, policy) if policy else None
            payload = {
                "project_id": project_id,
                "policy": policy.model_dump() if policy else None,
                "headroom": headroom.__dict__ if headroom else None,
                "allowed_models": {
                    "implementer": [
                        "anthropic/claude-3.5-sonnet",
                        "qwen/qwen-2.5-coder-32b-instruct",
                    ],
                    "reviewer": [
                        "openai/gpt-4o",
                        "meta-llama/llama-3.3-70b-instruct",
                        "mistralai/mistral-large",
                    ],
                },
            }
            if json_output:
                typer.echo(json.dumps(payload, indent=2, default=str))
                return

            typer.secho("=== OpenRouter Fallback Status ===", fg=typer.colors.CYAN, bold=True)
            if not policy:
                typer.echo("No policy configured.")
            else:
                typer.echo(f"Project: {project_id}")
                typer.echo(f"Enabled: {'YES' if policy.enabled else 'NO'}")
                breach_color = typer.colors.RED if policy.is_breached else typer.colors.GREEN
                typer.secho(f"Breached: {'YES' if policy.is_breached else 'NO'}", fg=breach_color)
                if headroom:
                    typer.echo(f"Daily Headroom: ${headroom.daily_headroom_usd:.4f}")
                    typer.echo(f"Monthly Headroom: ${headroom.monthly_headroom_usd:.4f}")
                typer.echo("\nConfigured Canonical Models:")
                typer.echo(
                    "  Implementer: anthropic/claude-3.5-sonnet, qwen/qwen-2.5-coder-32b-instruct"
                )
                typer.echo(
                    "  Reviewer: openai/gpt-4o, meta-llama/llama-3.3-70b-instruct, mistralai/mistral-large"
                )
    except Exception as e:
        typer.secho(f"Error fetching OpenRouter status: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@orchestrate_app.command("start")
def orchestrate_start_cmd(
    project_id: str = typer.Argument(..., help="Project identifier"),
    change_name: str = typer.Argument(..., help="OpenSpec change name"),
    project_root: str = typer.Option(".", "--path", "-p", help="Filesystem path to project root"),
    json_output: bool = typer.Option(False, "--json", help="Output result as JSON"),
) -> None:
    """Admit and orchestrate a single READY change autonomously to a legitimate stop."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = OrchestrationService(uow, project_root=project_root)
            run = service.start(project_id, change_name, project_root=project_root)
            status_view = service.get_status(run.run_id)

            if json_output:
                typer.echo(json.dumps(status_view.model_dump(), indent=2, default=str))
                return

            typer.secho(
                f"\n=== Orchestration Run {status_view.run_id} ===",
                fg=typer.colors.CYAN,
                bold=True,
            )
            typer.echo(f"Project: {status_view.project_id}")
            typer.echo(f"Change: {status_view.change_name}")
            typer.echo(f"Current Stage: {status_view.current_stage.value}")
            typer.echo(f"Generation: {status_view.current_generation}")
            if status_view.candidate_sha:
                typer.echo(f"Candidate SHA: {status_view.candidate_sha}")
            if status_view.pr_url:
                typer.echo(f"PR URL: {status_view.pr_url}")

            outcome_str = (
                status_view.stop_outcome.value if status_view.stop_outcome else "IN_PROGRESS"
            )
            outcome_color = (
                typer.colors.GREEN
                if status_view.stop_outcome
                and status_view.stop_outcome.value == "READY_FOR_HUMAN_MERGE"
                else typer.colors.YELLOW
                if status_view.stop_outcome and "WAITING" in status_view.stop_outcome.value
                else typer.colors.RED
            )
            typer.secho(f"Stop Outcome: {outcome_str}", fg=outcome_color, bold=True)
            if status_view.human_gate:
                typer.secho(
                    f"Human Gate: {status_view.human_gate.value}", fg=typer.colors.YELLOW, bold=True
                )
            if status_view.stop_reason:
                typer.echo(f"Stop Reason: {status_view.stop_reason}")

    except Exception as e:
        typer.secho(f"Orchestration error: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@orchestrate_app.command("resume")
def orchestrate_resume_cmd(
    run_id: str = typer.Argument(..., help="Orchestration run identifier"),
    project_root: str = typer.Option(".", "--path", "-p", help="Filesystem path to project root"),
    json_output: bool = typer.Option(False, "--json", help="Output result as JSON"),
) -> None:
    """Resume an existing orchestration run from its persisted checkpoint."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = OrchestrationService(uow, project_root=project_root)
            run = service.resume(run_id, project_root=project_root)
            status_view = service.get_status(run.run_id)

            if json_output:
                typer.echo(json.dumps(status_view.model_dump(), indent=2, default=str))
                return

            typer.secho(
                f"\n=== Resumed Orchestration Run {status_view.run_id} ===",
                fg=typer.colors.CYAN,
                bold=True,
            )
            typer.echo(f"Current Stage: {status_view.current_stage.value}")
            typer.echo(f"Resumable Stage: {status_view.resumable_stage.value}")
            outcome_str = (
                status_view.stop_outcome.value if status_view.stop_outcome else "IN_PROGRESS"
            )
            typer.echo(f"Stop Outcome: {outcome_str}")
            if status_view.human_gate:
                typer.echo(f"Human Gate: {status_view.human_gate.value}")
            if status_view.stop_reason:
                typer.echo(f"Stop Reason: {status_view.stop_reason}")
    except Exception as e:
        typer.secho(f"Orchestration resume error: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@orchestrate_app.command("resolve")
def orchestrate_resolve_cmd(
    run_id: str = typer.Argument(..., help="Orchestration run identifier"),
    remediate_preserved_candidate: bool = typer.Option(
        False, "--remediate-preserved-candidate", help="Start a new bounded remediation generation"
    ),
    contract: str | None = typer.Option(
        None, "--contract", help="Path to immutable remediation contract JSON"
    ),
    continue_preserved_candidate: bool = typer.Option(
        False, "--continue-preserved-candidate", help="Continue the validated preserved candidate"
    ),
    candidate_ref: str | None = typer.Option(
        None,
        "--candidate-ref",
        help="Adopt a local legacy candidate branch when the candidate has no persisted ref",
    ),
    project_root: str = typer.Option(".", "--path", "-p", help="Filesystem path to project root"),
    json_output: bool = typer.Option(False, "--json", help="Output result as JSON"),
) -> None:
    """Resolve a NEEDS_HUMAN preserved-candidate gate."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = OrchestrationService(uow, project_root=project_root)
            if remediate_preserved_candidate:
                if not contract:
                    raise typer.BadParameter(
                        "--contract is required with --remediate-preserved-candidate"
                    )
                run = service.remediate_preserved_candidate(
                    run_id,
                    contract,
                    project_root=project_root,
                )
                status_view = service.get_status(run.run_id)
                if json_output:
                    typer.echo(json.dumps(status_view.model_dump(), indent=2, default=str))
                else:
                    typer.echo(
                        f"Remediated orchestration run {run.run_id}; generation={run.current_generation}"
                    )
                return
            run = service.resolve_preserved_candidate(
                run_id,
                continue_preserved_candidate=continue_preserved_candidate,
                candidate_ref=candidate_ref,
                project_root=project_root,
            )
            status_view = service.get_status(run.run_id)
            if json_output:
                typer.echo(json.dumps(status_view.model_dump(), indent=2, default=str))
            else:
                typer.echo(
                    f"Resolved orchestration run {run.run_id}; stage={run.current_stage.value}"
                )
    except Exception as e:
        typer.secho(f"Orchestration resolution error: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@orchestrate_app.command("status")
def orchestrate_status_cmd(
    run_id: str = typer.Argument(..., help="Orchestration run identifier"),
    json_output: bool = typer.Option(False, "--json", help="Output status as JSON"),
) -> None:
    """Show operational status for an orchestration run."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            service = OrchestrationService(uow)
            status_view = service.get_status(run_id)

            if json_output:
                typer.echo(json.dumps(status_view.model_dump(), indent=2, default=str))
                return

            typer.secho(
                f"=== Orchestration Run {status_view.run_id} ===",
                fg=typer.colors.CYAN,
                bold=True,
            )
            typer.echo(f"Project: {status_view.project_id}")
            typer.echo(f"Change: {status_view.change_name}")
            typer.echo(f"Stage: {status_view.current_stage.value}")
            typer.echo(f"Resumable Stage: {status_view.resumable_stage.value}")
            typer.echo(f"Active: {'YES' if status_view.is_active else 'NO'}")
            typer.echo(f"Generation: {status_view.current_generation}")
            typer.echo(f"Base SHA: {status_view.base_sha}")
            typer.echo(f"Candidate SHA: {status_view.candidate_sha or '-'}")
            if status_view.manifest_hash:
                typer.echo(f"Manifest Hash: {status_view.manifest_hash}")
            if status_view.checks_status:
                typer.echo(f"Checks: {status_view.checks_status}")
            if status_view.review_verdict:
                typer.echo(f"Review Verdict: {status_view.review_verdict}")
            if status_view.audit_status:
                typer.echo(
                    f"Audit: {status_view.audit_status} (Risk: {status_view.audit_risk or '-'})"
                )
            if status_view.pr_url:
                typer.echo(f"PR: #{status_view.pr_number or '-'} -> {status_view.pr_url}")
            if status_view.stop_outcome:
                outcome_color = (
                    typer.colors.GREEN
                    if status_view.stop_outcome.value == "READY_FOR_HUMAN_MERGE"
                    else typer.colors.YELLOW
                    if "WAITING" in status_view.stop_outcome.value
                    else typer.colors.RED
                )
                typer.secho(
                    f"Stop Outcome: {status_view.stop_outcome.value}",
                    fg=outcome_color,
                    bold=True,
                )
            if status_view.human_gate:
                typer.secho(
                    f"Human Gate: {status_view.human_gate.value}",
                    fg=typer.colors.YELLOW,
                    bold=True,
                )
            if status_view.stop_reason:
                typer.echo(f"Reason: {status_view.stop_reason}")

    except Exception as e:
        typer.secho(f"Error showing orchestration status: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@orchestrate_app.command("list")
def orchestrate_list_cmd(
    project_id: str = typer.Option(None, "--project-id", "-p", help="Filter by project"),
    change_name: str = typer.Option(None, "--change-name", "-c", help="Filter by change"),
    is_active: bool = typer.Option(None, "--active/--all", help="Filter active vs all"),
    json_output: bool = typer.Option(False, "--json", help="Output runs as JSON"),
) -> None:
    """List orchestration runs."""
    try:
        with db_manager.session() as session:
            uow = PostgresPersistenceUnitOfWork(session)
            runs = uow.orchestration_runs.list_runs(
                project_id=project_id,
                change_name=change_name,
                is_active=is_active,
            )
            if json_output:
                typer.echo(json.dumps([r.model_dump() for r in runs], indent=2, default=str))
                return

            if not runs:
                typer.echo("No orchestration runs found.")
                return

            typer.secho("=== Orchestration Runs ===", fg=typer.colors.CYAN, bold=True)
            for r in runs:
                outcome_str = r.stop_outcome.value if r.stop_outcome else "RUNNING"
                gate_str = r.human_gate.value if r.human_gate else "-"
                typer.echo(
                    f"{r.run_id}  {r.project_id}  {r.change_name}  stage={r.current_stage.value}  outcome={outcome_str}  gate={gate_str}  gen={r.current_generation}  active={r.is_active}"
                )
    except Exception as e:
        typer.secho(f"Error listing orchestration runs: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8787, "--port", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
) -> None:
    """Start the mini me FastAPI daemon."""
    uvicorn.run("minime.api.app:app", host=host, port=port, reload=reload)


@app.command("console")
def console_cmd(
    refresh_interval: float = typer.Option(3.0, "--refresh", "-r", help="Refresh interval in seconds"),
) -> None:
    """Launch the interactive mini me TUI operator console."""
    from minime.tui.app import run_tui

    run_tui(refresh_interval=refresh_interval)


@app.command("tui")
def tui_cmd(
    refresh_interval: float = typer.Option(3.0, "--refresh", "-r", help="Refresh interval in seconds"),
) -> None:
    """Launch the interactive mini me TUI operator console (alias for console)."""
    from minime.tui.app import run_tui

    run_tui(refresh_interval=refresh_interval)


if __name__ == "__main__":
    app()
