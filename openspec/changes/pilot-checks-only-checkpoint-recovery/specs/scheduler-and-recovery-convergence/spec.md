## ADDED Requirements

### Requirement: Checks-Only Environmental Failure Checkpoint Recovery
The system SHALL provide an explicit, fenced recovery entry point (`recover_checks_only`) that resumes an orchestration run from a preserved candidate without invoking primary or fallback implementer models, without creating new implementer attempts, and without executing OpenSpec APPLY workflows.

#### Scenario: Authorized recovery executes checks directly
- **WHEN** checks-only recovery is requested for an active run where the active job status is `CHECKS_FAILED` and candidate SHA exists
- **THEN** the recovery convergence service SHALL acquire an authoritative recovery claim with an active lease heartbeat
- **AND** the system SHALL NOT invoke Codex, Antigravity, or OpenRouter implementer runners
- **AND** the system SHALL execute deterministic checks directly inside the preserved worktree
- **AND** zero new implementer attempts SHALL be persisted to PostgreSQL.

#### Scenario: Check passage advances to freezing and review
- **WHEN** deterministic checks execute and all configured commands exit with return code 0
- **THEN** the system SHALL persist new check results bound to the exact candidate SHA and generation
- **AND** the active job status SHALL transition to `CHECKS_PASSED`
- **AND** the run SHALL advance to `FREEZING_CANDIDATE` and downstream review stages.

#### Scenario: Check failure persists without runaway implementer loop
- **WHEN** deterministic checks execute and any check fails
- **THEN** the system SHALL persist the fresh check failure diagnostics
- **AND** the active job status SHALL remain `CHECKS_FAILED`
- **AND** the run SHALL stop fail-closed at `NEEDS_HUMAN`
- **AND** the system SHALL NOT dispatch an automated code repair attempt without human authorization.

### Requirement: Fail-Closed Tuple and Environmental Fault Verification
Checks-only recovery SHALL fail closed and refuse execution if any element of the full durable checkpoint tuple diverges from disk state or if prior check failure evidence does not substantiate an environmental or sandbox runner fault.

#### Scenario: Mismatched worktree HEAD is rejected
- **WHEN** the git HEAD SHA in the assigned worktree does not exactly match `job.candidate_sha`
- **THEN** checks-only recovery SHALL fail closed before executing checks
- **AND** the system SHALL raise a validation error and commit zero mutations.

#### Scenario: Check failure without environmental fault evidence is rejected
- **WHEN** prior check failure diagnostics indicate application test assertion or compilation failures rather than sandbox runner faults (`/dev/null` access failure or process confinement unavailability)
- **THEN** checks-only recovery SHALL reject execution
- **AND** the operator SHALL be informed that code-level remediation is required.

#### Scenario: Superseded claim fence aborts recovery
- **WHEN** another worker holds or supersedes the claim token for the run
- **THEN** checks-only recovery SHALL raise `StaleClaimError`
- **AND** zero database writes SHALL be committed.

### Requirement: Atomic Checkpoint State Reconciliation and Evidence Preservation
When checks-only recovery executes, the system SHALL reconcile the durable discrepancy between Run stage `IMPLEMENTING` and Job status `CHECKS_FAILED` without deleting or modifying historical attempt records or prior diagnostic evidence.

#### Scenario: Historical evidence is preserved
- **WHEN** checks-only recovery executes and stores new check results
- **THEN** preexisting `check_results` and `evidence_diagnostics` for prior failed executions SHALL remain intact in PostgreSQL
- **AND** the historical base SHA and candidate SHA references SHALL not be rewritten.
