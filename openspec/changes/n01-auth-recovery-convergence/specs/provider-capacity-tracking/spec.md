## MODIFIED Requirements

### Requirement: Non-inference readiness checks and expensive probe governance
The system SHALL distinguish provider local readiness (executable present) and authentication readiness from provider inference capacity, and SHALL NOT use an inference-consuming operation as a frequent availability heartbeat. Any probe that can consume provider/model quota SHALL be explicitly classified as expensive, SHALL be rate-limited by the configured cooldown/backoff, SHALL never run once per scheduler tick, SHALL NOT consume implementation retry budget, and SHALL leave observable evidence. A successful local authentication check or operator reauthentication acknowledgment SHALL NOT by itself mark a provider available. For an existing in-flight implementation whose provider remains `AUTH_REQUIRED`, a fresh explicit Control Plane authorization MAY permit exactly one real implementation attempt as the remote verification; the normalized result of that attempt SHALL determine durable provider health.

#### Scenario: Local reauthentication alone preserves auth-required health
- **WHEN** local provider credentials are renewed or a local login-status command succeeds
- **AND** no remote provider result has been observed
- **THEN** provider health SHALL remain `AUTH_REQUIRED`
- **AND** the system SHALL NOT claim remote authentication or capacity availability.

#### Scenario: Explicit continuation uses implementation as the only remote verification
- **GIVEN** an existing in-flight Job is waiting on its configured implementer in `AUTH_REQUIRED`
- **AND** a fresh operator-confirmed, claim-fenced continuation is bound to that Run, Job, provider, and exact health timestamp
- **WHEN** the authorized implementation attempt receives a normalized remote result
- **THEN** `SUCCESS` SHALL update health to `AVAILABLE`, `AUTH_ERROR` SHALL update health to `AUTH_REQUIRED`, and quota/rate-limit results SHALL update the corresponding capacity state
- **AND** no separate inference probe SHALL be issued for authentication verification.

#### Scenario: Authentication recovery authorization is not reusable or automatic
- **GIVEN** an authorization has been consumed by an implementation attempt, or continuation is requested without a fresh explicit authorization
- **WHEN** Control Plane, scheduler, or recovery processing evaluates the Run again
- **THEN** the authorization SHALL NOT permit another provider invocation
- **AND** automatic retry, generic force, or OpenRouter fallback SHALL NOT bypass the provider-health gate.

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
- **WHEN** an exhausted provider's non-inference readiness/auth check succeeds but no inference-capacity recovery evidence is available
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

#### Scenario: Independent reviewer unavailable after implementation
- **GIVEN** the authorized implementer produces a candidate while the configured independent reviewer is unavailable
- **WHEN** the pipeline reaches complementary review
- **THEN** the candidate and its evidence SHALL be preserved while the Job waits for reviewer capacity
- **AND** the review SHALL NOT be skipped or performed by the implementer.
