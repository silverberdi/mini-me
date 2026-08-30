## MODIFIED Requirements

### Requirement: Normalized execution outcome classification
The system SHALL classify every executor process result into a normalized, machine-readable outcome enum: `COMPLETED`, `CHANGES_REQUIRED`, `PREMATURE_STOP`, `FALSE_BLOCKER`, `REAL_BLOCKER`, `NO_PROGRESS`, `POLICY_VIOLATION`, `MALFORMED_RESULT`, `PROVIDER_FAILURE`, `PROVIDER_EXHAUSTED`, `ENVIRONMENT_UNAVAILABLE`, or `EVIDENCE_INSUFFICIENT`, and persist this classification alongside attempt execution evidence in PostgreSQL, ensuring transient provider infrastructure failures (`ProviderResultClass.TRANSIENT_ERROR`) map deterministically to `ExecutionOutcome.ENVIRONMENT_UNAVAILABLE` and `ContinuationDecision.WAIT_EXTERNAL` without incrementing corrective retry or reassignment counters.

#### Scenario: Successful execution outcome classified
- **WHEN** an executor finishes running and independent completion verification passes with all deterministic checks exiting 0, zero remaining OpenSpec tasks, and candidate commit verified
- **THEN** the system SHALL record the attempt outcome as `COMPLETED`.

#### Scenario: Premature executor termination detected
- **WHEN** an executor process exits claiming completion or stopping early, but OpenSpec tasks remain incomplete or candidate diff is missing expected changes
- **THEN** the system SHALL classify the attempt outcome as `PREMATURE_STOP` and reject transition to review.

#### Scenario: Malformed executor output payload
- **WHEN** an executor process returns invalid JSON or unparseable structured output
- **THEN** the system SHALL classify the attempt outcome as `MALFORMED_RESULT` and record the parse error.

#### Scenario: Provider exhaustion distinguished from execution failure
- **WHEN** an executor fails due to rate limits or HTTP 429 quota exhaustion from the provider API
- **THEN** the system SHALL classify the outcome as `PROVIDER_EXHAUSTED` rather than an implementation failure or premature stop.

#### Scenario: Transient provider error mapped deterministically to waiting state
- **WHEN** an executor execution encounters a transient network outage, connection reset, timeout, or HTTP 502/503/504 error from provider infrastructure (`ProviderResultClass.TRANSIENT_ERROR`)
- **THEN** the system SHALL classify the outcome as `ExecutionOutcome.ENVIRONMENT_UNAVAILABLE`
- **AND** the continuation engine SHALL decide `ContinuationDecision.WAIT_EXTERNAL`
- **AND** the orchestration coordinator SHALL stop the run in `OrchestrationStopOutcome.WAITING_EXTERNAL` preserving the resumable stage checkpoint
- **AND** the system SHALL NOT increment `corrective_retries_count` or `reassignment_count`.
