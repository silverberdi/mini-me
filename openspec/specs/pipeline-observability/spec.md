# Pipeline Observability Specification

## Purpose

Exposes job lifecycle status, execution logs, check results, and execution metrics through FastAPI endpoints and CLI commands.

## Requirements

### Requirement: Execution job API surface
The system SHALL provide REST API endpoints to list, inspect, trigger, and cancel execution jobs for registered projects.

#### Scenario: Query job status via API
- **WHEN** a client sends `GET /projects/{project_id}/jobs` or `GET /jobs/{job_id}`
- **THEN** the API returns structured JSON with the job's current status, timestamps, candidate SHA, implementer, and summary check outcomes.

#### Scenario: Query job execution logs via API
- **WHEN** a client sends `GET /jobs/{job_id}/logs`
- **THEN** the API returns the chronological, redacted log stream for the specified job.

### Requirement: Execution pipeline CLI surface
The system SHALL provide CLI commands to run execution jobs and inspect job history and details.

#### Scenario: Trigger execution job via CLI
- **WHEN** an operator runs `minime run <project_id> <change_name>`
- **THEN** the CLI queues/runs the execution job, prints the allocated job ID, and streams real-time status updates.

#### Scenario: Inspect job history via CLI
- **WHEN** an operator runs `minime jobs list <project_id>`
- **THEN** a formatted table of past and active jobs, their statuses, candidate SHAs, and check outcomes is displayed.
