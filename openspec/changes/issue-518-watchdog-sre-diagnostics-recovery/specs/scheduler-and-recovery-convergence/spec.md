## MODIFIED Requirements

### Requirement: Single Canonical Recovery Authority
Watchdog-triggered recovery SHALL enter through the existing `NativeOrchestrationCoordinator` execution path and its persisted run/stage claim, recovery, candidate, gate, and idempotency checks. The Watchdog SHALL NOT create a parallel recovery authority or independently drive continuation; any other existing continuation entry point SHALL preserve the same durable safety rules. Diagnosis may observe and classify durable evidence but SHALL NOT mutate run state, claims, candidate worktrees, or dispatch state.

#### Scenario: Startup, tick, direct resume, and Watchdog share authority
- **WHEN** continuation is requested by daemon startup, scheduler tick, REST/CLI resume, TUI/control-plane continue/retry, post-merge reconciliation, or Watchdog
- **THEN** each request SHALL resolve through the same recovery authority
- **AND** no entry point SHALL bypass durable claim/fencing or Stage F fresh-admission authority

#### Scenario: Diagnosis is read-only until canonical recovery accepts mutation
- **WHEN** the Watchdog identifies a possible stall or recovery action
- **THEN** it MAY persist its diagnosis through the authorized evidence path
- **AND** it SHALL NOT edit claims, run lifecycle state, candidate worktrees, or dispatch state directly
- **AND** any recovery mutation SHALL be accepted and performed through the current canonical claim/fencing authority

#### Scenario: Startup, tick, and direct resume share authority
- **GIVEN** identical durable run, claim, candidate, and gate evidence
- **WHEN** continuation is requested by daemon startup, scheduler tick, REST/CLI resume, TUI/control-plane continue/retry, post-merge reconciliation, or Watchdog
- **THEN** Watchdog continuation SHALL enter through `NativeOrchestrationCoordinator` and the existing run/stage recovery checks
- **AND** no entry point SHALL bypass durable claim/fencing or Stage F fresh-admission authority
