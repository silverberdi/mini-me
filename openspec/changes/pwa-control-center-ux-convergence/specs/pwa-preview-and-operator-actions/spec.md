## MODIFIED Requirements

### Requirement: Container Preview Lifecycle and URL Launcher
The system SHALL display preview lifecycle, URL, port and image/candidate identity only from the preview API and SHALL keep those facts bound to project, change, Run and candidate identity where provided. A missing or stale preview observation SHALL be explicit. Opening a preview SHALL be navigation only; the PWA SHALL NOT create, start, stop, or reconcile containers outside the existing authorized preview APIs.

#### Scenario: Open a ready candidate-bound preview
Given the preview API reports a READY preview bound to the selected candidate and provides a URL
When the operator selects Open Preview
Then the PWA SHALL open that returned URL in a separate browsing context
And SHALL show the preview's candidate identity and current lifecycle state.

#### Scenario: Launch active container preview
Given an active preview API response is `READY` and bound to the selected candidate
When the operator opens the preview panel
Then it SHALL show the returned status, port mappings and URL only when those fields are present in the response.

#### Scenario: Preview is stale or unavailable
Given the preview is bound to another head SHA, base SHA, image digest, or its current state cannot be observed
When the preview panel renders
Then it SHALL be marked stale or unavailable
And SHALL NOT offer a control that implies it is ready for the selected candidate.

### Requirement: Guided UI Validation Execution Checklist
The system SHALL display backend-defined validation scenarios and submit the operator's recorded PASS, FAIL, SKIP-with-reason, or NOTE only through the existing validation authority, bound to the exact candidate `(head_sha, base_sha, image_digest)` and required actor/session. It SHALL prevent final evidence presentation as current when candidate identity changes.

#### Scenario: Submit candidate-bound human validation
Given an authorized operator has completed all required scenarios for the currently displayed candidate and preview
When the operator submits a verdict with notes
Then the PWA SHALL send it through the existing validation endpoint
And SHALL display the persisted result and identity returned by the server.

#### Scenario: Submit passing guided validation verdict
Given an operator completed every required validation step for the current candidate and provided evidence notes
When the operator submits PASS
Then the existing validation endpoint SHALL receive the scenario results and exact candidate identity
And the UI SHALL render the persisted verdict only after the API confirms it.

#### Scenario: Candidate changes during validation
Given an operator is viewing validation steps for a candidate that becomes stale
When the operator attempts to submit its verdict
Then the PWA SHALL require a fresh authoritative state before submission
And SHALL NOT bind the old validation to the new candidate.

#### Scenario: Stale validation invalidation on candidate mutation
Given a validation was recorded for a candidate whose head/base SHA or image digest has changed
When the operator opens validation authority
Then the old result SHALL be shown as stale
And SHALL NOT satisfy current-candidate validation.

### Requirement: Contextual Operator Control Plane Actions
The PWA SHALL discover available actions and parameters from the existing Control Plane for the exact selected Run. It SHALL submit only an action returned as enabled, with the authoritative request fields, expected state/version and unique request identity supported by the API. Client-side visual state SHALL NOT authorize actions. Following a mutation, the PWA SHALL wait for the action response and refresh canonical state rather than claim success from an optimistic local transition.

#### Scenario: Confirm and execute an enabled action
Given the Control Plane reports an enabled action for the selected Run and its required parameters
When the operator reviews the consequence and confirms the action
Then the PWA SHALL submit it once to the existing execution endpoint
And SHALL display the durable action result before refreshing the Run view.

#### Scenario: Execute continue action via confirmation modal
Given the Control Plane reports `continue` enabled for the selected Run and requires confirmation
When the operator confirms the described consequence
Then the client SHALL submit one action request with the current concurrency identity
And SHALL refresh from the returned canonical state rather than fabricate an optimistic result.

#### Scenario: Action becomes stale or forbidden
Given action discovery is stale, the action is disabled, the operator is unauthorized, or optimistic concurrency fails
When the operator confirms or submits the action
Then the PWA SHALL NOT repeat or locally simulate the mutation
And SHALL display the server rejection and refresh the authoritative action/state view.

### Requirement: Destructive Action Safety Guard
The PWA SHALL require an accessible explicit confirmation for destructive or materially mutating actions whenever the Control Plane contract requires it. The confirmation SHALL state the server-provided action and impact; closing or cancelling the dialog SHALL issue no request. The PWA SHALL never expose merge as an executable action.

#### Scenario: Cancel a run only after confirmation
Given an enabled cancel action requires confirmation
When the operator opens its confirmation and chooses cancel or closes it
Then no mutation request SHALL be sent.

#### Scenario: Cancel run with confirmation guard
Given the Control Plane returns cancel as enabled and requiring confirmation
When the operator opens the confirmation dialog but does not confirm
Then no cancel request SHALL be sent
And the Run SHALL remain unchanged in the client until a server response establishes otherwise.

#### Scenario: Human merge gate
Given the selected Run is `READY_FOR_HUMAN_MERGE`
When the detail drawer renders available actions
Then it MAY provide a link to the bound Draft PR and evidence
And SHALL NOT submit any merge operation or imply that mini me can merge.

### Requirement: Run and Job Detail Drawer
The system SHALL provide a contextual Run/Job detail experience following the approved desktop drawer composition, with a compact identity/progress header and navigable sections for overview/attention, checkpoints, sandbox/worktree, Git/diff, checks, review, logs/events and cost/usage when data is available. Each section SHALL use existing detail and evidence read models, preserve candidate binding, redact sensitive diagnostics and show explicit unavailable/stale states. Tablet SHALL expose the detail in master-detail or split view; mobile SHALL use a focused full-screen detail view.

#### Scenario: Inspect active execution detail
Given a selected Run has a current Job, active phase, recent event and candidate/checkpoint evidence
When the operator opens its detail
Then the drawer SHALL show exact Run/Job and repository/change identity, active phase, newest relevant event and evidence links in their appropriate sections.

#### Scenario: Inspect READY_FOR_HUMAN_MERGE detail
Given a Run has a Draft PR and checks/review bound to its current candidate
When the operator opens its detail
Then it SHALL show the bound PR, head/base SHA, check and reviewer evidence, outstanding human action and consequences
And SHALL label this state as awaiting human merge, not merged, deployed, or DONE.

#### Scenario: Missing cost or log evidence
Given usage or diagnostic content is not present or is restricted
When the corresponding detail section is opened
Then the UI SHALL show unavailable/redacted evidence without estimating a fabricated value or exposing secrets.
