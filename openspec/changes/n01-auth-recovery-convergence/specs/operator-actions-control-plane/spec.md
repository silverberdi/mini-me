## ADDED Requirements

### Requirement: Explicit provider reauthentication continuation
The system SHALL expose a confirmation-bound `CONTINUE` action for an active Run stopped at `WAITING_CAPACITY` only when its exact linked implementation Job is also waiting on the configured executor whose durable health is `AUTH_REQUIRED`. The request MUST explicitly acknowledge that credentials were renewed and include the observed provider-health timestamp. The canonical claim/fence and Run/Job/project/change identity MUST authorize at most one provider attempt. This authorization MUST NOT mark health `AVAILABLE`, bypass other capacity or execution policy, alter anti-loop history, create another Run/Job, or bypass independent review.

#### Scenario: Discover the narrow recovery action
- **GIVEN** an active `IMPLEMENTING` Run with no candidate and a linked Job in `WAITING_CAPACITY` on its configured executor
- **AND** that executor is durably `AUTH_REQUIRED`
- **WHEN** an operator discovers available actions
- **THEN** `CONTINUE` SHALL be enabled with confirmation-required parameters for explicit reauthentication acknowledgment and the observed health timestamp
- **AND** unrelated active Runs SHALL retain the existing disabled CONTINUE behavior.

#### Scenario: Consume one authorized implementation attempt
- **GIVEN** the operator submits a fresh `CONTINUE` request with matching Run stage/generation, provider, health timestamp, and explicit reauthentication acknowledgment
- **AND** the canonical run claim/fence and linked Job identity are valid
- **WHEN** the action resumes the Run
- **THEN** exactly one attempt MAY invoke the configured implementer while health remains `AUTH_REQUIRED` pending its actual result
- **AND** the recovery decision and JobAttempt SHALL durably identify the authorization request
- **AND** replay of the same action request SHALL not create another attempt.

#### Scenario: Failed resume before dispatch preserves the waiting checkpoint
- **GIVEN** an authorized auth-recovery CONTINUE has persisted its fenced recovery decision
- **AND** orchestration resume fails or returns before a JobAttempt records that exact action request ID
- **WHEN** the Control Plane records the failed action
- **THEN** the same Run and linked Job SHALL remain active and `WAITING_CAPACITY` with no candidate or new attempt
- **AND** the recovery decision SHALL be `BLOCKED` with a pre-dispatch failure reason
- **AND** the workspace and prior attempts SHALL be preserved
- **AND** only a fresh operator CONTINUE request with a new action request ID and current health evidence MAY try again.

#### Scenario: Reject missing, stale, or mismatched reauthentication authority
- **GIVEN** an active waiting Run where the provider is not `AUTH_REQUIRED`, the health timestamp changed, the Job/provider identity differs, a candidate exists, or the explicit acknowledgment is absent
- **WHEN** an operator submits the reauthentication continuation
- **THEN** the action SHALL be rejected before mutating Run, Job, provider health, or attempt state.

#### Scenario: Preserve normal provider and review gates
- **GIVEN** an authorized implementation attempt returns authentication failure, quota exhaustion, or success
- **WHEN** the result is recorded and later pipeline stages are evaluated
- **THEN** provider health and waiting state SHALL reflect the normalized remote result
- **AND** a candidate needing independent review SHALL remain preserved until an eligible reviewer is available.
