# Execution Operations Dashboard Specification

## Purpose

Provides a unified operations dashboard read model, REST APIs, and self-contained web interface for multi-project orchestration visibility, real-time pipeline tracking, candidate authority management, and secret-scrubbed diagnostic presentation.

## Requirements

### Requirement: Change and Run Observability
The system SHALL provide a unified dashboard read model exposing discovered and active changes, orchestration runs, and execution states without requiring direct database queries.

#### Scenario: Overview query with active changes
Given registered projects and changes in various lifecycle states
When an operator queries the dashboard overview
Then the system SHALL return summary statistics, active executions, attention items, and change list
And each change entry SHALL include project identity, change name, current orchestration run, active job, current stage, executor, generation, candidate SHA, and timestamp.

#### Scenario: Empty state query
Given no registered changes or active runs
When an operator queries the dashboard overview
Then the system SHALL return empty lists for active executions and attention items with valid system health metadata.

### Requirement: Pipeline Stage Projection
The system SHALL expose the 6 core pipeline phases (readiness, implementation, deterministic checks, complementary review, DeepSeek audit, and PR/merge) derived strictly from durable persisted evidence.

#### Scenario: In-progress implementation stage
Given an orchestration run currently in stage `IMPLEMENTING`
When pipeline progress is projected
Then readiness SHALL be `PASSED`
And implementation SHALL be `RUNNING`
And checks, review, audit, and PR/merge SHALL be `NOT_STARTED`.

#### Scenario: Failed checks stage
Given an orchestration run where deterministic checks failed
When pipeline progress is projected
Then checks SHALL be `FAILED`
And review, audit, and PR/merge SHALL be `BLOCKED` or `NOT_STARTED`.

### Requirement: Attention and Blocker Surface
The system SHALL prominently surface runs requiring operator attention, including `NEEDS_HUMAN`, `WAITING_CAPACITY`, and `RECOVERY_BLOCKED` states with root cause details and structured stop codes.

#### Scenario: Run stopped at NEEDS_HUMAN
Given an orchestration run stopped with `NEEDS_HUMAN` stop outcome
When dashboard overview or change detail is requested
Then the run SHALL be included in attention items
And the item SHALL include canonical reason, structured stop code, and retry viability.

### Requirement: Candidate Authority and Stale Evidence Isolation
The system SHALL display the authoritative candidate generation, candidate SHA, and base SHA, and SHALL isolate review and audit evidence to the exact candidate generation.

#### Scenario: Remediation candidate generation
Given a run has progressed to generation 2
And generation 1 had an earlier review or audit
When change details are projected for the current generation
Then the candidate authority SHALL display generation 2 and generation 2 candidate SHA
And generation 1 review or audit results SHALL NOT be presented as valid approvals of generation 2.

### Requirement: Deterministic Check Result Presentation
The system SHALL project all deterministic check results for the current candidate, including check name, exit code, duration in milliseconds, PASS/FAIL status, and short diagnostic snippets.

#### Scenario: Check execution results
Given deterministic checks executed for candidate SHA `c1`
When check results are projected
Then each check result SHALL display check name, execution duration, exit code, and PASS/FAIL status bound to SHA `c1`.

### Requirement: Complementary Review Presentation
The system SHALL display the complementary review status, reviewer role and model, verdict, material finding count, mixed-authorship status, and finding details for the active candidate.

#### Scenario: Completed review with findings
Given a completed review with 1 blocker finding and 1 minor finding
When review details are projected
Then the verdict SHALL be `CHANGES_REQUIRED`
And material finding count SHALL be 1
And each finding SHALL include location, violated requirement, and severity.

### Requirement: DeepSeek Audit Presentation
The system SHALL display the independent DeepSeek Direct audit status, risk rating, material finding count, and audit summary for the active candidate.

#### Scenario: Audit completed with low risk
Given an independent DeepSeek audit completed with risk `low` and 0 findings
When audit details are projected
Then the audit status SHALL be `AUDIT_COMPLETED`
And risk rating SHALL be `low`
And material finding count SHALL be 0.

### Requirement: GitHub and PR State Presentation
The system SHALL project bound GitHub Issue number, Pull Request number, PR URL, PR state, candidate SHA binding, and merge status when present.

