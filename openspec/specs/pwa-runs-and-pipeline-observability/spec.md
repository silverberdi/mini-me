# pwa-runs-and-pipeline-observability Specification

## Purpose
TBD - created by archiving change 017-pwa-control-center. Update Purpose after archive.

## Requirements

### Requirement: Orchestration Runs Table and Filtering
The system SHALL provide an interactive orchestration runs list displaying run ID, project, target change name, current stage, status badge, created timestamp, and duration, supporting quick filtering by status (`ALL`, `IN_PROGRESS`, `NEEDS_HUMAN`, `FAILED`, `COMPLETED`).

#### Scenario: Filter runs by NEEDS_HUMAN status
Given multiple runs exist with statuses `IN_PROGRESS`, `NEEDS_HUMAN`, and `COMPLETED`
When the operator clicks the `NEEDS_HUMAN` filter button
Then the table SHALL display only runs requiring human attention.

### Requirement: Visual Pipeline Phase Stepper
The system SHALL provide a sequential visual phase stepper representing canonical lifecycle stages (`WORKTREE_SETUP`, `IMPLEMENTATION`, `CHECKS`, `REVIEW`, `AUDIT`, `PREVIEW`, `PR`, `MERGE_GATE`, `CLOSURE`), highlighting completed stages in green, active stage with pulsing progress indicator, paused human gates in warning color, and failed stages in danger color.

#### Scenario: Display active stage in pipeline stepper
Given an orchestration run currently in the `CHECKS` stage
When the pipeline stepper is rendered for the selected run
Then `WORKTREE_SETUP` and `IMPLEMENTATION` SHALL render as completed (checked/success)
And `CHECKS` SHALL render with an active progress indicator
And subsequent stages SHALL render as pending/upcoming.

### Requirement: Prominent Attention Banner for Human Gates
The system SHALL display a prominent Attention Banner at the top of the view whenever one or more runs are in `NEEDS_HUMAN` status, highlighting the gate reason, blocker claims, affected change, and providing a direct action link to the resolution drawer.

#### Scenario: Click attention banner to navigate to blocked run
Given a run is waiting for human gate resolution
When the operator clicks the attention banner alert
Then the UI SHALL select that run and open its action resolution panel.

### Requirement: Candidate Lineage, Checks, Review, and Audit Inspector
The system SHALL provide a dedicated candidate inspection pane displaying candidate generation, base SHA, head SHA, checks runner execution logs and exit codes, complementary reviewer verdict and structured findings, DeepSeek audit risk ratings, and clear visual indicators when displayed evidence belongs to a superseded candidate.

#### Scenario: Display complementary review verdict and findings
Given an authoritative candidate has completed complementary review with verdict `READY_TO_MERGE`
When the candidate inspector panel renders
Then the system SHALL display the reviewer role badge (`antigravity`), verdict `READY_TO_MERGE`, and zero blocking findings.

#### Scenario: Indicate stale evidence for superseded candidate
Given a previous candidate generation was reviewed
And a new candidate generation has since been created
When the previous candidate's evidence is viewed
Then the system SHALL display a prominent `STALE (Superseded by Gen N)` warning badge.
