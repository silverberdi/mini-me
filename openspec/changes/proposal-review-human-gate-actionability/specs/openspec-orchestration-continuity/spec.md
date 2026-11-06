## MODIFIED Requirements

### Requirement: Human Intervention Protocol and Option Fidelity
When human intervention is required, the system SHALL persist and expose the exact question and options for the currently blocking gate, preserving original wording emitted by OpenSpec or the agent and distinguishing native options from agent-generated recommendations. The active payload SHALL be replaced when a scoped later gate is reached and SHALL NOT be sourced from a resolved earlier gate. The scoped gates are review escalation, Apply escalation, PR1 merge acknowledgement, and physical validation. For exhausted independent proposal-review escalation, the active payload SHALL also preserve available structured finding fields and provide a concise, actionable Spanish explanation of the finding and the decision required. Native options SHALL remain distinguishable from system-generated alternatives; when no safe discrete alternatives exist, the operator SHALL be able to provide a free-text response. The system SHALL resume execution through the existing authorized response workflow upon receiving the operator's response.

#### Scenario: Verbatim options displayed to operator
- **GIVEN** OpenSpec Explore or Propose emitting explicit options during clarification
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
- **GIVEN** a paused run in `HUMAN REQUIRED` status
- **WHEN** the operator submits a valid response
- **THEN** mini me re-invokes the agent with the response as input context
- **AND** resumes execution directly from the paused stage without re-running completed steps.

#### Scenario: Exhausted proposal-review gate explains its finding and decision
- **GIVEN** independent proposal review reaches its attempt limit with structured findings
- **WHEN** the proposal-review escalation becomes the active human gate
- **THEN** the payload retains each available severity, location, affected requirement, and expected correction
- **AND** Trabajo actual presents a short Spanish explanation of what was found, where it applies, why it matters, and why the workflow stopped
- **AND** the operator sees native options when supplied, otherwise clearly labeled safe system-generated alternatives with consequences or a free-text response when no safe alternatives can be offered.

#### Scenario: Proposal-review response does not approve or bypass review
- **GIVEN** an operator responds to an exhausted proposal-review gate
- **WHEN** the existing response workflow accepts the response
- **THEN** the response is recorded as operator input
- **AND** it does not itself mark the proposal review approved or skip the required independent review.
