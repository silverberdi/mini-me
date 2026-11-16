## Why

Issue #404 documents an Apply that never reached its executor: a recent-success window rejects an otherwise available primary provider after idle time, and the preflight exception leaves a durable stage invocation open. Together these defects can keep an active Run paused indefinitely without running Apply.

## What Changes

- Allow an Apply dispatch to use its configured primary when capacity evidence says that provider is currently available; reserve the short recent-success rule for the degraded-peer recovery case it was designed to protect.
- Close a stage invocation deterministically when preflight fails before a workflow process starts, and permit only a bounded retry when the same candidate is proven unchanged.
- Preserve fail-closed recovery when process or candidate evidence is missing, ambiguous, or shows worktree changes; preserve the Run, worktree, and event history.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-orchestration-continuity`: close known pre-process stage failures durably and retry only when candidate/process evidence proves safe recovery.

## Impact

The change is limited to the existing capacity preflight and durable stage-invocation lifecycle in `CapacityLifecycleService`, `AgentRunner`, and `OrchestrationCoordinator`, with focused tests and PostgreSQL-backed integration evidence. It adds no provider, state machine, deployment behavior, OpenSpec substitute, or change to human authorization. Evidence must demonstrate both primary dispatch after idle time and safe recovery from a pre-process failure; ambiguous process/worktree state remains blocked.
