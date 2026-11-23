## ADDED Requirements

### Requirement: Recovery holds expose an actionable reason
When an active Run cannot enter or resume a stage because an operator authorization or other recovery prerequisite is missing, the system SHALL expose the concrete unmet prerequisite and the authorized action that can resolve it through the existing human-gate/API/UI path. It SHALL NOT leave the Run in an opaque paused state without a current question, action, or specific reason. Showing an action SHALL NOT grant that authorization or bypass existing human, security, candidate-identity, or retry controls.

#### Scenario: Missing recovery authorization is actionable
- **GIVEN** a Run is paused because the required recovery authorization is absent
- **WHEN** the current stage state is presented to the operator
- **THEN** the gate or API response identifies the missing authorization and presents the existing authorized action that can supply it
- **AND** the Run remains paused until an authorized operator submits that action.

#### Scenario: No safe recovery action exists
- **GIVEN** a stage is blocked by an unmet prerequisite for which no authorized operator action exists
- **WHEN** mini me presents the hold
- **THEN** it reports the specific prerequisite and why no available action can resolve it
- **AND** it preserves the candidate and does not fabricate an action or auto-advance.
