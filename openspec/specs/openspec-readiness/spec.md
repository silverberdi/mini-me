# OpenSpec Readiness Specification

## Purpose
Discover active OpenSpec work and enforce a structured Definition of Ready before any change becomes executable.

## Requirements

### Requirement: Active OpenSpec discovery
The system SHALL discover active OpenSpec changes and their standard artifacts for registered projects.

#### Scenario: Registered project contains an active change
- **GIVEN** a registered project with an OpenSpec directory
- **WHEN** the project contains an active change with standard artifacts
- **THEN** the change is discovered and associated with that registered project.

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

### Requirement: Runtime state remains outside OpenSpec
The system SHALL NOT write provider quota, retry, process, scheduler or other mutable runtime status into OpenSpec artifacts.

#### Scenario: Runtime status changes
- **GIVEN** a discovered OpenSpec change
- **WHEN** mutable runtime state changes in mini me
- **THEN** that runtime state is persisted outside OpenSpec
- **AND** the OpenSpec artifacts remain unchanged by that runtime transition.

### Requirement: Only current roadmap work becomes executable
The system SHALL enforce policy that prevents later-roadmap work from becoming READY merely because its files exist.

#### Scenario: Future roadmap change exists on disk
- **GIVEN** a later-roadmap OpenSpec change is present in the repository
- **WHEN** readiness is evaluated while an earlier required stage remains active
- **THEN** the later change is not marked READY
- **AND** the readiness result identifies roadmap gating as the reason.
