## Purpose

Defines observable behavior for orchestration attempt evaluation when deterministic checks fail (`JobStatus.CHECKS_FAILED`), preventing zero-delay hot loops and enforcing canonical attempt retry limits.

## MODIFIED Requirements

### Requirement: Continuation Decision Fallback and Precedence
The orchestration coordinator SHALL resolve attempt continuation decisions at the `EVALUATING_ATTEMPT` stage by preferring a non-null `latest_att.continuation_decision` over `job.continuation_decision`. IF `latest_att` exists but `latest_att.continuation_decision` is `None`, the coordinator SHALL fall back to `job.continuation_decision`.

#### Scenario: Fallback to job decision when attempt decision is null
- **WHEN** an orchestration run is evaluated at `EVALUATING_ATTEMPT` stage
- **AND** the latest attempt exists with `continuation_decision` equal to `None`
- **AND** `job.continuation_decision` is set to `CORRECT_AND_RETRY`
- **THEN** the effective decision SHALL evaluate to `CORRECT_AND_RETRY`

#### Scenario: Attempt decision retains precedence when non-null
- **WHEN** an orchestration run is evaluated at `EVALUATING_ATTEMPT` stage
- **AND** the latest attempt has a non-null `continuation_decision` (such as `NEEDS_HUMAN`)
- **AND** `job.continuation_decision` is set to `CORRECT_AND_RETRY`
- **THEN** the effective decision SHALL evaluate to `NEEDS_HUMAN`

### Requirement: Corrective Continuation Dispatch for Failing Checks
WHEN a job has status `CHECKS_FAILED` AND the effective decision is a corrective continuation (`CORRECT_AND_RETRY`, `CONTINUE_SAME_AGENT`, or `REASSIGN_AGENT`), the orchestration coordinator SHALL NOT transition back to `RUNNING_CHECKS`. IF canonical attempt retry budget permits (`len(attempts) < 2`), the coordinator SHALL transition directly to `IMPLEMENTING`.

#### Scenario: Corrective continuation dispatches to IMPLEMENTING when retry permitted
- **WHEN** a job has status `CHECKS_FAILED`
- **AND** the effective decision is `CORRECT_AND_RETRY`
- **AND** `len(attempts) < 2`
- **THEN** the coordinator SHALL transition to `IMPLEMENTING`
- **AND** the coordinator SHALL NOT transition back to `RUNNING_CHECKS`

#### Scenario: Corrective continuation terminates when retry budget exhausted
- **WHEN** a job has status `CHECKS_FAILED`
- **AND** the effective decision is `CORRECT_AND_RETRY`
- **AND** `len(attempts) >= 2`
- **THEN** the coordinator SHALL stop the run with `NEEDS_HUMAN` status
- **AND** stop details SHALL record `CHECKS_FAILED_RETRY_EXHAUSTED`
- **AND** no duplicate attempt SHALL be dispatched

### Requirement: Indefinite Hot-Loop Elimination
A job in `CHECKS_FAILED` status SHALL NEVER bounce indefinitely between `EVALUATING_ATTEMPT` and `RUNNING_CHECKS`. It MUST always achieve bounded forward progress to either `IMPLEMENTING` or a terminal `NEEDS_HUMAN` state.

#### Scenario: Hot loop prevented for failing checks without decision
- **WHEN** a job has status `CHECKS_FAILED` with persisted failing checks
- **AND** no continuation decisions are set (`decision` is `None`)
- **AND** `len(attempts) >= 2`
- **THEN** the coordinator SHALL stop the run with `NEEDS_HUMAN` status (`CHECKS_FAILED_RETRY_EXHAUSTED`)
- **AND** SHALL NOT loop back to `RUNNING_CHECKS`
