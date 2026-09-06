# Spec: Generic Provider Capacity Recovery & Drain Policy

## Requirements

### Scenario 1: Generic Provider Adapter Interface
- **GIVEN** a registered provider adapter conforming to `ProviderAdapterInterface`,
- **WHEN** the scheduler or health service interacts with the provider,
- **THEN** operations execute against the generic adapter contract without provider-specific hardcoded branching.

### Scenario 2: Autonomous Recovery Probing
- **GIVEN** a provider in `TEMPORARILY_UNAVAILABLE` or `EXHAUSTED` status,
- **WHEN** the scheduler executes a periodic tick,
- **THEN** the provider is probed via its adapter without creating Runs, Jobs, or consuming retry budget,
- **AND** a successful probe transitions the provider to `AVAILABLE` and emits `PRIMARY_CAPACITY_RECOVERED`.

### Scenario 3: Negative Probe Handling
- **GIVEN** an unavailable provider that fails its recovery probe,
- **WHEN** the probe completes,
- **THEN** the provider remains `TEMPORARILY_UNAVAILABLE` with fresh timestamp evidence,
- **AND** event `PROVIDER_PROBE_FAILED` is recorded.

### Scenario 4: Operator-Reported Reset Time
- **GIVEN** an operator provides an expected recovery timestamp for a provider,
- **WHEN** `set_operator_expected_reset` is invoked,
- **THEN** a `CapacityWindow` is saved with `source_signal = OPERATOR_REPORTED` and the specified timestamp.

### Scenario 5: Bounded Blind Waiting
- **GIVEN** an orchestration run in `WAITING_CAPACITY` with unknown reset timing,
- **WHEN** elapsed wait time exceeds 2 hours,
- **THEN** the run transitions to `NEEDS_HUMAN` and surfaces explicit operator choices (`Set Return Time`, `Finish with Drain Provider`, `Keep Waiting`).

### Scenario 6: Drain Fallback Eligibility
- **GIVEN** a change in `BACKLOG`, `READY`, or `QUEUED` status with no material execution started,
- **WHEN** drain fallback is evaluated,
- **THEN** fallback is denied because drain policy strictly applies only to materially in-progress work.

### Scenario 7: Future Provider Pluggability
- **GIVEN** a new provider (e.g., `CursorProviderAdapter`) registered in the adapter registry,
- **WHEN** provider health, probing, and execution are evaluated,
- **THEN** the new provider participates fully without modifying scheduler logic.
