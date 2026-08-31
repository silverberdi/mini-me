# Scheduler TUI Observability Specification

## Purpose
Provide operator visibility and control over queue depth, candidate rankings, explainability scores, and scheduler admission status in the TUI console.

## Requirements

### Requirement: Queue and Scheduler View
The system SHALL provide an interactive Queue View in the TUI console displaying queue depth, ready/blocked counts, ranked candidate table, and score breakdown.

#### Scenario: Inspect queue in TUI console
- **GIVEN** work items exist in the autonomous queue
- **WHEN** the operator switches to tab 5 (Queue & Scheduler)
- **THEN** the TUI SHALL display the ranked list of candidates with priority, roadmap stage, readiness state, priority score, and eligibility.

### Requirement: Interactive Explainability and Manual Tick
The system SHALL support inspecting score breakdowns for selected items and triggering on-demand scheduler ticks from the TUI.

#### Scenario: Operator selects item to inspect explainability
- **GIVEN** the operator is on the Queue tab
- **WHEN** a row in the queue table is selected
- **THEN** the explainability side panel SHALL display the score breakdown, blockers, and selection rationale.
