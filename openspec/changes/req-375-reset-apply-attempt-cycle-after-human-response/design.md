## Context

See `proposal.md` for the motivation and the two delta specs for observable behavior. The current Apply loop reads `apply_total_attempts` and `apply_no_progress` from `orchestration_runs.stop_details`, then dispatches only while the attempt count is below the hard limit. An accepted operator response is already recorded in `operator_action_records`; each native Apply dispatch also has durable stage-invocation evidence. The missing behavior is a cycle boundary between those two existing records.

The contract requires guided recovery on the same candidate, a hard limit, idempotent human decisions, and preserved evidence. It does not require that the hard limit span the entire lifetime of a Run. This Change scopes the existing limit to one Apply recovery cycle; it does not change the configured limit or relax fail-closed regression and identity checks.

### Confirmed implementation inventory

- `orchestration_runs.stop_details.apply_total_attempts` and `apply_no_progress` are the mutable counters for the active cycle; `apply_limits` records the effective per-cycle ceilings.
- `projects.execution_policy.apply_max_attempts` and `apply_max_no_progress` override the existing defaults through `_positive_policy_limit`; absent overrides retain the current three-attempt default and two-no-progress default. This Change does not alter either source or clamp.
- `operator_action_records.action_request_id` is the durable identity created by the accepted gate-response API. The API worker carries that same ID into the coordinator, which records it as `apply_cycle_started_by_action_id` before dispatch.
- `orchestration_stage_events` retains each native Apply invocation's start and terminal outcome. The accepted action ID is included in each newly authorized cycle invocation's start evidence; no prior event or action row is rewritten.
- `GET /api/v1/orchestration/runs` is the canonical persisted Run projection. `apply_cycle` exposes the active counters and ceilings while the Run is in `IMPLEMENTING`; Trabajo actual renders that projection, including 0/3 before the first invocation completes.
- No new table or migration is needed. The previous `apply_snapshot`, Run/candidate identity, and invocation events are retained across the reset.

## Goals / Non-Goals

**Goals:**

- Reset only the active Apply cycle counters when an accepted response resolves an Apply exhaustion gate and authorizes continuation.
- Make the reset durable and idempotent, so one human decision starts at most one cycle.
- Preserve every earlier invocation, its outcome, and the operator decision as auditable history.
- Keep the same Run, Change, candidate, branch, and worktree, and make the active cycle count observable in the Run projection.

**Non-Goals:**

- Changing the three-attempt limit, project budget/capacity policy, provider selection, or other stage retry counters.
- Rewriting historical attempt records or manually reducing a Run counter.
- Creating a second Run, a new attempt-history table, or a parallel Apply workflow.
- Automatically resuming a Run merely because code is deployed; a currently active gate still requires a newly accepted human continuation.

## Decisions

### Treat the accepted Apply-gate response as a cycle boundary

Only a durable, accepted response for the current Apply exhaustion gate that continues the Run starts a new Apply cycle. The response itself is not an Apply attempt. Cancellation and responses to other gate types do not reset Apply counters. The hard limit remains three attempts per cycle; the no-progress counter also restarts at zero for that cycle.

**Alternatives considered:** resetting on any non-empty operator message would reset for stale or unrelated gate input; resetting on every coordinator entry would make retries and recovery non-idempotent. Both are rejected.

### Reuse durable action and invocation evidence

Use the existing operator-action request identity as the idempotency key for the cycle boundary, and the existing stage-invocation records as the history of attempts. Pass the accepted action identity to the coordinator if the current internal dispatch path does not expose it there. Record which accepted action started the active cycle alongside the current-cycle counters in the Run checkpoint. If the same action is replayed, observe that marker and do not reset again or dispatch another invocation.

Reset `apply_total_attempts` and `apply_no_progress` for the new active cycle without deleting or decrementing invocation events, operator-action records, or the last candidate snapshot. Retaining the prior snapshot keeps regression checks grounded in the candidate's actual prior state.

**Alternatives considered:** decrementing the attempt count or deleting old events would falsify the audit trail; a new table or general retry-cycle framework adds durable state not justified by this single behavior. Both are rejected unless implementation inventory proves the existing records cannot provide the required idempotency and history.

### Keep the current gate and status projections on one source of truth

The API and Trabajo actual UI should read the active-cycle counters and hard limit from the canonical Run state. An exhausted gate reports the count for the cycle that just stopped; once a response starts the next cycle, the Run projection reports 0/3 until the first new invocation. Do not infer the count from the agent's narrative or from a stale gate payload.

**Alternatives considered:** adding client-side counter state would create a second source of truth and could survive a gate transition incorrectly. It is rejected.

### Preserve authorization and bounded execution

An accepted continuation is the operator's decision to begin another bounded cycle, not permission to skip the native workflow. Every new attempt still passes the existing provider capacity/budget checks, invokes native OpenSpec Apply on the same candidate, and stops on the per-cycle no-progress limit, the three-attempt ceiling, regression, or identity mismatch. Verify remains blocked until Apply is complete or natively ready.

**Alternatives considered:** making the cap per Run lifetime would reproduce the current dead end after a valid human intervention; removing the cap or extending it silently would weaken the contract. Neither is selected.

## Risks / Trade-offs

- **Repeated human continuations can authorize repeated bounded cycles and additional provider usage** → Make the current-cycle `0/3` state and prior cycle history visible; retain all existing budget, capacity, and operator authorization checks.
- **A duplicate or crash-retried response could otherwise reset twice** → Bind the reset to the durable accepted action ID and persist the cycle marker before dispatch; retain stage-invocation claims/fencing for one dispatch.
- **Existing active Runs may have a completed response action but still retain the old exhausted gate** → Do not rewrite that history during deployment. A fresh response to the still-current gate after the Change is deployed starts the new cycle; deployment itself does not dispatch work.
- **Counter reset could hide candidate regression if prior context is discarded** → Reset only cycle counters; retain the previous candidate snapshot and run/worktree identity evidence for regression checks.

## Migration Plan

No database migration is expected: the current-cycle counters and cycle marker fit in the existing Run checkpoint, while invocation and operator-action records preserve history. Confirm this against the deployed schema before implementation; if existing durable events cannot identify prior invocations reliably, stop and revise the design rather than dropping history.

The new behavior applies when a fresh, accepted Apply-gate response is processed after deployment. Existing Runs and completed operator actions are not backfilled or rewritten. Rollback restores the prior coordinator behavior without deleting cycle markers or historical evidence; if a rollback occurs after a new cycle starts, retain the checkpoint and action records for a forward recovery rather than resetting counters manually.

Deployment remains the project's CI/CD responsibility. No production deployment, scheduler restart, or modification of the current Múltiplo Run is part of this Change.
