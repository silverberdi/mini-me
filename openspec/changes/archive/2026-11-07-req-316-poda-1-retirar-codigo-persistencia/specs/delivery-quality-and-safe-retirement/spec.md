# Spec Delta

## MODIFIED Requirements

### Requirement: Superseded code is retired safely

The system SHALL retire only routes, controllers, services, models, tables, tests, dependencies, or configuration demonstrated to have no legitimate consumers within the active UI and authorized runtime. The active UI surface (Dashboard, Trabajo, Trabajo actual, Proyectos, Backlog y Administración de modelos) SHALL define the functional perimeter of mini me. Code and data structures not reachable from this perimeter SHALL be retired within the same Change. Candidate test validation SHALL be compared against the immutable baseline execution established by the operator prior to the pruning.

#### Scenario: Obsolete route has no consumers

- **WHEN** static, dynamic, and configuration consumers demonstrate that a replaced route is orphaned
- **THEN** the Change SHALL remove the orphaned implementation and relevant tests/configuration and SHALL execute the affected regression tests
- **AND** it SHALL record concise consumer evidence rather than a mandatory universal ledger

#### Scenario: Historical or active consumer remains

- **WHEN** a candidate route or data structure still has a legitimate consumer or historical compatibility obligation
- **THEN** the Change SHALL preserve it and record the reason briefly
- **AND** it SHALL not remove it solely because it is old or textually unmatched
- **AND** historical R01–R10 references SHALL not justify removal without current consumer evidence

#### Scenario: Route or service has no active UI consumer

- **GIVEN** an API route, controller, or backend service in mini me
- **WHEN** static, dynamic, and configuration auditing proves zero active consumers from the current UI views or authorized OpenSpec coordination
- **THEN** the Change SHALL remove the orphaned route, service, and unused dependencies
- **AND** it SHALL remove the obsolete tests that specifically covered the retired code without deleting tests of active flows
- **AND** it SHALL record verified zero-consumer evidence.

#### Scenario: Candidate validation against immutable baseline

- **GIVEN** an operator-established test execution baseline on an identified pre-pruning SHA
- **WHEN** the pruned candidate change is evaluated
- **THEN** all retained unit, integration, and E2E tests for active flows SHALL pass (exit code 0)
- **AND** the candidate test result SHALL match or improve upon the baseline without regressions in active functionality.

#### Scenario: Archival inventory of retired features

- **WHEN** features, routes, services, or persistence structures are retired in the Change
- **THEN** the Change SHALL record an archival inventory document (`docs/evidence/poda-1-inventario-features-retiradas.md`)
- **AND** it SHALL record for each retired feature its historical purpose, removed files/routes/tables, and reference commit/SHA for future recovery.
