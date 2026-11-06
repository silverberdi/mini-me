## Why

The coordinator persists the current stage but does not provide a durable, uniform record of each invocation's start, finish, and outcome. A Verify invocation was repeatedly dispatched for the same run and candidate, making in-progress work indistinguishable from a lost result and risking repeated resource use.

## What Changes

- Record each coordinator stage invocation durably with its run, stage, candidate identity, attempt identity, timestamps, and the native workflow's observed result/handoff.
- Atomically claim a run/stage/candidate invocation before dispatch so concurrent workers cannot launch duplicates.
- Preserve the native workflow's HUMAN_REQUIRED handoff, including its actual question/options when provided, as a completed invocation while retaining the gate on the same run; do not redispatch until an accepted response.
- Make accepted human-response reentry idempotent and continue the same run, worktree, stage, and candidate.
- Pass an accepted response as context to the same native stage workflow and make duplicate responses idempotent; recover an interrupted invocation only after durable coordinator/process identity proves the old coordinator process and spawned workflow process group have terminated and run/worktree/stage/candidate identity is unchanged. A lease timeout alone is not proof; stop for operator intervention if identity or liveness cannot be established.
- Preserve native OpenSpec workflows as the authority for propose, apply, verify, sync, and archive. The coordinator records invocation boundaries and observed results, guards duplicate dispatch, and re-enters only through the existing native invocation; it does not interpret artifacts, recreate workflow decisions, or substitute a verifier.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-orchestration-continuity`: define durable stage-invocation lifecycle, human-gate behavior, and bounded recovery.
- `transaction-and-concurrency-contract`: define the atomic, process-independent claim that prevents duplicate invocations for one run/stage/candidate.

## Impact

- PostgreSQL orchestration persistence and Alembic migration, if the existing durable records cannot represent the invocation lifecycle without loss.
- Coordinator dispatch, human-response reentry, and worker-recovery paths.
- Focused PostgreSQL integration coverage using the real coordinator, plus unit coverage for claim and recovery decisions.
- No UI redesign, OpenSpec workflow semantics, test-selection policy, build/CI policy, or deployment behavior changes. Existing consumers of stage-event records continue to treat only transition events as transitions.
