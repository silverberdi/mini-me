## ADDED Requirements

### Requirement: Propose recognizes sufficient local contingencies
When the native Propose workflow finds an unavailable external integration but a local fallback can satisfy the intended functional requirement, the thinking agent SHALL assess and record the fallback's functional sufficiency. The evidence record SHALL identify `status: fallback_applied` and `blocking: false` when the fallback is sufficient. The proposal SHALL NOT require a blocked status solely because the external integration is unavailable in that case.

#### Scenario: Local fallback satisfies the requirement
- **GIVEN** an external integration is unavailable during proposal investigation
- **AND** an available local fallback, such as a reference HTML artifact, functionally satisfies the relevant acceptance criterion
- **WHEN** the thinking agent prepares the OpenSpec proposal and evidence record
- **THEN** the evidence records `status: fallback_applied` and `blocking: false`
- **AND** the scenario and focused verification check the fallback's functional sufficiency
- **AND** the proposal does not mark the satisfied criterion as blocked.

#### Scenario: Fallback does not satisfy the requirement
- **GIVEN** an external integration is unavailable during proposal investigation
- **AND** no available fallback satisfies the required behavior
- **WHEN** the thinking agent prepares the OpenSpec proposal
- **THEN** it records the actual missing behavior and evidence
- **AND** it does not claim `fallback_applied` or `blocking: false` without functional support.
