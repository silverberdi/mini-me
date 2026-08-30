# Guided Validation Workflow Specification

## Purpose

Defines spec-driven visual validation scenarios, operator verdict submission interfaces, candidate-bound validation history tracking, and interactive preview and validation controls within the operations dashboard.

## Requirements

### Requirement: Guided Validation Scenarios
The system SHALL provide explicit, structured validation scenarios with ordered steps and expected visual outcomes for every UI-affecting change.

#### Scenario: Scenario structure and requirements
Given a UI change with defined acceptance criteria
When validation scenarios are loaded for the candidate
Then each scenario SHALL contain a scenario ID, title, ordered user steps, expected visible result, and required/optional flag.

### Requirement: Validation Run Verdict Submission
The system SHALL allow operators to execute scenarios, record scenario-level results, and submit an overall `PASS` or `FAIL` validation verdict.

#### Scenario: Successful operator PASS submission
Given an active candidate preview in `READY` status
When the operator reviews and passes all required scenarios and submits verdict `PASS`
Then a new `ValidationRun` record SHALL be persisted with `verdict=PASS`, timestamp, operator identity, and scenario results.

#### Scenario: Operator FAIL submission
Given an active candidate preview displaying visual defects
When the operator submits verdict `FAIL` with explanatory notes
Then a `ValidationRun` record SHALL be persisted with `verdict=FAIL`
And the orchestration pipeline SHALL record the validation failure.

### Requirement: Operations Dashboard Guided Validation UI
The system SHALL integrate the preview lifecycle and guided validation workflow into the operations dashboard web interface.

#### Scenario: Dashboard preview and validation display
Given an active orchestration run with a candidate requiring UI validation
When an operator navigates to the dashboard change detail
Then the dashboard SHALL display the preview lifecycle card (status, port, preview URL)
And the dashboard SHALL render the guided scenarios checklist, candidate tuple identity, and PASS/FAIL action controls.

#### Scenario: Stale validation alert display
Given an orchestration run whose candidate has drifted after an earlier validation
When the dashboard renders the change detail
Then the dashboard SHALL display a warning banner indicating that prior validation is stale
And the action controls SHALL prompt for a fresh validation run.
