# spec: Reviewer Independence and Telemetry

## Requirements

### Requirement 1: Technical Reviewer Independence Enforcement (Rule G)
The system SHALL track candidate material authors across all attempts leading to a frozen candidate (`material_candidate_authors`).
Eligible reviewers SHALL be computed as `configured_reviewers - material_candidate_authors`.
If an assigned reviewer has material authorship in the candidate, the system SHALL reject the review assignment with `REVIEWER_INDEPENDENCE_UNAVAILABLE` and SHALL NOT transition the candidate to `READY_TO_MERGE` or prepare a PR.

#### Scenario: Author agent prohibited from reviewing candidate
- **GIVEN** Antigravity authored material code in candidate `def5678`
- **WHEN** complementary review selection evaluates eligibility
- **THEN** Antigravity MUST be excluded from eligible reviewers
- **AND** if no other independent reviewer is available, the candidate MUST transition to `REVIEWER_INDEPENDENCE_UNAVAILABLE`.

#### Scenario: Pure independent review allowed
- **GIVEN** Codex is the sole author of candidate `def5678`
- **AND** Antigravity has zero material commits in candidate `def5678`
- **WHEN** complementary review is assigned to Antigravity
- **THEN** reviewer independence evaluation MUST pass.

---

### Requirement 2: Canonical `CHECKS_FAILED` Remediation Routing
When automated checks fail in stage `RUNNING_CHECKS`, the system SHALL NOT dead-end in `CHECKS_FAILED`.
The system SHALL classify the check failure (code/test fix vs platform defect vs bookkeeping) and route the candidate into canonical remediation (`REVIEW_REMEDIATION` / `IMPLEMENTING`), creating a subsequent candidate generation for verification.

#### Scenario: Failed checks route cleanly to remediation
- **GIVEN** candidate generation 1 encounters a test failure during `RUNNING_CHECKS`
- **WHEN** check runner completes with non-zero exit code
- **THEN** orchestration MUST transition to remediation
- **AND** subsequent candidate generation 2 MUST be prepared with failing test context.

---

### Requirement 3: PostgreSQL Efficiency Telemetry & UI Integration
The system SHALL persist per-change and per-run efficiency telemetry in PostgreSQL table `provider_efficiency_metrics`.
Recorded metrics SHALL include: attempts by provider, durations, productive attempt counts, no-progress counts, same-SHA retries, suppressed retries, reassignments, AG premium reason codes, provider exhaustion events, DRAIN transitions, and native self-hosting percentage.
The system SHALL expose these metrics via `/api/v1/telemetry/efficiency/{project_id}/{change_name}`, Textual TUI Provider Efficiency view, and PWA Provider Efficiency telemetry panel.

#### Scenario: Efficiency metrics persisted and exposed via API
- **GIVEN** an orchestration run completed with multiple provider attempts
- **WHEN** telemetry is persisted and queried via `/api/v1/telemetry/efficiency/{project_id}/{change_name}`
- **THEN** response JSON MUST include attempts_by_provider, productive_attempt_count, same_sha_retry_suppressed_count, and self_hosting_percentage.

#### Scenario: TUI and PWA display provider utilization
- **GIVEN** persisted efficiency metrics in PostgreSQL
- **WHEN** the TUI or PWA is rendered
- **THEN** provider utilization tables, productive ratios, and AG reason codes MUST be visually displayed.
