## MODIFIED Requirements

### Requirement: GitHub outage does not corrupt internal state
A GitHub synchronization or PR preparation failure SHALL be observable and reconcilable without deleting durable project/change/orchestration state, creating duplicate external work, or authorizing a PR whose head differs from the final independently audited candidate.

#### Scenario: PR creation is idempotent
- **GIVEN** a final candidate has passed all required checks, review, and audit
- **WHEN** orchestration prepares the GitHub PR more than once because of retry or restart
- **THEN** the integration uses a durable idempotency identity and reconciles one PR bound to the project/change and exact audited head SHA.

#### Scenario: GitHub is temporarily unavailable
- **GIVEN** internal evidence is complete but GitHub cannot be reached
- **WHEN** PR preparation fails transiently
- **THEN** the run preserves all internal evidence and stops in `WAITING_EXTERNAL` without marking the candidate ready for human merge.

#### Scenario: Unexpected remote identity is detected
- **WHEN** repository, base branch, PR binding, or remote head SHA differs from the durable project binding or audited candidate
- **THEN** the system records a structured invariant failure and stops for human attention without changing the binding or pushing a different candidate.

#### Scenario: External action reservation precedes mutation
- **WHEN** orchestration requests a branch push or PR create/update
- **THEN** a durable action identity, target identity, and request fingerprint are reserved and committed before the GitHub/Git mutation; failure to reserve prevents the mutation.

#### Scenario: GitHub synchronization is temporarily unavailable
- **GIVEN** durable project/change state already exists
- **WHEN** GitHub synchronization fails transiently
- **THEN** internal state remains intact and the synchronization failure is recorded for later reconciliation.
