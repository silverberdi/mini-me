## Why

Cancelling an active orchestration run currently leaves its linked `QUEUED` job active. The
canonical active-job selector therefore continues to consume global concurrency even though the
run is cancelled. This violates the operator expectation that a successful CANCEL fully releases
the execution it owns.

## What Changes

- Make successful `ControlPlaneService` CANCEL atomically terminalize the non-terminal job linked
  by `OrchestrationRun.active_job_id` through the canonical job transition authority.
- Fail closed when an active run declares a linked job that cannot be found, without persisting a
  partial run cancellation.
- Add a narrow, idempotent canonical reconciliation path for an already-cancelled run whose linked
  job remains non-terminal.
- Add focused control-plane and reconciliation coverage for linked-job terminality, rollback, and
  active-job-selector postconditions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `operator-actions-control-plane`: CANCEL and its canonical reconciliation must converge the
  active linked job with the run while preserving durable evidence and action audit history.

## Impact

- Affects `ControlPlaneService`, its existing UoW transaction boundary, and focused control-plane
  tests.
- Uses the existing `JobRepositoryInterface.transition(...)` authority; no schema, scheduler
  policy, repository binding, provider, UI, or deployment changes are introduced.
- The change is backend-only and needs no human UI-validation scenario.

## Non-Goals

- Context-discovery duplicate handling, scheduler concurrency redesign, active-job selector
  changes, Change/Backlog lifecycle changes, local-worker evidence persistence, provider routing,
  recovery redesign, worktree cleanup redesign, Qwen execution, and manual production mutation.
