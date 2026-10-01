# Proposal: Stage G — Scheduler and Recovery Convergence

## Context

Stage F closed the transaction/concurrency boundary for fresh admission and command mutation. Stage G now converges autonomous scheduling, daemon startup recovery, waiting-state recovery, saga recovery, post-merge reconciliation, and active-run continuation so they all resume work from durable truth without duplicate execution or parallel recovery authorities.

Canonical base: `15e55c515ae917c2f0330809f0d9e44d49bce12b`

Branch: `architecture/scheduler-and-recovery-convergence`

OpenSpec change: `scheduler-and-recovery-convergence`

## Problem

The current repository contains multiple overlapping recovery paths:

- `RestartRecoveryService.reconcile_on_startup()` scans active jobs, active runs, and durable sagas.
- Startup saga recovery directly invokes `IntakeService.prepare_work_item()` and `PostMergeReconciliationService.reconcile_post_merge()`.
- Startup run recovery may directly invoke `OrchestrationService.resume()`.
- Every `SchedulerService.tick()` independently performs post-merge reconciliation, waiting-run recovery, queued-run driving, intake sweep, discovery, and fresh admission.
- `scheduler-capacity-policy-convergence` is already fully implemented but remains an active OpenSpec change, creating overlapping scheduler contract authority.

These mechanisms can individually be valid while still failing to converge as one deterministic recovery model across restart, repeated ticks, concurrent scheduler processes, and partial external effects.

## Stage G Exit Requirement

> Repeated startup recovery and scheduler ticks converge to one durable next action per work item/run without guessing success, replaying completed work, bypassing Stage F admission, or duplicating external side effects.

## What Changes

1. Establish one canonical recovery planner/driver used by daemon startup and periodic scheduler ticks.
2. Enforce recovery-before-fresh-admission ordering.
3. Resume orchestration only from persisted safe checkpoints.
4. Route saga recovery through durable saga authority instead of direct service bypasses.
5. Route ambiguous external actions through observe-before-repeat semantics.
6. Preserve terminal dominance and fail closed when evidence is unavailable or contradictory.
7. Ensure waiting-capacity recovery is based on verified provider truth only.
8. Ensure post-merge continuation uses canonical closure saga / post-merge authority exactly once.
9. Preserve Stage F transaction, row-lock, advisory-lock, and retry guarantees.
10. Produce durable recovery decisions/events sufficient to explain what was resumed, deferred, blocked, or adopted.
11. Treat the already-delivered `scheduler-capacity-policy-convergence` contract as satisfied predecessor behavior and remove duplicate active contractual ownership during Stage G closure.

## Non-Goals

- No deployment.
- Do not enable `minime-scheduler.service`.
- No provider/model capability-selection redesign.
- No dynamic routing or scoring.
- No unrelated UI redesign.
- No Stage H documentation-wide convergence beyond Stage G-owned overlap cleanup.
- No change to human merge authority.

## Preservation

Stages A–F remain authoritative. In particular:
- lifecycle transitions remain Stage A single-writer controlled;
- external effects remain Stage B/D observable/idempotent/resumable;
- runtime/worktree isolation remains Stage C;
- intake/closure sagas remain Stage D durable authorities;
- query paths remain Stage E pure;
- fresh admission and concurrent command mutation remain Stage F serialized.
