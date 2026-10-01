# Task Plan: Stage G — Scheduler and Recovery Convergence

## 1. Contract & Audit
- [ ] 1.1 Validate proposal/design/spec against Stages A–F.
- [ ] 1.2 Audit G01–G20 and classify ALREADY_COMPLIANT / NEEDS_CHANGE.
- [ ] 1.3 Verify direct resume/retry/control-plane/post-merge entry-point inventory.
- [ ] 1.4 Verify all ExternalActionStatus repeat boundaries.
- [ ] 1.5 Freeze implementation contract SHA before production edits.

## 2. Durable Recovery Persistence
- [ ] 2.1 Add RecoveryClaim model/repository/migration with unique claim_key and monotonic fence_token.
- [ ] 2.2 Add configurable 60s lease / 15s heartbeat defaults with validation heartbeat < lease/3.
- [ ] 2.3 Implement atomic acquire/renew/release/reacquire semantics.
- [ ] 2.4 Add RecoveryDecision model/repository/migration with UNIQUE(cycle_id, claim_key).
- [ ] 2.5 Implement fenced pre-dispatch and result-application validation.

## 3. Canonical Recovery Authority
- [ ] 3.1 Implement/elevate RecoveryConvergenceService.
- [ ] 3.2 Route daemon startup through canonical reconcile_cycle().
- [ ] 3.3 Route SchedulerService.tick recovery through canonical reconcile_cycle().
- [ ] 3.4 Preserve failure isolation across identities.
- [ ] 3.5 Ensure no DB lock spans slow external I/O.

## 4. Direct Entry Points
- [ ] 4.1 Route REST orchestration resume through RecoveryConvergenceService.
- [ ] 4.2 Route CLI resume/retry through RecoveryConvergenceService.
- [ ] 4.3 Route ControlPlane CONTINUE/RESUME/RETRY through RecoveryConvergenceService.
- [ ] 4.4 Route scheduler DRAIN continuation through RecoveryConvergenceService.
- [ ] 4.5 Route queued-run drive and WAITING_CAPACITY/WAITING_EXTERNAL continuation through canonical authority.
- [ ] 4.6 Make low-level resume/drive primitives internal or require validated RecoveryClaimContext.

## 5. Checkpoint Recovery
- [ ] 5.1 Define candidate/check/review/audit safe-checkpoint mapping.
- [ ] 5.2 Preserve all valid candidate-bound evidence on restart.
- [ ] 5.3 Never infer provider success without committed completion evidence.
- [ ] 5.4 Re-read/lock canonical run/job state in short Stage F-compliant transactions before mutations.

## 6. Durable Saga Recovery
- [ ] 6.1 Replace startup intake direct call with SagaEngine checkpoint resume.
- [ ] 6.2 Replace startup closure direct call with closure SagaEngine checkpoint resume.
- [ ] 6.3 Bind closure saga continuation to parent run claim where run_id exists.
- [ ] 6.4 Preserve terminal-parent dominance.

## 7. External Action Reconciliation
- [ ] 7.1 Implement/centralize status matrix for COMPLETED.
- [ ] 7.2 Implement RESERVED observation-before-first/recovered-dispatch.
- [ ] 7.3 Implement EXECUTING observation-before-repeat.
- [ ] 7.4 Implement FAILED repeat only with proven absence + explicit retry authorization.
- [ ] 7.5 Implement UNKNOWN observation/adopt/wait/human behavior.
- [ ] 7.6 Implement AMBIGUOUS observation/adopt/wait/human behavior.
- [ ] 7.7 Prove existing reservation never itself authorizes mutation.

## 8. Waiting / Closure / Cleanup
- [ ] 8.1 Centralize WAITING_CAPACITY wake-up and require verified provider truth.
- [ ] 8.2 Require WAITING_EXTERNAL re-observation before continuation.
- [ ] 8.3 Centralize post-merge continuation under closure saga + run claim.
- [ ] 8.4 Handle PR closed-unmerged without entering merged closure.
- [ ] 8.5 Give cleanup mutations durable action identities and observe-before-repeat semantics.
- [ ] 8.6 Ensure CANCELLED/DONE/COMPLETED parents never resume execution.

## 9. Scheduler Ordering & Observability
- [ ] 9.1 Enforce truth -> recovery -> intake/discovery -> fresh admission ordering.
- [ ] 9.2 Preserve Stage F admit_work_item() as sole fresh-admission authority.
- [ ] 9.3 Persist recovery-cycle and RecoveryDecision observability.
- [ ] 9.4 Expose recovery status via pure query/read model.
- [ ] 9.5 Preserve delivered scheduler-capacity-policy-convergence behavior.

## 10. Adversarial Proving
- [ ] 10.1 Real PostgreSQL startup-vs-tick same-run claim contention.
- [ ] 10.2 Real PostgreSQL tick-vs-direct-resume/control-plane contention.
- [ ] 10.3 Expired lease increments fence; stale owner cannot apply lifecycle result.
- [ ] 10.4 Prove no DB lock is held during blocked slow external I/O.
- [ ] 10.5 Repeated unchanged recovery produces zero duplicate effects/calls.
- [ ] 10.6 Parameterized ExternalActionStatus reconciliation for RESERVED/EXECUTING/FAILED/UNKNOWN/AMBIGUOUS/COMPLETED.
- [ ] 10.7 Existing reservation cannot duplicate Issue/Project/spec/worktree/branch mutation.
- [ ] 10.8 WAITING_EXTERNAL direct resume re-observes and remains waiting when unobservable.
- [ ] 10.9 Intake saga resumes from non-zero checkpoint.
- [ ] 10.10 Closure saga resumes after merge exactly once.
- [ ] 10.11 PR closed-unmerged cleanup is idempotent and never enters merge closure.
- [ ] 10.12 Preserve candidate/check/review/audit checkpoints.
- [ ] 10.13 Terminal parent prevents execution resurrection.
- [ ] 10.14 WAITING_CAPACITY elapsed reset alone does not resume; verified recovery resumes once.
- [ ] 10.15 Recovery converges before fresh admission.
- [ ] 10.16 CLI/API/TUI/daemon/control-plane parity.
- [ ] 10.17 Preserve Stage C Git-lock tests.
- [ ] 10.18 Run Stage A–F targeted regressions.
- [ ] 10.19 Run PostgreSQL focused Stage G suite.
- [ ] 10.20 Run Ruff and full pytest only after focused suite is green.

## 11. Governance & Closure
- [ ] 11.1 openspec validate scheduler-and-recovery-convergence.
- [ ] 11.2 Independent contract review before implementation.
- [ ] 11.3 Independent final implementation review against frozen candidate.
- [ ] 11.4 Human PR merge only.
- [ ] 11.5 Post-merge sync/archive Stage G.
- [ ] 11.6 Archive/resolve stale active scheduler-capacity-policy-convergence contract without changing delivered behavior.
- [ ] 11.7 Keep minime-scheduler.service disabled; no deployment in Stage G.
