# Spec Delta

## MODIFIED Requirements

### Requirement: Orchestration Runs Table and Filtering
The system SHALL expose Trabajo as the independent sequence Último terminado → En ejecución → Siguiente trabajo, using verified project/Request/Change/Run identities, observed results and evidence links. Siguiente SHALL reflect remote FIFO eligibility and current-work closure dependency. The view SHALL NOT duplicate Backlog or select work in the browser.

#### Scenario: Filter runs by NEEDS_HUMAN status
- **WHEN** the operator follows a human-attention link for a Run whose legacy status is NEEDS_HUMAN and whose current authority exposes an unresolved HUMAN_REQUIRED
- **THEN** the UI focuses that exact Run and its question in Trabajo actual, excluding unrelated Runs from the resolution context; the legacy label alone neither creates a gate nor restores the retired status-filter table in Trabajo.

#### Scenario: Inspect three moments
- **WHEN** last completed, current and next eligible work have verified sources
- **THEN** Trabajo shows those three moments with contextual links and evidence, and links current work to Trabajo actual.

#### Scenario: A moment is absent or blocked
- **WHEN** no verified last completed or next eligible Request exists, or the current Request is blocked
- **THEN** the corresponding moment explains the absence or block without inventing a result, choosing an alternative or admitting a new Request.

### Requirement: Visual Pipeline Phase Stepper
The system SHALL display Trabajo actual as an independent route with actual OpenSpec stages, applicable tasks and observed status. Completion SHALL require evidence; stage position SHALL NOT imply preceding completion. Selecting a stage SHALL show verified task/attempt outputs, actual agent/model assignments and observed timestamps, distinguishing active, waiting, failed and unknown states. The UI SHALL NOT narrate agent thoughts.

#### Scenario: Display active stage in pipeline stepper
- **WHEN** the selected Run exposes its actual current stage and evidence for preceding stages
- **THEN** the stepper highlights the reported active stage, marks earlier stages complete only where supported by evidence and distinguishes pending or unknown stages without inferring completion from stage order or imposing the legacy lifecycle.

#### Scenario: Inspect actual stage evidence
- **WHEN** the operator selects a stage on a real Run
- **THEN** its own outputs, evidence, actual role/model and observed durations appear, and absent task totals or assignments are labeled unavailable rather than inferred.

#### Scenario: Missing earlier evidence
- **WHEN** a Run reports Apply but no completed Propose evidence is exposed
- **THEN** the UI shows the reported stage and missing evidence separately, without marking Propose complete or fabricating a percentage.

### Requirement: Prominent Attention Banner for Human Gates
The system SHALL notify actual HUMAN_REQUIRED on Dashboard and link to the exact Trabajo actual Run/stage for resolution. The request SHALL remain visible there until a durable decision is confirmed. Original workflow wording and options SHALL be preserved, distinguished from labeled agent suggestions, with Spanish context, consequences and available authority. WAITING_CAPACITY, UNKNOWN and legacy status labels SHALL NOT independently create a human gate.

#### Scenario: Click attention banner to navigate to blocked run
- **WHEN** the operator clicks the Dashboard attention alert for an authoritative unresolved HUMAN_REQUIRED
- **THEN** the UI opens Trabajo actual for that exact project, Run and stage with the durable question and authorized resolution controls, preserving the request until a decision is confirmed.

#### Scenario: Resume viewing an unresolved request
- **WHEN** the operator opens the Dashboard alert and then reloads or reopens the PWA before deciding
- **THEN** Trabajo actual displays the same unresolved question, original options and contextual identities from durable authority; Dashboard provides notification and navigation only.

#### Scenario: Capacity wait has no human question
- **WHEN** the Run is waiting for capacity without an authorized human request
- **THEN** the UI reports the wait and offers no invented answer, retry or approval action.

### Requirement: Candidate Lineage, Checks, Review, and Audit Inspector
The system SHALL expose actual results, artifacts, checks and reviews in optional stage detail, bound to project, Run, Change and immutable candidate SHA/generation where present. Reviewer/model identity SHALL come from evidence, without requiring a named provider or an audit that did not occur. Superseded evidence SHALL be visibly stale and SHALL NOT authorize current actions or validation.

#### Scenario: Display complementary review verdict and findings
- **WHEN** the selected immutable candidate has a recorded independent review with verdict READY_TO_MERGE and zero blocking findings
- **THEN** stage detail displays that actual verdict, findings, reviewer role/model and evidence links, without substituting a fixed provider or implying that a separate audit occurred.

#### Scenario: Indicate stale evidence for superseded candidate
- **WHEN** the operator views review evidence from a candidate generation superseded by a newer candidate
- **THEN** the UI prominently marks it stale, identifies the superseding generation where available and retains it as history without allowing it to certify or authorize actions on the current candidate.

#### Scenario: Inspect recorded review
- **WHEN** a stage contains an independent review result for the selected candidate
- **THEN** the UI shows its actual reviewer, verdict, findings and evidence links without substituting a configured default model.

#### Scenario: Candidate changed
- **WHEN** the selected evidence or validation belongs to a prior head/base SHA or image digest
- **THEN** it is marked stale, remains inspectable as history and cannot certify the new candidate.
