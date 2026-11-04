## ADDED Requirements

### Requirement: Terminal run projections are not human-required
The orchestration runs endpoint SHALL classify a run as non-human-required when its `stop_outcome` is `COMPLETED`, `FAILED`, or `CANCELLED`, or its `current_stage` is `COMPLETED`, regardless of stale human-gate or payload fields. Such a run SHALL retain the endpoint's existing non-human status projection. A non-terminal run SHALL retain the existing human-gate projection behavior.

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
- **GIVEN** a non-terminal run has a current human gate
- **WHEN** the operator requests `GET /api/v1/orchestration/runs`
- **THEN** the run retains the existing `HUMAN_REQUIRED` projection
