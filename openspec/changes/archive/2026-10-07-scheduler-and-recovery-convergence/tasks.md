# Task Plan: Stage G — Scheduler and Recovery Convergence

## 1. Contract & Audit
- [x] 1.1 Validate proposal/design/spec against Stages A–F.
- [x] 1.2 Audit G01–G20 and classify ALREADY_COMPLIANT / NEEDS_CHANGE.
- [x] 1.3 Verify direct resume/retry/control-plane/post-merge entry-point inventory.
- [x] 1.4 Verify all ExternalActionStatus repeat boundaries.
- [x] 1.5 Freeze implementation contract SHA before production edits.

## 2. Durable Recovery Persistence
- [x] 2.1 Add RecoveryClaim model/repository/migration with unique claim_key and monotonic fence_token.
- [x] 2.2 Add configurable 60s lease / 15s heartbeat defaults with validation heartbeat < lease/3.
- [x] 2.3 Implement atomic acquire/reacquire plus fenced CAS renew/release semantics.
- [x] 2.4 Add RecoveryDecision model/repository/migration with UNIQUE(cycle_id, claim_key).
- [x] 2.5 Implement atomic fenced dispatch-intent/attempt persistence immediately before external mutation.
- [x] 2.6 Implement fenced CAS result application; stale owners may record monotonic evidence but cannot advance lifecycle.
- [x] 2.7 Add uniqueness for logical dispatch attempt identity so the validation-to-I/O crash boundary is durable.

## 3. Canonical Recovery Authority
- [x] 3.1 Implement/elevate RecoveryConvergenceService.
- [x] 3.2 Route daemon startup through canonical reconcile_cycle().
- [x] 3.3 Route SchedulerService.tick recovery through canonical reconcile_cycle().
- [x] 3.4 Preserve failure isolation across identities.
- [x] 3.5 Ensure no DB lock spans slow external I/O.

## 4. Direct Entry Points
- [x] 4.1 Route REST orchestration resume through RecoveryConvergenceService.
- [x] 4.2 Route CLI resume/retry through RecoveryConvergenceService.
- [x] 4.3 Route ControlPlane CONTINUE/RESUME/RETRY through RecoveryConvergenceService.
- [x] 4.4 Route scheduler DRAIN continuation through RecoveryConvergenceService.
- [x] 4.5 Route queued-run drive and WAITING_CAPACITY/WAITING_EXTERNAL continuation through canonical authority.
- [x] 4.6 Make low-level resume/drive primitives internal or require validated RecoveryClaimContext.
- [x] 4.7 Inventory provider/pipeline execution primitives reachable outside drive_coordinator() and require RecoveryClaimContext or make them private.

## 5. Checkpoint Recovery
- [x] 5.1 Define candidate/check/review/audit safe-checkpoint mapping.
- [x] 5.2 Preserve all valid candidate-bound evidence on restart.
- [x] 5.3 Never infer provider success without committed completion evidence.
- [x] 5.4 Re-read/lock canonical run/job state in short Stage F-compliant transactions before mutations.

## 6. Durable Saga Recovery
- [x] 6.1 Replace startup intake direct call with SagaEngine checkpoint resume.
- [x] 6.2 Replace startup closure direct call with closure SagaEngine checkpoint resume.
- [x] 6.3 Bind closure saga continuation to parent run claim where run_id exists.
- [x] 6.4 Preserve terminal-parent dominance.

## 7. External Action Reconciliation
- [x] 7.1 Implement/centralize status matrix for COMPLETED.
- [x] 7.2 Implement RESERVED classification as PROVEN_NEVER_DISPATCHED vs POSSIBLY_DISPATCHED; reservation alone never authorizes mutation.
- [x] 7.2A Require Stage B/D original/retry authorization plus atomic fenced dispatch intent for any RESERVED first/repeat dispatch.
- [x] 7.3 Implement EXECUTING observation-before-repeat.
- [x] 7.4 Implement FAILED repeat only with proven absence + explicit retry authorization.
- [x] 7.5 Implement UNKNOWN observation/adopt/wait/human behavior.
- [x] 7.6 Implement AMBIGUOUS observation/adopt/wait/human behavior.
- [x] 7.7 Prove existing reservation never itself authorizes mutation.

