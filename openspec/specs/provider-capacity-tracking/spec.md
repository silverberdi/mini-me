# Provider Capacity Tracking Specification

## Purpose

Tracks primary provider health, normalized outcome classification, rate limits, quota exhaustion windows, and verified capacity reset probing in PostgreSQL.

## Requirements

### Requirement: Structured primary provider outcome classification
The system SHALL classify primary provider outcomes (Codex and Antigravity) into standardized result classes (`success`, `transient_error`, `quota_limit`, `rate_limit`, `auth_error`, `timeout`, `malformed_output`, `cancelled`, `policy_denied`, `unsafe_binding`, `unknown_error`) conforming to `schemas/provider-result.schema.json`.

#### Scenario: Quota exhaustion classified and recorded
- **WHEN** a primary provider returns a quota exceeded, out-of-credits, or capacity exhaustion error
- **THEN** the outcome is classified as `quota_limit`, recording provider identity, role, and capacity reset timestamp if explicitly signaled by the provider.

#### Scenario: Rate limit classified with retry-after
- **WHEN** a provider returns a temporary 429 rate limit with a `Retry-After` duration
- **THEN** the outcome is classified as `rate_limit` with the normalized `retry_after` duration recorded without marking the provider permanently exhausted.

#### Scenario: Normal domain verdicts do not degrade provider health
- **WHEN** an agent execution completes successfully and returns a domain verdict such as `CHANGES_REQUIRED` or lists code review findings
- **THEN** the provider transport outcome is classified as `success` and provider health remains `available`.

#### Scenario: Failure types distinguished from quota exhaustion
- **WHEN** a provider fails due to invalid authentication, a network timeout, or a CLI process crash
- **THEN** the outcome is classified under its specific class (`auth_error`, `transient_error`, `timeout`) and the system SHALL NOT treat it as quota exhaustion.

#### Scenario: Malformed provider output fails closed
- **WHEN** a provider returns unparseable or ambiguous output that cannot be reliably classified
- **THEN** the system classifies the result as `malformed_output`, logs the diagnostic evidence, and SHALL NOT falsely mark the provider available or exhausted.

### Requirement: Capacity windows and health persistence
The system SHALL persist primary provider health state (`available`, `temporarily_unavailable`, `exhausted`, `degraded`) and capacity reset windows in PostgreSQL (`provider_health` and `capacity_windows` tables) strictly for configured primary providers (`codex`, `antigravity`).

#### Scenario: Explicit provider quota reset signal captured
- **WHEN** a primary provider response includes an explicit reset timestamp
- **THEN** the system persists a `capacity_windows` record with the exact `capacity_reset_at` timestamp in PostgreSQL without inventing unverified timestamps.

#### Scenario: Unknown reset window handled safely
- **WHEN** a primary provider is exhausted but provides no reset timestamp signal
- **THEN** the system records the quota exhaustion with `capacity_reset_at` set to null and keeps the provider in `exhausted` state until explicit re-evaluation.

#### Scenario: Provider health status updated in PostgreSQL
- **WHEN** a primary provider encounters consecutive failures or transitions operational states
- **THEN** the provider's row in `provider_health` is updated with current status, failure count, last result class, and timestamps.

#### Scenario: Non-primary providers excluded from capacity tracking
- **WHEN** audit or external non-primary executions occur (e.g. DeepSeek Direct)
- **THEN** the system SHALL NOT persist records for them in `provider_health` or `capacity_windows`, leaving audit lifecycle management exclusively to the 004 audit subsystem.

### Requirement: Verified capacity reset probing
The system SHALL treat `capacity_reset_at` strictly as a scheduling eligibility hint and SHALL NOT mark a provider `available` upon window expiration without verified positive evidence from an availability probe.

#### Scenario: Reset time elapsed and provider still exhausted
- **WHEN** the current time passes a provider's `capacity_reset_at` and the verification probe returns `quota_limit`
- **THEN** the provider remains in `exhausted` state and the scheduler remains in `DRAIN` or `WAIT`.

#### Scenario: Reset time elapsed with transient probe failure
- **WHEN** `capacity_reset_at <= now` and an availability probe encounters a `transient_error` or network timeout
- **THEN** the system keeps the provider in its non-available status, logs the probe diagnostic, and does NOT transition the provider to `available`.

#### Scenario: Reset time elapsed with verified provider available
- **WHEN** `capacity_reset_at <= now` and an availability probe succeeds or a verified fresh success signal is received
- **THEN** the system transitions the provider's health to `available`, clears the exhaustion state, and signals the scheduler to recompute its mode.
