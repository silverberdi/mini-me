# Spec Delta

## MODIFIED Requirements

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
