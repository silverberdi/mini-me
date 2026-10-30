# f6-final-retirement Specification

## Purpose

Define the observable final-retirement contract for F6: remove only proven-obsolete
surfaces and durable state, preserve legitimate history and continuity, reconcile
the inherited E2E fixture, and prove the retained product still works after cleanup.

## Requirements

### Requirement: F6 retirement is inventory-bound and dependency-safe

For the authorized F6 Change, mini me SHALL maintain a reviewable inventory of code, callers, writers, endpoints, flags, dependencies, tests, documentation, migrations, worktrees, jobs/claims, bindings and durable references, with each item classified as REUSE, MODIFY, REMOVE or RETAIN-WITH-REASON. An item SHALL NOT be removed when a live F2–F5 capability, active test/closure, audit trail, candidate identity or legitimate historical obligation still consumes it.

#### Scenario: Obsolete surface has no legitimate consumer

- **WHEN** static reachability, configuration inspection and runtime evidence show that an F6 target has no live consumer and its replacement is already retained
- **THEN** the target and only its exclusive tests/configuration SHALL be removed in the same Change
- **AND** the affected retained behavior SHALL be revalidated after removal

#### Scenario: Active or historical dependency is discovered

- **WHEN** the inventory finds an active consumer, durable job/claim, audit record, candidate/worktree identity, applied migration, or historical OpenSpec evidence
- **THEN** the item SHALL be retained or migrated with an explicit reason and owner
- **AND** F6 SHALL NOT delete or mutate it merely because it is old or textually unmatched

### Requirement: PostgreSQL retirement preserves recoverability

F6 SHALL remove unused PostgreSQL tables or columns only through versioned Alembic migrations after confirming their data and writers are obsolete. Before a destructive migration, the process SHALL preserve the required backup, verify the target database is the authorized operational or explicitly disposable database, and provide a tested rollback or an explicit human authorization for an irreversible exception; it SHALL NOT auto-repair or silently discard operational history.

#### Scenario: Safe obsolete schema migration

- **WHEN** an unused table or column is confirmed to have no writers, readers, active references or retention obligation
- **THEN** an Alembic migration SHALL remove it while preserving required data backup evidence
- **AND** upgrade, physical postcondition and downgrade/rollback checks SHALL be recorded against the intended database identity

#### Scenario: Database identity or rollback is not proven

- **WHEN** the target database identity, backup, dependency census or rollback is unavailable or ambiguous
- **THEN** F6 SHALL fail closed before the destructive migration
- **AND** SHALL leave the schema and durable operational state unchanged

### Requirement: The inherited fixture is reconciled before any irreversible deletion

Before deleting `silverberdi/mini-me-r01-e2e-20261014`, F6 SHALL verify that F2–F5, active tests, active closures and any authorized reconciliation no longer depend on the `mini-me-fixture` repository, its bindings, worktrees, budget, jobs/claims or durable references. The deletion SHALL require explicit human authorization tied to the confirmed scope and SHALL be performed only as an F6 side effect.

#### Scenario: Fixture remains needed or reconciliation is incomplete

- **WHEN** any active or required test, closure, binding, worktree, job/claim, budget record or durable reference still depends on the fixture
- **THEN** the repository SHALL be preserved
- **AND** F6 SHALL report the dependency as a blocker without attempting deletion

#### Scenario: Authorized fixture deletion completes

- **WHEN** the dependency census is clear and explicit human authorization identifies the exact private repository
- **THEN** the deletion operation SHALL target only `silverberdi/mini-me-r01-e2e-20261014`
- **AND** a subsequent authoritative GitHub read SHALL prove the repository is absent
- **AND** mini me SHALL report no remaining operational references, without deleting historical evidence or credentials

### Requirement: Post-retirement proof is real and bound to the candidate

F6 SHALL execute deterministic checks and a real E2E journey after code, dependency and schema retirement. Evidence SHALL identify the candidate SHA, migration revision and database identity where applicable, the observed invocation and result, retained-path effects, denied obsolete paths, fixture postcondition, and any unresolved human gate. Mocks, health checks, task counts or self-claims SHALL NOT establish completion of an integration criterion.

#### Scenario: Retained product path works after cleanup

- **WHEN** the post-retirement E2E runs against the authorized candidate and real applicable interfaces
- **THEN** the retained F2–F5 behavior SHALL complete with its expected observable effects
- **AND** evidence SHALL be linked to the immutable candidate SHA and actual execution result

#### Scenario: Obsolete path or external postcondition is not proven

- **WHEN** an obsolete endpoint/command remains reachable, the fixture deletion cannot be observed, or the E2E result is simulated, missing or ambiguous
- **THEN** F6 SHALL fail closed as incomplete or human-required
- **AND** SHALL NOT claim that final retirement or Change completion succeeded

### Requirement: F6 does not activate future phases

F6 SHALL NOT implement or enable F7 request mutations, deferred pause/project switching, missing metrics/context capabilities, or the Angular F8 migration, and SHALL NOT deploy production or start a scheduler merely to create or validate this Change.

#### Scenario: Future capability is encountered during cleanup

- **WHEN** a candidate change would require adding an F7/F8 capability or production deployment
- **THEN** the work SHALL stop at the F6 boundary and record the item as out of scope
- **AND** no future-phase behavior SHALL be activated
