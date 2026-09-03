# Spec: Aggregate Provider Efficiency and Loop Telemetry Summary

## Overview
Defines observable behavior for computing and retrieving project-level aggregated provider efficiency facts and self-operating loop statistics.

## ADDED Requirements

### Requirement: Project Efficiency Summary Aggregation
`EfficiencyTelemetryService.get_project_efficiency_summary(project_id: str)` MUST query all recorded metrics for `project_id` and return a dictionary containing `total_runs`, `total_productive_attempts`, `total_no_progress_attempts`, `productive_attempt_ratio`, `total_same_sha_suppressed`, `total_corrective_retries`, `total_reassignments`, `average_self_hosting_percentage`, and `provider_breakdown`.

#### Scenario: No runs recorded
- **GIVEN** a project with 0 recorded efficiency metrics
- **WHEN** `get_project_efficiency_summary(project_id)` is invoked
- **THEN** it returns `total_runs: 0`, `productive_attempt_ratio: 0.0`, `average_self_hosting_percentage: 0.0`, and empty `provider_breakdown`.

#### Scenario: Multiple runs recorded
- **GIVEN** a project with 2 recorded efficiency metrics records
- **WHEN** `get_project_efficiency_summary(project_id)` is invoked
- **THEN** it correctly sums attempt counts, computes the combined productive ratio, and averages the self-hosting percentage.

### Requirement: Status Service Telemetry Summary Delegation
`StatusService.get_efficiency_summary(project_id: str | None = None)` MUST query and return the project efficiency summary, resolving the project ID from registered projects when omitted.

#### Scenario: Status service query
- **GIVEN** an active registered project "mini-me"
- **WHEN** `StatusService.get_efficiency_summary()` is called without arguments
- **THEN** it evaluates and returns the efficiency summary for "mini-me".
