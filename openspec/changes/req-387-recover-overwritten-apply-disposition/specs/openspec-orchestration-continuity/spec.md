## ADDED Requirements

### Requirement: Human-authorized rebaseline recovers a lost Apply checkpoint
For a lost validated Apply disposition checkpoint whose evidence proves a single unchanged candidate, the system SHALL offer an explicit, single-use operator authorization to treat the current strictly validated Change task dispositions as a new recovery baseline. It SHALL record the authorization and baseline durably and atomically while retaining prior snapshots, decisions, and invocation results as immutable history. After rechecking candidate identity and confirming no stage invocation is active, it SHALL dispatch at most one native Apply continuation for the same Run, Change, branch, worktree, generation, and candidate SHA. Replaying the same action SHALL NOT duplicate the baseline or Apply dispatch. If recovery is ambiguous or unsafe, the current human gate SHALL remain and SHALL offer preserving or cancelling the Run through existing authorized behavior.

#### Scenario: Operator authorizes a safe rebaseline
- **GIVEN** the human gate presents consistent evidence for the same Run, Change, branch, worktree, generation, and candidate SHA
- **AND** no stage invocation is active
- **WHEN** the operator explicitly authorizes using the current Change state as the recovery baseline
- **THEN** the system atomically records the authorization and baseline without deleting or rewriting prior snapshots or invocation history
- **AND** dispatches exactly one Apply continuation using that same candidate identity
- **AND** a replay of the authorization observes the persisted transition and does not dispatch a second Apply.

#### Scenario: Recovery is rejected when identity or invocation safety is uncertain
- **GIVEN** the candidate identity differs from the recorded evidence, a stage invocation is active, or the evidence cannot establish the lost-checkpoint sequence
- **WHEN** the operator attempts rebaseline or the coordinator evaluates recovery
- **THEN** the system keeps the human gate active and explains the mismatched or missing evidence
- **AND** creates no baseline and dispatches no Apply
- **AND** allows the operator to preserve or cancel the Run using the existing authorized cancellation path.

#### Scenario: Rebaseline does not certify pending validation
- **GIVEN** the current Change contains pending or deferred tasks and any published-version evidence has an unknown or non-matching SHA
- **WHEN** the operator authorizes rebaseline
- **THEN** the baseline retains those tasks as pending or deferred
- **AND** no task is marked complete and no candidate-specific validation is claimed from that published evidence.
