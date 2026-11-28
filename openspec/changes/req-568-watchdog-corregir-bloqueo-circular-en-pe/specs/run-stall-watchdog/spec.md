# Spec Delta

## MODIFIED Requirements

### Requirement: Bounded escalation and durable diagnosis record
The Watchdog SHALL persist a sanitized, structured diagnosis and remediation outcome in PostgreSQL, including project, run, stage, candidate SHA, observed evidence, root-cause classification, attempted action and result, and a passive recurrence-prevention suggestion when supported. Every persisted diagnosis SHALL retain the transition or intervention key that was observed for the event and a stable event identity, including when it is the first diagnosis for that transition. A diagnosis SHALL be idempotent for its event identity and run, stage, and candidate, and recurrence evaluation SHALL use the persisted transition or intervention key without requiring an earlier diagnosis to exist before the first observation can be stored. When semantic analysis produces an improvement suggestion, the suggestion SHALL be stored with the diagnosis and its initial status SHALL be `pending`. After one failed or ineffective remediation attempt, or immediately for a non-mechanical or ambiguous cause, the Watchdog SHALL use the existing `NEEDS_HUMAN`/human-gate mechanism with the current diagnostic question and actionable options; it SHALL NOT create synthetic debate, autonomous GitHub issues, unlimited retries, or bypass an existing human authorization.

#### Scenario: Mechanical recovery succeeds
- **WHEN** one permitted remediation attempt produces observable success through canonical recovery
- **THEN** the persisted record and typed stage event include the action and observed result
- **AND** the record retains the transition or intervention key and event identity for the observed intervention
- **AND** the same candidate resumes through existing orchestration authority

#### Scenario: First diagnosis is persisted without a prior record
- **WHEN** a run produces a gate or intervention with a transition or intervention key and no prior diagnosis exists for that key
- **THEN** the Watchdog persists the diagnosis with that key, event identity, run, stage, and candidate identity
- **AND** it does not discard the observation or require a prior diagnosis before persistence

#### Scenario: Recurrence finds the correct prior diagnosis
- **WHEN** a later diagnosis refers to a transition or intervention key already persisted for the same supported recurrence
- **THEN** recurrence evaluation finds the matching prior diagnosis by its persisted key and event-linked evidence
- **AND** the later diagnosis is persisted idempotently without duplicating the prior event

#### Scenario: Improvement suggestion is cataloged
- **WHEN** semantic analysis produces a supported recurrence-prevention suggestion for a persisted diagnosis
- **THEN** the diagnosis stores the suggestion in `improvement_suggestion` with status `pending`
- **AND** the suggestion remains linked to the diagnosis, transition or intervention key, event identity, and source run

#### Scenario: First remediation does not resolve the stall
- **WHEN** the same run, stage, and candidate stalls again after its one remediation attempt
- **THEN** the Watchdog stops automatic retries and opens or updates the existing human gate with the evidence and current question
- **AND** it preserves the candidate and prior diagnosis record

#### Scenario: Diagnosis is exposed to operators
- **WHEN** an authorized operator requests diagnosis history for a run
- **THEN** the response returns its sanitized records in chronological order with their candidate identities and outcomes
- **AND** records with an improvement suggestion include that suggestion with status `pending` until an authorized operator changes it
- **AND** secrets and unrelated project data are not exposed

### Requirement: Immutable intervention evidence
Every SRE Unblocker invocation SHALL append an immutable PostgreSQL intervention fact with timestamp, project, run, stage, trigger, action, observed result, autonomous/operator outcome, root-cause classification, a stable event identity, the transition or intervention key when observed, and any supported improvement reference. Replaying the same event identity SHALL be idempotent; later diagnosis or resolution SHALL be represented by a new fact rather than rewriting the prior record. The record SHALL not contain secrets or unrelated project data.

#### Scenario: Intervention fact is retained
- **WHEN** the Unblocker attempts or completes an action
- **THEN** the system appends a sanitized intervention record linked to the exact Run and stage
- **AND** the record retains its event identity and transition or intervention key when available
- **AND** the record remains unchanged when a later event records resolution or escalation

#### Scenario: Duplicate delivery of the same intervention event
- **WHEN** orchestration retries persistence for an intervention event already recorded
- **THEN** the event identity prevents a duplicate record or diagnosis
- **AND** the original timestamp, transition or intervention key, and evidence remain intact
