# Spec Delta

## ADDED Requirements

### Requirement: Wake-up reconciliation preserves transactional claims and idempotency
A Scheduler reconciliation triggered by a wake-up SHALL use the existing process-independent PostgreSQL claims, fencing, conditional state transitions, and idempotent dispatch intents before any execution. Notifications SHALL never bypass authorization, gate fingerprints, Run identity, ownership, or concurrency rules.

#### Scenario: Duplicate wake-ups and workers produce at most one dispatch
- **GIVEN** two equal wake-ups or two workers concurrently reconcile the same eligible Run
- **WHEN** both attempt Scheduler processing
- **THEN** the existing durable claim and idempotency controls SHALL allow at most one valid dispatch
- **AND** the losing reconciliation SHALL observe current durable state without duplicating execution.

#### Scenario: Stale wake-up cannot skip a gate
- **GIVEN** a wake-up refers to a Run whose durable gate, permission, fingerprint, or identity is no longer eligible
- **WHEN** reconciliation evaluates the Run
- **THEN** it SHALL refuse dispatch based on current PostgreSQL state
- **AND** it SHALL preserve the current authoritative state and evidence.

#### Scenario: Notification handling does not hold a transaction across execution
- **GIVEN** a wake-up causes reconciliation to select eligible work
- **WHEN** the Scheduler claims dispatch and invokes the existing workflow
- **THEN** claim and intent persistence SHALL complete in bounded transactions
- **AND** no database lock or notification transaction SHALL remain open across slow external execution.

