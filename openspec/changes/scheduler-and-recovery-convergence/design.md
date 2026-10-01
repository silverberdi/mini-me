# Design: Stage G — Scheduler and Recovery Convergence

## Canonical Base
`15e55c515ae917c2f0330809f0d9e44d49bce12b`

## Existing Reality

The current daemon already calls `RestartRecoveryService.reconcile_on_startup()` before entering its loop. However, recovery authority is distributed:

1. `RestartRecoveryService.reconcile_on_startup()`
   - scans active jobs;
   - scans active runs;
   - resumes durable sagas;
   - may call `OrchestrationService.resume()`.
2. `RestartRecoveryService.reconcile_durable_sagas()`
   - directly calls `IntakeService.prepare_work_item()` and `PostMergeReconciliationService.reconcile_post_merge()`.
3. `SchedulerService.tick()`
   - reconciles post-merge runs;
   - reconciles waiting runs;
   - drives queued active runs;
   - sweeps intake;
   - discovers work;
   - evaluates fresh admission.
4. Stage F now guarantees fresh admission serialization, but it intentionally did not define scheduler/recovery ordering.

The problem is therefore not “missing recovery”; it is multiple partially-overlapping recovery authorities.

## Architectural Laws G1–G7

- **G1 — Durable State First:** recovery decisions are authorized only after re-reading canonical durable state.
- **G2 — One Recovery Decision Per Identity:** one run/job/saga has one recovery decision authority per cycle.
- **G3 — Observe Before Repeat:** external mutation is never repeated until ambiguity is reconciled.
- **G4 — Checkpoint Preservation:** committed candidate-bound evidence is never discarded merely due to restart.
- **G5 — Recovery Before Admission:** interrupted in-flight work is classified before new READY work is admitted.
- **G6 — Concurrency Preservation:** recovery commands reuse Stage F row locks, savepoints, and retry boundaries; no process-local singleton assumption is correctness-critical.
- **G7 — Terminal Dominance:** terminal Change/Backlog/Run/Saga state cannot be resurrected by startup or periodic recovery.

## Proposed Service Boundary

Introduce a canonical `RecoveryConvergenceService` (name may be adjusted if an existing service can be safely elevated) responsible for planning and dispatching recovery.

It SHALL expose conceptually:

- `reconcile_cycle(project_id=None, source=STARTUP|TICK)`
- `reconcile_run(run_id)`
- `reconcile_saga(saga_id)`
- `reconcile_waiting_run(run_id)`

The service does not become a new lifecycle writer. It delegates lifecycle transitions to existing authorities.

`RestartRecoveryService` becomes a specialized adapter/helper for restart-specific evidence such as interrupted process classification and Git lock inspection, not an independent orchestration authority.

`SchedulerService.tick()` delegates recovery convergence rather than duplicating post-merge/waiting/queued-run continuation logic.

## Canonical Tick Order

1. Capture existing provider/external truth required for fail-closed decisions.
2. Execute recovery convergence for active/non-terminal durable work.
3. Reconcile closure and waiting continuations through canonical authorities.
4. Perform autonomous intake preparation sweep.
5. Discover/project queue truth.
6. Rank candidate projections.
7. Fresh admission only through Stage F `admit_work_item()`.
8. Persist decision/recovery observability.
9. Return.

Fresh admission pre-counts may be retained as optimization only; they are never authority.

## Recovery Classification

Each recoverable identity resolves to one of:

- `NO_ACTION`: already converged.
- `RESUME_SAFE_CHECKPOINT`: exactly one safe continuation exists.
- `ADOPT_OBSERVED_EFFECT`: external effect already happened and is verified.
- `WAITING_CAPACITY`: provider truth proves a temporary capacity block.
- `WAITING_EXTERNAL`: required external evidence is temporarily unobservable.
- `NEEDS_HUMAN`: evidence is contradictory, structurally invalid, or unsafe.
- `TERMINAL_DOMINATES`: parent lifecycle is terminal; no execution continuation allowed.

These are recovery classifications, not new lifecycle enums unless existing domain types cannot represent them cleanly.

## Surface Audit

| ID | Surface | Current Behavior | Stage G Requirement |
|---|---|---|---|
| G01 | daemon startup | restart recovery runs before loop | preserve, route through canonical recovery cycle |
| G02 | periodic tick recovery | post-merge/waiting/queued recovery embedded in tick | delegate to same recovery authority |
| G03 | active job interruption | resets using checkpoint heuristics | bind decision to durable candidate/evidence and fail closed on ambiguity |
| G04 | active run recovery | may call `resume()` directly | locked canonical re-read + unique safe continuation |
| G05 | intake saga recovery | direct `prepare_work_item()` call | resume via SagaEngine durable phase/checkpoint |
| G06 | closure saga recovery | direct post-merge call | resume/adopt through closure saga authority |
| G07 | external actions | AMBIGUOUS currently broadly blocks human | observe-before-repeat; WAITING_EXTERNAL when merely unobservable, NEEDS_HUMAN when contradictory |
| G08 | waiting capacity | tick independently resumes | canonical verified provider truth + locked resume |
| G09 | queued active runs | tick directly drives coordinator | canonical recovery classification then locked continuation |
| G10 | post-merge runs | every tick polls/reconciles | closure convergence authority, idempotent adoption |
| G11 | fresh admission ordering | same tick mixes recovery and admission | recovery convergence before fresh admission |
| G12 | repeated tick/restart | multiple recovery paths may overlap | idempotent no-duplicate convergence |
| G13 | concurrent scheduler processes | no singleton correctness guarantee | Stage F DB concurrency remains final authority |
| G14 | Git lock recovery | strong Stage C ownership proof exists | preserve unchanged, expose through convergence result |
| G15 | recovery observability | events exist but no single decision envelope | durable correlated recovery decision/evidence |
| G16 | entry-point parity | CLI/API/TUI/daemon all reach tick but startup differs | one canonical semantics for recovery + scheduling |

## Transaction Rules

- Do not hold DB locks around long provider/GitHub/Git subprocess operations.
- Prepare external observations outside lock where necessary.
- Acquire row lock, re-read canonical state, verify observation still applies, then persist decision.
- External mutation uses Stage B/D reservation/observe-before-repeat.
- Recovery retry never wraps an unreserved external side effect.
- Fresh admission remains Stage F-owned.

## Test Strategy

Mandatory evidence shall include:

- real PostgreSQL multi-session restart/tick contention on same run;
- repeated recovery no-op proof;
- interrupted job checkpoint preservation;
- ambiguous external action observable-adopt / unavailable-wait / contradictory-human cases;
- intake saga resume from non-zero checkpoint without duplicated external action;
- closure saga resume/adopt after observed merge;
- waiting capacity recovery only after verified health;
- terminal parent prevents recovery resurrection;
- recovery-before-admission ordering;
- two scheduler processes cannot double-drive continuation;
- daemon/CLI/API/TUI parity at canonical decision layer;
- Stage A–F regression suite.

## OpenSpec Overlap

`scheduler-capacity-policy-convergence` is fully checked off and its delivered behavior is treated as a predecessor. Stage G shall preserve that behavior and, at archive/closure time, remove the stale active duplicate contract so scheduler convergence has one active owner.

Other unrelated active changes are not folded into Stage G.
