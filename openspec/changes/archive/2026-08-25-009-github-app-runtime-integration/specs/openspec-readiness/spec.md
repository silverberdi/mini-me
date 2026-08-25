## MODIFIED Requirements

### Requirement: Structured readiness evaluation
The system SHALL evaluate readiness criteria and return structured unmet reasons rather than treating mere directory presence or unverified local metadata as READY, and SHALL require remote GitHub Issue verification against the bound repository via the canonical GitHub App runtime identity.

#### Scenario: Change is missing a readiness prerequisite
- **GIVEN** a discovered change that lacks a required binding or readiness criterion
- **WHEN** readiness is evaluated
- **THEN** the change is not marked READY
- **AND** a structured unmet reason identifies the blocking criterion.

#### Scenario: Remote Issue existence and ownership are verified
- **GIVEN** a discovered change with a durable ProjectBinding and bound Issue number
- **WHEN** readiness is evaluated
- **THEN** the system queries the GitHub App runtime adapter to verify the Issue exists in the bound repository
- **AND** readiness is granted only if remote verification succeeds.

#### Scenario: Nonexistent or mismatched Issue fails readiness
- **GIVEN** a change whose bound Issue does not exist remotely or belongs to a different repository
- **WHEN** readiness is evaluated
- **THEN** the change is marked NOT_READY with a structured unmet reason describing the Issue verification failure.
