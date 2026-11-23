## ADDED Requirements

### Requirement: Verified review corrections authorize guarded Apply re-entry
When a valid review result contains actionable corrections and the orchestration policy routes the same candidate back to implementation, the system SHALL authorize a new native Apply invocation using those observed corrections, without requiring an unrelated human recovery token. Re-entry SHALL remain bound to the same Run, Change, branch, worktree, and candidate lineage; SHALL preserve review findings and prior invocation evidence; and SHALL retain existing retry, budget, regression, and human-authorization limits. Review approval alone SHALL NOT bypass a genuine human gate or authorize a scope change.

#### Scenario: Review corrections resume Apply on the same candidate
- **GIVEN** a completed review records actionable corrections for the current candidate and the canonical workflow routes remediation to Apply
- **WHEN** the coordinator re-enters the Apply stage
- **THEN** it dispatches native Apply with the recorded corrections and valid invocation authority
- **AND** it reuses the same Run, Change, branch, worktree, and candidate lineage
- **AND** it retains prior attempts and applies existing retry and regression checks.

#### Scenario: Review correction cannot bypass identity or human authorization
- **GIVEN** review findings exist but the candidate identity changed, a required human decision remains unresolved, or the correction would exceed authorized scope
- **WHEN** Apply re-entry is evaluated
- **THEN** mini me blocks dispatch with the concrete reason and exposes any existing authorized recovery action
- **AND** it does not treat the findings themselves as authorization to change identity, scope, or human decisions.
