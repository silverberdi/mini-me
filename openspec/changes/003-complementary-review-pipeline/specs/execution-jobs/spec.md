## MODIFIED Requirements

### Requirement: Atomic state transitions
The system SHALL transition execution jobs through explicit validated statuses: `QUEUED` → `RUNNING` → `CHECKS_RUNNING` → `CHECKS_PASSED` → `REVIEW_RUNNING` → `READY_TO_MERGE` / `CHANGES_REQUIRED` / `CHECKS_FAILED` / `FAILED` / `CANCELLED`.

#### Scenario: Valid status transition recorded atomically
- **WHEN** an active job transitions to a subsequent phase (e.g. from `CHECKS_PASSED` to `REVIEW_RUNNING`, or `REVIEW_RUNNING` to `READY_TO_MERGE`)
- **THEN** the job status is updated in PostgreSQL within the same database transaction that appends the corresponding state transition event and timing metric.

#### Scenario: Invalid state transition rejected
- **WHEN** a transition is attempted from a terminal state (e.g. `FAILED` or `READY_TO_MERGE` to `RUNNING`)
- **THEN** the system SHALL reject the transition with a validation error and keep the job in its terminal state.

#### Scenario: Review only initiated after checks pass
- **WHEN** a job completes deterministic checks
- **THEN** review is launched ONLY if all checks passed with exit code 0; if any check failed, the job terminates at `CHECKS_FAILED` without launching review.
