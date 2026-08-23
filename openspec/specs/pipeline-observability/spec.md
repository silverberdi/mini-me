# Pipeline Observability Specification

## Purpose

Exposes job lifecycle status, execution logs, check results, review findings, and execution metrics through FastAPI endpoints and CLI commands.

## Requirements

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

### Requirement: Capacity and scheduler observability via API
The system SHALL expose REST API endpoints to inspect scheduler mode (`RUN`, `DRAIN`, `WAIT`), primary provider health states, capacity reset windows, `WAITING_CAPACITY` blockage reasons, and crash recovery status with secret redaction.

#### Scenario: Query scheduler status via API
- **WHEN** a client sends `GET /scheduler/status`
- **THEN** the API returns structured JSON containing current scheduler mode, active in-flight job counts, admission status, primary capacity availability, and reason if in `DRAIN` or `WAIT`.

#### Scenario: Query provider health and capacity windows via API
- **WHEN** a client sends `GET /providers/health`
- **THEN** the API returns structured JSON with each primary provider's status (`available`, `temporarily_unavailable`, `exhausted`, `degraded`), consecutive failure counts, last result class, and known capacity reset timestamps.

#### Scenario: Query job blockage details via API
- **WHEN** a client sends `GET /jobs/{job_id}` for a job in `WAITING_CAPACITY` or `RECOVERY_BLOCKED`
- **THEN** the response includes structured fields indicating the blocking provider identity, last outcome class, expected reset timestamp if available, or lock recovery blockage path and reason.

### Requirement: Capacity and scheduler observability via CLI
The system SHALL provide CLI commands to inspect scheduler mode, primary provider capacity health, and in-flight capacity blockage.

#### Scenario: Inspect scheduler status via CLI
- **WHEN** an operator runs `minime scheduler status`
- **THEN** the CLI displays current scheduler mode (`RUN`, `DRAIN`, `WAIT`), admission policy status, active in-flight jobs, and primary capacity state.

#### Scenario: Inspect provider health via CLI
- **WHEN** an operator runs `minime providers health`
- **THEN** the CLI displays a formatted table of configured primary providers, their health status, failure counts, last outcome, and reset timestamps.

### Requirement: Budget and fallback observability via API
The system SHALL provide REST API endpoints to query token usage, committed spend, active reservations, daily/monthly budget caps, remaining headroom, unresolved settlements, policy breach status, and OpenRouter fallback configuration status with full secret redaction.

#### Scenario: Query budget usage and spend status via API
- **WHEN** a client sends `GET /budget/usage` or `GET /projects/{project_id}/budget`
- **THEN** the API returns structured JSON with daily and monthly spend caps (UTC), committed spend, currently reserved spend, remaining reservable headroom, unresolved settlements count and amounts, policy breach flag (`is_breached`), and token usage breakdown by canonical model.

#### Scenario: Query OpenRouter fallback status via API
- **WHEN** a client sends `GET /providers/openrouter/status`
- **THEN** the API returns structured JSON indicating whether OpenRouter fallback is enabled, allowed canonical models for implementer and reviewer roles, active budget status, policy breach status, recent fallback invocation counts, and fallback denial reasons if any.

#### Scenario: Secret redaction in observability endpoints
- **WHEN** any budget or provider status endpoint is queried
- **THEN** all provider API keys, tokens, and authorization headers are completely redacted.

### Requirement: Budget and fallback observability via CLI
The system SHALL provide CLI commands to inspect budget consumption against caps, active reservations, token usage breakdowns, policy breach status, and OpenRouter fallback readiness.

#### Scenario: Inspect budget usage via CLI
- **WHEN** an operator runs `minime budget status`
- **THEN** the CLI displays a formatted summary of daily and monthly spend against configured caps (UTC), committed spend, active reservations, remaining headroom, unresolved settlements, and policy breach warnings if present.

#### Scenario: Inspect OpenRouter fallback status via CLI
- **WHEN** an operator runs `minime providers openrouter`
- **THEN** the CLI displays fallback enablement, configured allowed canonical models, pricing snapshot rates, policy health (`is_breached`), and recent fallback execution metrics.
