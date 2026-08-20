# Project Registry Specification

## Purpose
Register projects with immutable identity and explicit execution policy so mini me can address repositories safely and consistently.

## Requirements

### Requirement: Immutable internal project identity
Each registered project SHALL have an immutable internal project identifier distinct from its display name.

#### Scenario: Project display name changes
- **GIVEN** a registered project with an internal project identifier
- **WHEN** its human-readable display name is changed
- **THEN** the internal project identifier remains unchanged.

### Requirement: Required project policy
Project registration SHALL capture canonical repository identity, base branch, OpenSpec path, configured implementer/reviewer roles, deterministic checks, and relevant provider/deployment policy placeholders.

#### Scenario: Required project policy is incomplete
- **GIVEN** a project registration request missing a required policy field
- **WHEN** registration is validated
- **THEN** the project is not considered execution-ready
- **AND** the missing policy field is reported structurally.

### Requirement: Complementary primary roles
When both primary roles are configured, the system SHALL require implementer and reviewer to be Codex/Antigravity complements rather than the same primary agent.

#### Scenario: Same primary agent is configured for both roles
- **GIVEN** a project configuration that assigns the same primary agent as implementer and reviewer
- **WHEN** the configuration is validated
- **THEN** validation fails with a complementary-role policy reason.
