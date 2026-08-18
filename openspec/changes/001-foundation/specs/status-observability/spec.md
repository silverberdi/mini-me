## Purpose
Expose safe Foundation health, readiness, correlation, and metric facts needed to operate mini me and diagnose blocked work.

## ADDED Requirements

### Requirement: Health and status surface
The system SHALL expose a minimal API and CLI surface showing database health, registered projects, discovered changes, and readiness reasons.

#### Scenario: Operator requests Foundation status
- **GIVEN** mini me is running with registered projects
- **WHEN** the operator requests status through the supported API or CLI
- **THEN** database health, registered projects, discovered changes, and readiness reasons are returned.

### Requirement: Structured correlation
Operational logging and evidence SHALL include stable correlation identifiers for project, change, and operation and SHALL apply secret redaction.

#### Scenario: Operation emits diagnostic evidence
- **GIVEN** an operation associated with a project and change
- **WHEN** logs or durable evidence are emitted
- **THEN** stable correlation identifiers are included
- **AND** configured secret values are not exposed in the emitted evidence.

### Requirement: Metrics facts begin at Foundation
The system SHALL persist timestamps and outcome facts sufficient to later derive discovery/readiness timing and attempt/outcome metrics without relying only on current state.

#### Scenario: Readiness changes over time
- **GIVEN** a discovered change whose readiness is evaluated more than once
- **WHEN** the readiness state changes
- **THEN** timestamped facts are retained so the transition timing can be derived later
- **AND** the previous historical evidence is not replaced solely by current state.
