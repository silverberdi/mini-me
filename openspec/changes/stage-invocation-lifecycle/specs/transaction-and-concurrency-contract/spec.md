## ADDED Requirements

### Requirement: Atomic Stage Invocation Claim
The system SHALL use a durable process-independent atomic claim keyed by run, stage, and candidate identity before launching a stage workflow. At most one non-expired claim and active invocation SHALL exist for that key. A losing concurrent dispatcher SHALL observe the current attempt and SHALL NOT start a second invocation. Claims SHALL use lease expiry and fencing so a worker that loses ownership cannot commit a completion or continue orchestration as the current owner. This claim coordinates dispatch only; it SHALL NOT replace or emulate the native workflow.

#### Scenario: Concurrent workers contend for one stage invocation
- **GIVEN** two workers attempt to dispatch the same run, stage, and candidate concurrently
- **WHEN** both request the durable invocation claim
- **THEN** exactly one worker owns the claim and may invoke the workflow
- **AND** the other worker observes the active attempt and does not dispatch

#### Scenario: Expired claim fences the prior worker
- **GIVEN** a worker's invocation claim expires and recovery acquires a higher fencing generation
- **WHEN** the prior worker attempts to persist a result or advance the run
- **THEN** the stale write is rejected and only the current fenced owner may complete the invocation
