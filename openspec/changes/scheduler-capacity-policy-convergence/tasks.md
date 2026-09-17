## 1. Domain Enums and Evaluation Models

- [x] 1.1 Update `AdmissionDecisionKind` enum (`RUN`, `DRAIN`, `WAIT`, `NEEDS_HUMAN`) in `src/minime/domain/enums.py`
- [x] 1.2 Add `AdmissionBlockCondition` enum (`CAPACITY_EXHAUSTED`, `AUTH_REQUIRED`, `CONFIGURATION_INVALID`, `HARNESS_UNAVAILABLE`, `PROVIDER_UNAVAILABLE`, `EVIDENCE_INSUFFICIENT`, `REVIEWER_INDEPENDENCE_UNAVAILABLE`, `LOCAL_RUNTIME_FAILURE`, `LIFECYCLE_BLOCKED`, `HUMAN_APPROVAL_REQUIRED`, `UNKNOWN_CAPACITY`, `BUDGET_EXCEEDED`) in `src/minime/domain/enums.py`
- [x] 1.3 Add `AdmissionEvaluationResult` domain model to `src/minime/domain/models.py`

## 2. Safe Executable Pair Engine (`SAFE_EXECUTABLE_PAIR_EXISTS`)

- [x] 2.1 Update `SchedulerService.evaluate_admission` to evaluate `SAFE_EXECUTABLE_PAIR_EXISTS` by checking eligible implementers against `ProviderHealthService`
- [x] 2.2 Implement paired reviewer evaluation in `SchedulerService` verifying at least one independent reviewer (under `ModelIndependencePolicy`) is healthy and not in cooldown
- [x] 2.3 Require simultaneous availability of both implementer and independent reviewer before issuing `RUN`
- [x] 2.4 Emit `WAIT` with `CAPACITY_EXHAUSTED` / `REVIEWER_INDEPENDENCE_UNAVAILABLE` when implementer is available but all candidate reviewers are in cooldown

## 3. Strict Drain Fallback Policy Isolation

- [x] 3.1 Restrict `DRAIN` evaluation in `SchedulerService` to active in-flight jobs where material execution has started (`is_material_execution_started == True`)
- [x] 3.2 Unconditionally refuse new `READY` backlog items with `WAIT` or `NEEDS_HUMAN` when primary subscriptions are exhausted, even when drain credits exist
- [x] 3.3 Validate distinct model identity between implementer and reviewer during in-flight drain continuation
- [x] 3.4 Halt in-flight drain runs with `NEEDS_HUMAN` (`BUDGET_EXCEEDED`) when remaining drain budget is exhausted

## 4. Pre-Admission vs Post-Execution Failure Separation

- [x] 4.1 Classify structural harness absence as `NEEDS_HUMAN` (`HARNESS_UNAVAILABLE`) without triggering capacity cooldown
- [x] 4.2 Classify missing/invalid provider credentials as `NEEDS_HUMAN` (`AUTH_REQUIRED`)
- [x] 4.3 Classify malformed project/model configuration as `NEEDS_HUMAN` (`CONFIGURATION_INVALID`)
- [x] 4.4 Enforce that textual provider output lacking repository-editing evidence (`EVIDENCE_INSUFFICIENT`) maps strictly to `NEEDS_HUMAN` without automatic retry or capacity wait
- [x] 4.5 Classify lifecycle blocks accurately (`WAIT` for progressing predecessor / dependency; `NEEDS_HUMAN` for explicit human gates, approval requirements, or invalid OpenSpec artifacts)

## 5. Epistemic Honesty and Cooldown Handling

- [x] 5.1 Set `has_deterministic_eta=True` and exact `cooldown_until` when upstream provider returns explicit `Retry-After` / reset headers
- [x] 5.2 Set `has_deterministic_eta=False` and suppress speculative ETA calculation when provider reset interval is unmeasured or unknown
- [x] 5.3 Enforce probe locks to prevent API probe polling during active provider cooldown windows
- [x] 5.4 Enforce `UNKNOWN MUST NEVER BECOME RUN`, failing closed to `WAIT` (if probe active) or `NEEDS_HUMAN`

## 6. Single Converged Entry Point

- [x] 6.1 Unify CLI command `minime scheduler tick` to invoke `SchedulerService.evaluate_admission`
- [x] 6.2 Unify REST API endpoint `POST /api/v1/scheduler/tick` to invoke `SchedulerService.evaluate_admission`
- [x] 6.3 Unify background daemon service (`minime-scheduler.service`) tick loop to consume converged admission engine without private bypasses

## 7. Non-Interference and Guardrail Verification

- [x] 7.1 Verify that provider policy and model independence rules remain authoritative and are not bypassed
- [x] 7.2 Verify that task complexity and risk classification snapshots remain orthogonal to capacity evaluation
- [x] 7.3 Verify that human merge and human validation gates are preserved without automated bypass

## 8. Acceptance Tests

- [x] 8.1 Implement unit and integration tests for `SAFE_EXECUTABLE_PAIR_EXISTS` evaluation
- [x] 8.2 Implement tests for strict drain isolation (in-flight continuation allowed vs new admission refused)
- [x] 8.3 Implement tests for failure taxonomy classification across pre-admission observables and post-execution outcomes
- [x] 8.4 Implement tests for epistemic honesty (deterministic header handling vs unknown ETA)
- [x] 8.5 Implement parity tests across CLI, REST API, TUI, and daemon entry points for identical admission decisions
