## Why

Autonomous intake treated a roadmap prose bullet as work and prepared a `NEXT` roadmap stage. That created saga, GitHub, and managed-checkout side effects without preparation authority.

## What Changes

- Recognize roadmap list work items only when their key is an explicit numeric/stage-prefixed identity.
- Limit autonomous roadmap preparation to `CURRENT`/`READY` projections while retaining local-backlog behavior.
- Add an idempotent, evidence-bound reconciliation command for invalid discovery and deferred roadmap intake.
- Archive the delivered context-discovery deduplication change.

## Capabilities

### New Capabilities

- `intake-abandoned-reconciliation`: Safely converge a cancelled/deferred intake saga and its exact side effects.

### Modified Capabilities

- `autonomous-intake-preparation-and-admission`: Make roadmap preparation eligibility depend on roadmap evidence.
- `durable-sagas`: Require claimed, evidence-bound cancellation for abandoned intake reconciliation.

## Impact

Changes context discovery, intake selection, saga/external-action reconciliation, guarded managed-workspace cleanup, and focused tests. No schema, provider, scheduler-concurrency, or execution-worktree redesign is included.
