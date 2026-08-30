# TUI Operator Console Specification

## ADDED Requirements

### Requirement: Interactive Terminal Operator Console
The system SHALL provide an interactive terminal operator console (`minime console` / `minime tui`) built with Textual that presents multi-project system status, attention items, active executions, pipeline progression, candidate lineage, check diagnostics, review findings, DeepSeek audit risk, 013 preview state, and transition history without direct PostgreSQL queries from UI widgets.

#### Scenario: Launch console and display overview
Given a running mini me environment with registered projects and changes
When an operator launches `minime console`
Then the TUI SHALL display the Overview screen
And the header SHALL display database connectivity, scheduler mode, active runs count, and attention items count
And the screen SHALL render system health, attention queue, active executions, provider capacity, and recent completions.

#### Scenario: Empty state overview
Given no registered changes or active runs
When an operator opens the Overview screen
Then the TUI SHALL display clear empty-state cards explaining that no active executions or attention items exist
And the system health status SHALL show healthy database connectivity.

### Requirement: Responsive Multi-Viewport Terminal Adaptation
The system SHALL adapt its layout intelligently across narrow (<110 cols), normal (110–170 cols), and wide (>170 cols) terminal widths, maximizing usable space on wide terminals without overflowing or clipping on narrow terminals.

#### Scenario: Wide terminal layout
Given a terminal viewport with width greater than 170 columns
When the TUI is rendered
Then the layout SHALL utilize a multi-column format
And the navigation, pipeline details, and candidate evidence panels SHALL be visible simultaneously without excessive blank margins.

#### Scenario: Normal terminal layout
Given a terminal viewport with width between 110 and 170 columns
When the TUI is rendered
Then the layout SHALL use a balanced two-column format with change lists on the left and active pipeline/evidence details on the right.

#### Scenario: Narrow terminal layout
Given a terminal viewport with width less than 110 columns
When the TUI is rendered
Then the layout SHALL stack panels vertically and use tabbed drill-down navigation
And no text or borders SHALL overlap or clip unreadably.

### Requirement: Interactive Change and Run Navigation
The system SHALL provide an interactive Changes screen allowing operators to inspect, filter, and select changes, immediately loading the corresponding run detail and pipeline view.

#### Scenario: Select change from table
Given multiple changes listed in the Changes table
When an operator navigates to a change and presses `Enter`
Then the TUI SHALL switch to the Run Detail view for that change
And the header and pipeline stepper SHALL reflect that change's current stage and candidate identity.

### Requirement: Visual Pipeline Stage and Candidate Lineage Projection
The system SHALL project the 6 core pipeline phases (readiness, implementation, checks, review, audit, pr_merge) using visual badges and stepper indicators, and display the candidate authority hierarchy distinguishing the current candidate from historical/superseded candidates.

#### Scenario: Active pipeline stage progression
Given a run currently in stage `CHECKS_RUNNING`
When the Run Detail screen is viewed
Then the Readiness and Implementation phases SHALL show `PASSED`
And the Checks phase SHALL show `RUNNING`
And the Review, Audit, and PR/Merge phases SHALL show `NOT_STARTED` or `BLOCKED`.

#### Scenario: Candidate lineage with remediation generation
Given a run with candidate generation 2
When the Candidate Lineage panel is viewed
Then generation 2 SHALL be marked as the authoritative `CURRENT` candidate
And generation 1 SHALL be visually marked as `SUPERSEDED` / `HISTORICAL`.

### Requirement: Deterministic Check Diagnostics and Review/Audit Authority
The system SHALL display candidate check results, complementary review verdicts, and DeepSeek audit risk assessments, with all diagnostics scrubbed of secret tokens and credentials.

#### Scenario: Check results display
Given check runs recorded for the candidate
When the Checks panel is viewed
Then each check SHALL display its name, status (`PASS`/`FAIL`), exit code, duration in milliseconds, and redacted diagnostic output snippet.

#### Scenario: Stale review and audit isolation
Given a candidate update that incremented candidate generation
And earlier review and audit records exist for the previous generation
When the Review and Audit panels are viewed
Then the TUI SHALL flag the previous review and audit as `STALE`
And they SHALL NOT be displayed as approving the current candidate generation.

### Requirement: 013 Container Preview and Guided Validation Projection
The system SHALL project the real-time lifecycle of container previews (`BUILDING`, `STARTING`, `PROBING`, `READY`, `FAILED`), candidate authority binding `(head_sha, base_sha, image_digest)`, guided validation scenarios with ordered steps and expected outcomes, and prominent `STALE VALIDATION` alerts.

#### Scenario: Ready preview with guided validation scenarios
Given an active container preview session in `READY` status with endpoint URL `http://127.0.0.1:8088`
And configured validation scenarios
When the Preview & Validation screen is viewed
Then the preview status SHALL show `READY` with port 8088 and image digest
And the validation scenarios SHALL display scenario titles, ordered steps, and expected outcomes.

#### Scenario: Stale validation alert on candidate drift
Given a previous validation run with verdict `PASS` for candidate `(sha_h1, sha_b1, img1)`
And the active candidate has changed to `sha_h2`
When the Preview & Validation screen is viewed
Then the validation status SHALL display a `STALE VALIDATION` warning
And the UI SHALL indicate that a fresh validation run is required for the new candidate.

### Requirement: Keyboard-First Navigation and Accessibility
The system SHALL provide discoverable, efficient keyboard shortcuts for all primary navigation and inspection actions, including a dedicated help modal.

#### Scenario: Open keyboard shortcuts help modal
Given the TUI is active on any screen
When the operator presses `?` or `F1`
Then the TUI SHALL open the Keyboard Shortcuts modal displaying all available navigation keys
And pressing `Esc` or `Enter` SHALL dismiss the modal and return to the active screen.

#### Scenario: Switch view tabs via number keys
Given the TUI is active on the Overview screen
When the operator presses `2`
Then the TUI SHALL switch to the Changes screen
And pressing `1` SHALL switch back to the Overview screen.
