## Why

After a provider authentication failure, an operator may legitimately authorize continuation of the same Run and Job. The current recovery gate rejects that attempt when a durable recovery snapshot already exists and ownership is CREATED, even if the preserved workspace is intact and contains no implementation progress.

## What Changes

- Permit AUTH_REQUIRED only for an already-existing CREATED worktree when the latest attempt history, ownership, snapshot, canonical continuation claim, Git state, and published OpenSpec tree jointly prove safe reuse.
- Keep DELETED worktree recreation policy unchanged; AUTH_REQUIRED alone never authorizes recreating an absent directory.
- Reject inconsistent attempt counters, ambiguous latest attempts, candidate/progress evidence, unresolved external actions, invalid claims, and any worktree identity or content mismatch.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `worktree-lifecycle`: authorize one narrowly evidenced CREATED-worktree continuation after AUTH_REQUIRED without changing history or relaxing DELETED recovery.

## Impact

- Affected code: `WorktreeManager` recovery verification and the focused N01 PostgreSQL/Git recovery tests.
- No database schema, provider policy, scheduler, or production state changes. No provider execution or inference is part of validation.
- No UI change.
