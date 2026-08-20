# PostgreSQL Durable State Specification

## Purpose
Provide PostgreSQL-backed durable operational state, versioned schema evolution, and restart-safe evidence for mini me.

## Requirements

### Requirement: PostgreSQL is the runtime state store
The system SHALL use PostgreSQL as the operational persistence engine and SHALL NOT require SQLite for normal or development runtime behavior.

#### Scenario: mini me starts with valid PostgreSQL configuration
- **GIVEN** a valid PostgreSQL connection is configured
- **WHEN** mini me starts its persistence layer
- **THEN** operational state is stored in PostgreSQL
- **AND** no SQLite runtime database is required.

### Requirement: Versioned schema evolution
The system SHALL evolve the operational schema through versioned Alembic migrations.

#### Scenario: Database schema is behind the application version
- **GIVEN** a PostgreSQL database whose schema is behind the required revision
- **WHEN** the migration command is executed
- **THEN** Alembic applies the versioned migrations to the required revision.

### Requirement: Durable current state and event evidence
The system SHALL persist externally meaningful current state and corresponding auditable event evidence so daemon restart does not forget registered or discovered work.

#### Scenario: Daemon restarts
- **GIVEN** a registered project and discovered change were committed
- **WHEN** the daemon process restarts
- **THEN** the project/change and their last durable state remain visible
- **AND** the corresponding event evidence remains queryable.
