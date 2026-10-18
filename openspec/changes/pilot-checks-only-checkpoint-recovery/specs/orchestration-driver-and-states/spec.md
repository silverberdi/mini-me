## ADDED Requirements

### Requirement: Checks-Only State Re-Entry Without Implementer Loop
The orchestration driver SHALL support entering `RUNNING_CHECKS` from an in-progress or interrupted run without transitioning through the `IMPLEMENTING` provider execution loop when recovering a preserved, unmutated candidate.

#### Scenario: Driver receives checks-only continuation directive
- **WHEN** `drive_coordinator()` is invoked with a valid claim context and an explicit checks-only directive
- **AND** the active job has a verified `candidate_sha` and worktree HEAD match
- **THEN** the coordinator SHALL transition directly to `RUNNING_CHECKS`
- **AND** the coordinator SHALL execute deterministic checks using `ChecksRunner`
- **AND** the coordinator SHALL NOT execute `pipeline.execute_queued_job()` or dispatch new implementer attempts.

#### Scenario: Checks pass and coordinator advances to freeze and review
- **WHEN** `RUNNING_CHECKS` completes successfully under checks-only continuation
- **THEN** the driver SHALL advance the run to `FREEZING_CANDIDATE`
- **AND** subsequent execution SHALL follow canonical candidate manifest generation, complementary code review, and PR preparation.
