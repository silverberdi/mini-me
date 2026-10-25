## Purpose

Make a small, observable set of agent capabilities available to Greenfield projects through existing F2 preparation, without duplicating OpenSpec, security guards, or provider catalogs.

## ADDED Requirements

### Requirement: Greenfield installation uses the existing capability catalog

The system SHALL resolve compatible skills, hooks, commands, and harnesses from the observed project/provider catalog and SHALL install only capabilities required by the configured profiles and supported by the project.

#### Scenario: Greenfield receives compatible capabilities

- **WHEN** a Greenfield project is created and its profiles and provider capabilities are verified
- **THEN** the bootstrap SHALL reuse the existing project preparation, catalog, OpenSpec official setup, and provider conventions
- **AND** the selected capabilities SHALL be available to the configured agents

#### Scenario: Unsupported capability fails closed

- **WHEN** a required capability or official integration cannot be observed or used by its selected provider
- **THEN** the bootstrap SHALL preserve the project and report the concrete incompatibility
- **AND** it SHALL NOT emulate OpenSpec or silently substitute another provider

### Requirement: Capability installation is idempotent and non-destructive

The system SHALL resume or repeat Greenfield installation without duplicating compatible resources, overwriting unrelated files, copying runtime-only protections into the project, or losing source and checkpoint evidence.

#### Scenario: Existing compatible resource is reused

- **WHEN** a resumed bootstrap finds a compatible skill, hook, command, harness, or OpenSpec integration
- **THEN** it SHALL reuse and verify that resource without reinstalling it or producing duplicates

#### Scenario: Real conflict is preserved

- **WHEN** an existing resource conflicts with the requested capability and safe reconciliation is unavailable
- **THEN** the bootstrap SHALL retain the candidate and report the conflict for the existing recovery path
- **AND** it SHALL NOT overwrite the resource speculatively

### Requirement: Installation is restricted to Greenfield

The system SHALL install or alter the F4 capability package only during Greenfield bootstrap; Brownfield projects SHALL retain their existing files and configuration.

#### Scenario: Brownfield is not modified

- **WHEN** a project is identified as Brownfield
- **THEN** F4 SHALL not install or modify its skills, hooks, commands, harnesses, or provider configuration
- **AND** no Greenfield readiness claim SHALL be fabricated for it

### Requirement: Readiness is a light observable preflight

The system SHALL reuse the existing preflight, confinement, worktree, authentication, capacity, and catalog evidence to verify only indispensable capabilities before declaring Greenfield readiness.

#### Scenario: Ready project can select installed skills

- **WHEN** Greenfield installation finishes
- **THEN** the preflight SHALL verify the selected Codex and Antigravity capabilities and OpenSpec integration as observed by the configured profiles
- **AND** the project SHALL be ready only when indispensable capabilities are usable

#### Scenario: Later stage does not reinstall routinely

- **WHEN** F3 starts a new invocation for an already prepared project
- **THEN** it SHALL use the prepared resources and perform only the light availability checks required by the existing lifecycle
- **AND** it SHALL not spend quota on routine reinstallation

#### Scenario: Greenfield is ready for mini me to execute F5

- **WHEN** the Greenfield bootstrap is used to prepare the mini me project itself for the later F5 phase
- **THEN** the isolated validation SHALL demonstrate the configured Codex and Antigravity profiles, official OpenSpec workflow resolution, Worktree identity, confinement, and GitHub coordination bindings
- **AND** it SHALL record the capability evidence without executing or installing F5
- **AND** it SHALL not modify Brownfield projects, production, PostgreSQL operational state, or the scheduler

