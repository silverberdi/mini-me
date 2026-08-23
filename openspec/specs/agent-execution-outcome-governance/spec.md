# agent-execution-outcome-governance Specification

## Purpose
Provides normalized machine-readable execution outcome classification, deterministic fail-closed completion verification, and durable multi-attempt execution tracking for AI implementers.

## Requirements

### Requirement: Normalized execution outcome classification
The system SHALL classify every executor process result into a normalized, machine-readable outcome enum: `COMPLETED`, `CHANGES_REQUIRED`, `PREMATURE_STOP`, `FALSE_BLOCKER`, `REAL_BLOCKER`, `NO_PROGRESS`, `POLICY_VIOLATION`, `MALFORMED_RESULT`, `PROVIDER_FAILURE`, `PROVIDER_EXHAUSTED`, `ENVIRONMENT_UNAVAILABLE`, or `EVIDENCE_INSUFFICIENT`, and persist this classification alongside attempt execution evidence in PostgreSQL.

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

### Requirement: Fail-closed completion verification
The system SHALL independently verify implementation completion claims by inspecting OpenSpec task checkbox state, worktree git status, presence of required candidate artifacts, deterministic check exit codes, and candidate commit SHA before advancing a job to the review phase.

#### Scenario: Executor claims completion with pending OpenSpec tasks
- **WHEN** an executor reports completion but `openspec/changes/<change_id>/tasks.md` contains uncompleted checkboxes
- **THEN** completion verification SHALL fail closed, classify the outcome as `PREMATURE_STOP` or `EVIDENCE_INSUFFICIENT`, and block transition to review.

#### Scenario: Executor claims completion with failing deterministic checks
- **WHEN** an executor claims completion but one or more configured deterministic checks exit with non-zero status
- **THEN** completion verification SHALL fail closed, classify the outcome as `CHANGES_REQUIRED`, and record the failing check evidence.

#### Scenario: Unmodified worktree on completion claim
- **WHEN** an executor reports completion but `git status --porcelain` and `git diff` against base SHA show zero candidate file modifications
- **THEN** completion verification SHALL fail closed, classify the outcome as `NO_PROGRESS`, and prevent review invocation.

### Requirement: Durable execution attempt persistence
The system SHALL persist every execution attempt in PostgreSQL with an incremental attempt number, executor role and model identity, worktree start/end SHAs, execution duration, raw and redacted logs, normalized outcome classification, progress metrics, and verification results.

#### Scenario: Multi-attempt history retained
- **WHEN** an execution job runs across multiple attempts due to retries or reassignment
- **THEN** each attempt is saved as a discrete record linked to the `job_id`, preserving full auditability of what each agent attempted and produced.
