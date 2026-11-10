## Context

See `proposal.md` for the observed failure. The existing Apply snapshot is captured before native Update; the validated Update checkpoint already persists on the same Run. Recovery currently treats any completed-task loss against that old snapshot as candidate regression.

## Goals / Non-Goals

**Goals:** Carry the validated Update's exact task disposition changes and candidate identity into the recovery comparison, while retaining current fail-closed checks for all other evidence.

**Non-Goals:** Change retry limits, candidate/worktree identity rules, provider selection, Run state model, or the semantics of native OpenSpec Update.

## Decisions

- Reuse the existing durable Apply-gate Update checkpoint. Store or derive the before/after disposition map and bind it to the already recorded Run, Change, branch, worktree, and candidate identity; do not add a table or migration.
- Adjust only the task-loss comparison for task IDs proven to have changed disposition in that strictly validated checkpoint. Keep Git identity, changed-file, diff, test, and unrelated task comparisons intact. Reject malformed, mismatched, or ambiguous checkpoint data.
- Make recovery consume the checkpoint idempotently. A replay may observe the same validated checkpoint but cannot expand its affected task set or erase previous invocation/audit evidence.
- Add focused coordinator regression tests and extend PostgreSQL-backed E2E coverage to exercise operator response → native Update → strict validation → Apply recovery comparison, including an unrelated real regression that must still stop.

## Risks / Trade-offs

- **Risk:** A broad snapshot reset could mask actual loss of work. **Mitigation:** Reconcile only explicit task IDs from the validated Update; test that an unaffected task regression still fails closed.
- **Risk:** A stale checkpoint could be applied to a different candidate. **Mitigation:** Require exact Run/Change/branch/worktree/candidate match before using any reclassification.

## Migration Plan

No schema migration is expected. Existing incomplete Runs without a complete, matching Update checkpoint retain current fail-closed behavior. Deploy through the normal project CI/CD process; this Change does not deploy the application.
