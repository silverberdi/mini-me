# Proposal: Durable Intake and Closure Sagas

## Why

Currently in mini me, work intake (backlog creation, OpenSpec generation, GitHub Issue creation, GitHub Project item binding, DoR readiness evaluation) and post-human-merge closure (merged PR observation, candidate ancestry verification, GitHub Issue closure, GitHub Project item completion, OpenSpec spec sync, OpenSpec change archiving, worktree cleanup, branch deletion, lock release) execute as linear, in-memory procedures without durable phase checkpointing or explicit pre-action state reservations in PostgreSQL.

If the system crashes, restarts, encounters a network timeout, or receives an ambiguous response during intake or closure, it currently faces severe operational risks:
1. **Duplicate Remote Effects**: Retrying an intake API call after a post-response crash can create duplicate GitHub Issues or GitHub Project items.
2. **Phase Skipping & Blind Retries**: Closure operations lack phase-level durable evidence checkpoints; retrying a partially completed post-merge closure re-runs completed phases blindly or fails when trying to archive already-moved directories.
3. **Resurrection of Terminal Work**: System startup or stale queue read models can re-trigger intake or closure on work items already marked `COMPLETED` or `CANCELLED`.
4. **Fabrication of Success**: A process crash or missing remote evidence might leave work in ambiguous states, leading to incomplete closure being inferred from a single terminal flag (`Change.DONE` or `BacklogItem.COMPLETED`).
5. **Loss of Operational State**: An operator cannot inspect where a crashed saga was, requiring manual intervention and reconstruction of past external actions.

Stage D addresses these risks by implementing **Architectural Law 4**:
> Every external side effect is observable, idempotent, and resumable.

It also strictly enforces the foundational cross-program invariants:
- Lifecycle transitions have one single writer (`LifecycleTransitionAuthority`).
- Missing or unavailable evidence is never interpreted as success (`UNKNOWN` fails closed).
- Observations and projections cannot resurrect terminal work.
- Deployed runtime checkout is never a managed workspace.

## What Changes

- **Durable Saga & Action Identity**:
  - Introduce generic PostgreSQL operational persistence models `DurableSagaModel` (`durable_sagas`) and `SagaActionModel` (`saga_actions`).
  - Assign every intake or closure operation a unique durable saga identity carrying saga ID, saga type (`INTAKE`, `CLOSURE`), project ID, work item key, change name, run ID, job ID, attempt/generation, current phase checkpoint, status (`IN_PROGRESS`, `BLOCKED`, `COMPLETED`, `FAILED`, `CANCELLED`), blocking reason, and evidence references.
  - Require pre-execution reservation of a `SagaActionModel` record with status `REQUESTED` / `IN_FLIGHT` and request fingerprint BEFORE executing any external mutation (GitHub Issue creation/update/closure, GitHub Project item add/done, OpenSpec authoring/sync/archive, branch/worktree cleanup).

- **Reconcile Before Retry & Idempotency**:
  - Before retrying any action in `REQUESTED`, `IN_FLIGHT`, or `AMBIGUOUS` state, the saga engine MUST inspect the target external system using fingerprint evidence.
  - If the external side effect is found to have occurred, the saga adopts the result as `SUCCESS` and advances without duplicating the mutation.
  - If non-occurrence is positively established, the saga retries the mutation safely.
  - If truth remains unobservable, the saga remains `BLOCKED` with status `AMBIGUOUS` and surfaces evidence to the operator.

- **Durable Intake Saga**:
  - Convert `IntakeService` to drive a multi-phase durable saga (`INTAKE_CREATED` -> `CONTEXT_CHECKED` -> `OPENSPEC_AUTHORED` -> `ISSUE_BOUND` -> `PROJECT_ITEM_BOUND` -> `READINESS_EVALUATED` -> `READY`).
  - Intake ends cleanly when preparation durably reaches state from which `SchedulerService` admission authority operates.

- **Durable Closure Saga**:
  - Convert `PostMergeReconciliationService` into a multi-phase durable saga (`MERGE_OBSERVED` -> `ANCESTRY_VERIFIED` -> `RUN_JOB_RECONCILED` -> `ISSUE_CLOSED` -> `PROJECT_ITEM_DONE` -> `SPEC_SYNCED` -> `SYNC_VERIFIED` -> `SPEC_ARCHIVED` -> `ARCHIVE_VERIFIED` -> `WORKTREE_CLEANED` -> `BRANCH_CLEANED` -> `LOCKS_RELEASED` -> `FINAL_CLOSED`).
  - Terminal transition to `Change.DONE` and `BacklogItem.COMPLETED` occurs ONLY via `LifecycleTransitionAuthority` after ALL required closure phases are durably proven complete.

- **Terminal Identity Protection & Recovery**:
  - Enforce strict checks preventing completed or cancelled `Change` or `BacklogItem` identities from returning to executable states.
  - Integrate `RestartRecoveryService` and `ControlPlaneService` to discover, reconcile, and safely resume pending sagas from persisted checkpoints upon startup or operator command.

## Scope & Non-Goals

### Non-Goals
- Do NOT implement Stage E projection purity (except directly blocking Stage D dependencies).
- Do NOT perform Stage F concurrency redesign.
- Do NOT perform Stage G scheduler convergence.
- Do NOT modify provider/model selection or adaptive routing.
- Do NOT activate `minime-scheduler.service`.
- Do NOT perform production deployments or UI redesigns.
- Do NOT modify Stage C managed repository runtime isolation guarantees.

## Capabilities

### New Capability: Durable Intake and Closure Sagas
Provides PostgreSQL-backed, phase-checkpointed, idempotent intake and post-merge closure sagas that reserve action identities before remote mutations, reconcile external state before retry, protect terminal work from resurrection, and recover safely from process crashes.
