# pwa-runs-and-pipeline-observability Specification

## Purpose
TBD - created by archiving change 017-pwa-control-center. Update Purpose after archive.

## Requirements

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
The system SHALL display Trabajo actual as an independent route with actual OpenSpec stages, applicable tasks and observed status. Completion SHALL require evidence; stage position SHALL NOT imply preceding completion. Selecting a stage SHALL show verified task/attempt outputs, actual agent/model assignments and observed timestamps, distinguishing active, waiting, failed and unknown states. When no Run is explicitly selected, Trabajo actual SHALL select only an active Run and SHALL NOT fall back to an inactive historical Run. The UI SHALL NOT narrate agent thoughts. When the selected Run exposes `stop_details.complexity` with the value `high`, `moderate` or `low`, the stepper SHALL display that assigned complexity. When `stop_details.complexity_evidence` exists, the stepper SHALL display the evidence. When no complexity evaluation exists, the stepper SHALL display “Pendiente” and SHALL NOT infer or invent a complexity value. For `high`, the UI SHALL indicate that proposal and code review are mandatory according to the existing Run data and SHALL NOT re-evaluate complexity.

#### Scenario: Display active stage in pipeline stepper
- **WHEN** the selected Run exposes its actual current stage and evidence for preceding stages
- **THEN** the stepper highlights the reported active stage, marks earlier stages complete only where supported by evidence and distinguishes pending or unknown stages without inferring completion from stage order or imposing the legacy lifecycle.

#### Scenario: Inspect actual stage evidence
- **WHEN** the operator selects a stage on a real Run
- **THEN** its own outputs, evidence, actual role/model and observed durations appear, and absent task totals or assignments are labeled unavailable rather than inferred.

#### Scenario: Missing earlier evidence
- **WHEN** a Run reports Apply but no completed Propose evidence is exposed
- **THEN** the UI shows the reported stage and missing evidence separately, without marking Propose complete or fabricating a percentage.

#### Scenario: No active run is available
- **GIVEN** the run list contains only inactive historical Runs and none is explicitly selected
- **WHEN** the operator opens Trabajo actual
- **THEN** no inactive Run is selected as current work and no stale human gate is presented for it.

#### Scenario: Display assigned complexity and available evidence
- **GIVEN** the selected Run exposes `stop_details.complexity` as `high`, `moderate` or `low`
- **WHEN** the operator views the pipeline phase stepper
- **THEN** the UI displays the assigned complexity and, when present, `stop_details.complexity_evidence` without recalculating the assessment.

#### Scenario: Complexity evaluation is pending
- **GIVEN** the selected Run has no `stop_details.complexity`, such as before VALIDATING completes
- **WHEN** the operator views the pipeline phase stepper
- **THEN** the UI displays “Pendiente” and does not invent or infer a complexity value.

#### Scenario: High complexity communicates review implication
- **GIVEN** the selected Run has `stop_details.complexity` equal to `high`
- **WHEN** the operator views the assigned complexity
- **THEN** the UI indicates that proposal and code review are mandatory according to the existing Run data, without implementing a second complexity evaluation.

#### Scenario: Complexity is read from the selected Run
- **GIVEN** the evaluation is persisted in `orchestration_runs.stop_details` and also represented by the existing classification snapshot
- **WHEN** the frontend renders the stepper
- **THEN** it reads the selected Run’s `stop_details.complexity` and `stop_details.complexity_evidence` already returned by `GET /api/v1/orchestration/runs`, and does not modify backend evaluation or persistence logic.

