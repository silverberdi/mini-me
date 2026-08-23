## MODIFIED Requirements

### Requirement: Atomic state transitions
The system SHALL transition execution jobs through explicit validated statuses: `QUEUED` → `RUNNING` → `CHECKS_RUNNING` → `CHECKS_PASSED` → `REVIEW_RUNNING` → `AUDIT_RUNNING` → `READY_TO_MERGE` / `AUDIT_BLOCKED` / `CHANGES_REQUIRED` / `CHECKS_FAILED` / `WAITING_CAPACITY` / `NEEDS_HUMAN` / `FAILED` / `CANCELLED`, supporting multi-attempt continuation loops before terminal disposition. Evidence diagnostics (such as `REVIEW_ENVIRONMENT_INVALID` or `ENVIRONMENT_UNAVAILABLE`) SHALL NOT be treated as job lifecycle statuses.

#### Scenario: Valid status transition recorded atomically
- **WHEN** an active job transitions to a subsequent phase (e.g. from `REVIEW_RUNNING` to `AUDIT_RUNNING`, or `AUDIT_RUNNING` to `READY_TO_MERGE` / `AUDIT_BLOCKED` / `NEEDS_HUMAN`)
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

#### Scenario: Job transitions to WAITING_CAPACITY upon primary provider exhaustion
- **WHEN** an in-flight job requires an implementer or reviewer whose primary provider is exhausted or unavailable
- **THEN** the job transitions to `WAITING_CAPACITY` and records the exhaustion event and blocking provider without corrupting prior phase evidence.

#### Scenario: Job transitions to NEEDS_HUMAN upon unresolvable condition
- **WHEN** an execution job encounters an unresolvable real blocker, reaches the maximum allowed reassignment ceiling, or detects irreconcilable policy/invariant conflict
- **THEN** the system SHALL transition the job status to `NEEDS_HUMAN` and record the structured escalation rationale.
