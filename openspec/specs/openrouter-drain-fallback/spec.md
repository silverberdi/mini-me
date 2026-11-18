# openrouter-drain-fallback Specification

## Purpose
Provides paid drain fallback execution via OpenRouter during dual-primary subscription provider exhaustion, enforcing strict eligibility, pinned exact model routing, canonical model independence, role authority, and secret isolation.

## Requirements

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

### Requirement: No fabricated implementation candidates
The system SHALL NOT fabricate an implementation candidate when a provider returns a textual success but no real repository-editing harness has materially applied repository changes for the requested task. When OpenRouter is selected as an implementer but no real repository-editing harness exists, the system SHALL return a truthful governed failure/escalation outcome, SHALL NOT modify the repository, SHALL NOT create a placeholder candidate file, SHALL NOT create a candidate commit, SHALL NOT claim implementation success, and SHALL NOT persist a false progress lifecycle event.

#### Scenario: OpenRouter success without repository materialization creates no candidate
- **WHEN** OpenRouter implementer fallback returns a successful text response but no real repository-editing harness exists
- **THEN** the system SHALL NOT create a candidate artifact (including any `candidate_impl.py`), SHALL NOT create a candidate commit, and SHALL return a truthful governed failure/escalation outcome.

#### Scenario: No false progress event for a non-materialized candidate
- **WHEN** an implementer path concludes without material repository changes
- **THEN** the system SHALL NOT persist a lifecycle progress event or candidate record implying implementation success.

#### Scenario: OpenRouter outcome never claims implementation success without a candidate
- **WHEN** an OpenRouter call returns success but no candidate-bound material change exists to review
- **THEN** the system SHALL classify the attempt truthfully (for example `EVIDENCE_INSUFFICIENT` or `PROVIDER_FAILURE`) and SHALL NOT advance the job as if implementation completed.

### Requirement: Configured fallback without artificial spend gates
The system SHALL use the configured fallback profile for eligible in-flight work without requiring separate project budget authorization, a daily/monthly cap, or available local headroom. It SHALL preserve all non-budget fallback eligibility and pipeline safeguards, and SHALL NOT use fallback to admit new work, bypass role separation, or replace required review.

#### Scenario: Eligible in-flight work dispatches configured fallback
- **WHEN** an in-flight execution is eligible under the configured provider-capacity and pipeline policy and the fallback profile is configured
- **THEN** Mini Me invokes that configured profile without a legacy budget-policy/headroom check and records the provider result

#### Scenario: Apply fallback is independent of reviewer-provider health
- **WHEN** the primary provider assigned to an active Apply is quota-limited, the independent reviewer provider remains available, and the configured fallback profile supports Apply
- **THEN** Mini Me invokes the configured fallback for Apply with its exact provider and model, without changing or bypassing the independent reviewer role

#### Scenario: Missing or unavailable fallback profile
- **WHEN** in-flight work is eligible but the fallback profile or its required credentials are not configured
- **THEN** Mini Me does not dispatch and reports the precise configuration/capability gap

#### Scenario: New work cannot use rescue fallback
- **WHEN** a new ready item is considered for admission while primary provider capacity is unavailable
- **THEN** Mini Me does not admit it through the in-flight rescue path

#### Scenario: Provider-native failure is surfaced accurately
- **WHEN** the configured fallback provider returns quota, balance, rate-limit, authentication, or model-unavailable failure
- **THEN** Mini Me records that provider outcome, preserves the candidate/work, and does not report a local budget denial or silently choose a different provider

#### Scenario: Independent review remains enforced
- **WHEN** fallback completes an implementation stage
- **THEN** the candidate continues through all required deterministic checks and independent review, with no self-review or audit bypass

### Requirement: Configured provider outcome normalization and secret isolation
The system SHALL normalize configured fallback outcomes through the standard provider result contract and SHALL redact provider credentials from logs, API responses, and persisted evidence.

#### Scenario: Provider result is normalized
- **WHEN** the configured fallback returns success or an error
- **THEN** Mini Me records the standard provider result classification and available latency/usage facts

#### Scenario: Provider credentials remain secret
- **WHEN** fallback request or result evidence is logged, returned, or persisted
- **THEN** API keys and authorization headers are redacted and credentials for other providers are not transmitted
