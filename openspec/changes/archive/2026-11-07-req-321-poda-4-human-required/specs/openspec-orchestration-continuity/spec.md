## MODIFIED Requirements

### Requirement: Human Intervention Protocol and Option Fidelity
When human intervention is required, the system SHALL persist and expose the exact question and options for the currently blocking gate across all workflow stages (including Explore checkpoint, Propose clarification, review escalation, Apply recovery exhaustion, PR1 merge acknowledgement, and physical validation), preserving original wording emitted by OpenSpec or the agent and distinguishing native options from agent-generated recommendations. The active payload SHALL be unified in PostgreSQL across stage checkpoints, `orchestration_runs.human_gate`, and `stop_details.human_payload`, and SHALL NOT be sourced from a resolved or superseded earlier gate. For exhausted Apply recovery, the active payload SHALL capture attempt counts, hard ceilings, pending task lists, candidate SHA, and test outcomes, providing a concise, actionable Spanish explanation of what stopped the workflow and what decision is needed. When the operator submits an authorized response, the system SHALL accept it idempotently, record it atomically in PostgreSQL, clear the active gate immediately, and resume execution without rejecting the response with HTTP 409 or re-surfacing resolved gates.

#### Scenario: Verbatim options displayed to operator
- **GIVEN** OpenSpec Explore or Propose emitting explicit options during clarification
- **WHEN** mini me prepares a `HUMAN REQUIRED` operator prompt
- **THEN** it presents the exact verbatim options in Spanish
- **AND** clearly separates native OpenSpec options from agent advice
- **AND** pauses execution cleanly until human input is received.

#### Scenario: Each scoped gate persists its active question and options
- **GIVEN** a Run has a prior gate payload or no gate payload
- **WHEN** Explore checkpoint, Propose clarification, review escalation, Apply recovery exhaustion, PR1 merge acknowledgement, or physical validation blocks that Run
- **THEN** the Run durably records the current gate's question and options as its active human request in PostgreSQL
- **AND** the active payload identifies the current gate and does not retain the prior gate's question or options.

#### Scenario: Explore checkpoint response accepted without 409
- **GIVEN** an active Run paused at Explore with a verified `HUMAN_REQUIRED` checkpoint
- **WHEN** the operator submits a response to the active gate endpoint
- **THEN** the system matches the Explore checkpoint as the current human gate
- **AND** accepts the response without returning HTTP 409 Conflict
- **AND** persists the operator input atomically and transitions the gate to resolved.

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

#### Scenario: Exhausted Apply recovery gate explains diagnostic context
- **GIVEN** Apply recovery halts due to reaching the attempt ceiling or lack of progress
- **WHEN** Apply escalation becomes the active human gate
- **THEN** the active payload retains attempt count vs. ceiling, pending tasks, candidate SHA, and test results
- **AND** Trabajo actual presents an actionable Spanish explanation of why recovery stopped, what tasks remain, and what decision is required
- **AND** if execution logs are unavailable, explicitly indicates their absence instead of presenting a generic unformatted string.

#### Scenario: Proposal-review response does not approve or bypass review
- **GIVEN** an operator responds to an exhausted proposal-review gate
- **WHEN** the existing response workflow accepts the response
- **THEN** the response is recorded as operator input
- **AND** it does not itself mark the proposal review approved or skip the required independent review.

#### Scenario: Resolved gate never resurfaces after stage progression or reload
- **GIVEN** an operator has responded to an active human gate and the stage has transitioned
- **WHEN** the operator reloads the page or the coordinator continues to a subsequent stage
- **THEN** the resolved gate is permanently inactive in the API projection
- **AND** does not reappear as a zombie prompt or generic intervention.
