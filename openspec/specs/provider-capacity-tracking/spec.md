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
The system SHALL treat `capacity_reset_at` strictly as a scheduling eligibility hint and SHALL NOT mark a provider `available` upon window expiration without verified positive evidence from an availability probe. Availability probing SHALL be governed by deterministic, configurable cooldown and backoff so that an unavailable provider is never probed once per scheduler tick, and unknown reset timing SHALL NOT imply immediate or continuous probing.

#### Scenario: Reset time elapsed and provider still exhausted
- **WHEN** the current time passes a provider's `capacity_reset_at` and the verification probe returns `quota_limit`
- **THEN** the provider remains in `exhausted` state and the scheduler remains in `DRAIN` or `WAIT`.

#### Scenario: Reset time elapsed with transient probe failure
- **WHEN** `capacity_reset_at <= now` and an availability probe encounters a `transient_error` or network timeout
- **THEN** the system keeps the provider in its non-available status, logs the probe diagnostic, and does NOT transition the provider to `available`.

#### Scenario: Reset time elapsed with verified provider available
- **WHEN** `capacity_reset_at <= now` and an availability probe succeeds or a verified fresh success signal is received
- **THEN** the system transitions the provider's health to `available`, clears the exhaustion state, resets the probe backoff state, and signals the scheduler to recompute its mode.

#### Scenario: Known future reset time suppresses probing before the window
- **WHEN** a provider is unavailable with a known future `capacity_reset_at`
- **THEN** the system SHALL NOT execute an availability probe before that reset window, regardless of scheduler tick count.

#### Scenario: Unknown reset time does not cause continuous probing
- **WHEN** a provider is unavailable with an unknown `capacity_reset_at`
- **THEN** the system SHALL NOT treat the provider as immediately probe-eligible; the next probe SHALL be governed by the configured cooldown/backoff bound, not by scheduler tick cadence.

#### Scenario: Probe frequency bounded across many scheduler cycles
- **WHEN** the scheduler executes many consecutive cycles while a provider remains unavailable
- **THEN** the number of availability probes for that provider SHALL remain within the configured cooldown/backoff bound and SHALL NOT approach one probe per scheduler cycle.

#### Scenario: Failed recovery probe delays the next probe
- **WHEN** a recovery probe fails while a provider remains unavailable
- **THEN** the system SHALL record the probe failure and delay the next probe by the configured backoff interval, up to the configured maximum.

#### Scenario: Successful recovery probe resets backoff
- **WHEN** a recovery probe succeeds and transitions the provider to `available`
- **THEN** the system SHALL reset the probe backoff state so a subsequent exhaustion episode starts from the base interval.

### Requirement: Non-inference readiness checks and expensive probe governance
The system SHALL distinguish provider local readiness (executable present) and authentication readiness from provider inference capacity, and SHALL NOT use an inference-consuming operation as a frequent availability heartbeat. Any probe that can consume provider/model quota SHALL be explicitly classified as expensive, SHALL be rate-limited by the configured cooldown/backoff, SHALL never run once per scheduler tick, SHALL NOT consume implementation retry budget, and SHALL leave observable evidence.

#### Scenario: Missing executable fails readiness without inference
- **WHEN** a provider's CLI executable is not present or not resolvable
- **THEN** readiness evaluation SHALL fail with a local, deterministic reason (for example `misconfigured` or `unreachable`) WITHOUT dispatching any inference-consuming probe.

#### Scenario: Authentication unavailable yields truthful auth_required
- **WHEN** a provider's local authentication/readiness check reports that authentication is unavailable
- **THEN** the system SHALL reflect a truthful `auth_required` outcome and SHALL NOT run an inference-consuming probe or claim capacity availability.

#### Scenario: Readiness checks are non-inference and quota-free
- **WHEN** provider readiness is evaluated
- **THEN** the checks used SHALL be local and non-inference (executable presence and authentication/readiness status) and SHALL NOT consume provider/model quota.

#### Scenario: Readiness success does not prove recovered capacity
- **WHEN** an exhausted provider's non-inference readiness/auth check succeeds (for example `agy models` confirms catalog/auth reachability) but no inference-capacity recovery evidence is available
- **THEN** the system SHALL NOT transition the provider to `available`; it SHALL preserve the exhausted/unknown-capacity state until verified inference-capacity recovery evidence is produced.

#### Scenario: Expensive probes are explicitly classified
- **WHEN** any probe is capable of consuming provider/model quota or inference capacity
- **THEN** it SHALL be explicitly classified as expensive and governed by the expensive-probe rate limit.

#### Scenario: Expensive probes are rate-limited and observable
- **WHEN** an expensive probe is executed
- **THEN** the system SHALL enforce the configured cooldown/backoff bound, SHALL NOT exceed the configured maximum per window, and SHALL persist an observable event recording provider, probe kind, timestamp, and outcome.

#### Scenario: Concurrent expensive-probe reservations do not exceed the per-window maximum
- **WHEN** multiple independent scheduler/service instances concurrently evaluate and reserve an expensive probe for the same provider at the same eligibility boundary
- **THEN** the reservation SHALL be atomic across PostgreSQL sessions such that no more than the policy-authorized number of probes dispatches and the persisted per-window probe count SHALL NOT exceed the configured maximum per window.

#### Scenario: Provider recovery does not consume implementation retry budget
- **WHEN** an availability/recovery probe is executed
- **THEN** it SHALL NOT decrement or consume any implementation attempt retry budget and SHALL NOT create Runs or Jobs.
