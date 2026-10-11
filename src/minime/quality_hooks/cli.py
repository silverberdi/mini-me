"""Command-Line Interface for OpenSpec Lifecycle Quality Hooks V1 with strict canonical evidence enforcement."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

from minime.quality_hooks.engine import (
    evaluate_archive,
    evaluate_post_apply,
    evaluate_pre_apply,
    evaluate_verify,
)
from minime.quality_hooks.models import (
    HumanApprovalEvidence,
    MergeEvidence,
    QualityHookReport,
    ReviewEvidence,
    VerificationResult,
)
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
    implementer_identity: str | None = typer.Option(None, "--implementer-identity", help="Implementer role"),
    implementer_model: str | None = typer.Option(None, "--implementer-model", help="Implementer model identity"),
    review_evidence_file: str | None = typer.Option(None, "--review-evidence-file", "-r", help="Path to ReviewEvidence JSON file"),
    repo_root: str = typer.Option(".", "--repo-root", help="Repository root path"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Output report as JSON"),
) -> None:
    """Evaluate POST-APPLY quality hook for expert review and independence.

    Fails closed as BLOCKED if review_evidence_file is missing, untrusted, or unbound.
    """
    review_evidence: ReviewEvidence | None = None
    if review_evidence_file:
        path = Path(review_evidence_file)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            review_evidence = ReviewEvidence.model_validate(data)

    report = evaluate_post_apply(
        change_id=change_id,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        implementer_identity=implementer_identity,
        implementer_model_identity=implementer_model,
        review_evidence=review_evidence,
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
    evidence_file: str | None = typer.Option(None, "--evidence-file", "-e", help="Path to VerificationResult JSON file"),
    run_checks: bool = typer.Option(False, "--run-checks", help="Execute real test, lint & schema suite on candidate worktree"),
    repo_root: str = typer.Option(".", "--repo-root", help="Repository root path"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Output report as JSON"),
) -> None:
    """Evaluate VERIFY quality hook gate.

    Fails closed as BLOCKED if no verifiable evidence is provided or generated.
    """
    ver_res: VerificationResult | None = None

    if evidence_file:
        path = Path(evidence_file)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            ver_res = VerificationResult.model_validate(data)
    elif run_checks:
        root_path = Path(repo_root)

        # 1. Verify working tree identity against candidate SHA
        head_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root_path),
            capture_output=True,
            text=True,
        )
        head_sha = head_proc.stdout.strip()

        diff_index_proc = subprocess.run(
            ["git", "diff-index", "--quiet", "HEAD", "--"],
            cwd=str(root_path),
            check=False,
        )
        is_dirty = (diff_index_proc.returncode != 0)

        if head_sha != candidate_sha or is_dirty:
            # Cannot attribute checks to candidate SHA
            report = evaluate_verify(
                change_id=change_id,
                base_sha=base_sha,
                candidate_sha=candidate_sha,
                verification_result=None,
                findings=[],
                repo_root=repo_root,
            )
            # Override with specific tree attribution reason
            if json_output:
                res_dict = report.model_dump()
                res_dict["final_verdict"] = "BLOCKED"
                res_dict["verdict_reason"] = (
                    f"Working tree HEAD '{head_sha}' or dirty status ({is_dirty}) does not match "
                    f"candidate SHA '{candidate_sha}'; cannot attribute execution."
                )
                typer.echo(json.dumps(res_dict, indent=2, default=str))
            else:
                typer.echo("Hook: VERIFY | Verdict: BLOCKED\nReason: Working tree mismatch with candidate SHA.")
            sys.exit(1)

        # 2. Run real test suite
        test_proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_openspec_quality_hooks.py", "-q"],
            cwd=str(root_path),
            capture_output=True,
            text=True,
        )
        tests_ok = test_proc.returncode == 0

        # 3. Run real lint suite
        lint_proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "src/minime/quality_hooks"],
            cwd=str(root_path),
            capture_output=True,
            text=True,
        )
        lint_ok = lint_proc.returncode == 0

        # 4. Run real schema validation
        schemas_dir = root_path / "schemas"
        schemas_ok = True
        schema_files = list(schemas_dir.glob("*.json"))
        if not schema_files:
            schemas_ok = False
        for sf in schema_files:
            try:
                json.loads(sf.read_text(encoding="utf-8"))
            except Exception:
                schemas_ok = False
                break

        ver_res = VerificationResult(
            candidate_sha=candidate_sha,
            deterministic_checks_passed=(tests_ok and lint_ok and schemas_ok),
            tests_passed=tests_ok,
            linters_passed=lint_ok,
            schemas_passed=schemas_ok,
            evidence_source="canonical-worktree-runner",
            provenance="canonical-worktree-runner",
            check_details={
                "pytest_returncode": test_proc.returncode,
                "ruff_returncode": lint_proc.returncode,
                "schemas_validated": len(schema_files),
            },
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
    merge_evidence_file: str | None = typer.Option(None, "--merge-evidence-file", "-m", help="Path to MergeEvidence JSON file"),
    human_approval_file: str | None = typer.Option(None, "--human-approval-file", "-a", help="Path to HumanApprovalEvidence JSON file"),
    repo_root: str = typer.Option(".", "--repo-root", help="Repository root path"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Output report as JSON"),
) -> None:
    """Evaluate ARCHIVE quality hook gate.

    Fails closed as BLOCKED if authoritative merge or approval evidence is missing or untrusted.
    """
    merge_ev: MergeEvidence | None = None
    if merge_evidence_file:
        m_path = Path(merge_evidence_file)
        if m_path.exists():
            m_data = json.loads(m_path.read_text(encoding="utf-8"))
            merge_ev = MergeEvidence.model_validate(m_data)

    approval_ev: HumanApprovalEvidence | None = None
    if human_approval_file:
        a_path = Path(human_approval_file)
        if a_path.exists():
            a_data = json.loads(a_path.read_text(encoding="utf-8"))
            approval_ev = HumanApprovalEvidence.model_validate(a_data)

    report = evaluate_archive(
        change_id=change_id,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        merge_evidence=merge_ev,
        human_approval_evidence=approval_ev,
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
