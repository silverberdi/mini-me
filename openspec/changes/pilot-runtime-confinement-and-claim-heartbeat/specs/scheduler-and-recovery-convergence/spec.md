## ADDED Requirements

### Requirement: Explicit Operational Heartbeat Ownership across Trajectories
The system SHALL enforce a single explicit owner for `OperationalHeartbeat` lifecycle management per execution trajectory, ensuring consistent claim renewal across multi-minute stages without duplicate renewal threads or uncoordinated lease expirations.

#### Scenario: Direct admission coordinator explicitly manages heartbeat
- **GIVEN** an orchestration run initiated via direct admission (`SchedulerService.admit_work_item(drive_admitted=True)` or `orchestrate start`)
- **WHEN** `drive_coordinator` begins driving stages with a valid `claim_context`
- **THEN** `drive_coordinator` SHALL explicitly instantiate and own an `OperationalHeartbeat` with interval strictly less than one-third of the configured lease duration
- **AND** the heartbeat SHALL renew the claim periodically via isolated database session
- **AND** `drive_coordinator` SHALL reliably stop the heartbeat and idempotently release the claim in a `finally` block upon completion.

#### Scenario: Recovery continuation delegates without nested duplicate heartbeats
- **GIVEN** an orchestration run resumed via `RecoveryConvergenceService` or `orchestrate resume` where an outer `OperationalHeartbeat` already manages the claim
- **WHEN** `drive_coordinator` is entered for continuation
- **THEN** the caller SHALL explicitly indicate that heartbeat ownership is externally managed
- **AND** `drive_coordinator` SHALL NOT spawn a secondary heartbeat renewal thread
- **AND** `drive_coordinator` SHALL NOT release the outer claim upon stage exit.

#### Scenario: Claim release is strictly idempotent
- **GIVEN** an operational recovery claim that has already been released, expired, or superseded
- **WHEN** `release_claim` is invoked during cleanup or error handling
- **THEN** the operation SHALL complete safely as a no-op without raising unhandled exceptions
- **AND** no active successor claim or incremented fence token SHALL be modified.

### Requirement: Fencing Fail-Closed without Post-Loss Database Mutations
A worker whose claim lease has expired, whose heartbeat renewal has failed, or whose fencing token has been superseded SHALL NOT perform any mutating database operations, SHALL NOT write `NEEDS_HUMAN` or stage events to PostgreSQL, and SHALL halt immediately with `StaleClaimError`.

#### Scenario: Heartbeat renewal failure aborts without database writes
- **GIVEN** an active coordinator driving a run under an operational claim
- **WHEN** heartbeat renewal fails (e.g. database disconnect or query failure)
- **THEN** the coordinator SHALL detect the failure before attempting any subsequent stage mutation
- **AND** the coordinator SHALL NOT execute `_stop_run`, SHALL NOT update `current_stage`, and SHALL NOT commit the database session
- **AND** the process SHALL raise `StaleClaimError` and roll back uncommitted changes
- **AND** existing run state, candidate SHA, and evidence SHALL remain preserved for legitimate recovery.

#### Scenario: Superseded worker cannot mutate run or release successor claim
- **GIVEN** worker A holds a claim that expires or is superseded by worker B with a higher fencing token
- **WHEN** worker A completes an external execution step and attempts a fenced stage update
- **THEN** the compare-and-swap query SHALL match zero rows
- **AND** worker A SHALL NOT alter the run state, job state, or recovery claim
- **AND** cleanup in worker A SHALL NOT release worker B's active claim.
