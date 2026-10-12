## ADDED Requirements

### Requirement: Continue an existing run without duplicating execution identity
The system SHALL continue an existing Run and its linked Job only through canonical Control Plane `CONTINUE` with optimistic concurrency and durable action evidence. It SHALL preserve the Run ID, Job ID, and prior attempt history and SHALL NOT create another Run, Job, or intake saga.

#### Scenario: Existing run has a safely reconstructable deleted worktree
- **WHEN** a `CONTINUE` action targets an existing Run/Job whose worktree ownership is `DELETED`
- **AND** the persisted project/repository binding, run/job/change identity, recovery branch/base, durable recovery snapshot, and published intake artifact identity all verify
- **THEN** WorktreeManager reconstructs only the canonical worktree path and branch
- **AND** the same Run and Job identities and historical attempt evidence remain

#### Scenario: Deleted worktree evidence is incomplete or contradictory
- **WHEN** repository identity, ownership, branch, base SHA, recovery snapshot, integration base, or published artifact identity cannot be proven
- **THEN** continuation fails closed without adopting an arbitrary directory or restoring terminal ownership by direct mutation

#### Scenario: Main advanced after the prior attempt
- **WHEN** the current canonical base differs from the durable worktree source base and the configured integration policy cannot prove safe reconstruction
- **THEN** WorktreeManager blocks reconstruction and preserves existing Run/Job/worktree evidence

#### Scenario: Remote main advanced while the managed local ref is stale
- **WHEN** the bound repository's authoritative remote base ref differs from the persisted source base
- **THEN** WorktreeManager blocks reconstruction even if the managed checkout's local base ref is unchanged
- **AND** it observes the ref using the existing non-interactive GitHub App Git authority

#### Scenario: Recovery continues after a local environment failure
- **WHEN** the prior attempt is durably recorded as an environment/provider infrastructure failure with no candidate and a valid recovery snapshot
- **THEN** a canonical `CONTINUE` may requeue and reconstruct the same execution identity without consuming a second admission
- **AND** no provider is invoked merely to validate worktree reconstruction
