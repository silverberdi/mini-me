## Why

After a host interruption, a durable in-flight `PREMATURE_STOP` attempt can be mistaken for a finalized attempt, blocking canonical continuation of an already-created, snapshot-verified N01 worktree. The recovery path must recognize only that interruption-backed state while preserving the original Run, Job, base, snapshot, publication, and Git safety evidence.

## What Changes

- Permit a `CREATED` historical recovery worktree to continue after an unfinished `PREMATURE_STOP` attempt only when the canonical on-demand Control Plane continuation emits a matching post-attempt `JOB_RECOVERED`; startup-only recovery events are not required.
- Preserve the existing lineage, identity, publication, Git cleanliness, snapshot, candidate, and canonical CONTINUE claim/fencing checks.
- Reject the exception for `DELETED` worktrees, completed attempts, missing or contradictory recovery evidence, unauthorized Git changes, or existing candidate state.
- Add isolated PostgreSQL and real-Git coverage for successful continuation and fail-closed cases; do not change attempt history or counters.

## Capabilities

### New Capabilities
- `n01-crash-interrupted-created-worktree-recovery`: Narrow recognition of a crash-interrupted, unfinished attempt when continuing an already-created historical recovery worktree.

### Modified Capabilities

## Impact

Impacts `WorktreeManager` recovery validation and focused PostgreSQL/Git continuation tests. No schema, production data, scheduler, provider, or deployment changes are required; validation uses a diagnostic runner and does not invoke inference.
