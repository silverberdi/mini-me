# Proposal: 018.4 Proving Run — Aggregate Provider Efficiency and Loop Telemetry Summary

## Why
Operators, autonomous monitors, and status consumers require an aggregate project-level view of provider productivity, self-operating loop metrics, same-SHA suppressions, and attempt distributions across all completed runs in a registered project.

## What Changes
- Add `get_project_efficiency_summary(project_id: str)` to `EfficiencyTelemetryService` to aggregate metrics across all runs for a project.
- Add `get_efficiency_summary(project_id: str | None = None)` to `StatusService` returning the aggregate telemetry dictionary.
- Add comprehensive unit test coverage in `tests/test_efficiency_telemetry.py`.

## Non-Goals
- UI redesign or dashboard changes.
- Alembic database migrations (uses existing `ProviderEfficiencyMetrics` table and models).