## 8. Waiting / Closure / Cleanup
- [x] 8.1 Centralize WAITING_CAPACITY wake-up and require verified provider truth.
- [x] 8.2 Require WAITING_EXTERNAL re-observation before continuation.
- [x] 8.3 Centralize post-merge continuation under closure saga + run claim.
- [x] 8.4 Handle PR closed-unmerged without entering merged closure.
- [x] 8.5 Give cleanup mutations durable action identities and observe-before-repeat semantics.
- [x] 8.6 Ensure CANCELLED/DONE/COMPLETED parents never resume execution.

## 9. Scheduler Ordering & Observability
- [x] 9.1 Enforce truth -> recovery -> intake/discovery -> fresh admission ordering.
- [x] 9.2 Preserve Stage F admit_work_item() as sole fresh-admission authority.
- [x] 9.3 Persist recovery-cycle and RecoveryDecision observability.
- [x] 9.4 Expose recovery status via pure query/read model.
- [x] 9.5 Preserve delivered scheduler-capacity-policy-convergence behavior.

## 10. Adversarial Proving
- [x] 10.1 Real PostgreSQL startup-vs-tick same-run claim contention.
- [x] 10.2 Real PostgreSQL tick-vs-direct-resume/control-plane contention.
- [x] 10.3 Expired lease increments fence; stale owner cannot apply lifecycle result.
- [x] 10.4 Prove no DB lock is held during blocked slow external I/O.
- [x] 10.5 Repeated unchanged recovery produces zero duplicate effects/calls.
- [x] 10.6 Parameterized ExternalActionStatus reconciliation for RESERVED/EXECUTING/FAILED/UNKNOWN/AMBIGUOUS/COMPLETED.
- [x] 10.7 Existing reservation cannot duplicate Issue/Project/spec/worktree/branch mutation.
- [x] 10.8 WAITING_EXTERNAL direct resume re-observes and remains waiting when unobservable.
- [x] 10.9 Intake saga resumes from non-zero checkpoint.
- [x] 10.10 Closure saga resumes after merge exactly once.
- [x] 10.11 PR closed-unmerged cleanup is idempotent and never enters merge closure.
- [x] 10.12 Preserve candidate/check/review/audit checkpoints.
- [x] 10.13 Terminal parent prevents execution resurrection.
- [x] 10.14 WAITING_CAPACITY elapsed reset alone does not resume; verified recovery resumes once.
- [x] 10.15 Recovery converges before fresh admission.
- [x] 10.16 CLI/API/TUI/daemon/control-plane parity.
- [x] 10.17 Preserve Stage C Git-lock tests.
- [x] 10.18 Run Stage A–F targeted regressions.
- [x] 10.19 Run PostgreSQL focused Stage G suite.
- [x] 10.20 Stale worker validation-to-dispatch race: lease expires, successor acquires, only one dispatch intent/network mutation occurs.
- [x] 10.21 Stale heartbeat and stale release are rejected after fence increment.
- [x] 10.22 RESERVED proven-never-dispatched vs possibly-dispatched semantics require Stage B/D authorization.
- [x] 10.23 Direct provider/pipeline primitive invocation without RecoveryClaimContext is rejected.
- [x] 10.24 Run Ruff and full pytest only after focused suite is green.

## 11. Governance & Closure
- [x] 11.1 openspec validate scheduler-and-recovery-convergence.
- [ ] 11.2 Independent contract review before implementation.
- [ ] 11.3 Independent final implementation review against frozen candidate.
- [x] 11.4 Human PR merge only.
- [x] 11.5 Post-merge sync/archive Stage G.
- [x] 11.6 Archive/resolve stale active scheduler-capacity-policy-convergence contract without changing delivered behavior.
- [ ] 11.7 Keep minime-scheduler.service disabled; no deployment in Stage G.