### Requirement: Prominent Attention Banner for Human Gates
The system SHALL notify actual HUMAN_REQUIRED on Dashboard and link to the exact Trabajo actual Run and active stage for resolution. Trabajo actual SHALL render the question and options from the current unresolved gate's durable payload, and SHALL keep the existing authorized operator-response path available. When a Run is in `NEEDS_HUMAN` or waiting on operator intervention, Trabajo actual and Dashboard attention indicators SHALL NOT report "Sin anomalías reportadas" or simulate normal execution. When a later scoped gate replaces an earlier one or a gate is resolved, the active gate SHALL reflect only the current unresolved request; a resolved earlier gate's payload SHALL NOT be used as fallback or displayed as current across page reloads or stage transitions. Original workflow wording and options SHALL be preserved verbatim, distinguished from labeled agent suggestions, with Spanish explanation of causes and consequences. For exhausted Apply recovery, the UI SHALL display diagnostic context (attempts, pending tasks, candidate SHA, test outcomes) and plainly indicate when logs are unavailable. WAITING_CAPACITY, UNKNOWN and legacy status labels SHALL NOT independently create a human gate. The human intervention card SHALL present an executive Spanish summary in no more than two concise lines, render pending blockers, warnings or decisions as titled visual bullets with warning affordances, and SHALL NOT expose the complete technical message as one semicolon-concatenated paragraph. Action options SHALL have a clear Spanish title and effect description. Technical hashes, raw payloads, large diffs and equivalent low-level evidence SHALL be collapsed by default under an accordion titled "Detalles técnicos y auditoría", while preserving the gate identity and surrounding context when expanded. If the enriched fields are absent, the UI SHALL split and clean legacy semicolon-delimited strings and present existing options with an orderly readable fallback.

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

#### Scenario: Structured gate is readable in Spanish
- **GIVEN** a current `proposal_feasibility` gate contains a summary and multiple technical warnings separated by semicolons
- **WHEN** the operator opens its card in Trabajo actual
- **THEN** the card shows a concise Spanish summary, separate titled warning bullets and action-oriented Spanish options
- **AND** it does not show the warnings as one monolithic technical paragraph.

#### Scenario: Technical audit remains available without dominating the gate
- **GIVEN** a current Human Gate includes hashes, raw payload fields or an extensive diff
- **WHEN** the operator views the gate card
- **THEN** those details are collapsed under "Detalles técnicos y auditoría"
- **AND** expanding the accordion keeps the current gate question, options and identity in context.

#### Scenario: Legacy payload degrades safely
- **GIVEN** a historical run has no `summary_es`, `pending_items` or `options_es`
- **WHEN** Trabajo actual renders its Human Gate
- **THEN** the UI remains functional, cleans semicolon-delimited legacy text into ordered bullets and renders the existing options in a readable fallback.

### Requirement: Structured Spanish Human Gate payload
The Runs read path SHALL expose `stop_details["human_payload"]` with `summary_es`, a clean list `pending_items`, and Spanish plain-language `options_es` for active `proposal_feasibility` and `apply_escalation` gates. The enriched fields SHALL be derived from the current gate only, SHALL remain safe for the existing redaction boundary, and SHALL NOT replace the original workflow question, option values or durable response authority.

#### Scenario: Proposal feasibility payload is enriched
- **GIVEN** the coordinator pauses an active Run with `HUMAN_REQUIRED` for `proposal_feasibility`
- **WHEN** the Runs endpoint returns the current `stop_details["human_payload"]`
- **THEN** it includes a concise `summary_es`, parsed `pending_items` and Spanish `options_es` with descriptions of each option's effect
- **AND** the original question and machine-action values remain available for response submission.

#### Scenario: Apply escalation payload is enriched
- **GIVEN** the coordinator pauses an active Run with `HUMAN_REQUIRED` for `apply_escalation`
- **WHEN** the Runs endpoint returns the current `stop_details["human_payload"]`
- **THEN** it includes the same Spanish summary, pending-item and option fields for the Apply escalation context
- **AND** it does not change the existing transition or response semantics.

#### Scenario: Enrichment does not weaken fail-closed behavior
- **GIVEN** a gate payload cannot be safely parsed or the current gate identity is ambiguous
- **WHEN** the coordinator or Runs endpoint constructs the human payload
- **THEN** the existing fail-closed gate and redaction behavior remains in force
- **AND** no fabricated option, transition, approval or normal-running status is emitted.

