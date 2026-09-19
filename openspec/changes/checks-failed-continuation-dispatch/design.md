## Context

During orchestration execution, after deterministic checks run and fail, the job status is set to `CHECKS_FAILED` and orchestration stage advances to `EVALUATING_ATTEMPT`.

In `OrchestrationService.drive_coordinator()`, decision resolution previously evaluated:
```python
decision = (
    latest_att.continuation_decision
    if latest_att
    else job.continuation_decision
)
```

Because `latest_att` was present but its `continuation_decision` was `None`, the expression evaluated to `None`, shadowing `job.continuation_decision` (`CORRECT_AND_RETRY`). As a result, the `EVALUATING_ATTEMPT` stage did not match any continuation branch (`CORRECT_AND_RETRY`, `NEEDS_HUMAN`, etc.) and fell through to the `else` block:
`self._advance_stage(run, OrchestrationStage.RUNNING_CHECKS)`

In `RUNNING_CHECKS`, persisted check failures sent the coordinator straight back to `EVALUATING_ATTEMPT`, causing a zero-delay hot loop.

## Goals / Non-Goals

**Goals:**
1. Resolve effective continuation decision by falling back to `job.continuation_decision` when `latest_att` exists but `latest_att.continuation_decision` is `None`.
2. Ensure attempt-level non-null `continuation_decision` retains precedence over `job.continuation_decision`.
3. For `CHECKS_FAILED` + effective `CORRECT_AND_RETRY` (or related corrective decisions), dispatch corrective implementation without transitioning back to `RUNNING_CHECKS`.
4. Enforce canonical retry governance before advancing to `IMPLEMENTING`: if attempt budget is exhausted (`len(attempts) >= 2`), terminate with `NEEDS_HUMAN` (`CHECKS_FAILED_RETRY_EXHAUSTED`).
5. Guarantee bounded forward progress for `CHECKS_FAILED` jobs to either `IMPLEMENTING` or `NEEDS_HUMAN`.

**Non-Goals:**
- No redesign of continuation governance or retry budget limits.
- No changes to scheduler admission or provider selection.
- No production database mutation or scheduler startup.

## Architectural Decisions

### D1: Decision Resolution Precedence

In `OrchestrationService.drive_coordinator()`, `EVALUATING_ATTEMPT` stage:

```python
if latest_att and latest_att.continuation_decision is not None:
    decision = latest_att.continuation_decision
else:
    decision = job.continuation_decision
```

This guarantees:
- Non-null `latest_att.continuation_decision` takes precedence.
- Null `latest_att.continuation_decision` falls back to `job.continuation_decision`.
- When both are null, `decision` is `None`.

### D2: Retry Governance & Hot-Loop Elimination for `CHECKS_FAILED`

When `decision` evaluates to a corrective decision (`CORRECT_AND_RETRY`, `CONTINUE_SAME_AGENT`, `REASSIGN_AGENT`):

Before advancing stage to `IMPLEMENTING`:
Check canonical retry budget (`len(attempts) >= 2`).
- If retry budget permits (`len(attempts) < 2`): advance to `IMPLEMENTING`.
- If retry budget exhausted (`len(attempts) >= 2`): stop run with `NEEDS_HUMAN` and `stop_details={"code": "CHECKS_FAILED_RETRY_EXHAUSTED"}` (if `CHECKS_FAILED`) or `"RETRY_EXHAUSTED"`.

When `decision` is `None` and `job.status == CHECKS_FAILED`:
- If `len(attempts) >= 2`: stop run with `NEEDS_HUMAN` and `stop_details={"code": "CHECKS_FAILED_RETRY_EXHAUSTED"}`.
- If `len(attempts) < 2`: advance to `IMPLEMENTING`.

This ensures `CHECKS_FAILED` never transitions to `RUNNING_CHECKS` from `EVALUATING_ATTEMPT`.
