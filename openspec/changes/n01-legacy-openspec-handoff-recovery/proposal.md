## Why

The execution handoff can fail after a historical recovery snapshot omitted only the published artifacts' final LF, and the resulting worktree is durably `CREATED`. CONTINUE must safely reconcile that exact legacy representation and adopt the same owned worktree so the existing Run/Job can proceed without rewriting history.

## What Changes

- Permit only a proven recovery worktree to repair OpenSpec files whose bytes are exactly the verified published blob or that blob with its single final LF omitted.
- Validate the full published manifest and every file before writing, restore exact published bytes, and record durable repair evidence.
- Allow canonical adoption of the same `CREATED` historical recovery worktree while preserving its original base, snapshot, branch, ownership, and Run/Job identities.
- Reject all other content, path, identity, publication, snapshot, candidate, and ancestry discrepancies.

## Capabilities

### New Capabilities
- `n01-legacy-published-artifact-recovery`: Safe repair and continuation of a historically snapshotted execution worktree whose OpenSpec files differ from the published tree only by a missing final LF.

### Modified Capabilities

## Impact

- Affected: `WorktreeManager` execution-worktree adoption and published OpenSpec materialization, durable event evidence, and focused Git/PostgreSQL tests.
- No database schema, provider policy, credential, scheduler, or production behavior is changed directly; the code only enables a future canonical CONTINUE after deployment.
- No UI impact. Repository identity remains derived from the durable managed binding. No provider execution or inference is part of validation.
