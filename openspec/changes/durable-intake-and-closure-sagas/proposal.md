# Proposal: Durable Intake and Closure Sagas

## Why

Currently in mini me, work intake (backlog creation, OpenSpec generation, GitHub Issue creation, GitHub Project item binding, DoR readiness evaluation) and post-human-merge closure (merged PR observation, candidate ancestry/squash delivery verification, GitHub Issue closure, GitHub Project item completion, OpenSpec spec sync, OpenSpec change archiving, worktree cleanup, branch deletion, lock release) execute as linear, in-memory procedures without durable phase checkpointing or explicit pre-action state reservations in PostgreSQL.

If the system crashes, restarts, encounters a network timeout, or receives an ambiguous response during intake or closure, it currently faces severe operational risks:
1. **Duplicate Remote Effects**: Retrying an intake API call after a post-response crash can create duplicate GitHub Issues or GitHub Project items if title-only or un-indexed checks are performed.
2. **Phase Skipping & Blind Retries**: Closure operations lack phase-level durable evidence checkpoints; retrying a partially completed post-merge closure re-runs completed phases blindly or fails when trying to archive already-moved directories.
3. **Resurrection of Terminal Work**: System startup or stale queue read models can re-trigger intake or closure on work items already marked `COMPLETED` or `CANCELLED`.
4. **Fabrication of Success**: Inferring closure from a single terminal domain flag (`Change.DONE` or `BacklogItem.COMPLETED`) when required closure phases (e.g. OpenSpec spec sync or archiving) remain unverified fabricates success.
5. **Loss of Operational State**: An operator cannot inspect where a crashed saga was, requiring manual intervention and reconstruction of past external actions.

Stage D addresses these risks by implementing **Architectural Law 4**:
> Every external side effect is observable, idempotent, and resumable.

It also strictly enforces foundational cross-program invariants:
- Lifecycle transitions have one single writer (`LifecycleTransitionAuthority`).
- Missing or unavailable evidence is never interpreted as success (`UNKNOWN` fails closed).
- Observations and projections cannot resurrect terminal work.
- Deployed runtime checkout is never a managed workspace (Stage C isolation).

## What Changes

- **Durable Saga Identity & Generalized Single External-Action Authority**:
  - Introduce `DurableSagaModel` (`durable_sagas`) in PostgreSQL to track saga ID, saga type (`INTAKE`, `CLOSURE`), project ID, work item key, change name, run ID, job ID, generation, current phase checkpoint, status (`IN_PROGRESS`, `BLOCKED`, `COMPLETED`, `FAILED`, `CANCELLED`), blocking reason, and evidence references.
  - **Single External Action Authority**: Avoid creating a duplicate store. Generalize the existing canonical `OrchestrationExternalActionModel` (`orchestration_external_actions`) by adding an optional `saga_id` foreign key and making `run_id` and `candidate_sha` conditional, while retaining global deterministic `action_key` uniqueness.
  - Require pre-execution reservation of an `OrchestrationExternalActionModel` record with status `RESERVED` / `IN_FLIGHT` and `request_fingerprint` BEFORE executing any external mutation.

- **Inherit Stage B Identities Exactly & Reconcile Before Retry**:
  - For GitHub Issues: deterministic `operation_key` is authoritative; body carries exact `<!-- minime-opkey: <operation_key> -->` comment marker. Reconciliation matches this marker; title-only deduplication is FORBIDDEN.
  - For GitHub Project items: reconcile using exact project identity + issue URL / operation-key semantics already established by Stage B; no fuzzy or title matching.
  - For OpenSpec authoring/sync/archive: reconcile via project ID, change name, and filesystem verification.
  - For Worktrees & Branches: reconcile via Stage C 4-way verification, `git show-ref` exit code 1, and remote 404 HTTP outcomes.

- **Squash-Merge-Aware Delivery Verification**:
  - Refine merge verification phase to `MERGED_DELIVERY_VERIFIED`.
  - Distinguish ancestry-preserving merges (verified via `git merge-base --is-ancestor`) from squash merges.
  - For squash merges: verify PR `is_merged == True`, repository/base identity is exact, PR head SHA equals audited candidate SHA, observed `merge_commit_sha` exists, and canonical base branch contains `merge_commit_sha`. Candidate non-ancestry after a verified squash merge is NOT a verification failure.

- **Terminal Domain State != Saga Closure**:
  - If work is terminal during Intake (`COMPLETED`, `DONE`, `CANCELLED`), never reopen, re-admit, or restart preparation.
  - If domain state is already terminal during Closure but `ClosureSaga` evidence is incomplete: DO NOT resurrect work and DO NOT infer closure success. Enter reconciliation-only mode to observe/check missing closure postconditions, adopt already-completed effects where proven, and complete saga ONLY when complete required evidence set exists; if evidence cannot be safely reconstructed, remain `BLOCKED` / `NEEDS_HUMAN`.

- **Boundary Separation (Stage F Scope Boundary)**:
  - Stage D guarantees durable saga identity, deterministic action identity, uniqueness constraints, sequential/repeated resume idempotency, reconcile-before-repeat, and crash recovery.
  - Comprehensive multi-worker concurrency and race proving are explicitly deferred to Stage F (`transaction-and-concurrency-contract`).

- **Durable Intake Saga**:
  - Convert `IntakeService` to drive a multi-phase durable saga (`INTAKE_CREATED` -> `CONTEXT_CHECKED` -> `OPENSPEC_AUTHORED` -> `ISSUE_BOUND` -> `PROJECT_ITEM_BOUND` -> `READINESS_EVALUATED` -> `READY`).

- **Durable Closure Saga**:
  - Convert `PostMergeReconciliationService` into a multi-phase durable saga (`MERGE_OBSERVED` -> `MERGED_DELIVERY_VERIFIED` -> `RUN_JOB_RECONCILED` -> `ISSUE_CLOSED` -> `PROJECT_ITEM_DONE` -> `SPEC_SYNCED` -> `SYNC_VERIFIED` -> `SPEC_ARCHIVED` -> `ARCHIVE_VERIFIED` -> `WORKTREE_CLEANED` -> `BRANCH_CLEANED` -> `LOCKS_RELEASED` -> `FINAL_CLOSED`).

## Scope & Non-Goals

### Non-Goals
- Do NOT implement Stage E projection purity (except directly blocking Stage D dependencies).
- Do NOT perform Stage F full multi-worker concurrency contract redesign.
- Do NOT perform Stage G scheduler convergence.
- Do NOT modify provider/model selection or adaptive routing.
- Do NOT activate `minime-scheduler.service`.
- Do NOT perform production deployments or UI redesigns.
- Do NOT modify Stage C managed repository runtime isolation guarantees.

## Capabilities

### New Capability: Durable Intake and Closure Sagas
Provides PostgreSQL-backed, phase-checkpointed, idempotent intake and post-merge closure sagas reusing the single canonical external-action authority, enforcing Stage B deterministic identity matching, supporting squash-merge delivery verification, protecting terminal domain states, and recovering safely from process crashes.
