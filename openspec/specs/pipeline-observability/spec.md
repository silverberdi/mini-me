# Pipeline Observability Specification

## Purpose

Exposes job lifecycle status, execution logs, check results, review findings, and execution metrics through FastAPI endpoints and CLI commands.

## Requirements

### Requirement: Execution job API surface
The system SHALL provide REST API endpoints to list, inspect, trigger, and cancel execution jobs for registered projects, including review and DeepSeek audit status, risk rating, and structured findings with secret redaction.

#### Scenario: Query job status via API
- **WHEN** a client sends `GET /projects/{project_id}/jobs` or `GET /jobs/{job_id}`
- **THEN** the API returns structured JSON with the job's current status, timestamps, candidate SHA, implementer, reviewer, summary check outcomes, review verdict, audit status, and audit risk rating if available.

#### Scenario: Query job execution logs via API
- **WHEN** a client sends `GET /jobs/{job_id}/logs`
- **THEN** the API returns the chronological, redacted log stream for the specified job without exposing provider secrets or API keys.

#### Scenario: Query review details via API
- **WHEN** a client sends `GET /jobs/{job_id}/review`
- **THEN** the API returns structured JSON containing review status, reviewer identity, verdict, candidate SHA, and individual structured findings with severities.

#### Scenario: Query audit details via API
- **WHEN** a client sends `GET /jobs/{job_id}/audit`
- **THEN** the API returns structured JSON containing audit status (`AUDIT_COMPLETED`, `AUDIT_BLOCKED`, `AUDIT_FAILED`, etc.), overall risk (`low`, `medium`, `high`, `critical`), summary narrative, candidate SHA binding, error messages if any, and individual structured findings with severities, categories, and file locations with secret redaction.

### Requirement: Execution pipeline CLI surface
The system SHALL provide CLI commands to run execution jobs, inspect job history, and view detailed review and audit outcomes.

#### Scenario: Trigger execution job via CLI
- **WHEN** an operator runs `minime run <project_id> <change_name>`
- **THEN** the CLI queues/runs the execution job, prints the allocated job ID, and streams real-time status updates through check execution, complementary review, and DeepSeek audit completion.

#### Scenario: Inspect job history via CLI
- **WHEN** an operator runs `minime jobs list <project_id>`
- **THEN** a formatted table of past and active jobs, their statuses, candidate SHAs, check outcomes, review verdicts, and audit risk levels is displayed.

#### Scenario: Inspect review details via CLI
- **WHEN** an operator runs `minime jobs review <job_id>`
- **THEN** the CLI displays the reviewer identity, candidate SHA binding, verdict (`READY_TO_MERGE` or `CHANGES_REQUIRED`), and formatted list of findings with severity levels.

#### Scenario: Inspect audit details via CLI
- **WHEN** an operator runs `minime jobs audit <job_id>`
- **THEN** the CLI displays the audit status, candidate SHA binding, overall risk rating (`low`, `medium`, `high`, `critical`), summary narrative, and formatted list of findings with severity, category, message, and location.
