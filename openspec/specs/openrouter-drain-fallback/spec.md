# openrouter-drain-fallback Specification

## Purpose
Provides paid drain fallback execution via OpenRouter during dual-primary subscription provider exhaustion, enforcing strict eligibility, pinned exact model routing, canonical model independence, role authority, and secret isolation.

## Requirements

### Requirement: Strict 10-point paid drain fallback eligibility policy
The system SHALL permit OpenRouter fallback execution ONLY when ALL 10 eligibility conditions are simultaneously met (scheduler in `DRAIN`, existing in-flight job, blocked on implementer/reviewer stage, no new `READY` work admitted, **both** Codex and Antigravity verified exhausted/unavailable, fallback explicitly enabled, reservable budget available, valid independent model selected, valid candidate identity bindings, and all pipeline invariants preserved), and SHALL strictly prohibit OpenRouter invocation during `RUN` mode, during single-primary exhaustion, or for admitting new `READY` changes.

#### Scenario: OpenRouter fallback forbidden in RUN mode
- **WHEN** the scheduler is in `RUN` mode and execution is requested
- **THEN** the system executes exclusively using configured primary subscription providers and SHALL NOT invoke OpenRouter fallback.

#### Scenario: OpenRouter fallback forbidden when only one primary is exhausted
- **WHEN** the scheduler is in `DRAIN` mode and only one primary provider is exhausted while the other has capacity (e.g., Codex available, Antigravity exhausted)
- **THEN** the system SHALL NOT invoke OpenRouter fallback to accelerate progress, and preserves the job under 005 DRAIN rules.

#### Scenario: OpenRouter fallback never admits new READY changes
- **WHEN** a change is in `READY` status, the scheduler is in `DRAIN` mode, and both primary providers are exhausted
- **THEN** the system refuses to admit or start the change under OpenRouter fallback and keeps the change in `READY` status.

#### Scenario: In-flight job advances using OpenRouter fallback during dual-primary exhaustion
- **WHEN** the scheduler is in `DRAIN` mode, both Codex and Antigravity are verified exhausted, the in-flight job is blocked on an execution stage, explicit fallback is enabled, and reservable budget exists
- **THEN** the system invokes OpenRouter fallback for that stage and advances the in-flight job upon successful execution.

#### Scenario: In-flight job pauses in WAITING_CAPACITY when fallback is disabled
- **WHEN** the scheduler is in `DRAIN` mode, both primary providers are exhausted, and OpenRouter fallback is disabled or unconfigured
- **THEN** the system transitions the in-flight job safely to `WAITING_CAPACITY` without attempting paid calls.

#### Scenario: No paid execution in WAIT mode without explicit budget
- **WHEN** the scheduler is in `WAIT` mode or budget capacity is depleted
- **THEN** the system halts all provider invocations and admits no paid calls.

### Requirement: Pinned exact routing and price ceiling enforcement
The system SHALL require that every OpenRouter fallback request binds to a fixed exact model route with a verified pricing snapshot, and SHALL strictly prohibit uncontrolled auto-routing or routes whose maximum cost cannot be proven before dispatch.

#### Scenario: Fallback request allowed with pinned route and verified pricing
- **WHEN** an eligible fallback request specifies a pinned model route whose per-token input/output pricing is verified in the pricing snapshot
- **THEN** the system computes the maximum billable cost, reserves budget, and executes the request.

#### Scenario: Uncontrolled auto-routing rejected before dispatch
- **WHEN** a fallback request targets an auto-routing endpoint or route where execution could resolve to a more expensive unverified model/provider
- **THEN** the system rejects the request before HTTP dispatch (`policy_denied`), logs a routing violation, and transitions the job to `WAITING_CAPACITY`.

#### Scenario: Unverified pricing snapshot fails closed
- **WHEN** the current per-token pricing snapshot for a requested model route is unavailable or ambiguous
- **THEN** the system refuses reservation and dispatches no HTTP request.

### Requirement: Canonical model identity and independence policy
The system SHALL normalize model identifiers into canonical model identities (family, architecture, and underlying model) and SHALL enforce that when OpenRouter handles both substantive implementation and authoritative review for a candidate, the authoritative reviewer's canonical model identity MUST strictly differ from the substantive implementer's canonical model identity.

