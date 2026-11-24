# Spec Delta

## ADDED Requirements

### Requirement: Accepted durable actions publish a post-commit Scheduler wake-up
When the API durably records an authorized action that may leave Scheduler-owned work eligible, it SHALL publish a Scheduler wake-up associated with that transaction only after the transaction commits. The API SHALL preserve HTTP `202 Accepted`, SHALL NOT execute the Scheduler-owned stage directly, and SHALL keep the existing UI SSE stream separate from the internal wake-up channel.

#### Scenario: Accepted action wakes the Scheduler after commit
- **GIVEN** an authorized API action is durably recorded and may make a Run eligible
- **WHEN** the database transaction commits
- **THEN** the API emits the associated Scheduler wake-up after commit
- **AND** the API response remains `202 Accepted` with the durable operation identity.

#### Scenario: Failed transaction emits no usable wake-up
- **GIVEN** the API action transaction rolls back
- **WHEN** the action would otherwise have emitted a wake-up
- **THEN** no post-commit wake-up SHALL be delivered for that rolled-back action
- **AND** no Scheduler-owned stage SHALL execute from the failed request.

#### Scenario: Scheduler authority and UI stream remain separate
- **GIVEN** a stage belongs to Scheduler authority, including `DOC_CLOSING`
- **WHEN** the API records the accepted action
- **THEN** the API SHALL NOT dispatch that stage directly
- **AND** existing SSE transition events for the interface SHALL remain available independently of the internal Scheduler wake-up.

