## ADDED Requirements

### Requirement: Checks-Only Environmental Failure Checkpoint Recovery
The system SHALL provide an explicit, fenced recovery entry point (`recover_checks_only`) that resumes an orchestration run from a preserved candidate without invoking primary or fallback implementer models, without creating new implementer attempts, and without executing OpenSpec APPLY workflows.

#### Scenario: Authorized recovery executes checks directly without model inference
- **WHEN** checks-only recovery is requested for an active run where the active job status is `CHECKS_FAILED` and candidate SHA exists
- **THEN** the recovery convergence service SHALL acquire an authoritative recovery claim with an active lease heartbeat
- **AND** the system SHALL NOT invoke Codex, Antigravity, DeepSeek, or OpenRouter models
- **AND** the system SHALL execute deterministic checks directly inside the preserved worktree
- **AND** zero new implementer attempts SHALL be persisted to PostgreSQL.

#### Scenario: Check passage advances and halts at review pending
- **WHEN** deterministic checks execute and all configured commands exit with return code 0
- **THEN** the system SHALL persist new check results bound to the exact candidate SHA and generation
- **AND** the active job status SHALL transition from `CHECKS_RUNNING` to `CHECKS_PASSED`
- **AND** the run SHALL advance to `FREEZING_CANDIDATE` to materialize candidate manifest and candidate records
- **AND** the recovery execution SHALL stop at a durable review-pending checkpoint without automatically dispatching reviewer or auditor models.

#### Scenario: Check failure persists without runaway implementer loop
- **WHEN** deterministic checks execute and any check fails
- **THEN** the system SHALL persist the fresh check failure diagnostics
- **AND** the active job status SHALL transition from `CHECKS_RUNNING` to `CHECKS_FAILED`
- **AND** the run SHALL stop fail-closed at `NEEDS_HUMAN`
- **AND** the system SHALL NOT dispatch an automated code repair attempt without human authorization.

### Requirement: Fail-Closed Tuple and Environmental Fault Verification
Checks-only recovery SHALL fail closed and refuse execution if any element of the authoritative durable checkpoint tuple diverges from disk state, if candidate authority is corrupt, or if prior check failure evidence does not substantiate a proven runner environmental fault.

#### Scenario: Authoritative tuple validation
- **WHEN** checks-only recovery evaluates preflight eligibility
- **THEN** the system SHALL verify:
  - `run.is_active` is True and `run.active_job_id == job.id`
  - `run.base_sha == job.base_sha`
  - `job.candidate_sha` is non-empty and `git -C <worktree> rev-parse HEAD == job.candidate_sha`
  - Generation authority is derived from `run.current_generation` (acknowledging `Job` possesses no generation property)
  - Worktree working tree is clean (`git status --porcelain` is empty).

#### Scenario: Pre-freeze candidate state characterization
- **WHEN** checks-only recovery runs for a candidate that failed checks before freezing
- **THEN** the system SHALL recognize that no `OrchestrationCandidate` row or review manifest exists yet
- **AND** the system SHALL NOT fail preflight due to the absence of a frozen candidate row
- **AND** the system SHALL NOT fabricate a frozen candidate row prior to check passage.

#### Scenario: Environmental fault proof from latest check attempt
- **WHEN** prior check failure diagnostics for the active job and candidate are inspected
- **THEN** checks-only recovery SHALL require verifiable proof of a runner environmental fault (`PermissionError: [Errno 13] Permission denied: '/dev/null'` or process confinement preflight failure)
- **AND** if the diagnostics indicate application test assertion, compilation, or syntax errors, recovery SHALL fail closed and refuse execution.

#### Scenario: Superseded claim fence aborts recovery
- **WHEN** another worker holds or supersedes the claim token for the run
- **THEN** checks-only recovery SHALL raise `StaleClaimError`
- **AND** zero database writes SHALL be committed.

### Requirement: Single-Batch Check Completeness and Evidence Preservation
When checks-only recovery executes, the system SHALL require that every configured project check executes and passes within the single authorized recovery batch, preserving historical evidence without stale evidence inheritance.

#### Scenario: All configured project checks must pass in single batch
- **WHEN** deterministic checks execute under checks-only recovery
- **THEN** every check command defined in `project.checks` SHALL execute in the current execution batch
- **AND** `job.status` SHALL NOT transition to `CHECKS_PASSED` if any configured check is missing or unexecuted in that batch.

#### Scenario: Stale check results are never inherited
- **WHEN** checks-only recovery evaluates check results for stage transition
- **THEN** results from prior failed attempts SHALL NOT be counted as passing evidence for the current execution
- **AND** all historical `check_results` and `evidence_diagnostics` rows SHALL remain immutably preserved in PostgreSQL.

### Requirement: Single Heartbeat Ownership and Fenced Teardown
`recover_checks_only` SHALL maintain exclusive ownership of the recovery claim heartbeat, propagating claim authority to coordinator execution without creating nested heartbeat threads or duplicate claim releases.

#### Scenario: Outer recovery manages heartbeat and delegates cleanly
- **WHEN** `recover_checks_only` invokes coordinator execution
- **THEN** it SHALL pass `manage_heartbeat=False` and the active `claim_context`
- **AND** the coordinator SHALL NOT spawn an inner heartbeat thread
- **AND** the coordinator SHALL NOT release the claim upon stage completion.

#### Scenario: Unclean teardown or blocked renewal suppresses claim release
- **WHEN** heartbeat renewal is blocked or thread teardown exceeds timeout
- **THEN** `recover_checks_only` SHALL mark `heartbeat_failed=True`, roll back uncommitted changes, suppress claim release, and return status `BLOCKED`.
