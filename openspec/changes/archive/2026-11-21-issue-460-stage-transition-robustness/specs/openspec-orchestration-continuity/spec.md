## ADDED Requirements

### Requirement: Scheduler is the sole DOC_CLOSING workflow dispatcher after a gate response
When an operator response makes a Run eligible to continue at `DOC_CLOSING`, the API SHALL persist the response and eligible transition through the existing durable, idempotent action path, but SHALL NOT launch the native DOC_CLOSING workflow. The API SHALL return its acceptance without waiting for the Scheduler or workflow process. After that acceptance, the PWA SHALL immediately show that the response was received and identify the pending stage; it SHALL update the displayed stage from observed Run/Scheduler state rather than implying that an agent has already started. The Scheduler SHALL be the sole authority that dispatches the workflow, and SHALL acquire the existing durable stage-invocation claim before dispatch. Concurrent or repeated API and Scheduler activity SHALL produce at most one native invocation for the same Run, stage, and candidate.

#### Scenario: Accepted DOC_CLOSING gate response awaits Scheduler dispatch
- **GIVEN** a Run is paused at a current `DOC_CLOSING` human gate
- **WHEN** the API accepts and durably records the operator's response
- **THEN** it returns `ACCEPTED` for the same Run and stage without waiting for or launching a workflow process
- **AND** the PWA immediately shows that the response was received and that `DOC_CLOSING` is pending, without claiming that the native workflow is already running
- **AND** the Scheduler later claims and dispatches the native workflow once
- **AND** the response remains idempotent if submitted again.

#### Scenario: API rejects the response
- **GIVEN** a gate response is rejected or cannot be durably accepted
- **WHEN** the API returns an error
- **THEN** the PWA shows the failure and retains the unresolved gate for correction
- **AND** it does not show a successful acceptance or clear the gate optimistically.

#### Scenario: Concurrent scheduler workers cannot duplicate DOC_CLOSING
- **GIVEN** multiple Scheduler workers observe the same eligible Run and candidate
- **WHEN** they attempt to dispatch `DOC_CLOSING`
- **THEN** only the worker holding the durable stage-invocation claim may launch the native workflow
- **AND** the other workers do not launch a second process.

### Requirement: Human gates explain affected evidence and the consequences of available actions
Every human-gate payload SHALL identify the condition that stopped the Run and the affected requirement, task, or other relevant evidence when applicable. When the gate is caused by changed proposal/task content, the payload SHALL include a readable before/after diff for the affected items. The payload fields `diff`, `affected_items`, and `option_explanations` SHALL be optional; existing and historical payloads without them SHALL remain valid. Every presented action option SHALL explain the concrete action and its consequence for the Run when an explanation is available. The system SHALL preserve native question/option values and their authorization meaning, distinguish native options from system-generated explanations, and SHALL NOT invent a diff or evidence that it cannot observe. When no artifact diff applies or one cannot be observed, the payload SHALL state that fact and include the available evidence or diagnostic instead of implying a diff exists.

#### Scenario: Drift gate identifies the changed tasks and shows their diff
- **GIVEN** a feasibility gate is raised because one or more OpenSpec task descriptions or scenarios changed after assessment
- **WHEN** the active gate payload is created
- **THEN** it identifies each affected task or scenario and presents the observed before/after diff
- **AND** its available options explain the action and operational consequence of each choice
- **AND** the exact native option response values and their authorization effects remain unchanged.

#### Scenario: Existing gate payload omits optional evidence fields
- **GIVEN** a current or historical gate payload has no `diff`, `affected_items`, or `option_explanations` field, or a field is null or empty
- **WHEN** the PWA renders the gate
- **THEN** the gate remains visible and usable without a null error
- **AND** existing question, options, and response behavior remain unchanged.

#### Scenario: Gate has no artifact diff or the diff is unavailable
- **GIVEN** a human gate is caused by a condition without changed proposal/task content, or its source diff cannot be observed
- **WHEN** the active gate payload is created
- **THEN** it identifies the actual blocking condition and relevant available evidence
- **AND** it explicitly says that no artifact diff applies or that the diff is unavailable
- **AND** it does not synthesize affected content or claim the gate is resolved.

#### Scenario: Operator selects an explained native option
- **GIVEN** a human gate presents native options with Spanish action/consequence explanations
- **WHEN** the operator selects an option
- **THEN** the system submits the original stable option response value
- **AND** the selected action has the same authorization and transition effect as the native option.
