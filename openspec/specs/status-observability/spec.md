# Status and Observability Specification

## Purpose
Expose safe Foundation health, readiness, correlation, and metric facts needed to operate mini me and diagnose blocked work.

## Requirements

### Requirement: Health and status surface
The system SHALL expose API and CLI status for an orchestration run, provider health, and GitHub runtime identity, including project, change, run ID, current stage/checkpoint, operational job/current executor, candidate generation and SHA, base SHA, check/review/audit status and candidate bindings, provider health with capacity reset windows resolved from durable capacity window records, retry/reassignment counters, pending handoff, GitHub App authentication mode and health, PR number/URL/head SHA when present, human gate, last deterministic transition, and structured stop detail, with secrets redacted.

#### Scenario: Operator inspects orchestration status
- **GIVEN** an orchestration run exists
- **WHEN** the operator requests `orchestrate status` through the supported API or CLI
- **THEN** the response reports the durable fields needed to identify what will happen next and why, without claiming progress from an uncommitted agent output.

#### Scenario: Operator inspects provider health status via CLI
- **GIVEN** one or more primary providers have health and capacity window records
- **WHEN** the operator runs `minime providers health`
- **THEN** provider status, consecutive failures, and reset timestamps resolved from associated capacity windows are formatted cleanly without attribute errors or process termination.

#### Scenario: Status reports candidate-bound evidence
- **WHEN** a review or audit exists for a run
- **THEN** status identifies the candidate generation/SHA and base SHA to which that evidence applies, and marks prior evidence historical after remediation.

#### Scenario: Status does not expose secrets
- **WHEN** provider, subprocess, Git, or GitHub diagnostics are returned
- **THEN** credentials, tokens, private keys, and configured secret values are redacted.

#### Scenario: Operator requests Foundation status
- **GIVEN** mini me is running with registered projects
- **WHEN** the operator requests status through the supported API or CLI
- **THEN** database health, registered projects, discovered changes, GitHub App authentication mode, and readiness reasons are returned.

#### Scenario: GitHub authentication diagnostics are observable
- **WHEN** a GitHub operation fails or succeeds
- **THEN** status diagnostics indicate GitHub App authentication mode and machine-readable failure category (such as invalid credentials, unauthorized installation, remote unobservable, or repository mismatch) without revealing token or private key material.

### Requirement: Structured correlation
Operational logging and evidence SHALL include stable correlation identifiers for project, change, and operation and SHALL apply secret redaction.

#### Scenario: Operation emits diagnostic evidence
- **GIVEN** an operation associated with a project and change
- **WHEN** logs or durable evidence are emitted
- **THEN** stable correlation identifiers are included
- **AND** configured secret values are not exposed in the emitted evidence.

### Requirement: Metrics facts begin at Foundation
The system SHALL persist timestamps and outcome facts sufficient to later derive discovery/readiness timing and attempt/outcome metrics without relying only on current state.

#### Scenario: Readiness changes over time
- **GIVEN** a discovered change whose readiness is evaluated more than once
- **WHEN** the readiness state changes
- **THEN** timestamped facts are retained so the transition timing can be derived later
- **AND** the previous historical evidence is not replaced solely by current state.
