## MODIFIED Requirements

### Requirement: Safe recovery of orphaned stage invocations after restart
The coordinator SHALL recover an incomplete stage invocation only when the durable claim is no longer active, the recorded candidate and stage match the invocation being resumed, and persisted process identity evidence proves that the previous coordinator and workflow process group are gone. A different recorded boot identity SHALL classify the previous process as gone when the identity belongs to the same host. Recovery SHALL use the existing fenced claim mechanism to replace the expired ownership, record one auditable `STAGE_INVOCATION_ABANDONED` event with a reason grounded in the observed evidence, and start a new invocation for the same candidate and stage. When an abandoned `APPLY` invocation is evaluated under mechanical remediation and its managed worktree contains uncommitted changes, recovery SHALL accept the mechanically restored worktree matching the candidate SHA before recalculating candidate identity; it SHALL NOT treat the restored candidate as ambiguous. A `DOC_CLOSING` worktree SHALL be recorded in the existing durable worktree-ownership registry before it is created or reused. Any reuse or recovery SHALL match the persisted run, Change, canonical path, registered source repository, branch, and base identity; a legacy worktree without an ownership record MAY be adopted only when an incomplete `SYNC` or `ARCHIVE` invocation event recorded while the Run was in `DOC_CLOSING`, together with Git worktree metadata, independently proves that exact identity, and the ownership record is persisted before cleanup. For an abandoned `SYNC` or `ARCHIVE` invocation in `DOC_CLOSING` whose managed worktree has uncommitted or untracked changes, recovery SHALL restore that exact owned worktree to its current `HEAD` before recalculating candidate identity; it SHALL NOT apply this reset to another stage, worktree, or candidate. Live, unknown, mismatched, or otherwise ambiguous process or worktree evidence SHALL remain fail-closed. A proven-absent process SHALL NOT bypass an active durable claim or its fencing rules. No direct database repair or manual SQL SHALL be required for the proven-dead restart case.

#### Scenario: Restarted host has a different boot identity
- **GIVEN** an incomplete invocation with an expired claim, an unchanged candidate and stage, and coordinator/workflow identities from an earlier boot on the same host
- **WHEN** the coordinator evaluates recovery and confirms the prior processes are gone
- **THEN** it SHALL record exactly one `STAGE_INVOCATION_ABANDONED` event citing the observed restart/process evidence
- **AND** it SHALL acquire a successor claim with a higher fencing token and start a new invocation for the same candidate and stage.

#### Scenario: Prior process is absent after scheduler restart
- **GIVEN** an incomplete invocation with an expired claim, an unchanged candidate and stage, and a recorded process identity whose PID is no longer present
- **WHEN** recovery verifies the coordinator, workflow process, and process group are gone
- **THEN** it SHALL durably mark the old invocation abandoned and proceed under a successor fenced claim
- **AND** the previous invocation SHALL NOT be treated as completed.

#### Scenario: Restored apply worktree candidate matches entry identity
- **GIVEN** an incomplete `APPLY` invocation whose prior process is proven absent
- **WHEN** mechanical remediation restores the worktree to the entry candidate SHA preserving OpenSpec change artifacts
- **THEN** the coordinator SHALL recalculate candidate identity from the restored worktree
- **AND** it SHALL verify that the restored candidate matches the entry candidate identity
- **AND** it SHALL mark the prior attempt abandoned and launch a new invocation without human gate.

#### Scenario: Dirty documentation worktree is restored before identity is recalculated
- **GIVEN** an incomplete `SYNC` or `ARCHIVE` invocation recorded while its Run is in `DOC_CLOSING`, with an expired claim, proven-absent prior processes, and the exact still-owned worktree containing uncommitted or untracked changes
- **WHEN** recovery is authorized to acquire the successor fenced claim
- **THEN** it SHALL restore that worktree to its current `HEAD` using the approved managed-worktree cleanup boundary
- **AND** it SHALL recalculate the candidate fingerprint from the restored worktree
- **AND** it SHALL hold the current successor claim row for update in the same PostgreSQL transaction that persists both invocation events, preventing a competing fence from being acquired between validation and commit
- **AND** it SHALL persist the old `STAGE_INVOCATION_ABANDONED` event and successor `STAGE_INVOCATION_STARTED` event together in one PostgreSQL transaction after cleanup and current-fence validation
- **AND** it SHALL dispatch the same native operation for the restored candidate without treating the stale dirty fingerprint as a different active invocation.

