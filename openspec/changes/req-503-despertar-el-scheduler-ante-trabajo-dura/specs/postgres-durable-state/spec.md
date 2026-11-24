# Spec Delta

## ADDED Requirements

### Requirement: Scheduler wake-up publication shares the durable transaction boundary
The PostgreSQL wake-up mechanism SHALL reuse the existing durable transaction boundary and notification channel, SHALL deliver a notification only after commit, and SHALL NOT introduce a second durable queue, work table, workflow engine, or source of truth. Durable PostgreSQL state and existing event evidence SHALL remain authoritative for reconciliation.

#### Scenario: Commit delivers a wake-up without a second durable entity
- **GIVEN** a transaction records an action that may make Scheduler work eligible
- **WHEN** the transaction commits successfully
- **THEN** a wake-up notification associated with that action becomes deliverable
- **AND** no additional durable queue row or work table is created.

#### Scenario: Rollback cannot advertise durable work
- **GIVEN** the transaction recording the action is rolled back
- **WHEN** listeners observe the PostgreSQL notification channel
- **THEN** they SHALL receive no valid post-commit wake-up for that rolled-back action
- **AND** reconciliation SHALL rely only on durable state.

#### Scenario: Lost or duplicated notifications are recoverable
- **GIVEN** a listener disconnects or receives duplicate, stale, or grouped notifications
- **WHEN** the Scheduler next starts, reconnects, or performs its periodic poll
- **THEN** it SHALL reconcile pending durable state
- **AND** the notification history SHALL not be required as a durable work record.

