## Purpose

Provides PostgreSQL-backed durable state tracking for review lifecycles, structured review records, and individual review findings.

## ADDED Requirements

### Requirement: Durable review record persistence
The system SHALL persist review records in PostgreSQL referencing the job ID, project ID, change ID, reviewer role, candidate SHA, base SHA, review status, and verdict.

#### Scenario: Review record created upon review launch
- **WHEN** a review stage is initiated for a candidate job
- **THEN** a `reviews` table record is inserted with status `REVIEW_RUNNING`, binding the exact candidate SHA and base SHA.

### Requirement: Review lifecycle state machine
The system SHALL transition review records through explicit statuses: `REVIEW_PENDING` → `REVIEW_RUNNING` → `REVIEW_COMPLETED` / `REVIEW_FAILED` / `REVIEW_TIMED_OUT`.

#### Scenario: Review completes successfully
- **WHEN** a reviewer process finishes and emits a valid structured verdict
- **THEN** the review record status is updated to `REVIEW_COMPLETED`, the verdict is persisted, and duration metrics are recorded in `metric_facts`.

#### Scenario: Restart recovery of review state
- **WHEN** the daemon restarts while review records exist in PostgreSQL
- **THEN** all committed review records, verdicts, and findings remain queryable without loss.

### Requirement: Structured review findings persistence
The system SHALL persist individual findings emitted by a review as structured records in the `review_findings` table linked to the review ID.

#### Scenario: Review findings recorded in PostgreSQL
- **WHEN** a review returns one or more findings
- **THEN** each finding is stored with `severity`, `location`, `violated_requirement`, and `expected_correction`.
