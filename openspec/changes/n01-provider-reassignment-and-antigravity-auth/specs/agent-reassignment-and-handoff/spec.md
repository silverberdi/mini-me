## ADDED Requirements

### Requirement: Human executor reassignment is durable and fenced
The Control Plane SHALL persist a successful explicit REASSIGN choice for the linked Job under the canonical run recovery claim and SHALL NOT start provider execution as part of REASSIGN.

#### Scenario: Explicit reassignment supersedes an older automatic handoff
- **GIVEN** an inactive Run with a linked Job, an older unconsumed automatic JobHandoff, and a human-authorized REASSIGN to an eligible configured provider
- **WHEN** the REASSIGN action is accepted and a subsequent authorized CONTINUE runs
- **THEN** the Job executor used by recovery and ExecutionPipeline SHALL be the explicitly reassigned provider
- **AND** the action record and fenced Job executor update SHALL be durable and idempotent
- **AND** no attempt, retry, or reassignment counter SHALL be reset
- **AND** existing provider capacity, health, and anti-loop limits SHALL remain enforced.

#### Scenario: Reassignment cannot bypass provider availability or anti-loop limits
- **GIVEN** a requested executor is not configured, is exhausted/unavailable, or the Job reached the canonical reassignment ceiling
- **WHEN** an operator requests REASSIGN
- **THEN** the Control Plane SHALL reject the request without changing the executor or invoking a provider.

#### Scenario: Reassignment and continuation remain separate actions
- **GIVEN** a valid inactive Run and linked Job
- **WHEN** REASSIGN succeeds
- **THEN** the result SHALL report the durable executor assignment only
- **AND** execution SHALL begin only after a separate authorized CONTINUE action.
