# Spec: Pipeline Execution Diagnostic Summary

## Requirement: Pipeline Diagnostic Snapshot
`StatusService` SHALL provide a method `get_pipeline_diagnostic(run_id: str | None = None)` that returns a dictionary snapshot of an orchestration run's execution status.

### Scenarios

#### Scenario: Active Run Diagnostic Retrieval
- GIVEN an existing orchestration run in the database,
- WHEN `StatusService.get_pipeline_diagnostic(run.run_id)` is invoked,
- THEN it SHALL return a dictionary containing `run_id`, `project_id`, `change_name`, `stage`, `candidate_sha`, `pr_url`, `review_verdict`, and `audit_risk`.

#### Scenario: Non-existent Run Returns None
- GIVEN a run_id that does not exist in persistence,
- WHEN `StatusService.get_pipeline_diagnostic("unknown-run-id")` is invoked,
- THEN it SHALL return `None`.
