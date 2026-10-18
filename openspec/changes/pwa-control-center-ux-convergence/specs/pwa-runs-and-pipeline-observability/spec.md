## MODIFIED Requirements

### Requirement: Orchestration Runs Table and Filtering
The system SHALL provide an authenticated run list backed by the orchestration/dashboard read models, displaying only returned identity, project/change, current stage, exact status, timestamp and duration. It SHALL support useful status filtering on desktop and tablet and an equivalent compact list on mobile; filtering SHALL NOT change lifecycle state or collapse distinct states such as `RUNNING`, `WAITING_CAPACITY`, `NEEDS_HUMAN`, `RECOVERY`, `UNKNOWN` and `READY_FOR_HUMAN_MERGE`.

#### Scenario: Filter an authoritative human-attention run
Given the run list contains runs in different canonical states including `NEEDS_HUMAN`
When the operator selects the human-attention filter
Then only matching runs SHALL be shown with their exact state and project/change identity
And selecting a row SHALL open its associated detail view.

#### Scenario: Filter runs by NEEDS_HUMAN status
Given multiple runs exist with authoritative statuses `RUNNING`, `NEEDS_HUMAN`, and `COMPLETED`
When the operator selects the `NEEDS_HUMAN` filter
Then the list SHALL show only the runs whose returned status is `NEEDS_HUMAN`.

#### Scenario: Preserve unknown and waiting states
Given a run status is `WAITING_CAPACITY`, `RECOVERY`, or `UNKNOWN`
When a filter or compact mobile card renders it
Then the exact state and any server-provided reason SHALL remain distinguishable from `PAUSED`, `FAILED`, and `NEEDS_HUMAN`.

### Requirement: Visual Pipeline Phase Stepper
The system SHALL visualize the pipeline from authoritative per-run phase evidence and candidate-bound checkpoints. It SHALL not assume completion or ordering from a display-only list of stages, and missing, stale, or conflicting evidence SHALL be rendered as `UNKNOWN`/stale. The visual hierarchy SHALL follow the approved Stitch Run detail composition while keeping progress understandable without motion or color.

#### Scenario: Display active pipeline phase
Given a selected Run detail returns completed, active, pending and blocked phase evidence
When the operator views the pipeline
Then completed and active phases SHALL match the returned evidence
And phases without evidence SHALL NOT be marked complete.

#### Scenario: Display active stage in pipeline stepper
Given the selected Run detail reports an active canonical phase and evidence for prior phases
When the pipeline stepper renders
Then prior phases SHALL be marked complete only when evidence says they completed
And the reported active phase SHALL be highlighted without inferring later phases.

#### Scenario: Conflicting candidate checkpoint evidence
Given a checkpoint belongs to a different candidate generation or SHA than the selected candidate
When the pipeline detail renders
Then that checkpoint SHALL be marked stale or unrelated
And SHALL NOT be shown as verification of the selected candidate.

### Requirement: Prominent Attention Banner for Human Gates
The system SHALL surface human-only decisions and blocked work from authoritative attention items, including reason, affected project/change, Run/Job identity, consequence and available safe next step when supplied. `WAITING_CAPACITY` and `UNKNOWN` SHALL NOT be recast as human decisions. Navigation to details SHALL preserve the selected Run identity.

#### Scenario: Open a genuine human attention item
Given the dashboard overview contains a `NEEDS_HUMAN` item with canonical reason and remediation guidance
When the operator selects the item
Then the UI SHALL open the matching Run/Job detail and display the reason, consequence and permitted next step.

#### Scenario: Click attention banner to navigate to blocked run
Given an authoritative attention item identifies a Run requiring a human decision
When the operator selects that item from the banner
Then the matching Run SHALL be selected and its detail SHALL be opened.

#### Scenario: Capacity wait is not a human gate
Given a Run is waiting for provider capacity and no human decision is required
When the attention surface renders
Then it SHALL display a capacity wait state and evidence freshness
And SHALL NOT solicit a human answer or show an enabled action not authorized by the backend.

### Requirement: Candidate Lineage, Checks, Review, and Audit Inspector
The system SHALL present candidate lineage and its checks/reviews/audits only when bound to the selected project, Run/Job, generation, head SHA and base SHA. It SHALL distinguish absent, pending, failed, stale, superseded and unknown evidence. It SHALL show structured findings and sanitized summaries without treating an audit, check, or image value as a review or merge authorization.

#### Scenario: Inspect evidence for the exact current candidate
Given dashboard detail returns a candidate and checks/review evidence matching its generation and SHAs
When the operator opens candidate evidence
Then the candidate identity and corresponding evidence SHALL be displayed together with source state and timestamp.

#### Scenario: Display complementary review verdict and findings
Given the current candidate has an independent review bound to its exact identity
When the candidate inspector renders
Then the reviewer identity, verdict and structured findings SHALL match the returned review evidence.

#### Scenario: Review evidence belongs to a superseded candidate
Given review evidence is bound to an earlier candidate generation
When the current candidate is displayed
Then the earlier review SHALL be marked stale/superseded
And SHALL NOT appear as approval of the current candidate or authorize merge.

#### Scenario: Indicate stale evidence for superseded candidate
Given an earlier candidate generation has review evidence and a newer generation is current
When the earlier evidence is viewed
Then it SHALL be labeled stale/superseded and excluded from the current candidate's approval state.

#### Scenario: Evidence is absent or diagnostic output is sensitive
Given evidence is missing or its summary contains secret-like material
When evidence is rendered
Then missing evidence SHALL remain pending/unavailable
And diagnostics SHALL be redacted and safely encoded before display.
