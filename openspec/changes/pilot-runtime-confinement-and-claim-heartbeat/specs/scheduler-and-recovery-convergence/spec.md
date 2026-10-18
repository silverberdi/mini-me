## ADDED Requirements

### Requirement: Operational Heartbeat in Direct Coordinator Drive
When the orchestration service executes run stage transitions via `drive_coordinator`, the system SHALL maintain an active `OperationalHeartbeat` for the supplied `claim_context` throughout stage evaluation, long-running agent execution, and deterministic checks, renewing the claim lease at periodic intervals strictly less than one-third of the configured lease duration.

#### Scenario: Long-running agent execution does not expire recovery claim
- **GIVEN** an active orchestration run executing an agent implementation pass that takes longer than the base lease duration (e.g. 10 minutes vs 60 seconds)
- **WHEN** the stage completes and the coordinator attempts a fenced stage transition
- **THEN** the recovery claim lease SHALL have been renewed periodically via isolated database session
- **AND** the fenced compare-and-swap update SHALL succeed with `rowcount == 1`
- **AND** the run SHALL NOT fail with `StaleClaimError`.

#### Scenario: Nested or duplicate heartbeats are prevented
- **GIVEN** an orchestration run initiated through recovery convergence where an outer operational heartbeat is already active for the claim
- **WHEN** `drive_coordinator` is entered with the existing claim context
- **THEN** `drive_coordinator` SHALL detect the existing heartbeat and avoid spawning a redundant renewal thread
- **AND** only one active heartbeat loop SHALL renew the claim in PostgreSQL.

#### Scenario: Heartbeat renewal failure stops coordinator safely
- **GIVEN** an active coordinator driving a run under an operational claim
- **WHEN** heartbeat renewal fails (e.g. due to database connection loss or claim fence supersede by another node)
- **THEN** the coordinator SHALL detect the heartbeat failure
- **AND** the coordinator SHALL stop execution immediately without advancing stages
- **AND** existing run state, candidate SHA, and evidence SHALL remain durably preserved in PostgreSQL.
