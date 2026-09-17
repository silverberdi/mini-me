## MODIFIED Requirements

### Requirement: Structured readiness evaluation
The system SHALL evaluate readiness criteria and return structured unmet reasons rather than treating mere directory presence or unverified local metadata as READY, SHALL require remote GitHub Issue verification against the bound repository via the canonical GitHub App runtime identity, and SHALL require that the OpenSpec change passes strict validation (`openspec validate --strict --type change`) before being marked READY.

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

#### Scenario: OpenSpec strict validation fails

- **GIVEN** a discovered change whose OpenSpec artifacts fail `openspec validate --strict --type change`
- **WHEN** readiness is evaluated
- **THEN** the change is marked NOT_READY with a structured unmet reason containing the validation failure details
- **AND** the reason SHALL distinguish between missing artifacts, malformed artifacts, invalid capability references, and other validation error categories.

#### Scenario: OpenSpec strict validation passes

- **GIVEN** a discovered change whose OpenSpec artifacts pass `openspec validate --strict --type change` and all other readiness criteria are met
- **WHEN** readiness is evaluated
- **THEN** the change is marked READY.

#### Scenario: Artifact completeness is independent from strict validation

- **GIVEN** a change missing a required planning artifact
- **WHEN** readiness is evaluated
- **THEN** the existing artifact-completeness gate blocks readiness
- **AND** the canonical strict-validation result is reported truthfully without an artificial override.
