# Spec Delta

## Purpose

Conecta las capacidades funcionales posteriores al MVP visual con las autoridades existentes de mini me, preservando la fuente remota, la continuidad de Changes, los permisos y la evidencia verificable.

## ADDED Requirements

### Requirement: Governed F7 enablement
F7 SHALL admit operational work only when F6 is closed and an explicit human authorization for this Change is durably recorded. Until then, the `disabled` state SHALL prevent Request admission, model execution and server intervention; planning artifacts alone SHALL NOT enable runtime behavior.

#### Scenario: Authorization enables the governed flow
- **WHEN** the recorded authorization names Issue #189 and Change `gacela-07-capacidades-diferidas`
- **THEN** the system SHALL remove `disabled` through the governed path and SHALL expose the F7 operations for admission
- **AND** it SHALL retain an auditable authorization record

#### Scenario: Missing prerequisite remains fail-closed
- **WHEN** F6 is not closed or the specific authorization is absent
- **THEN** no F7 Request SHALL be admitted, model SHALL be invoked, or server operation performed
- **AND** the remote item SHALL remain labeled `disabled`

### Requirement: Single executor and deferred transitions
The system SHALL maintain exactly one selected executor project per installation and SHALL serialize project changes and global/project pauses through the existing orchestration and PostgreSQL continuity authorities. A requested transition SHALL stop new admissions, allow the active Change to complete through PR2 and remote closure, and only then apply the new selection or pause; idle transitions SHALL apply immediately. The system SHALL NOT kill processes, discard worktrees, create duplicate Runs, or introduce a scheduler or parallel execution engine.

#### Scenario: Only the selected project executes
- **WHEN** multiple projects are registered and one is selected as executor
- **THEN** only that project SHALL admit and execute Requests
- **AND** other projects SHALL remain non-executing without parallel admission

#### Scenario: Project change is deferred
- **WHEN** the operator requests a different executor while a Change is active
- **THEN** the current Change SHALL finish through PR2 and remote closure
- **AND** no subsequent Request SHALL be admitted until the transition completes

#### Scenario: Pause is deferred or immediate
- **WHEN** a project or global pause is requested
- **THEN** an active Change SHALL finish fully before the pause takes effect
- **AND** an idle installation/project SHALL pause immediately
- **AND** F2 administrative `ACTIVE`/`PAUSED` SHALL remain distinct from effective execution pause

### Requirement: Provider-agnostic logical Request management
The configured ticket provider SHALL be the authority for Request creation, editing, deactivation, reactivation and logical deletion. Physical deletion SHALL NOT occur. Only a Request not durably admitted may be freely edited, deactivated or logically deleted; a logically deleted Request SHALL preserve remote audit history and SHALL be excluded from FIFO.

#### Scenario: Manage a not-started Request
- **WHEN** the operator edits, deactivates, reactivates or logically deletes a Request that has not been admitted
- **THEN** the provider SHALL confirm the resulting state
- **AND** the system SHALL preserve the original remote identity and audit trail

#### Scenario: Reject mutation after admission
- **WHEN** a Request is admitted, in progress or finished and the operator requests free editing, deactivation or deletion
- **THEN** the operation SHALL be rejected without mutation
- **AND** an in-progress Request SHALL accept clarifications only through `HUMAN_REQUIRED`
- **AND** a finished Request SHALL remain immutable from this UI

### Requirement: Human input uses F4 normalization
New Requests SHALL require a human title, natural-language description and natural-language acceptance criteria. The system SHALL preserve the original body and provenance, invoke the existing F4 normalizer before Explore, publish or verify complete Given/When/Then criteria, and elevate material ambiguity through `HUMAN_REQUIRED`; the form SHALL NOT require operator-authored Gherkin or reimplement normalization.

#### Scenario: Normalize a complete human Request
- **WHEN** a valid human Request reaches its FIFO turn
- **THEN** the original title/body/criteria and provenance SHALL be preserved remotely
- **AND** F4 SHALL publish verified Gherkin before Explore

#### Scenario: Material ambiguity requires a human
- **WHEN** authoritative context cannot resolve a material business decision
- **THEN** the Request SHALL pause at `HUMAN_REQUIRED` with the original question/options or a grounded clarification
- **AND** Explore SHALL not proceed by inventing requirements

### Requirement: Verifiable projections and governed integrations
Dashboard, Projects and Request views SHALL display only data backed by a technical source and valid denominator, distinguishing unavailable from zero. Where available, projections MAY report model/window quota or remaining capacity, iterations, avoidable clarifications versus mandatory authorizations, execution/wait time, and tokens or cost per Request. Document context editing SHALL be versioned, authorized and auditable; unsupported providers such as ADO SHALL not be implemented before need.

#### Scenario: Missing metric source
- **WHEN** a metric lacks a real source or denominator
- **THEN** the UI SHALL show unavailable
- **AND** it SHALL not show fabricated progress, quota or cost

#### Scenario: Authorized context version
- **WHEN** an operator edits document context through an available authorized route
- **THEN** the system SHALL use version/optimistic-concurrency checks, preserve history and report the resulting version
- **AND** arbitrary repository path writes SHALL be rejected

### Requirement: Secure, idempotent real integration
Every F7 operation SHALL be authorized in the backend and enforce permissions, optimistic concurrency, idempotency, traceability and safe retirement while reusing existing action, intake, normalization, PostgreSQL and Git/PR contracts. A real E2E scenario with a compatible provider SHALL observe invocation, provider result and durable effects; mocks SHALL not be presented as E2E evidence.

#### Scenario: Stale or duplicate command
- **WHEN** a command has stale project/Request/run state or is submitted again with the same idempotency key
- **THEN** the stale command SHALL be rejected without an unauthorized side effect
- **AND** the duplicate SHALL return its persisted result without duplicating transitions or remote mutations

#### Scenario: Real provider E2E
- **WHEN** a compatible provider executes a F7 operation in an E2E run
- **THEN** evidence SHALL show the authorized invocation, remote result, durable transition and observable effect
- **AND** failure or ambiguous evidence SHALL fail closed
