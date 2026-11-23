# Durable Cost Settlement Specification

## Purpose

Provides a durable, observable settlement boundary that records only verified provider usage and real monetary amounts for each completed agent invocation or execution stage.

## Requirements

### Requirement: Verified invocation cost settlement

The system SHALL settle every completed provider invocation or execution stage for which authoritative usage and monetary cost are available, associating the entry with the project, provider, model when supplied, amount, source usage identity, and observation timestamp.

#### Scenario: Completed DeepSeek invocation is settled

- **WHEN** a DeepSeek Direct invocation completes with provider-verified usage and a verifiable monetary amount
- **THEN** the system records one liquidated `budget_ledger` entry for the project with DeepSeek Direct identity, model, amount, usage identity, and observed timestamp

#### Scenario: Completed Codex invocation is settled

- **WHEN** a Codex invocation completes and its execution contract exposes authoritative usage and cost
- **THEN** the system records the observed amount in `budget_ledger` with the project, Codex provider identity, model when available, and timestamp

### Requirement: Atomic and idempotent durable ledger write

The system SHALL persist a verified settlement transactionally with the completion outcome and SHALL make retries idempotent using the provider invocation or stage usage identity, so a repeated completion cannot create duplicate financial entries.

#### Scenario: Completion retry does not duplicate spend

- **WHEN** the same verified provider usage identity is processed more than once because orchestration resumes or retries
- **THEN** `budget_ledger` contains one corresponding liquidated entry
- **AND** the completion path reports the existing settlement without adding another amount

#### Scenario: Ledger failure does not claim settlement

- **WHEN** the provider outcome is complete but the durable ledger transaction cannot be committed
- **THEN** the execution result remains explicitly unsettled or failed for reconciliation
- **AND** the system does not report the amount as available to the Dashboard

### Requirement: Fail closed for unverifiable usage or identity

The system SHALL NOT create a zero, estimated, or synthetic monetary entry when usage, amount, provider identity, model attribution, or timestamp is not authoritative; unresolved outcomes SHALL remain distinguishable for later reconciliation without fabricating cost.

#### Scenario: Missing provider amount remains unsettled

- **WHEN** an invocation completes but the provider does not return an authoritative monetary amount
- **THEN** no liquidated `budget_ledger` entry is created for that invocation
- **AND** the outcome remains unknown or unresolved rather than being recorded as zero

#### Scenario: Unknown provider cannot be attributed

- **WHEN** a usage result has an amount but its provider identity cannot be verified against the provider catalog
- **THEN** the system does not attribute or settle it as a known provider
- **AND** the unresolved result remains excluded from the Dashboard's known-provider cost projection
