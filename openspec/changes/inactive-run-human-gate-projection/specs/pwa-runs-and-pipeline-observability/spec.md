## MODIFIED Requirements

### Requirement: Visual Pipeline Phase Stepper
The system SHALL display Trabajo actual as an independent route with actual OpenSpec stages, applicable tasks and observed status. Completion SHALL require evidence; stage position SHALL NOT imply preceding completion. Selecting a stage SHALL show verified task/attempt outputs, actual agent/model assignments and observed timestamps, distinguishing active, waiting, failed and unknown states. When no Run is explicitly selected, Trabajo actual SHALL select only an active Run and SHALL NOT fall back to an inactive historical Run. The UI SHALL NOT narrate agent thoughts.

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
