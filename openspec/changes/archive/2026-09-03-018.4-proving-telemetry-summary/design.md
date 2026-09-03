# Design: 018.4 Proving Run — Aggregate Provider Efficiency and Loop Telemetry Summary

## Context & Architecture
`EfficiencyTelemetryService` persists per-run telemetry records in the `provider_efficiency_metrics` table. To provide project-wide operational observability, `EfficiencyTelemetryService` queries all metrics for a given `project_id` and aggregates:
- `total_runs`: integer count of recorded runs.
- `total_productive_attempts`: sum of `productive_attempt_count`.
- `total_no_progress_attempts`: sum of `no_progress_attempt_count`.
- `productive_attempt_ratio`: float ratio of productive attempts to total attempts (percentage 0.0-100.0, rounded to 2 decimals).
- `total_same_sha_suppressed`: sum of `same_sha_retry_suppressed_count`.
- `total_corrective_retries`: sum of `corrective_retry_count`.
- `total_reassignments`: sum of `reassignments_count`.
- `average_self_hosting_percentage`: average of `self_hosting_percentage` across runs.
- `provider_breakdown`: aggregated attempt count and total duration per provider.

`StatusService` exposes `get_efficiency_summary(project_id: str | None = None)` which defaults to the primary project if `project_id` is omitted and calls `EfficiencyTelemetryService.get_project_efficiency_summary`.

## Verification Strategy
Deterministic unit tests in `tests/test_efficiency_telemetry.py` using in-memory / mock UOW asserting correct aggregation behavior across single and multiple runs, including edge cases (zero runs).
