## MODIFIED Requirements

### Requirement: Human Intervention Protocol and Option Fidelity
When human intervention is required, the system SHALL persist and expose the exact question and options for the currently blocking gate, preserving original wording emitted by OpenSpec or the agent and distinguishing native options from agent-generated recommendations. The active payload SHALL be replaced when a scoped later gate is reached and SHALL NOT be sourced from a resolved earlier gate. The scoped gates are review escalation, Apply escalation, PR1 merge acknowledgement, and physical validation. The system SHALL resume execution through the existing authorized response workflow upon receiving the operator's response.

#### Scenario: Verbatim options displayed to operator
- **GIVEN** OpenSpec Explore or Propose emits explicit options during clarification
- **WHEN** mini me prepares a `HUMAN REQUIRED` operator prompt
- **THEN** it presents the exact verbatim options in Spanish
- **AND** clearly separates native OpenSpec options from agent advice
- **AND** pauses execution cleanly until human input is received.

#### Scenario: Each scoped gate persists its active question and options
- **GIVEN** a Run has a prior gate payload or no gate payload
- **WHEN** review escalation, Apply escalation, PR1 merge acknowledgement, or physical validation blocks that Run
- **THEN** the Run durably records the current gate's question and options as its active human request
- **AND** the active payload identifies the current gate and does not retain the prior gate's question or options.

#### Scenario: Resume preserves progress without duplicate execution
- **GIVEN** a paused run in `HUMAN_REQUIRED` status
- **WHEN** the operator submits a valid response
- **THEN** mini me re-invokes the agent with the response as input context
- **AND** resumes execution directly from the paused stage without re-running completed steps.
