# Proposal: 018.2 Proving Run — Pipeline Execution Diagnostic Summary

## Why
Operators and autonomous monitors require a direct diagnostic query on `StatusService` to inspect the real-time execution health, stage, candidate SHA, PR status, and review/audit verdicts of active orchestration runs.

## What Changes
- Add `get_pipeline_diagnostic(run_id: str | None = None)` to `StatusService`.
- Return a structured summary dictionary containing `run_id`, `project_id`, `change_name`, `stage`, `candidate_sha`, `pr_url`, `review_verdict`, and `audit_risk`.
- Add unit test coverage in `tests/test_status_observability.py`.

## Non-Goals
- UI dashboard modifications.
- Schema changes.
