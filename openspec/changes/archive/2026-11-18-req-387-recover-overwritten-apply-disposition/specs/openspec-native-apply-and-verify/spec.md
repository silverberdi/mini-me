## ADDED Requirements

### Requirement: Recovery of a lost validated Apply disposition checkpoint
When a pre-deployment Run has a durable Apply snapshot and an accepted operator action linked to a completed, strictly validated native OpenSpec Update, but a later no-op Update replaced the validated disposition details, the system SHALL detect the lost checkpoint from persisted evidence and SHALL NOT infer that the Update's task dispositions are still available or validated. It SHALL preserve the current Change, candidate, prior Apply snapshot, operator action, and native invocation history. It SHALL NOT mark pending or deferred tasks complete from the old snapshot or from published-version evidence without a matching immutable candidate SHA.

#### Scenario: Lost checkpoint is evidenced for the same candidate
- **GIVEN** an Apply-gated Run has a prior Apply snapshot and accepted operator action
- **AND** durable stage-invocation evidence records a completed and strictly validated native Update for the same Run, Change, branch, worktree, generation, and candidate SHA
- **AND** a later Update record is a no-op and lacks the original disposition detail
- **WHEN** recovery evaluates the Run
- **THEN** it keeps the Run gated and presents the prior snapshot, current task dispositions, accepted action, validated Update result, no-op result, and exact candidate identity for human review
- **AND** it preserves all tasks that remain pending or deferred as such
- **AND** it dispatches no Apply until the operator explicitly authorizes recovery.

#### Scenario: Evidence does not prove one unchanged candidate
- **GIVEN** the snapshot, accepted action, Update invocation, Run, Change, branch, worktree, generation, or candidate SHA is missing, ambiguous, active, or mismatched
- **WHEN** recovery evaluates the lost-checkpoint report
- **THEN** it keeps the Run stopped for human intervention
- **AND** it neither creates a new baseline nor dispatches Apply.
