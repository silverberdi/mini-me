"""Reviewer execution prompt context builder."""

from __future__ import annotations

import json
from pathlib import Path

from minime.domain.models import CheckResult, Project


def build_reviewer_prompt(
    project: Project,
    change_name: str,
    job_id: str,
    candidate_sha: str,
    base_sha: str,
    candidate_worktree_path: Path,
    checks_results: list[CheckResult],
) -> str:
    """Build a structured, provider-neutral review context prompt.

    Contains explicit immutable identifiers, check evidence, and strict output instructions.
    """
    checks_summary = [
        {
            "name": c.check_name,
            "command": c.command,
            "exit_code": c.exit_code,
            "duration_ms": c.duration_ms,
            "output_snippet": c.output_snippet,
        }
        for c in checks_results
    ]

    change_dir = candidate_worktree_path / project.openspec_path / "changes" / change_name
    proposal_text = ""
    tasks_text = ""
    design_text = ""
    specs_texts: list[dict[str, str]] = []

    if (change_dir / "proposal.md").exists():
        proposal_text = (change_dir / "proposal.md").read_text(encoding="utf-8")
    if (change_dir / "tasks.md").exists():
        tasks_text = (change_dir / "tasks.md").read_text(encoding="utf-8")
    if (change_dir / "design.md").exists():
        design_text = (change_dir / "design.md").read_text(encoding="utf-8")
    specs_root = change_dir / "specs"
    if specs_root.exists():
        for spec_file in sorted(specs_root.glob("**/*.md")):
            rel_path = spec_file.relative_to(specs_root)
            specs_texts.append(
                {
                    "path": str(rel_path),
                    "content": spec_file.read_text(encoding="utf-8"),
                }
            )

    payload = {
        "project_id": project.project_id,
        "repository": project.repository,
        "change_id": change_name,
        "job_id": job_id,
        "candidate_sha": candidate_sha,
        "base_sha": base_sha,
        "implementer": project.implementer,
        "reviewer": project.reviewer,
        "worktree_path": str(candidate_worktree_path),
        "preceding_checks": checks_summary,
        "openspec": {
            "proposal": proposal_text,
            "tasks": tasks_text,
            "design": design_text,
            "specs": specs_texts,
        },
    }

    instructions = """
You are the complementary reviewer for mini me.

CRITICAL REVIEW RULES:
1. Review ONLY the exact change_id specified above. Do NOT infer or select any other change.
2. Review the candidate code corresponding to the exact candidate_sha provided.
3. You are strictly READ-ONLY. Do NOT modify any files, do NOT make git commits, do NOT update checkboxes.
4. Output your authoritative review verdict as a valid JSON object in a ```json ``` block with the following schema:
{
  "verdict": "READY_TO_MERGE" | "CHANGES_REQUIRED",
  "summary": "Brief summary of review verdict",
  "findings": [
    {
      "severity": "BLOCKER" | "MAJOR" | "MINOR",
      "location": "file path and line number if applicable",
      "violated_requirement": "Name or text of the spec requirement/check violated",
      "expected_correction": "What must be corrected"
    }
  ]
}
If all requirements and tests are satisfied, emit verdict "READY_TO_MERGE" with an empty findings list [].
If issues exist, emit verdict "CHANGES_REQUIRED" with one or more structured findings.
"""

    return f"### REVIEW CONTEXT PAYLOAD ###\n{json.dumps(payload, indent=2)}\n\n{instructions.strip()}\n"
