## MODIFIED Requirements

### Requirement: Atomic state transitions
The system SHALL transition execution jobs through explicit validated operational statuses, including `QUEUED`, `RUNNING`, `CHECKS_RUNNING`, `CHECKS_PASSED`, `REVIEW_RUNNING`, `AUDIT_RUNNING`, `READY_TO_MERGE`, `AUDIT_BLOCKED`, `CHANGES_REQUIRED`, `CHECKS_FAILED`, `WAITING_CAPACITY`, `NEEDS_HUMAN`, `FAILED`, and `CANCELLED`, while storing orchestration stages and human-gate outcomes in separate durable orchestration state. Evidence diagnostics SHALL NOT be treated as job lifecycle statuses, and an orchestration stage SHALL NOT be inferred from a job status alone.

#### Scenario: Job and orchestration transition together without authority duplication
- **WHEN** an orchestration checkpoint requires an operational job transition
- **THEN** the relevant job status, orchestration stage event, and timing/evidence facts are committed atomically where they share a transition, while each remains queryable from its own authority.

#### Scenario: Human gate does not overload JobStatus
- **WHEN** the final audited candidate is ready for human merge
- **THEN** the orchestration human gate records `READY_FOR_HUMAN_MERGE` and the operational job retains its applicable terminal operational status rather than receiving an invented orchestration phase.

#### Scenario: Invalid orchestration advancement is rejected
- **WHEN** a caller attempts to advance a run from a stage without its required committed evidence or from a terminal human gate
- **THEN** the transition is rejected and neither the job status nor orchestration checkpoint is changed.

#### Scenario: Valid status transition recorded atomically
- **WHEN** an active job transitions to a subsequent operational phase
- **THEN** the job status is updated in PostgreSQL within the same transaction that appends the corresponding state transition event and timing metric.

#### Scenario: Invalid state transition rejected
- **WHEN** a transition is attempted from a terminal job state to `RUNNING`
- **THEN** the system rejects the transition and keeps the job in its terminal state.

#### Scenario: Review only initiated after checks pass
- **WHEN** a job completes deterministic checks
- **THEN** review is launched only if all checks passed with exit code 0; otherwise the job remains `CHECKS_FAILED` and review/audit are not launched.

#### Scenario: Audit only initiated after complementary review produces READY_TO_MERGE
- **WHEN** complementary review produces `READY_TO_MERGE`
- **THEN** the job transitions to `AUDIT_RUNNING`; a changes-required, failed, timed-out, or malformed review does not launch audit.

#### Scenario: Deterministic audit risk gating
- **WHEN** DeepSeek Direct audit concludes
- **THEN** only an audit with `0 CRITICAL`, `0 HIGH`, and `0 MEDIUM` findings can provide the evidence needed for the orchestration human gate; LOW findings may remain only when explicitly reported and non-blocking.

#### Scenario: Job transitions to WAITING_CAPACITY upon primary provider exhaustion
- **WHEN** an in-flight job requires an exhausted or unavailable primary provider
- **THEN** the job transitions to `WAITING_CAPACITY` and records the provider and reason without corrupting prior evidence.

#### Scenario: Job transitions to NEEDS_HUMAN upon unresolvable condition
- **WHEN** an execution job encounters an unresolvable blocker, exhausted reassignment ceiling, or irreconcilable policy/invariant conflict
- **THEN** the job transitions to `NEEDS_HUMAN` with structured escalation rationale.
