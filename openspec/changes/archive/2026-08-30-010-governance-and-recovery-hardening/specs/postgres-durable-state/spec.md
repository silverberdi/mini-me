## MODIFIED Requirements

### Requirement: Versioned schema evolution
The system SHALL evolve the operational schema through versioned Alembic migrations, and SHALL verify physical table and column invariants in PostgreSQL derived from canonical SQLAlchemy metadata before admitting orchestration runs, failing closed with `SCHEMA_INVARIANT_VIOLATION` if migration version matches head but required application tables or required columns (including `reviews.is_mixed_authorship`) are absent, without performing automatic database repairs.

#### Scenario: Database schema is behind the application version
- **GIVEN** a PostgreSQL database whose schema is behind the required revision
- **WHEN** the migration command is executed
- **THEN** Alembic applies the versioned migrations to the required revision.

#### Scenario: Migration head present with missing application table fails admission
- **GIVEN** a PostgreSQL database where `alembic_version` is marked at head revision but one or more required application tables do not physically exist
- **WHEN** autonomous change admission or persistence preflight executes
- **THEN** the system SHALL fail closed, refuse admission with structured error `SCHEMA_INVARIANT_VIOLATION`, and NOT attempt automatic destructive schema repair.

#### Scenario: Migration head present with missing required column fails admission
- **GIVEN** a PostgreSQL database where `alembic_version` is marked at head revision and tables exist, but a required column (such as `reviews.is_mixed_authorship`) is missing from the physical schema
- **WHEN** autonomous change admission or persistence preflight executes
- **THEN** the system SHALL fail closed, refuse admission with structured error `SCHEMA_INVARIANT_VIOLATION`, and NOT attempt automatic schema repair.

#### Scenario: Valid physical schema passes preflight
- **GIVEN** a PostgreSQL database where `alembic_version` matches the expected head revision and all required tables and columns are physically verified
- **WHEN** autonomous change admission or persistence preflight executes
- **THEN** the physical schema invariant check passes and admission proceeds.

### Requirement: PostgreSQL is the runtime state store
The system SHALL use PostgreSQL as the operational persistence engine, SHALL NOT require SQLite for normal or development runtime behavior, and SHALL isolate the canonical operational database from candidate test execution by ensuring deterministic test suites cannot accidentally inherit canonical database credentials or execute destructive operations against non-disposable targets.

#### Scenario: mini me starts with valid PostgreSQL configuration
- **GIVEN** a valid PostgreSQL connection is configured
- **WHEN** mini me starts its persistence layer
- **THEN** operational state is stored in PostgreSQL
- **AND** no SQLite runtime database is required.

#### Scenario: Destructive tests target only explicitly disposable database
- **GIVEN** candidate test execution runs deterministic project checks or pytest
- **WHEN** tests perform schema mutations, resets, or destructive PostgreSQL assertions
- **THEN** the test environment SHALL require an explicitly isolated disposable database and verified expected database name
- **AND** the execution SHALL fail closed immediately if pointed at the canonical operational database URL.
