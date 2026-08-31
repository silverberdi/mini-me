# Scheduler TUI Observability Specification

## ADDED Requirements

### Requirement: TUI Queue and Scheduler Projection
The system SHALL provide an interactive Textual TUI screen dedicated to the work queue and scheduler, displaying scheduler mode, queue depth, READY count, blocked count, prioritized candidates table, next-to-admit spotlight, blocker reasons, and recent admission decisions.

#### Scenario: Display queue metrics and ranked items
Given a queue containing 3 items (1 READY, 2 BLOCKED) and scheduler mode `RUN`
When an operator navigates to the Queue screen in the TUI
Then the header SHALL display `Mode: RUN | Depth: 3 | Ready: 1 | Blocked: 2`
And the candidates table SHALL list all 3 items ordered by priority score
And the READY item SHALL be highlighted in the next-to-admit spotlight.

### Requirement: Interactive Operator Controls for Scheduler
The system SHALL provide operator controls within the TUI to trigger a manual scheduler tick (`t`), refresh queue state (`r`), and inspect item explainability details (`enter`) without bypassing backend authority rules.

#### Scenario: Trigger manual scheduler tick
Given the operator viewing the Queue screen
When the operator presses the `t` key
Then the TUI SHALL invoke `POST /api/v1/scheduler/tick`
And refresh the view with updated admission decisions and newly active runs.

### Requirement: Multi-Viewport Responsive Layouts
The system SHALL support responsive layout adaptations across narrow (80-100 columns), normal (120-160 columns), and wide (>170 columns) viewports, avoiding clipped diagnostic information or overlapping panels.

#### Scenario: Responsive layout in narrow viewport
Given a terminal with width 90 columns
When the Queue screen renders
Then the view SHALL collapse secondary metadata columns into compact format while preserving change name, priority, and blocker reason visibility.
