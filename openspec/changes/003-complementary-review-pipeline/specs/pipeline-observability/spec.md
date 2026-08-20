## MODIFIED Requirements

### Requirement: Execution job API surface
The system SHALL provide REST API endpoints to list, inspect, trigger, and cancel execution jobs for registered projects, including review status, verdict, and findings.

#### Scenario: Query job status via API
- **WHEN** a client sends `GET /projects/{project_id}/jobs` or `GET /jobs/{job_id}`
- **THEN** the API returns structured JSON with the job's current status, timestamps, candidate SHA, implementer, reviewer, summary check outcomes, and review verdict if available.

#### Scenario: Query job execution logs via API
- **WHEN** a client sends `GET /jobs/{job_id}/logs`
- **THEN** the API returns the chronological, redacted log stream for the specified job.

#### Scenario: Query review details via API
- **WHEN** a client sends `GET /jobs/{job_id}/review`
- **THEN** the API returns structured JSON containing review status, reviewer identity, verdict, candidate SHA, and individual structured findings with severities.

### Requirement: Execution pipeline CLI surface
The system SHALL provide CLI commands to run execution jobs, inspect job history, and view detailed review outcomes.

#### Scenario: Trigger execution job via CLI
- **WHEN** an operator runs `minime run <project_id> <change_name>`
- **THEN** the CLI queues/runs the execution job, prints the allocated job ID, and streams real-time status updates through review completion.

#### Scenario: Inspect job history via CLI
- **WHEN** an operator runs `minime jobs list <project_id>`
- **THEN** a formatted table of past and active jobs, their statuses, candidate SHAs, check outcomes, and review verdicts is displayed.

#### Scenario: Inspect review details via CLI
- **WHEN** an operator runs `minime jobs review <job_id>`
- **THEN** the CLI displays the reviewer identity, candidate SHA binding, verdict (`READY_TO_MERGE` or `CHANGES_REQUIRED`), and formatted list of findings with severity levels.
