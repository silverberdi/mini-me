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

#### Scenario: Main advanced as a descendant after the prior attempt
- **WHEN** the authoritative remote base is C and the durable worktree source base is B
- **AND** an exact authenticated fetch resolves to C when the local managed base ref is stale
- **AND** the local managed base ref is an ancestor of C
- **AND** Git proves B is an ancestor of C
- **AND** a second authoritative remote observation still reports C before recreation
- **THEN** WorktreeManager reconstructs the preserved recovery branch from its original B-based snapshot
- **AND** ownership, WorktreeInfo, Run, and Job continue to record B as their source base
- **AND** C is retained only as the observed current integration base, without rewriting historical provenance

#### Scenario: Main diverged, was rewritten, or remote observation is ambiguous
- **WHEN** B or the local managed base is not an ancestor of authoritative remote base C
- **OR** the authenticated fetch does not equal the SHA returned by remote observation
- **THEN** WorktreeManager blocks reconstruction and preserves existing Run/Job/worktree evidence

#### Scenario: CONTINUE request completes but execution does not remain active
- **WHEN** the Control Plane processes CONTINUE and the synchronous continuation reaches a stopped, waiting, or failed persisted state
- **THEN** the action result reports the actual persisted Run outcome and linked Job status
- **AND** it does not claim that execution resumed successfully

#### Scenario: Recovery continues after a local environment failure
- **WHEN** the prior attempt is durably recorded as an environment/provider infrastructure failure with no candidate and a valid recovery snapshot
- **THEN** a canonical `CONTINUE` may requeue and reconstruct the same execution identity without consuming a second admission
- **AND** no provider is invoked merely to validate worktree reconstruction
