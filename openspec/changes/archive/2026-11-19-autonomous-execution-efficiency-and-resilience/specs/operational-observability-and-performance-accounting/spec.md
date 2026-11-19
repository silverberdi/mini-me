## Purpose

Provides granular backend operational performance, duration, and token accounting across all orchestration stages, separating active inference, check execution, transport stalls, and recovery overhead to enable objective efficiency measurement without frontend dependencies.

## ADDED Requirements

### Requirement: Granular stage and attempt duration accounting
The system SHALL record discrete, durable timestamps and durations (in milliseconds) for each orchestration stage and attempt transition: admission preparation, CONTRACT_REVIEW, APPLY execution, deterministic check execution, CODE_REVIEW, candidate freezing, and PR preparation. The system SHALL explicitly distinguish active compute duration from provider queue wait, network transport delay, and human gate wait time.

#### Scenario: End-to-end run duration is broken down by operational component
- **GIVEN** a completed orchestration run that reached `READY_FOR_HUMAN_MERGE`
- **WHEN** operational metrics are queried for the run
- **THEN** the metrics report exact duration breakdown across:
  - Admission duration
  - Pre-apply contract review duration
  - Implementer sandbox active compute duration
  - Deterministic check execution duration
  - Independent code review duration
  - Git push and GitHub Draft PR preparation duration
  - Idle/waiting duration (including network reconnect waits or rate-limit pauses).

### Requirement: Token consumption and transport stall attribution
The system SHALL record input (prompt) and output (completion) token counts, provider-reported costs, and transport retry counts associated with each Run, Job, and Attempt in durable storage.

#### Scenario: Token consumption and retries tracked per stage
- **GIVEN** an orchestration run executing contract review and code review with DeepSeek Direct and apply with Antigravity
- **WHEN** stage events and ledger entries are persisted
- **THEN** prompt tokens, completion tokens, and dollar amount are attributed to the exact `run_id`, `job_id`, and `stage`
- **AND** any transient network retries or transport stalls are logged with count and cumulative stall duration in `evidence_diagnostics`.

#### Scenario: No credential or sensitive prompt leakage in telemetry
- **WHEN** operational metrics and stage events are persisted
- **THEN** the system SHALL NOT record full raw prompts containing secrets, environment variables, or private keys
- **AND** all metadata adheres to strict secret redaction rules before storage.
