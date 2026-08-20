# GitHub Work Binding Specification

## Purpose
Provide durable GitHub work-tracking identifiers while ensuring presentation metadata never becomes execution authority.

## Requirements

### Requirement: Durable GitHub identifiers
The system SHALL persist repository Issue and global Project item identifiers associated with a project/change without using their display text as execution identity.

#### Scenario: Persist GitHub work identifiers without display-name authority
- **GIVEN** a registered project and discovered OpenSpec change
- **WHEN** a GitHub Issue and global Project item are associated with that change
- **THEN** their durable identifiers are persisted with the project/change binding
- **AND** issue titles, labels, Project fields, or display names do not become execution identity.

### Requirement: GitHub outage does not corrupt internal state
A GitHub synchronization failure SHALL be observable and reconcilable without deleting durable project/change state.

#### Scenario: GitHub synchronization is temporarily unavailable
- **GIVEN** durable project/change state already exists
- **WHEN** GitHub synchronization fails transiently
- **THEN** the internal state remains intact
- **AND** the synchronization failure is recorded for later reconciliation.
