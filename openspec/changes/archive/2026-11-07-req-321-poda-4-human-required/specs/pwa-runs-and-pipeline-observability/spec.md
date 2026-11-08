## MODIFIED Requirements

### Requirement: Prominent Attention Banner for Human Gates
The system SHALL notify actual HUMAN_REQUIRED on Dashboard and link to the exact Trabajo actual Run and active stage for resolution. Trabajo actual SHALL render the question and options from the current unresolved gate's durable payload, and SHALL keep the existing authorized operator-response path available. When a Run is in `NEEDS_HUMAN` or waiting on operator intervention, Trabajo actual and Dashboard attention indicators SHALL NOT report "Sin anomalías reportadas" or simulate normal execution. When a later scoped gate replaces an earlier one or a gate is resolved, the active gate SHALL reflect only the current unresolved request; a resolved earlier gate's payload SHALL NOT be used as fallback or displayed as current across page reloads or stage transitions. Original workflow wording and options SHALL be preserved verbatim, distinguished from labeled agent suggestions, with Spanish explanation of causes and consequences. For exhausted Apply recovery, the UI SHALL display diagnostic context (attempts, pending tasks, candidate SHA, test outcomes) and plainly indicate when logs are unavailable. WAITING_CAPACITY, UNKNOWN and legacy status labels SHALL NOT independently create a human gate.

#### Scenario: Click attention banner to navigate to blocked run
- **WHEN** the operator clicks the Dashboard attention alert for an authoritative unresolved HUMAN_REQUIRED
- **THEN** the UI opens Trabajo actual for that exact project, Run and stage with the durable question and authorized resolution controls, preserving the request until a decision is confirmed.

#### Scenario: Resume viewing an unresolved request
- **WHEN** the operator opens the Dashboard alert and then reloads or reopens the PWA before deciding
- **THEN** Trabajo actual displays the same unresolved question, original options and contextual identities from durable authority; Dashboard provides notification and navigation only.

#### Scenario: Later gate replaces the previous question
- **GIVEN** a prior review gate was resolved and the same Run reaches a later Apply, PR1 acknowledgement, or physical-validation gate
- **WHEN** the operator refreshes or reopens Trabajo actual for that Run
- **THEN** the PWA displays the later gate's question and options from its current durable payload
- **AND** does not display the resolved review question or its options as current.

#### Scenario: Active human gate suppresses false normal status
- **GIVEN** an active Run has an unresolved `HUMAN_REQUIRED` gate or `NEEDS_HUMAN` status
- **WHEN** the operator views Trabajo actual or Dashboard attention summaries
- **THEN** the UI indicates that human attention is required
- **AND** does NOT display "Sin anomalías reportadas" or describe the Run as normally executing.

#### Scenario: Exhausted Apply recovery displays actionable Spanish diagnosis
- **GIVEN** an active Run halts at Apply recovery with exhausted attempts
- **WHEN** the operator views the human intervention card in Trabajo actual
- **THEN** the UI displays an actionable explanation in Spanish
- **AND** details the attempts vs. limit, list of pending tasks, candidate commit SHA, and test outcomes
- **AND** if logs are unavailable, explicitly discloses that execution details are absent rather than offering an ungrounded continue button.

#### Scenario: Operator can answer the current gate
- **GIVEN** Trabajo actual displays the active gate's question and options
- **WHEN** the operator submits an authorized response through the existing response control
- **THEN** the system applies the existing response workflow to that Run and keeps the request visible until durable acceptance and refreshed authority confirm resolution.

#### Scenario: Capacity wait has no human question
- **WHEN** the Run is waiting for capacity without an authorized human request
- **THEN** the UI reports the wait and offers no invented answer, retry or approval action.
