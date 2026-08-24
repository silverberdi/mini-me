## Why

Changes 001–007 provide the durable readiness, execution, review, audit, resilience, fallback, and continuation mechanisms needed for safe delivery, but an operator still has to coordinate each handoff manually. Change 008 makes mini me the durable coordinator for one already-READY OpenSpec change, carrying it through the existing authorities until it reaches a human merge gate, capacity wait, or human escalation.

## What Changes

- Add a one-change orchestration run that admits an existing READY change only after durable project/repository/change binding and readiness are revalidated.
- Persist a deterministic orchestration stage/checkpoint lifecycle separately from operational `JobStatus`, continuation decisions, provider capacity modes, and human-gate outcomes.
- Invoke the existing implementation pipeline and 007 continuation governance without copying agent claims into orchestration authority.
- Coordinate deterministic checks, candidate freezing, complementary review/remediation, and mandatory full DeepSeek Direct audit/remediation loops.
- Track candidate generations, base/candidate SHAs, manifests, and review/audit authority so remediation invalidates stale evidence.
- Reconcile idempotent GitHub push/PR actions, then record a separate `READY_FOR_HUMAN_MERGE` human-gate outcome; mini me never merges, deploys, or archives automatically.
- Provide restart-safe CLI/API status and structured stop reasons for one orchestration run, with four legitimate outcomes: `READY_FOR_HUMAN_MERGE`, `WAITING_CAPACITY`, `WAITING_EXTERNAL`, and `NEEDS_HUMAN`.

## Capabilities

### New Capabilities

- `autonomous-change-orchestration`: Durable single-change orchestration, stage progression, candidate authority, stop gates, and CLI/API control.

### Modified Capabilities

- `execution-jobs`: Clarify that operational job status remains separate from orchestration stage and human-gate state.
- `process-restart-recovery`: Extend recovery to orchestration checkpoints and in-flight idempotent external actions.
- `status-observability`: Expose truthful orchestration run status and candidate-bound evidence without secrets.
- `github-work-binding`: Add idempotent PR preparation/reconciliation bound to the independently audited candidate.

## Impact

The daemon/core gains an orchestration coordinator, PostgreSQL persistence for runs, stage events/checkpoints, candidate generations, and external-action idempotency records, plus an Alembic migration chained from `007_continuation_governance`. Existing implementation, continuation, provider-capacity, review, audit, repository-binding, worktree, check, and GitHub binding services remain authorities and are invoked through adapters. The CLI/API gains `orchestrate start`, `status`, and `resume` operations. This change is service/API operational behavior, not a UI feature; no human UI validation session is required.
