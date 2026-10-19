## ADDED Requirements

### Requirement: Claim-Fenced Job Terminal State on Checks Pipeline Exception
When an unexpected exception occurs during the execution of deterministic checks, the system SHALL atomically update the `Job` status to `CHECKS_FAILED` with the sanitized error message under recovery claim fencing before or in conjunction with stopping the parent `Run` in `NEEDS_HUMAN`.

#### Scenario: Unhandled checks exception leaves Job in CHECKS_FAILED
- **WHEN** `run_checks_only` or check execution fails with an unhandled exception (e.g. `PermissionError`, I/O failure)
- **THEN** the recovery worker transactionally transitions the associated `Job` from `CHECKS_RUNNING` to `CHECKS_FAILED` with the sanitized exception message
- **AND** the `Run` is stopped with outcome `NEEDS_HUMAN` and `human_gate=NEEDS_HUMAN`
- **AND** no `Job` remains trapped in an indeterminate `CHECKS_RUNNING` state while the `Run` is stopped and inactive.

### Requirement: Governed Re-Entry for Interrupted Checks Recovery
The recovery convergence authority SHALL permit authorized checks-only re-entry for a preserved candidate from the observed interrupted state (`RUNNING_CHECKS` / `NEEDS_HUMAN` Run with `CHECKS_FAILED` or `CHECKS_RUNNING` Job) when the failure is substantiated by a proven runner environmental fault, without mutating the candidate SHA or invoking AI models.

#### Scenario: Authorized checks-only recovery from interrupted state
- **GIVEN** an inactive Run in `current_stage=RUNNING_CHECKS` with `stop_outcome=NEEDS_HUMAN`
- **AND** the Job is in `CHECKS_FAILED` (or interrupted `CHECKS_RUNNING`) with verified environmental fault evidence (e.g. runner permissions or confinement setup failure)
- **AND** candidate SHA and worktree HEAD match exactly and worktree is clean
- **AND** durable managed repository binding is valid
- **WHEN** an operator authorizes `recover-checks` for this Run
- **THEN** `RecoveryConvergenceService` validates eligibility and admits the run directly into deterministic checks execution
- **AND** no OpenSpec APPLY attempt is created
- **AND** no model inference calls are dispatched.

#### Scenario: Re-entry rejected if candidate or worktree dirty
- **GIVEN** an interrupted checks Run
- **WHEN** worktree HEAD diverges from `job.candidate_sha` or contains uncommitted changes
- **THEN** recovery eligibility SHALL fail closed and reject admission with `PREFLIGHT_REJECTED`.
