# run-autorecovery-and-autonomous-continuation Specification

## Purpose
Recupera de forma segura Runs huérfanos tras interrupciones y permite continuar etapas estándar cuando la evidencia durable lo autoriza, sin saltarse gates humanos ni mostrar acciones de ejecución engañosas.

## Requirements

### Requirement: Orphan Run recovery
The daemon SHALL detect non-terminal Runs whose worker lease or heartbeat is stale at startup, acquire a durable fenced recovery claim, and resume or reconcile them using canonical lifecycle rules.

#### Scenario: Interrupted implementation resumes
- **WHEN** the daemon starts with an orphan Run in IMPLEMENTING and a resumable checkpoint
- **THEN** it claims the Run once and resumes from that checkpoint without creating a duplicate Run or Job

#### Scenario: Recovery is fenced
- **WHEN** two daemon instances discover the same orphan Run
- **THEN** only one instance obtains the durable claim and the other records a non-owner result without dispatching provider work

### Requirement: Autonomous standard stage continuation
The system SHALL transition an active Run from IMPLEMENTING to RUNNING_TESTS and from RUNNING_TESTS to CODE_REVIEW only when the required durable evidence and policy conditions are satisfied, without artificial operator confirmation.

#### Scenario: Implementation evidence advances automatically
- **WHEN** implementation completes with valid candidate evidence and no blocking human gate
- **THEN** the Run advances to RUNNING_TESTS and persists the transition atomically

#### Scenario: Human gate remains authoritative
- **WHEN** a stage exposes HUMAN_REQUIRED or another canonical blocking gate
- **THEN** recovery pauses at that gate, preserves the original question/options, and does not auto-advance

### Requirement: Active-work admission protection
The system SHALL prevent and visually suppress starting a later Request while a project has an active Run that owns the current execution slot.

#### Scenario: Later ticket is blocked while Run active
- **WHEN** an operator views or attempts to start a later eligible Request during an active Run
- **THEN** the UI explains the block and the API rejects the duplicate admission without creating work

#### Scenario: Terminal Run releases admission
- **WHEN** the active Run reaches a canonical terminal state
- **THEN** the next eligible Request can be projected and admitted through the existing FIFO/lifecycle authority

### Requirement: Recovery holds expose an actionable reason
When an active Run cannot enter or resume a stage because an operator authorization or other recovery prerequisite is missing, the system SHALL expose the concrete unmet prerequisite and the authorized action that can resolve it through the existing human-gate/API/UI path. It SHALL NOT leave the Run in an opaque paused state without a current question, action, or specific reason. Showing an action SHALL NOT grant that authorization or bypass existing human, security, candidate-identity, or retry controls.

#### Scenario: Missing recovery authorization is actionable
- **GIVEN** a Run is paused because the required recovery authorization is absent
- **WHEN** the current stage state is presented to the operator
- **THEN** the gate or API response identifies the missing authorization and presents the existing authorized action that can supply it
- **AND** the Run remains paused until an authorized operator submits that action.

#### Scenario: No safe recovery action exists
- **GIVEN** a stage is blocked by an unmet prerequisite for which no authorized operator action exists
- **WHEN** mini me presents the hold
- **THEN** it reports the specific prerequisite and why no available action can resolve it
- **AND** it preserves the candidate and does not fabricate an action or auto-advance.