#### Scenario: Exact same model forbidden for fallback review
- **WHEN** OpenRouter fallback executed implementation using model `anthropic/claude-3.5-sonnet` and review is requested using `anthropic/claude-3.5-sonnet`
- **THEN** the system rejects the reviewer model selection, refuses self-review, and transitions the job to `WAITING_CAPACITY`.

#### Scenario: Different aliases resolving to same canonical model forbidden
- **WHEN** OpenRouter fallback executed implementation using a model alias and review is requested using a different alias or route that resolves to the same underlying canonical model family
- **THEN** the system identifies the canonical model collision, rejects the reviewer model, and transitions the job to `WAITING_CAPACITY`.

#### Scenario: Unprovable canonical model identity fails closed
- **WHEN** the canonical model family or underlying identity of a candidate reviewer cannot be deterministically proven distinct from the implementer
- **THEN** the system fails closed, refuses to execute the review, and transitions the job to `WAITING_CAPACITY`.

#### Scenario: Independently verified canonical models allowed
- **WHEN** OpenRouter fallback executed implementation using `anthropic/claude-3.5-sonnet` and review is requested using a verified distinct canonical model such as `openai/gpt-4o`
- **THEN** the system accepts the distinct model selection, records both canonical model identities in review evidence, and executes the review.

### Requirement: Complementary review authority and pipeline invariants
The system SHALL preserve authoritative role separation and pipeline invariants during OpenRouter fallback, ensuring that fallback results never silently become approvals, DeepSeek Direct audit is never replaced or skipped, and OpenRouter execution never alters primary provider health or triggers a return to `RUN` mode.

#### Scenario: Fallback implementation requires independent complementary review
- **WHEN** an in-flight job completes implementation via OpenRouter fallback
- **THEN** the candidate MUST undergo deterministic checks and independent complementary review before proceeding to audit.

#### Scenario: Fallback reviewer cannot self-review fallback implementation
- **WHEN** an execution job requests complementary review for an OpenRouter fallback implementation
- **THEN** the system enforces distinct reviewer model selection and prohibits the implementer instance or model from providing the review verdict.

#### Scenario: OpenRouter never replaces or skips DeepSeek Direct audit
- **WHEN** a fallback-reviewed candidate advances to the audit stage
- **THEN** the system invokes DeepSeek Direct via direct API only; OpenRouter SHALL NOT replace, proxy, or provide fallback for DeepSeek Direct audit.

#### Scenario: OpenRouter outcomes never alter primary provider health
- **WHEN** an OpenRouter fallback call succeeds, fails, or encounters rate limits
- **THEN** the system SHALL NOT alter the health status (`available`, `exhausted`, `degraded`) of primary providers (Codex and Antigravity).

#### Scenario: OpenRouter success never returns scheduler to RUN
- **WHEN** an OpenRouter fallback invocation completes successfully in `DRAIN` mode
- **THEN** the scheduler remains in `DRAIN` or `WAIT` mode; return to `RUN` mode requires verified recovery evidence from primary providers.

### Requirement: Provider outcome normalization and secret isolation
The system SHALL normalize all OpenRouter outcomes through the standard provider result contract, distinguish local budget denials from OpenRouter provider errors, and strictly redact OpenRouter credentials while isolating DeepSeek credentials.

#### Scenario: Outcome normalization through standard provider result contract
- **WHEN** an OpenRouter API call completes or encounters an error
- **THEN** the adapter normalizes the result into `schemas/provider-result.schema.json` classification (`success`, `rate_limit`, `quota_limit`, `auth_error`, `transient_error`, `timeout`, `model_unavailable`, `malformed_output`), preserving latency and token metrics.

#### Scenario: Local budget denial distinguished from OpenRouter provider errors
- **WHEN** a fallback invocation is denied due to daily/monthly budget exhaustion or missing policy
- **THEN** the system classifies the outcome as `budget_denial` or `policy_denial` without marking the OpenRouter provider as exhausted or failing.

#### Scenario: Strict redaction of OpenRouter credentials
- **WHEN** an OpenRouter call is dispatched, logged, or recorded in PostgreSQL
- **THEN** `OPENROUTER_API_KEY` and authorization headers are completely redacted.

#### Scenario: Strict isolation of DeepSeek Direct credentials
- **WHEN** OpenRouter fallback is configured or executed
- **THEN** `DEEPSEEK_API_KEY` is never supplied, routed, or transmitted to OpenRouter.
