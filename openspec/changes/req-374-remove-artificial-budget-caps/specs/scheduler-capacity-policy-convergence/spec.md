## REMOVED Requirements

### Requirement: Strict Drain Fallback Policy
**Reason**: The active requirement makes OpenRouter policy-table and daily/monthly headroom conditions part of scheduling eligibility.
**Migration**: Preserve DRAIN, in-flight, no-new-READY, and provider-capacity restrictions; remove only the artificial spend-policy/headroom checks.

## ADDED Requirements

### Requirement: In-flight fallback eligibility is independent of internal spend caps
The scheduler SHALL evaluate configured fallback eligibility using provider role/configuration, actual provider capacity evidence, and in-flight pipeline state; it SHALL NOT require an internal daily/monthly budget cap, budget-policy row, or headroom calculation. It SHALL keep new READY work out of the rescue path and preserve the required DRAIN/WAIT and role-separation rules.

#### Scenario: In-flight execution continues without a legacy cap policy
- **WHEN** a materially started execution is in the permitted drain state, required primary providers are verified unavailable, and a fallback profile is configured
- **THEN** the scheduler allows the configured fallback decision without testing local daily/monthly headroom

#### Scenario: New ready work remains excluded
- **WHEN** a new READY item is evaluated while rescue fallback is available
- **THEN** the scheduler does not admit that item through the in-flight fallback path

#### Scenario: Provider capacity is unknown
- **WHEN** required primary-provider capacity cannot be verified
- **THEN** the scheduler follows the existing fail-safe WAIT or human decision path and does not infer that a spend cap caused the block

#### Scenario: Fallback profile is unavailable
- **WHEN** the permitted in-flight path is reached but no configured fallback profile or credentials are available
- **THEN** the scheduler reports that exact provider configuration gap and preserves the in-flight state
