# Execution Jobs Specification

## Purpose

Provides durable PostgreSQL-backed state tracking, atomic lifecycle state transitions, timing metrics, and structured event logs for implementation execution jobs.

## Requirements

### Requirement: Durable execution job tracking
The system SHALL persist execution jobs in PostgreSQL with unique immutable job IDs, referencing the target project ID, change ID, configured implementer role, and status.

#### Scenario: Job created in queued state
- **WHEN** a job execution is triggered for an eligible READY change
- **THEN** an execution job record is inserted with status `QUEUED`, capturing `project_id`, `change_id`, `implementer`, creation timestamp, and an initial `JOB_QUEUED` event.

### Requirement: Atomic state transitions
The system SHALL transition execution jobs through explicit validated statuses: `QUEUED` → `RUNNING` → `CHECKS_RUNNING` → `CHECKS_PASSED` → `REVIEW_RUNNING` → `AUDIT_RUNNING` → `READY_TO_MERGE` / `AUDIT_BLOCKED` / `CHANGES_REQUIRED` / `CHECKS_FAILED` / `FAILED` / `CANCELLED`.

#### Scenario: Valid status transition recorded atomically
- **WHEN** an active job transitions to a subsequent phase (e.g. from `REVIEW_RUNNING` to `AUDIT_RUNNING`, or `AUDIT_RUNNING` to `READY_TO_MERGE` / `AUDIT_BLOCKED`)
- **THEN** the job status is updated in PostgreSQL within the same database transaction that appends the corresponding state transition event and timing metric.

#### Scenario: Invalid state transition rejected
- **WHEN** a transition is attempted from a terminal state (e.g. `FAILED`, `AUDIT_BLOCKED`, or `READY_TO_MERGE` to `RUNNING`)
- **THEN** the system SHALL reject the transition with a validation error and keep the job in its terminal state.

#### Scenario: Review only initiated after checks pass
- **WHEN** a job completes deterministic checks
- **THEN** review is launched ONLY if all checks passed with exit code 0; if any check failed, the job terminates at `CHECKS_FAILED` without launching review or audit.

#### Scenario: Audit only initiated after complementary review produces READY_TO_MERGE
- **WHEN** complementary review produces a `READY_TO_MERGE` verdict
- **THEN** the system transitions the job to `AUDIT_RUNNING` and executes DeepSeek Direct audit; if the reviewer returned `CHANGES_REQUIRED`, `REVIEW_FAILED`, `REVIEW_TIMED_OUT`, or malformed output, the job terminates in the review failure/correction state without executing audit.

#### Scenario: Deterministic audit risk gating
- **WHEN** DeepSeek Direct audit execution concludes
- **THEN** if overall risk is `low` or `medium` (with no `critical` or `high` severity findings), the job transitions to `READY_TO_MERGE`; if overall risk is `high` or `critical`, or if any finding has severity `high` or `critical`, the job transitions to `AUDIT_BLOCKED`, preventing progression to human merge.

### Requirement: Job timing and metric retention
The system SHALL calculate and persist phase durations (implementer duration, checks duration, review duration, audit duration, total duration) as structured metric facts.

#### Scenario: Metrics persisted upon terminal state
- **WHEN** a job completes execution or reaches a terminal state
- **THEN** metric facts for `implementer_duration_ms`, `checks_duration_ms`, `review_duration_ms`, `audit_duration_ms`, and `total_duration_ms` are recorded in the `metric_facts` table.
