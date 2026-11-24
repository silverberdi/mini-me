# Spec Delta

## ADDED Requirements

### Requirement: Durable wake-up hints trigger canonical reconciliation
The Scheduler SHALL accept PostgreSQL wake-up notifications as non-authoritative hints that trigger an immediate reconciliation through the existing recovery and claim authority. It SHALL consult durable PostgreSQL state before dispatching any work, and a hint without still-eligible work SHALL produce no execution.

#### Scenario: Eligible work is reconciled after a wake-up
- **GIVEN** a committed durable action leaves a Run eligible for Scheduler processing
- **WHEN** the Scheduler receives its wake-up hint
- **THEN** it immediately reconciles the authoritative PostgreSQL state
- **AND** it processes the work only through the existing claims, fencing, permissions, gate fingerprint, Run identity, and idempotency rules.

#### Scenario: Obsolete or empty wake-up does not dispatch
- **GIVEN** a wake-up is duplicated, delayed, grouped, or refers to work that is no longer eligible
- **WHEN** the Scheduler reconciles PostgreSQL state
- **THEN** it SHALL perform no dispatch for that hint
- **AND** it SHALL NOT skip a gate or treat the notification as a queue or source of truth.

### Requirement: Scheduler wake-up lifecycle preserves reconciliation fallback
The Scheduler SHALL reconcile immediately at process startup and listener reconnection, and SHALL retain a lightweight periodic poll to recover from listener disconnection or lost notifications. Scheduler-produced transitions SHALL NOT create a self-triggering dispatch loop.

#### Scenario: Startup and reconnection reconcile
- **GIVEN** the Scheduler starts or its PostgreSQL listener reconnects
- **WHEN** the listener becomes usable
- **THEN** the Scheduler performs an immediate durable reconciliation
- **AND** it continues the configured lightweight periodic poll.

#### Scenario: Scheduler transition does not loop
- **GIVEN** the Scheduler produces a durable transition while processing eligible work
- **WHEN** that transition is observed by the notification path
- **THEN** it SHALL NOT cause duplicate processing of the same logical work
- **AND** concurrent workers SHALL still converge through the existing claims and idempotency.