#### Scenario: Bound PR state
Given an external PR action completed with PR number 42 and URL `https://github.com/silverberdi/mini-me/pull/42`
When change detail is projected
Then GitHub status SHALL include Issue number, PR number 42, PR URL, and merge state.

### Requirement: Chronological Transition History
The system SHALL provide a chronological event timeline for a selected run or change based on persisted orchestration events.

#### Scenario: Run event history
Given a run with persisted stage transition and check events
When the run event timeline is queried
Then events SHALL be ordered chronologically
And each event SHALL include timestamp, event type, stage transition, and sanitized summary.

### Requirement: Secret Redaction and Diagnostic Sanitization
The system SHALL sanitize all diagnostics, summaries, error messages, and event payloads before returning them via the dashboard API or UI.

#### Scenario: Error message with embedded API key
Given an error message or command diagnostic containing a secret key
When projected through the dashboard service
Then the secret key SHALL be redacted.

### Requirement: Standalone Dashboard Web Interface and Static Asset Delivery
The system SHALL serve a responsive, self-contained web interface with dark/light theme support, accessible badges, and auto-refresh capabilities via FastAPI at `/` and `/dashboard`.

#### Scenario: Accessing the web interface
Given the mini me daemon is running
When an operator accesses `/` or `/dashboard`
Then the server SHALL return the HTML application
And static assets under `/static/` SHALL be delivered without external network dependencies.

### Requirement: Liquidated provider cost presentation
The Dashboard SHALL present cost data only from verifiable liquidated entries in the durable PostgreSQL budget ledger, never by deriving a price from run tokens or by substituting synthetic values. Each presented cost point SHALL retain its ledger timestamp, provider identity, model identity when available, and USD amount at the ledger's precision, and SHALL be attributable separately at minimum to DeepSeek Direct and OpenRouter.

#### Scenario: Display settled DeepSeek and OpenRouter costs
- **WHEN** the durable ledger contains liquidated cost entries for DeepSeek Direct and OpenRouter, including provider, model, amount, and timestamps
- **THEN** the Dashboard displays the real USD amounts in separate provider series or groups
- **AND** each displayed amount retains its recorded provider, model when available, timestamp, and ledger-compatible precision

#### Scenario: Preserve model breakdown when recorded
- **WHEN** liquidated ledger entries for one provider contain distinct model identities
- **THEN** the Dashboard keeps those model identities as a visible breakdown
- **AND** it does not merge the entries into an unattributed provider total when the model data is available

#### Scenario: Include verified-provider costs with unidentified models
- **WHEN** a liquidated ledger entry has a verified provider identity but its model is null or not recognized
- **THEN** the Dashboard includes its amount in that provider's total
- **AND** the model breakdown shows the amount under `Modelo no identificado`
- **AND** it does not attribute the amount to a specific model or another provider

#### Scenario: Do not infer a cost from run tokens
- **WHEN** a Run exposes token counts but the durable ledger has no liquidated price for that usage
- **THEN** the Dashboard does not calculate or display a USD cost from those tokens
- **AND** the usage is not attributed to DeepSeek Direct, OpenRouter, or any model by default

#### Scenario: Explicit no-data state
- **WHEN** no verifiable liquidated cost exists for the Dashboard query
- **THEN** the Dashboard cost payload has the structure `{ "status": "no_data", "providers": [], "series": [] }`
- **AND** the cost visualization displays an explicit “sin datos” state
- **AND** it does not display `0`, `CLI`, an estimate, or a provider/model attribution

#### Scenario: Exclude unknown provider identities
- **WHEN** the durable ledger contains an otherwise liquidated entry whose provider identity is unknown to the existing provider catalog
- **THEN** the entry is excluded from the Dashboard cost payload and provider aggregation
- **AND** the Dashboard does not relabel it as DeepSeek Direct, OpenRouter, or another known identity

#### Scenario: Timestamp-backed time series
- **WHEN** the Dashboard renders a time series of liquidated costs
- **THEN** every point is backed by an observable ledger timestamp and a defined aggregation granularity
- **AND** entries without the required verifiable timestamp are not silently assigned to an invented time bucket

#### Scenario: End-to-end ledger-to-dashboard representation
- **WHEN** PostgreSQL contains registered liquidated usage for DeepSeek Direct and OpenRouter
- **THEN** a real end-to-end verification observes the ledger records, invokes the Dashboard read path, and demonstrates the corresponding provider/model costs in the rendered visualization
