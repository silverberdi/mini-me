"""Command-Line Interface for OpenSpec Lifecycle Quality Hooks V1."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from minime.quality_hooks.engine import (
    evaluate_archive,
    evaluate_post_apply,
    evaluate_pre_apply,
    evaluate_verify,
)
from minime.quality_hooks.models import QualityHookReport, ReviewSpecialty, VerificationResult
from minime.quality_hooks.specialties import select_specialties_for_files

cli_app = typer.Typer(
    name="quality-hooks",
    help="OpenSpec Lifecycle Quality Hooks V1 CLI.",
    add_completion=False,
)


@cli_app.command("select-specialties")
def select_specialties_cmd(
    files: list[str] = typer.Option(..., "--file", "-f", help="Changed file path (can be passed multiple times)"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Output result as JSON"),
) -> None:
    """Select required review specialties based on changed files."""
    specialties = select_specialties_for_files(files)
    if json_output:
        res = {
            "changed_files": files,
            "required_specialties": [s.value for s in specialties],
            "required_specialties_labels": [s.label for s in specialties],
        }
        typer.echo(json.dumps(res, indent=2))
    else:
        typer.echo("Required Specialties:")
        for s in specialties:
            typer.echo(f"  • {s.value} ({s.label})")


@cli_app.command("evaluate-pre-apply")
def evaluate_pre_apply_cmd(
    change_id: str = typer.Option(..., "--change", "-c", help="OpenSpec change name/id"),
    base_sha: str = typer.Option(..., "--base-sha", help="Base commit SHA"),
    candidate_sha: str = typer.Option(..., "--candidate-sha", help="Candidate commit SHA"),
    repo_root: str = typer.Option(".", "--repo-root", help="Repository root path"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Output report as JSON"),
) -> None:
    """Evaluate PRE-APPLY quality hook for implementation readiness."""
    report = evaluate_pre_apply(
        change_id=change_id,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        repo_root=repo_root,
    )
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(f"Hook: {report.hook_id} | Verdict: {report.final_verdict.value}")
        typer.echo(f"Reason: {report.verdict_reason}")

    if report.final_verdict.value != "PASS":
        sys.exit(1)


@cli_app.command("evaluate-post-apply")
def evaluate_post_apply_cmd(
    change_id: str = typer.Option(..., "--change", "-c", help="OpenSpec change name/id"),
    base_sha: str = typer.Option(..., "--base-sha", help="Base commit SHA"),
    candidate_sha: str = typer.Option(..., "--candidate-sha", help="Candidate commit SHA"),
    implementer_model: str = typer.Option(..., "--implementer-model", help="Implementer model identity"),
    reviewer_model: str = typer.Option(..., "--reviewer-model", help="Reviewer model identity"),
    files: list[str] = typer.Option([], "--file", "-f", help="Changed file path"),
    evaluated_specialties: list[str] = typer.Option([], "--specialty", "-s", help="Evaluated specialty"),
    repo_root: str = typer.Option(".", "--repo-root", help="Repository root path"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Output report as JSON"),
) -> None:
    """Evaluate POST-APPLY quality hook for expert review and independence."""
    eval_specs = [ReviewSpecialty(s) for s in evaluated_specialties if s in ReviewSpecialty._value2member_map_]
    report = evaluate_post_apply(
        change_id=change_id,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        implementer_model_identity=implementer_model,
        reviewer_model_identity=reviewer_model,
        changed_files=files,
        evaluated_specialties=eval_specs,
        repo_root=repo_root,
    )
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(f"Hook: {report.hook_id} | Verdict: {report.final_verdict.value}")
        typer.echo(f"Reason: {report.verdict_reason}")

    if report.final_verdict.value != "PASS":
        sys.exit(1)


@cli_app.command("evaluate-verify")
def evaluate_verify_cmd(
    change_id: str = typer.Option(..., "--change", "-c", help="OpenSpec change name/id"),
    base_sha: str = typer.Option(..., "--base-sha", help="Base commit SHA"),
    candidate_sha: str = typer.Option(..., "--candidate-sha", help="Candidate commit SHA"),
    tests_passed: bool = typer.Option(True, "--tests-passed/--tests-failed", help="Tests outcome"),
    repo_root: str = typer.Option(".", "--repo-root", help="Repository root path"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Output report as JSON"),
) -> None:
    """Evaluate VERIFY quality hook gate."""
    ver_res = VerificationResult(
        deterministic_checks_passed=tests_passed,
        tests_passed=tests_passed,
        linters_passed=True,
        schemas_passed=True,
    )
    report = evaluate_verify(
        change_id=change_id,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        verification_result=ver_res,
        repo_root=repo_root,
    )
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(f"Hook: {report.hook_id} | Verdict: {report.final_verdict.value}")
        typer.echo(f"Reason: {report.verdict_reason}")

    if report.final_verdict.value != "PASS":
        sys.exit(1)


@cli_app.command("evaluate-archive")
def evaluate_archive_cmd(
    change_id: str = typer.Option(..., "--change", "-c", help="OpenSpec change name/id"),
    base_sha: str = typer.Option(..., "--base-sha", help="Base commit SHA"),
    candidate_sha: str = typer.Option(..., "--candidate-sha", help="Candidate commit SHA"),
    pr_merged_by_human: bool = typer.Option(..., "--merged-by-human/--not-merged-by-human", help="Human merge confirmation"),
    repo_root: str = typer.Option(".", "--repo-root", help="Repository root path"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Output report as JSON"),
) -> None:
    """Evaluate ARCHIVE quality hook gate."""
    report = evaluate_archive(
        change_id=change_id,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        pr_merged_by_human=pr_merged_by_human,
        repo_root=repo_root,
    )
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(f"Hook: {report.hook_id} | Verdict: {report.final_verdict.value}")
        typer.echo(f"Reason: {report.verdict_reason}")

    if report.final_verdict.value != "PASS":
        sys.exit(1)


@cli_app.command("validate-report")
def validate_report_cmd(
    report_file: str = typer.Option(..., "--report", "-r", help="Path to QualityHookReport JSON file"),
) -> None:
    """Validate a JSON file against QualityHookReport schema."""
    path = Path(report_file)
    if not path.exists():
        typer.secho(f"Error: report file '{report_file}' not found.", fg=typer.colors.RED, err=True)
        sys.exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    report = QualityHookReport.model_validate(data)
    typer.secho(f"Valid report: {report.hook_id} -> {report.final_verdict.value}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    cli_app()
