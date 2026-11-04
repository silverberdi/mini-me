## Why

Re-entering `DOC_CLOSING` after native OpenSpec Archive has already moved the Change out of `openspec/changes/` currently dispatches Sync again and can fail with `change not found`. The coordinator must observe the documentation worktree's durable state so completed sync/archive work does not block the documentation PR.

## What Changes

- Observe the Change and its synced specs in the documentation worktree before dispatching native Sync or Archive on a `DOC_CLOSING` re-entry.
- When the archived Change and synced specs are already present, skip those completed workflows and continue through the existing documentation PR preparation and creation path.
- Treat the already-archived state as completed work rather than a fatal missing-Change error.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `two-phase-pr-and-closure`: make native OpenSpec Sync/Archive re-entry idempotent when archive and spec synchronization are already complete, preserving the existing PR2 path.

## Impact

- `src/minime/services/orchestration_coordinator.py`: DOC_CLOSING state observation and the existing `_run_sync_and_archive` dispatch boundary.
- Focused tests for native sync/archive orchestration and documentation PR continuation.
- No API, database schema, or other workflow stage changes.