#### Scenario: Archive recovery replays sync effects removed by reset
- **GIVEN** an abandoned `ARCHIVE` invocation in `DOC_CLOSING` and a previously completed native `SYNC` whose main-spec changes are uncommitted in the same worktree
- **WHEN** recovery resets that exact worktree to its current `HEAD`
- **THEN** the DOC_CLOSING flow SHALL rerun native `SYNC` for the same Change and worktree before `ARCHIVE`
- **AND** it SHALL require the replayed SYNC invocation's existing effect postcondition to succeed before archiving with `--skip-specs`
- **AND** it SHALL NOT treat a SYNC completion from before the reset as evidence that the synced main specs still exist.

#### Scenario: Documentation worktree ownership is persisted before reuse
- **GIVEN** a Run in `DOC_CLOSING` requests creation or reuse of its documentation worktree
- **WHEN** the worktree is returned to the coordinator
- **THEN** the existing durable ownership registry SHALL identify its project, run, Change, canonical path, source repository, branch, and base identity
- **AND** a mismatched or ambiguous existing path SHALL be rejected without modifying its contents.

#### Scenario: Legacy documentation worktree is adopted only from matching durable evidence
- **GIVEN** a documentation worktree exists without an ownership record while its Run is in `DOC_CLOSING`
- **WHEN** the persisted invocation identity and Git worktree metadata both match the requested run, Change, canonical path, registered repository, branch, and base identity
- **THEN** the system SHALL persist matching ownership before it reuses or cleans the worktree
- **AND** if any identity is missing or mismatched, it SHALL preserve the worktree and fail closed.

#### Scenario: Dirty worktree is not reset when recovery proof is incomplete
- **GIVEN** an incomplete invocation whose claim is active, whose process identity is live or unknown, or whose worktree ownership/candidate cannot be matched exactly
- **WHEN** recovery evaluates the invocation
- **THEN** it SHALL NOT reset, clean, or dispatch the worktree
- **AND** it SHALL preserve the existing claim and evidence for safe later reconciliation.

#### Scenario: Competing recovery cannot fence between validation and event commit
- **GIVEN** recovery has validated an expired DOC_CLOSING invocation under a successor claim whose lease expires before the recovery event transaction commits
- **WHEN** another scheduler attempts to reacquire that claim after the lease expires
- **THEN** the row lock held by recovery SHALL prevent the competing fence from being acquired before both `STAGE_INVOCATION_ABANDONED` and successor `STAGE_INVOCATION_STARTED` events commit
- **AND** after that commit, the existing claim mechanism MAY grant a newer fence to the competing scheduler.

#### Scenario: Process identity is live or unknown
- **GIVEN** an incomplete invocation with an expired claim
- **WHEN** any required process or process-group identity is live, unknown, unavailable, or cannot be proven gone
- **THEN** recovery SHALL NOT abandon or redispatch the invocation
- **AND** it SHALL preserve the candidate, claim/event evidence, and fail-closed behavior.

#### Scenario: Candidate or stage does not match the interrupted invocation
- **GIVEN** an incomplete invocation with an expired claim
- **WHEN** the candidate identity or stage differs from the invocation being considered for recovery
- **THEN** recovery SHALL NOT reuse that invocation's abandonment evidence to dispatch work for the different candidate or stage.

#### Scenario: Stale worker returns after successor claim is acquired
- **GIVEN** recovery has acquired a successor claim with a higher fencing token
- **WHEN** the previous worker later attempts to record a result or mutate the run
- **THEN** the existing fencing checks SHALL reject that mutation
- **AND** the successor claim and run state SHALL remain unchanged by the stale worker.
