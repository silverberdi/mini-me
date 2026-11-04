## MODIFIED Requirements

### Requirement: Prominent Attention Banner for Human Gates
The system SHALL notify actual HUMAN_REQUIRED on Dashboard and link to the exact Trabajo actual Run and active stage for resolution. Trabajo actual SHALL render the question and options from the current unresolved gate's durable payload, and SHALL keep the existing authorized operator-response path available. When a later scoped gate replaces an earlier one, the later gate's question and options SHALL become visible after refresh or navigation; a resolved earlier gate's payload SHALL NOT be used as fallback or displayed as current. Original workflow wording and options SHALL be preserved, distinguished from labeled agent suggestions, with Spanish context, consequences and available authority. WAITING_CAPACITY, UNKNOWN and legacy status labels SHALL NOT independently create a human gate.

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

#### Scenario: Operator can answer the current gate
- **GIVEN** Trabajo actual displays the active gate's question and options
- **WHEN** the operator submits an authorized response through the existing response control
- **THEN** the system applies the existing response workflow to that Run and keeps the request visible until durable acceptance and refreshed authority confirm resolution.

#### Scenario: Capacity wait has no human question
- **WHEN** the Run is waiting for capacity without an authorized human request
- **THEN** the UI reports the wait and offers no invented answer, retry or approval action.