### Requirement: Human Gate presentation verification
The change SHALL include focused frontend unit coverage for legacy-string parsing and option rendering, backend coverage for both enriched gate types, and a Playwright browser check against the served Trabajo actual experience. The verification SHALL observe the existing response request and resulting authoritative Run update without replacing them with a simulated transition.

#### Scenario: Browser verifies structured gate and preserved response path
- **GIVEN** an isolated real-browser fixture exposes a current structured Human Gate in Trabajo actual
- **WHEN** Playwright renders the page and the operator selects and submits an option
- **THEN** the browser observes the Spanish structured card, the technical accordion and the existing response request
- **AND** the refreshed Run reflects the backend-authoritative response outcome and state transition.

### Requirement: Immediate feedback for human gate responses
Trabajo actual SHALL provide immediate optimistic feedback when the operator submits a response to the current human gate. While the response is being submitted, it SHALL hide the answered question and show submission progress. After server acceptance, it SHALL show «Respuesta enviada, procesando…» while the coordinator continues. If the response is rejected or the request fails, the UI SHALL restore the same unresolved gate and show the error. The optimistic state SHALL NOT alter the durable Run projection or claim that execution has completed.

#### Scenario: Response is accepted
- **WHEN** the operator submits a valid response and the existing endpoint accepts it
- **THEN** the answered gate is hidden immediately, «Respuesta enviada, procesando…» is shown, and the UI waits for the authoritative run update

#### Scenario: Response fails
- **WHEN** the endpoint rejects the response or the request fails
- **THEN** the gate question and options are restored and the UI displays an error without claiming acceptance

#### Scenario: Coordinator publishes the updated run
- **WHEN** a later SSE update refreshes the Run after the accepted response
- **THEN** the optimistic acknowledgement is reconciled with the authoritative current gate or run state, including any newly raised gate

### Requirement: Terminal run projections are not human-required
The orchestration runs endpoint SHALL classify a run as non-human-required when `is_active` is false, its `stop_outcome` is `COMPLETED`, `FAILED`, or `CANCELLED`, or its `current_stage` is `COMPLETED`, regardless of stale human-gate or payload fields. Such a run SHALL retain the endpoint's existing non-human status projection (`COMPLETED` when inactive). A non-terminal active run SHALL retain the existing human-gate projection behavior.

#### Scenario: Completed run has a stale human gate
- **GIVEN** a run has `current_stage=COMPLETED`, `stop_outcome=COMPLETED`, `is_active=false`, and `human_gate=NEEDS_HUMAN`
- **WHEN** the operator requests `GET /api/v1/orchestration/runs`
- **THEN** the run is projected as `COMPLETED` and not `HUMAN_REQUIRED`

#### Scenario: Failed or cancelled stop outcome has a stale human gate
- **GIVEN** an inactive run has `human_gate=NEEDS_HUMAN` and `stop_outcome` is `FAILED` or `CANCELLED`
- **WHEN** the operator requests `GET /api/v1/orchestration/runs`
- **THEN** the run is not projected as `HUMAN_REQUIRED`

#### Scenario: Completed stage has a stale human stop outcome
- **GIVEN** a run has `current_stage=COMPLETED`, `is_active=false`, and stale human-gate data
- **WHEN** the operator requests `GET /api/v1/orchestration/runs`
- **THEN** the run is not projected as `HUMAN_REQUIRED`, even if another persisted gate field is stale

#### Scenario: Non-terminal run still exposes its current human gate
- **GIVEN** an active non-terminal run has a current human gate
- **WHEN** the operator requests `GET /api/v1/orchestration/runs`
- **THEN** the run retains the existing `HUMAN_REQUIRED` projection

#### Scenario: Inactive run has a residual human stop outcome
- **GIVEN** a run has `is_active=false`, a non-terminal `current_stage`, and `human_gate=NEEDS_HUMAN` or `stop_outcome=NEEDS_HUMAN`
- **WHEN** the operator requests `GET /api/v1/orchestration/runs`
- **THEN** the run is projected as `COMPLETED` and not `HUMAN_REQUIRED`

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
