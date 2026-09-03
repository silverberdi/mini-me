# Design: 018.2 Proving Run — Pipeline Execution Diagnostic Summary

## Overview
`StatusService.get_pipeline_diagnostic(run_id: str | None = None)` queries the active or specified `OrchestrationRun`, resolves its latest `Job`, `Review`, and `AuditRecord`, and returns an operational summary.

```json
{
  "run_id": "...",
  "project_id": "mini-me",
  "change_name": "018.2-proving-diagnostic-status",
  "stage": "READY_FOR_HUMAN_MERGE",
  "candidate_sha": "...",
  "review_verdict": "READY_TO_MERGE",
  "audit_risk": "low",
  "github_pr_url": "https://github.com/silverberdi/mini-me/pull/..."
}
```

## Implementation Strategy
1. Extend `StatusService` with `get_pipeline_diagnostic`.
2. Retrieve the run from `uow.orchestration_runs`.
3. If `run_id` is omitted, resolve the most recently updated run.
4. Retrieve candidate, review, and audit details from persistence.
5. Provide comprehensive unit tests in `tests/test_status_observability.py`.
