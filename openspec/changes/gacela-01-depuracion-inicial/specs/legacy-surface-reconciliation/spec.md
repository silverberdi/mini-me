## Purpose

Makes the remaining public surfaces and historical artifacts accurately represent the limited F1 capability rather than exposing retired or future behavior.

## ADDED Requirements

### Requirement: Retired public operations fail clearly
mini me SHALL remove or disable API, CLI, UI, and service entry points that depend exclusively on retired legacy behavior. A retained compatibility endpoint or command SHALL return an explicit unavailable error naming the deferred phase; it SHALL NOT report success, enqueue work, or invoke the old flow.

#### Scenario: API client calls a retired operation
- **WHEN** an authenticated client calls an endpoint retained solely to report transition status for a removed operation
- **THEN** it SHALL receive a machine-readable unavailable response with no mutation
- **AND** the response SHALL identify whether replacement belongs to F2, F3, F4, F5, or F6 when known.

#### Scenario: CLI invokes a retired command
- **WHEN** an operator invokes a CLI command whose prior behavior required a removed legacy subsystem
- **THEN** the command SHALL exit non-zero with an actionable unavailable message
- **AND** SHALL NOT activate scheduler, agents, migrations, or an historical Change.

### Requirement: Historical OpenSpec artifacts are reconciled as read-only evidence
mini me SHALL inventory non-archived historical Changes and conflicting specifications, record their relationship to the six-phase plan, and treat them as non-executable evidence until a later authorized reconciliation action. F1 SHALL NOT apply, continue, archive, delete, or silently reactivate them.

#### Scenario: Historical Change directory is discovered
- **WHEN** a non-archived historical Change directory is present in the repository
- **THEN** the F1 inventory SHALL record its slug, status, conflicts, and any real external or durable reference
- **AND** SHALL not infer an active execution from the directory alone.

#### Scenario: Historical work is actually active
- **WHEN** the inventory finds a live process, durable active record, or confirmed external operation tied to historical work
- **THEN** mini me SHALL preserve it and report it as a reconciliation blocker
- **AND** SHALL not terminate, mutate, or advance it automatically.

#### Scenario: Historical specification conflicts with the rector contract
- **WHEN** a historical specification prescribes behavior that contradicts `docs/CONTRATO_RECTOR.md` or an F1 delta specification
- **THEN** mini me SHALL preserve the historical file unchanged and record the conflict in the in-design reconciliation inventory
- **AND** SHALL map it to its owning F2–F6 phase for reconciliation by the installed native OpenSpec update workflow before that phase applies code
- **AND** SHALL NOT execute, revive, or derive F1 behavior from that historical requirement.

### Requirement: Regression evidence measures simplification
F1 acceptance SHALL include deterministic evidence that retired symbols have no active consumers, retained paths still function, and the runnable application does not expose a route to the retired behavior. Test doubles, health checks, or self-claims alone SHALL NOT prove this result.

#### Scenario: Post-retirement verification
- **WHEN** F1 implementation is verified after code and schema retirement
- **THEN** the evidence SHALL include static reachability checks, focused unit/integration tests, a real API/CLI functional flow for retained capabilities, and a denied invocation of each retired operation
- **AND** SHALL identify the candidate SHA and migration revision used for the checks.
