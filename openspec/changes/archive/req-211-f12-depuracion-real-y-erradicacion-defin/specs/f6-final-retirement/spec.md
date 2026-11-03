# Spec Delta

## MODIFIED Requirements

### Requirement: F6 retirement is inventory-bound and dependency-safe
For the authorized retirement Change, mini me SHALL maintain a reviewable inventory of code, callers, writers, endpoints, flags, dependencies, tests, documentation, migrations, worktrees, jobs/claims, bindings and durable references, with each item classified as REUSE, MODIFY, REMOVE or RETAIN-WITH-REASON. The inventory SHALL include the F12 TUI, legacy web/API/CLI, OpenSpec-emulation and obsolete-test targets. An item SHALL NOT be removed when a live capability, active test/closure, audit trail, candidate identity or legitimate historical obligation still consumes it.

#### Scenario: Obsolete surface has no legitimate consumer
- **WHEN** static reachability, configuration inspection and applicable runtime evidence show that an F12 target has no live consumer and its replacement is retained
- **THEN** the target and only its exclusive tests/configuration SHALL be removed in the same Change
- **AND** the affected retained behavior SHALL be revalidated after removal.

#### Scenario: Active or historical dependency is discovered
- **WHEN** the inventory finds an active consumer, durable job/claim, audit record, candidate/worktree identity, applied migration or historical OpenSpec evidence
- **THEN** the item SHALL be retained or migrated with an explicit reason and owner
- **AND** the Change SHALL NOT delete or mutate it merely because it is old or textually unmatched.

### Requirement: Post-retirement proof is real and bound to the candidate
The retirement Change SHALL execute deterministic checks and a real applicable E2E journey after code, dependency and schema retirement. Evidence SHALL identify the candidate SHA, migration revision and database identity where applicable, observed invocation and result, retained-path effects, denied or absent obsolete paths, and unresolved human gates. Mocks, health checks, task counts or self-claims SHALL NOT establish an integration criterion.

#### Scenario: Retained product path works after cleanup
- **WHEN** the post-retirement E2E runs against the authorized candidate and real applicable interfaces
- **THEN** retained behavior SHALL complete with expected observable effects
- **AND** evidence SHALL link the result to the immutable candidate SHA.

#### Scenario: Obsolete path or external postcondition is not proven
- **WHEN** an obsolete endpoint/command remains reachable, a target deletion cannot be observed, or the E2E result is simulated, missing or ambiguous
- **THEN** the Change SHALL fail closed as incomplete or human-required
- **AND** SHALL NOT claim final retirement succeeded.

