## REMOVED Requirements

### Requirement: Strict 10-point paid drain fallback eligibility policy
**Reason**: The policy makes an internal budget row and spend headroom mandatory fallback gates, contrary to the configured provider-role policy and Issue #374.
**Migration**: Replace only the artificial budget conditions; preserve verified provider eligibility, configured profile, role, in-flight, candidate, and pipeline constraints.

### Requirement: Pinned exact routing and price ceiling enforcement
**Reason**: A local price ceiling and reservation are an artificial spend authorization gate, not a provider capability check.
**Migration**: Continue to route only to the configured model/profile and preserve provider-reported outcomes; do not use unverified local price estimates as a dispatch veto.

### Requirement: Provider outcome normalization and secret isolation
**Reason**: The local-budget-denial branch is obsolete after removal of artificial caps; provider result normalization and secret isolation remain required.
**Migration**: Remove local budget-denial classifications from live provider routing while retaining standard provider outcome normalization and credential redaction.

## ADDED Requirements

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
