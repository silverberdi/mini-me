# pwa-app-shell-and-queue Specification

## Purpose
TBD - created by archiving change 017-pwa-control-center. Update Purpose after archive.

## Requirements

### Requirement: PWA Application Shell and Navigation
The system SHALL provide a modern Progressive Web App shell displaying brand identity, real-time backend connection status, scheduler mode indicator (`RUN`/`DRAIN`/`WAIT`), database health, and configurable auto-refresh controls (5s, 10s, 30s, or manual).

#### Scenario: View application shell with live health indicators
Given the PWA Control Center is loaded in a web browser
When the application initializes
Then the system SHALL render the brand header, current scheduler mode badge, database health indicator, and auto-refresh dropdown.

#### Scenario: Toggle auto-refresh interval
Given the PWA Control Center is actively polling at 10s intervals
When the operator selects a 5s interval from the refresh dropdown
Then the polling timer SHALL adjust to 5s and trigger an immediate data fetch.

### Requirement: KPI Summary Overview Grid
The system SHALL render an operational KPI grid displaying current system state, attention count (human gates / active blockers), active in-flight executions count, and total completed/merged changes.

#### Scenario: Render KPI summary with active executions
Given an orchestration run is currently in progress
And one run is paused at a `NEEDS_HUMAN` gate
When the overview KPI grid renders
Then the `SYSTEM STATE` card SHALL indicate active status
And the `ATTENTION REQUIRED` card SHALL display count `1`
And the `ACTIVE EXECUTIONS` card SHALL display count `1`.

### Requirement: Autonomous Queue Prioritization Telemetry
The system SHALL render the autonomous queue prioritization panel showing ranked candidate changes, calculated priority scores, starvation aging bonuses, dependency states, and explainable admission refusal reasons (`ROADMAP_PREDECESSOR_INCOMPLETE`, `PROVIDER_DRAIN`, `GLOBAL_CONCURRENCY_LIMIT`, etc.).

#### Scenario: Inspect ranked queue candidates and explainability
Given two candidate items in the work queue where Item A has higher priority score than Item B
When the queue panel renders
Then Item A SHALL be displayed above Item B
And expanding Item A SHALL display its base score, starvation aging bonus, total score, and admission eligibility.

#### Scenario: Display blocked reason for ineligible queue item
Given a queue item for change `017-pwa-control-center` blocked by an incomplete predecessor stage
When the queue candidate item is inspected
Then the system SHALL render a `BLOCKED` badge with the refusal code `ROADMAP_PREDECESSOR_INCOMPLETE`.
