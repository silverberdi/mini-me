## Why

Apply currently carries its exhausted attempt count into a Run after the operator has answered its human gate, so the coordinator immediately returns the same gate instead of making the requested recovery attempt. The operator's response should authorize a new bounded Apply cycle while the prior attempts remain auditable.

## What Changes

- Define the three-attempt hard limit as applying to each automatic Apply recovery cycle.
- When an accepted response to an Apply exhaustion gate authorizes continuation, begin a new cycle at 0/3 and reset that cycle's no-progress count.
- Preserve the same Run, Change, branch, worktree, and candidate identity, and retain prior invocation and operator-action evidence.
- Keep cancellation terminal and make repeated idempotent responses unable to start duplicate cycles or invocations.
- Show the active cycle's attempt count in the human gate and run status.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-apply-and-verify`: scope Apply retry and no-progress limits to a recovery cycle, with a new cycle after an accepted human continuation.
- `openspec-orchestration-continuity`: make resolving an Apply exhaustion gate start exactly one new cycle while preserving the Run and its audit history.

## Impact

The orchestration coordinator's Apply recovery and human-response path, the persisted Run status projection, and focused orchestration/API tests. Existing PostgreSQL Run details, invocation events, and operator-action idempotency are the first audit sources to reuse; any persistence change must preserve prior attempts and avoid duplicating history. No changes to Múltiplo, provider roles, project budgets, deployment, or OpenSpec workflow semantics are in scope.
