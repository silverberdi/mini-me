## 1. Core Orchestration Fix

- [x] 1.1 Fix decision resolution in `OrchestrationService.drive_coordinator()` under `EVALUATING_ATTEMPT` stage to fall back to `job.continuation_decision` when `latest_att.continuation_decision` is `None`
- [x] 1.2 Verify bounded retry check before advancing to `IMPLEMENTING` for corrective decisions (`CORRECT_AND_RETRY`, `CONTINUE_SAME_AGENT`, `REASSIGN_AGENT`)
- [x] 1.3 Ensure `CHECKS_FAILED` status with corrective decision never falls through to `RUNNING_CHECKS`

## 2. Regression Tests

- [x] 2.1 Add CASE 1 regression test: exact production scenario (`latest_att.continuation_decision = None`, `job.continuation_decision = CORRECT_AND_RETRY`, `job.status = CHECKS_FAILED`, persisted failing checks) -> effective decision `CORRECT_AND_RETRY`, no loop to `RUNNING_CHECKS`
- [x] 2.2 Add CASE 2 test: retry permitted (`len(attempts) < 2`) -> transitions to `IMPLEMENTING`
- [x] 2.3 Add CASE 3 test: retry exhausted (`len(attempts) >= 2`) -> terminates with `NEEDS_HUMAN` (`CHECKS_FAILED_RETRY_EXHAUSTED`)
- [x] 2.4 Add CASE 4 test: attempt-level decision wins (`latest_att.continuation_decision` non-null overrides `job.continuation_decision`)
- [x] 2.5 Add CASE 5 test: no decisions available (genuinely absent continuation decisions preserve bounded remediation)

## 3. Validation & Recovery Analysis

- [x] 3.1 Run `openspec validate checks-failed-continuation-dispatch --strict`
- [x] 3.2 Run all orchestration tests and relevant test suites
- [x] 3.3 Perform recovery analysis on preserved production state
