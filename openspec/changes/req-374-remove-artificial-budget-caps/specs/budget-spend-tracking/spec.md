## REMOVED Requirements

### Requirement: Authoritative budget policy guard and breach persistence
**Reason**: An internal OpenRouter project policy, daily/monthly cap, or breach flag is an artificial admission gate and is not part of the rector contract.
**Migration**: Remove runtime reads/writes and the policy persistence through a forward-only migration; preserve historical migrations and observed usage/ledger evidence.

### Requirement: Durable pricing snapshots and true maximum-request reservation
**Reason**: A locally computed maximum-cost reservation tied to a cap is not a provider usage fact and must not block configured provider dispatch.
**Migration**: Retain only reservation or pricing evidence still required by direct reviewer accounting and usage reconciliation; remove OpenRouter cap admission dependencies.

### Requirement: Persistent cross-boundary unresolved encumbrance and settlement
**Reason**: Unresolved spend evidence must remain visible but cannot be encumbered against invented daily/monthly headroom.
**Migration**: Preserve unresolved provider outcomes and immutable usage history, without cap calculations or cross-boundary spend blocking.

## ADDED Requirements

### Requirement: Record observed provider usage without artificial admission caps
The system SHALL record provider-reported cost and usage with provider identity, source, and observation time when supplied; it SHALL NOT require a project budget-policy row, daily/monthly cap, or internal headroom before dispatch of a configured and otherwise eligible provider. Missing usage after an ambiguous outcome SHALL remain unknown and SHALL NOT be recorded as zero.

#### Scenario: Eligible configured fallback has no legacy cap row
- **WHEN** a fallback profile is configured and all applicable provider and in-flight eligibility conditions pass, but no legacy budget-policy row exists
- **THEN** Mini Me dispatches the configured fallback without a local budget-policy denial and records the actual provider outcome

#### Scenario: Legacy zero cap does not block an eligible dispatch
- **WHEN** a previously stored legacy cap is zero and the configured fallback is otherwise eligible
- **THEN** the legacy value does not block dispatch or create a local budget-denial result

#### Scenario: Provider rejects request for quota or account capacity
- **WHEN** the configured provider rejects a dispatched request for quota, balance, rate limit, or account capacity
- **THEN** Mini Me records the observed provider classification and preserves the in-flight work without silently substituting another provider

#### Scenario: Usage is unavailable after an ambiguous outcome
- **WHEN** a request may have reached a provider but no authoritative usage result is available
- **THEN** Mini Me retains an unknown/unresolved outcome and SHALL NOT claim zero cost or apply it as artificial daily/monthly headroom

#### Scenario: Historical provider usage remains queryable
- **WHEN** an operator reads retained spend evidence after legacy policy removal
- **THEN** observed usage and ledger records remain immutable and queryable with their available provider/source/time attribution

#### Scenario: Unobserved provider balance is not fabricated
- **WHEN** a provider does not report a balance or remaining percentage
- **THEN** Mini Me reports the value as unavailable in its API and dashboard instead of substituting a fixed balance, total, model, or percentage
