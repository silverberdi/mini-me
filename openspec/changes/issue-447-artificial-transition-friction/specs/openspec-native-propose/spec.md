## ADDED Requirements

### Requirement: Empty stage-precondition references do not create a standalone blocker
When a validated task assessment reaches a stage-specific dependency check and a declared precondition has an empty `evidence_refs` list, the system SHALL NOT create a blocker solely because the list is empty. The system SHALL continue to block missing or unverified required capabilities and any non-empty evidence reference that is unknown, absent, or unverified. This rule SHALL NOT satisfy a real dependency or replace evidence when the task assessment identifies one.

#### Scenario: Empty evidence list does not stop a transition by itself
- **GIVEN** a validated task assessment with a precondition for the current stage and `evidence_refs: []`
- **AND** every required stage capability is verified
- **WHEN** the system checks blockers before that stage
- **THEN** the empty list alone produces no blocker or human gate
- **AND** the assessment does not claim that an external dependency was verified.

#### Scenario: Non-empty unknown evidence remains fail-closed
- **GIVEN** a validated task assessment with a non-empty evidence reference that cannot be verified
- **WHEN** the system checks blockers before the referenced stage
- **THEN** it blocks that transition with the unresolved reference
- **AND** it does not treat an empty or unrelated reference as evidence for it.
