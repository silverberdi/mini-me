## Why

After a validated native Update reclassifies tasks, a later human response that only authorizes another Apply cycle can trigger a no-op Update. That replaces the validated disposition checkpoint with an empty one, so Apply incorrectly reports the same tasks as regressed again.

## What Changes

- Route continuation-only responses through Apply without dispatching another native Update.
- Reuse the prior strictly validated disposition checkpoint for the same Run, Change, branch, worktree, and candidate across subsequent retry gates.
- Preserve that checkpoint and its audit evidence unless a new, explicitly authorized disposition Update completes and strictly validates.
- Keep current fail-closed regression checks and attempt limits for every unrelated task, file, test, and identity.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-apply-and-verify`: retain validated reclassifications across a continuation-only Apply retry.
- `openspec-orchestration-continuity`: avoid rerunning or overwriting a validated Update checkpoint when the operator only authorizes continuation.

## Impact

- `src/minime/services/orchestration_coordinator.py` gate routing and checkpoint reuse.
- Focused continuation/retry regression coverage and PostgreSQL-backed operator-response-to-Apply E2E coverage.
- No schema, migration, API, provider, or retry-limit changes.
