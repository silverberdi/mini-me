# Spec Delta

## MODIFIED Requirements

### Requirement: Versioned schema evolution

The system SHALL evolve the operational schema through versioned Alembic migrations, SHALL verify physical table and column invariants in PostgreSQL derived from canonical SQLAlchemy metadata before admitting orchestration runs, failing closed with `SCHEMA_INVARIANT_VIOLATION` if migration version matches head but required application tables or required columns (including `reviews.is_mixed_authorship`) are absent, without performing automatic database repairs, and SHALL retire unused historical tables, columns, or relations only through reversible Alembic migrations. Retiring tables or schema elements SHALL require verified zero-consumer evidence from active UI and coordination paths, SHALL preserve or export historical data where required, and SHALL NOT execute destructive operations or schema modifications against production databases.

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

#### Scenario: Unused table or column retirement via Alembic migration
- **GIVEN** a table, column, or relation identified as orphan with zero active readers, writers, or UI consumers
- **WHEN** the schema retirement migration is applied
- **THEN** Alembic applies the versioned downgrade-safe migration
- **AND** canonical SQLAlchemy metadata is updated to remove the retired model
- **AND** the physical schema invariant check matches the updated canonical metadata head.

#### Scenario: Production isolation during schema retirement
- **GIVEN** a candidate change retiring orphaned persistence structures
- **WHEN** tests, checks, or migrations are executed during change verification
- **THEN** execution SHALL target only isolated, disposable databases
- **AND** the operation SHALL fail closed if pointed at the production database environment.
