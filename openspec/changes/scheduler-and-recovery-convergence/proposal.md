# Proposal: Stage G — Scheduler and Recovery Convergence

## Context

Stage F closed fresh-admission and command-side transaction/concurrency authority. Stage G converges autonomous scheduling, daemon startup recovery, direct continuation commands, waiting-state recovery, durable saga recovery, post-merge reconciliation, and repeated ticks so all continuation paths resolve from the same durable truth.

- Canonical base: `15e55c515ae917c2f0330809f0d9e44d49bce12b`
- Branch: `architecture/scheduler-and-recovery-convergence`
- OpenSpec change: `scheduler-and-recovery-convergence`

## Problem

The current repository has several partially-overlapping continuation/recovery authorities:

- `RestartRecoveryService.reconcile_on_startup()` scans and mutates Jobs, Runs, and durable sagas.
- Startup saga recovery directly invokes `IntakeService.prepare_work_item()` and `PostMergeReconciliationService.reconcile_post_merge()`.
- Startup run recovery may directly invoke `OrchestrationService.resume()`.
- `SchedulerService.tick()` independently reconciles post-merge state, waiting runs, queued active runs, intake, discovery, and fresh admission.
- Direct API/CLI/control-plane CONTINUE/RESUME/RETRY paths can invoke continuation semantics outside startup/tick recovery.
- Existing external-action rows may be RESERVED, EXECUTING, COMPLETED, FAILED, UNKNOWN, or AMBIGUOUS and require status-specific observe/repeat rules.
- A Stage F row lock protects short DB mutations but does not by itself prevent two processes from sequentially acquiring the lock and both performing slow Git/GitHub/provider work after the lock is released.
- `scheduler-capacity-policy-convergence` is already delivered but remains an active overlapping OpenSpec contract.

Stage G must therefore solve both **logical convergence** and **cross-process continuation ownership**.

## Stage G Exit Requirement

> Repeated startup recovery, periodic ticks, and direct continuation commands converge to one durable next action per identity without guessing success, replaying completed work, bypassing Stage F admission, resurrecting terminal execution, or duplicating external effects.

## What Changes

1. Introduce one canonical `RecoveryConvergenceService` for startup, tick, and direct continuation requests.
2. Introduce a durable `RecoveryClaim` lease/fencing mechanism for slow continuation ownership.
3. Introduce a durable `RecoveryDecision` record with one decision per recovery cycle/identity.
4. Require recovery-before-fresh-admission ordering.
5. Route active-run, waiting-run, queued-run, API/CLI resume, control-plane continue/retry, and post-merge triggers through the canonical authority.
6. Route intake/closure recovery through durable SagaEngine checkpoints.
7. Define status-specific observe-before-repeat semantics for every nonterminal ExternalActionStatus.
8. Preserve safe candidate/check/review/audit checkpoints and never infer success from interruption.
9. Distinguish temporary unobservability (WAITING_EXTERNAL) from contradictory evidence (NEEDS_HUMAN).
10. Define terminal-parent behavior: terminal execution never resumes, while already-authorized closure/cleanup may finish without reopening lifecycle.
11. Preserve Stage F row locks/advisory locks/savepoints/retry boundaries inside short DB transactions.
12. Preserve Stage B/D action identity and mutation authorization around every slow external effect.
13. Before every slow external mutation, atomically persist a fenced dispatch intent/attempt under the current RecoveryClaim so the validation-to-network-call gap cannot produce an unrecorded stale dispatch.
14. Require fenced compare-and-swap semantics for claim heartbeat, release, dispatch-intent creation, and result application.
15. Require claim context on provider/pipeline execution primitives whenever they are invoked as continuation/recovery paths outside the canonical coordinator.
16. Preserve delivered scheduler capacity semantics as predecessor behavior and remove duplicate active contractual ownership only at Stage G closure.

## Non-Goals

- No deployment.
- Do not enable `minime-scheduler.service`.
- No provider/model routing or capability selection.
- No scoring redesign.
- No unrelated UI redesign.
- No automated merge.
- No broad Stage H documentation cleanup beyond Stage G-owned overlap.
- Do not replace Stages A–F authority.

## Preservation

- Stage A remains the only lifecycle-transition writer.
- Stage B/D remain the authority for external action identity, observation, and authorized repeat.
- Stage C remains authority for managed workspace/lock safety.
- Stage D remains authority for durable intake and closure sagas.
- Stage E query paths remain side-effect-free.
- Stage F remains sole fresh-admission authority and final DB concurrency authority for short transactions.