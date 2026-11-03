# Spec Delta

## MODIFIED Requirements

### Requirement: Retired public operations fail clearly
mini me SHALL remove API, CLI, UI and service entry points that depend exclusively on retired legacy behavior when no legitimate consumer or historical compatibility obligation remains. It SHALL NOT preserve a dead 410 transition route merely as a substitute for removal. A retained compatibility endpoint or command SHALL return an explicit unavailable error naming the deferred phase, with no mutation or old-flow invocation.

#### Scenario: Orphaned legacy operation is removed
- **WHEN** an authenticated client or operator targets a legacy dashboard, orchestration, queue, scheduler, control-plane, preview, validation, job or TUI operation with no legitimate consumer
- **THEN** the route/command and its exclusive tests/configuration SHALL be absent from the active application
- **AND** the invocation SHALL NOT enqueue work, invoke an agent or mutate state.

#### Scenario: Compatibility obligation remains
- **WHEN** an active or historical consumer requires a compatibility surface
- **THEN** the surface SHALL remain with a machine-readable unavailable response and no mutation
- **AND** the response SHALL identify the owning deferred phase when known.

#### Scenario: API client calls a retired operation
- **WHEN** an authenticated client calls an endpoint retained solely to report transition status for a removed operation
- **THEN** it SHALL receive a machine-readable unavailable response with no mutation
- **AND** the response SHALL identify whether replacement belongs to F2, F3, F4, F5, or F6 when known.

#### Scenario: CLI invokes a retired command
- **WHEN** an operator invokes a CLI command whose prior behavior required a removed legacy subsystem
- **THEN** the command SHALL exit non-zero with an actionable unavailable message
- **AND** SHALL NOT activate scheduler, agents, migrations, or an historical Change.
