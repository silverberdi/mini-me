## Why

The existing CREATED-worktree recovery rule permits only one same-SHA AUTH_REQUIRED suppression, so a later explicitly authorized continuation is blocked even when every repeated authentication failure is durably shown to have made no code progress.

## What Changes

- Permit finite, ordered AUTH_REQUIRED / NO_PROGRESS duplicate chains only when every duplicate has one exact suppression event and the chain retains a genuine provider/preflight failure anchor.
- Keep CREATED ownership, candidate absence, Git/snapshot/publication integrity, current Control Plane CONTINUE claim/fence, and all DELETED-worktree rules unchanged.
- Add an isolated PostgreSQL and real-Git regression for the four-attempt history with two suppressions.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `worktree-lifecycle`: allow a newly authorized human continuation to reuse an intact CREATED worktree after a fully evidenced finite chain of repeated AUTH_REQUIRED suppressions.

## Impact

The change is limited to the existing worktree recovery predicate, its PostgreSQL/Git tests, and the worktree lifecycle contract. It does not change automatic retry behavior, provider policy, production records, or deleted-worktree recovery.
