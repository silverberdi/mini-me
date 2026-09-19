## Why

When an execution attempt completes with failing deterministic checks (`JobStatus.CHECKS_FAILED`), the orchestration coordinator evaluates attempt continuation in `OrchestrationService.drive_coordinator()`.

Under the current implementation, decision resolution evaluates:
```python
decision = (
    latest_att.continuation_decision
    if latest_att
    else job.continuation_decision
)
```

When a job attempt completes, `latest_att` exists. If `latest_att.continuation_decision` is `None` while `job.continuation_decision` holds an authoritative decision (such as `CORRECT_AND_RETRY`), the `None` value shadows the job-level decision. Consequently, the coordinator falls through to `RUNNING_CHECKS`, where persisted failing checks transition the job back to `EVALUATING_ATTEMPT`, triggering a zero-delay hot loop between `EVALUATING_ATTEMPT` and `RUNNING_CHECKS`.

Furthermore, continuation governance must be respected before initiating corrective implementation attempts: when retry budget is exhausted for a failing checks job, execution must terminate deterministically with `NEEDS_HUMAN` rather than launching unbudgeted attempts or hot-looping.

## What Changes

- **Decision Fallback Resolution**: Update attempt decision resolution so `latest_att.continuation_decision` is used only when non-null. When `latest_att.continuation_decision` is `None`, decision resolution falls back to `job.continuation_decision`.
- **Attempt Decision Precedence**: When `latest_att.continuation_decision` is explicitly set (non-null), it remains authoritative over `job.continuation_decision`.
- **Hot-Loop Prevention for `CHECKS_FAILED`**: For `CHECKS_FAILED` with effective `CORRECT_AND_RETRY` (or other corrective continuation decisions), dispatch directly to corrective implementation or terminate if retry budget is exhausted, preventing transition back to `RUNNING_CHECKS`.
- **Bounded Retry Governance**: Enforce canonical retry budget check before advancing to `IMPLEMENTING`. If retry budget is exhausted (e.g. `len(attempts) >= 2`), transition to terminal `NEEDS_HUMAN` with `CHECKS_FAILED_RETRY_EXHAUSTED`.
- **Preserved Genuinely Absent Decisions**: Preserve existing bounded checks-failure remediation for jobs where neither attempt nor job continuation decisions are present.

## Capabilities

### Modified Capabilities
- `execution-pipeline-orchestration`: Fixed continuation decision resolution in `OrchestrationService.drive_coordinator()` to fall back from null attempt-level decision to authoritative job-level decision, dispatch corrective retries without looping, and bound attempt retries under canonical retry limits.

## Non-Goals

- Do NOT redesign continuation governance or invent new attempt limits.
- Do NOT modify scheduler admission, provider health, or model independence policies.
- Do NOT alter retry budgets or retry thresholds.
- Do NOT mutate production data or start the background scheduler.
