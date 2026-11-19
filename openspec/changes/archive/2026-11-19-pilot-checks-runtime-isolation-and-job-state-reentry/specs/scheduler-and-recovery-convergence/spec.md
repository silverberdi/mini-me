## ADDED Requirements

### Requirement: Claim-Fenced Job Terminal State on Checks Pipeline Exception
When an unexpected exception occurs during the execution of deterministic checks, the system SHALL atomically update the `Job` status to `CHECKS_FAILED` with the sanitized error message under recovery claim fencing before or in conjunction with stopping the parent `Run` in `NEEDS_HUMAN`, with zero database writes if the claim fence is lost.

#### Scenario: Non-fence runner exception commits CHECKS_FAILED and stops Run
- **WHEN** `run_checks_only` or check execution fails with an unhandled non-fence exception (e.g. `PermissionError`, I/O failure)
- **THEN** under valid recovery claim fence, the recovery worker transactionally transitions the associated `Job` from `CHECKS_RUNNING` to `CHECKS_FAILED` with the sanitized exception message and persists diagnostic evidence
- **AND** the `Run` is stopped with outcome `NEEDS_HUMAN` and `human_gate=NEEDS_HUMAN`
- **AND** the database transaction commits both updates atomically, ensuring no `Job` remains trapped in `CHECKS_RUNNING`.

#### Scenario: Fence loss during runner exception rolls back with zero writes
- **WHEN** claim fence is lost or heartbeat fails during check execution or exception handling
- **THEN** the system performs a complete rollback (`uow.rollback()`)
- **AND** writes zero rows to `jobs`, `orchestration_runs`, or `evidence_diagnostics` after fence loss.

### Requirement: Governed Re-Entry for Interrupted Checks Recovery
The recovery convergence authority SHALL permit authorized checks-only re-entry for a preserved candidate from the observed interrupted state (`RUNNING_CHECKS` / `NEEDS_HUMAN` Run with `CHECKS_FAILED` or interrupted `CHECKS_RUNNING` Job) only when the failure is substantiated by a proven latest runner environmental fault, without mutating the candidate SHA or invoking AI models.

#### Scenario: Authorized checks-only recovery from interrupted state
- **GIVEN** an inactive Run in `current_stage=RUNNING_CHECKS` with `stop_outcome=NEEDS_HUMAN`
- **AND** the Job is in `CHECKS_FAILED` (or interrupted `CHECKS_RUNNING`)
- **AND** the latest failure is proven in `Run.stop_details` with code `CHECKS_ONLY_PIPELINE_EXCEPTION` and an allowlisted environmental exception type (e.g. `PermissionError`), or proven sandbox preflight failure
- **AND** candidate SHA and worktree HEAD match exactly and worktree is clean
- **AND** durable managed repository binding is valid
- **WHEN** an operator authorizes `recover-checks` for this Run with explicit one-shot human authorization
- **THEN** `RecoveryConvergenceService` validates eligibility and admits the run directly into deterministic checks recovery under active claim fence
- **AND** eligibility alone does not execute; separate human authorization is required.

#### Scenario: Application code errors reject recovery re-entry
- **GIVEN** an interrupted checks Run
- **WHEN** prior check failure or latest execution evidence indicates an application code error (e.g. `AssertionError`, `SyntaxError`, `TypeError`, pytest failure)
- **THEN** recovery eligibility SHALL fail closed and reject admission with `PREFLIGHT_REJECTED`.

### Requirement: Fresh Checks Batch Execution on RUNNING_CHECKS Replay Edge
When a run resumes from `RUNNING_CHECKS` under authorized checks-only recovery, the orchestrator SHALL invoke `pipeline.run_checks_only()` to execute a fresh, single complete batch of checks rather than inspecting pre-existing historical check results.

#### Scenario: Fresh checks batch executed from RUNNING_CHECKS
- **WHEN** `drive_coordinator()` encounters an active run at `RUNNING_CHECKS` with `checks_only=True` and no passed batch for the current generation
- **THEN** it executes `pipeline.run_checks_only()` exactly once
- **AND** records new `CheckResult` records bound to the current generation, current candidate SHA, and fresh timestamps
- **AND** validates completeness against configured project checks (no duplicates, all exit code 0)
- **AND** freezes the identical candidate SHA `2fcad0ef73eb4766ca1bb6249a081cb4070ecced` without mutating code
- **AND** transitions to `NEEDS_HUMAN` / `REVIEW_AUTHORIZATION_PENDING`
- **AND** strictly avoids calling `execute_queued_job`, replaying OpenSpec APPLY, or dispatching AI models.
