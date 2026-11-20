## ADDED Requirements

### Requirement: Safe recovery of orphaned stage invocations after restart

The coordinator SHALL recover an incomplete stage invocation only when the durable claim is no longer active, the recorded candidate and stage match the invocation being resumed, and persisted process identity evidence proves that the previous coordinator and workflow process group are gone. A different recorded boot identity SHALL classify the previous process as gone when the identity belongs to the same host. Recovery SHALL use the existing fenced claim mechanism to replace the expired ownership, record one auditable `STAGE_INVOCATION_ABANDONED` event with a reason grounded in the observed evidence, and start a new invocation for the same candidate and stage. Live, unknown, mismatched, or otherwise ambiguous process evidence SHALL remain fail-closed. No direct database repair or manual SQL SHALL be required for the proven-dead restart case.

#### Scenario: Restarted host has a different boot identity
- **GIVEN** an incomplete invocation with an expired claim, an unchanged candidate and stage, and coordinator/workflow identities from an earlier boot on the same host
- **WHEN** the coordinator evaluates recovery and confirms the prior processes are gone
- **THEN** it SHALL record exactly one `STAGE_INVOCATION_ABANDONED` event citing the observed restart/process evidence
- **AND** it SHALL acquire a successor claim with a higher fencing token and start a new invocation for the same candidate and stage.

#### Scenario: Prior process is absent after scheduler restart
- **GIVEN** an incomplete invocation with an expired claim, an unchanged candidate and stage, and a recorded process identity whose PID is no longer present
- **WHEN** recovery verifies the coordinator, workflow process, and process group are gone
- **THEN** it SHALL durably mark the old invocation abandoned and proceed under a successor fenced claim
- **AND** the previous invocation SHALL NOT be treated as completed.

#### Scenario: Process identity is live or unknown
- **GIVEN** an incomplete invocation with an expired claim
- **WHEN** any required process or process-group identity is live, unknown, unavailable, or cannot be proven gone
- **THEN** recovery SHALL NOT abandon or redispatch the invocation
- **AND** it SHALL preserve the candidate, claim/event evidence, and fail-closed behavior.

#### Scenario: Candidate or stage does not match the interrupted invocation
- **GIVEN** an incomplete invocation with an expired claim
- **WHEN** the candidate identity or stage differs from the invocation being considered for recovery
- **THEN** recovery SHALL NOT reuse that invocation's abandonment evidence to dispatch work for the different candidate or stage.

#### Scenario: Stale worker returns after successor claim is acquired
- **GIVEN** recovery has acquired a successor claim with a higher fencing token
- **WHEN** the previous worker later attempts to record a result or mutate the run
- **THEN** the existing fencing checks SHALL reject that mutation
- **AND** the successor claim and run state SHALL remain unchanged by the stale worker.
