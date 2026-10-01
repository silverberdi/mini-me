# Task Plan: Stage G — Scheduler and Recovery Convergence

## 1. Contract & Audit
- [ ] 1.1 Validate Stage G proposal/design/spec against canonical correction-program laws.
- [ ] 1.2 Audit G01–G16 against current code and classify each as ALREADY_COMPLIANT / NEEDS_CHANGE.
- [ ] 1.3 Confirm overlap boundaries with completed `scheduler-capacity-policy-convergence`.
- [ ] 1.4 Freeze implementation contract SHA before production edits.

## 2. Canonical Recovery Authority
- [ ] 2.1 Introduce/elevate one canonical recovery convergence service.
- [ ] 2.2 Make daemon startup delegate to the canonical recovery cycle.
- [ ] 2.3 Make `SchedulerService.tick()` delegate recovery work to the same authority.
- [ ] 2.4 Preserve failure isolation so one blocked identity does not abort unrelated recovery.

## 3. Run / Job Recovery
- [ ] 3.1 Define durable safe-checkpoint mapping for non-terminal Job states.
- [ ] 3.2 Preserve completed candidate-bound checks/review/audit evidence.
- [ ] 3.3 Never infer provider success from an interrupted process without completion evidence.
- [ ] 3.4 Reconcile active runs under Stage F row-lock authority before mutating continuation.
- [ ] 3.5 Prevent duplicate queued-run coordinator drive across startup/tick/concurrent processes.

## 4. Durable Saga Recovery
- [ ] 4.1 Replace direct intake recovery bypass with SagaEngine checkpoint resume.
- [ ] 4.2 Replace direct closure recovery bypass with closure saga checkpoint/adoption.
- [ ] 4.3 Preserve terminal parent dominance for intake and closure.
- [ ] 4.4 Reconcile Stage D external actions before any repeated mutation.

## 5. External Evidence & Ambiguity
- [ ] 5.1 Classify externally unobservable state as WAITING_EXTERNAL without guessing.
- [ ] 5.2 Classify contradictory/irreconcilable evidence as NEEDS_HUMAN.
- [ ] 5.3 Adopt verified already-completed external effects without repeating them.
- [ ] 5.4 Preserve Stage B/D action identity and mutation-retry authorization semantics.

## 6. Waiting / Closure Convergence
- [ ] 6.1 Centralize WAITING_CAPACITY wake-up under recovery authority.
- [ ] 6.2 Require verified provider AVAILABLE/DEGRADED evidence; reset timestamps alone never resume.
- [ ] 6.3 Centralize post-merge continuation under closure authority.
- [ ] 6.4 Ensure repeated merge observation is idempotently adopted.

## 7. Scheduler Ordering & Entry Points
- [ ] 7.1 Enforce canonical tick order: truth -> recovery -> intake/discovery -> fresh admission.
- [ ] 7.2 Preserve Stage F `SchedulerService.admit_work_item()` as sole fresh-admission authority.
- [ ] 7.3 Ensure CLI/API/TUI/daemon tick paths share the same convergence semantics.
- [ ] 7.4 Ensure no service activation/deploy behavior is introduced.

## 8. Observability
- [ ] 8.1 Persist correlation-bound recovery cycle evidence.
- [ ] 8.2 Persist prior checkpoint, observations, chosen recovery classification, and result.
- [ ] 8.3 Expose sufficient status data to explain resumed/waiting/human/no-op outcomes without query mutation.

## 9. Adversarial Proving
- [ ] 9.1 Real PostgreSQL: two workers recover same run; exactly one mutating continuation.
- [ ] 9.2 Real PostgreSQL: repeated unchanged recovery cycle produces no duplicate transitions/actions.
- [ ] 9.3 Restart checkpoint preservation for candidate + checks/review/audit.
- [ ] 9.4 External action: observed-complete adopts; unavailable waits; contradictory needs human.
- [ ] 9.5 Intake saga resumes from durable non-zero checkpoint with no duplicate mutation.
- [ ] 9.6 Closure saga resumes after observed merge with no duplicate closure effect.
- [ ] 9.7 WAITING_CAPACITY does not resume on elapsed reset estimate alone.
- [ ] 9.8 Verified provider recovery resumes exactly once.
- [ ] 9.9 Terminal Change/Backlog prevents recovery resurrection.
- [ ] 9.10 Recovery-before-fresh-admission ordering proof.
- [ ] 9.11 Concurrent scheduler process proof with no double-drive.
- [ ] 9.12 Entry-point parity proof.
- [ ] 9.13 Preserve Stage C Git-lock fail-closed tests.
- [ ] 9.14 Run Stage A–F targeted regression suite.
- [ ] 9.15 Run full pytest and Ruff once after focused proving is green.

## 10. Governance & Closure
- [ ] 10.1 OpenSpec validate Stage G.
- [ ] 10.2 Independent review against frozen candidate.
- [ ] 10.3 Human PR merge only.
- [ ] 10.4 Post-merge sync/archive Stage G.
- [ ] 10.5 Resolve/archive completed stale `scheduler-capacity-policy-convergence` active contract without changing delivered behavior.
- [ ] 10.6 Keep `minime-scheduler.service` disabled; no deploy in Stage G.
