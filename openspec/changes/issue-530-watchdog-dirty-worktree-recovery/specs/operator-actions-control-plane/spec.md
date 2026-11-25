## MODIFIED Requirements

### Requirement: Deterministic Request Idempotency
The system SHALL require or generate a unique `action_request_id` for every action request and ensure that duplicate requests with the same ID return the previously persisted result without duplicate state transitions, duplicate jobs, or duplicate side effects. When an accepted gate response ends in an unprogressed or paused state without effecting a stage transition, the system SHALL renew the active gate identity so subsequent operator submissions are not blocked by a stale cached `COMPLETED` result.

#### Scenario: Repeated duplicate action request
Given an action request with ID `req-12345` that completed successfully
When the client re-submits an identical action request with ID `req-12345`
Then the system SHALL return the previously recorded result with status `COMPLETED`
And no additional database events, jobs, or handoffs SHALL be created.

#### Scenario: Stalled or paused gate outcome forces gate renewal
- **WHEN** an operator submits an action resolving a human gate
- **AND** the execution fails to effect a stage transition and halts in `PAUSED`
- **THEN** the system SHALL renew the `gate_id` for the active human gate
- **AND** it SHALL NOT match subsequent operator submissions to the failed action's cached result.
