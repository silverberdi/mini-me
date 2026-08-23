## MODIFIED Requirements

### Requirement: Execution job API surface
The system SHALL provide REST API endpoints to list, inspect, trigger, and cancel execution jobs for registered projects, including review and DeepSeek audit status, attempt histories, normalized outcomes, continuation decisions, blocker fingerprints and validation records, evidence diagnostics, handoffs, and NEEDS_HUMAN escalation details with secret redaction.

#### Scenario: Query job status via API
- **WHEN** a client sends `GET /projects/{project_id}/jobs` or `GET /jobs/{job_id}`
- **THEN** the API returns structured JSON with the job's current status, timestamps, candidate SHA, current executor, previous executors, attempt count, latest normalized outcome, progress classification, blocker status, continuation decision, reassignment count, summary check outcomes, review verdict, evidence diagnostics, audit status, audit risk rating, and escalation reason if in `NEEDS_HUMAN`.

#### Scenario: Query job execution logs via API
- **WHEN** a client sends `GET /jobs/{job_id}/logs`
- **THEN** the API returns the chronological, redacted log stream for the specified job without exposing provider secrets or API keys.

#### Scenario: Query job execution attempts via API
- **WHEN** a client sends `GET /jobs/{job_id}/attempts`
- **THEN** the API returns a structured list of all execution attempts for the job, including attempt number, executor role and model, start/end timestamps, outcome classification, deterministic progress signals, blocker fingerprints, corrective prompts, and generated handoff IDs.

#### Scenario: Query review details via API
- **WHEN** a client sends `GET /jobs/{job_id}/review`
- **THEN** the API returns structured JSON containing review status, reviewer identity, verdict, candidate SHA, evidence diagnostics (including `REVIEW_ENVIRONMENT_INVALID` if present), mixed authorship disclosure, and individual structured findings with severities.

#### Scenario: Query audit details via API
- **WHEN** a client sends `GET /jobs/{job_id}/audit`
- **THEN** the API returns structured JSON containing audit status (`AUDIT_COMPLETED`, `AUDIT_BLOCKED`, `AUDIT_FAILED`, etc.), overall risk (`low`, `medium`, `high`, `critical`), summary narrative, candidate SHA binding, error messages if any, and individual structured findings with severities, categories, and file locations with secret redaction.

### Requirement: Execution pipeline CLI surface
The system SHALL provide CLI commands to run execution jobs, inspect job history, view execution attempts, blocker fingerprints, and handoff records, and inspect detailed review and audit outcomes.

#### Scenario: Trigger execution job via CLI
- **WHEN** an operator runs `minime run <project_id> <change_name>`
- **THEN** the CLI queues/runs the execution job, prints the allocated job ID, and streams real-time status updates through check execution, continuation governance, complementary review, and DeepSeek audit completion.

#### Scenario: Inspect job history via CLI
- **WHEN** an operator runs `minime jobs list <project_id>`
- **THEN** a formatted table of past and active jobs, their statuses, attempt counts, executors, candidate SHAs, check outcomes, review verdicts, and audit risk levels is displayed.

#### Scenario: Inspect job attempts via CLI
- **WHEN** an operator runs `minime jobs attempts <job_id>`
- **THEN** the CLI displays a chronological summary of each execution attempt, its executor, normalized outcome classification, progress delta, blocker fingerprint, continuation action, and handoff links.

#### Scenario: Inspect review details via CLI
- **WHEN** an operator runs `minime jobs review <job_id>`
- **THEN** the CLI displays the reviewer identity, candidate SHA binding, evidence diagnostics, mixed authorship flags if present, verdict (`READY_TO_MERGE` or `CHANGES_REQUIRED`), and formatted list of findings with severity levels.

#### Scenario: Inspect audit details via CLI
- **WHEN** an operator runs `minime jobs audit <job_id>`
- **THEN** the CLI displays the audit status, candidate SHA binding, overall risk rating (`low`, `medium`, `high`, `critical`), summary narrative, and formatted list of findings with severity, category, message, and location.
