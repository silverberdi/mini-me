# Proposal: Stage F — Transaction and Concurrency Contract

## Context & Purpose
Stage F establishes one coherent, process-independent transaction and concurrency model for command execution in `mini me`.

- **Repository:** `/Users/silveriobernal/Documents/Code/Development/mini-me`
- **Canonical Branch:** `main`
- **Canonical Base SHA:** `fab5a5e2aa8df9fef83552cf04bdfc4a8cc0a342`
- **Branch:** `architecture/transaction-and-concurrency-contract`
- **OpenSpec Change:** `transaction-and-concurrency-contract`

In Stages A–E, `mini me` established canonical lifecycle authority (Stage A), fail-closed external evidence/actions (Stage B), managed repository/runtime isolation (Stage C), durable intake/closure sagas (Stage D), and projection purity with API CQS (Stage E).

However, command execution admission currently suffers from a count-then-insert read/check/create race condition in `SchedulerService.evaluate_admission()` and `SchedulerService.admit_work_item()`. Specifically, `evaluate_admission()` reads active runs via an un-locked `uow.orchestration_runs.list_runs(is_active=True)` query and checks project/global concurrency counts before `OrchestrationService.admit_change()` inserts a new active run in a separate commit. Two independent processes or database transactions can evaluate active counts simultaneously, observe available capacity, and both admit work items, violating configured project (`Project.max_concurrent_jobs`) and global (`scheduler.max_global_jobs`) concurrency limits.

Stage F resolves this vulnerability by defining a process-independent, database-authoritative concurrency model. The canonical correction-program exit requirement for Stage F is:
> **Concurrent admission cannot create duplicate active execution.**

Stage F makes this invariant true for same-change duplication, project-level concurrency limits, global scheduler concurrency limits, and identified command-side state transition races across independent processes, PostgreSQL sessions, and concurrent API/scheduler/CLI callers.

## Core Laws Established by Stage F
1. **F1. Single Concurrency Boundary:** Any command whose correctness depends on durable state MUST acquire concurrency authority, re-read state, evaluate decisions, perform mutations, and commit within one defined transaction boundary.
2. **F2. Database as Final Authority:** In-process locks, Python mutexes, single-worker deployment assumptions, or scheduler tick timing SHALL NOT be relied upon for correctness. Correctness MUST hold across independent processes and PostgreSQL sessions.
3. **F3. Explicit & Minimal Lock Scope:** Every lock MUST name its protected invariant, lock key, acquisition order, release boundary, and timeout behavior. Table locks are prohibited.
4. **F4. Side-Effect Retry Boundary:** Transactions that may be automatically retried MUST NOT contain unprotected external side effects. External effects remain governed by Stage B/D reservation-commit-call patterns.
5. **F5. Classified Transaction Retries:** Automatic retry MAY cover explicitly classified PostgreSQL transient concurrency errors (`40001` serialization failure, `40P01` deadlock, and conditionally `55P03` lock timeout on coordination paths). It MUST NOT retry policy, lifecycle, authorization, budget, or external denials, and MUST NOT automatically retry generic `57014` query cancellations.
6. **F6. Terminal State Inviolability:** Concurrency retries or re-reads MAY transition a command to `WAIT`/denied, but MUST NOT override Stage A lifecycle truth or resurrect terminal states.

## Scope
- Authoring the comprehensive design and specification for Stage F (`transaction-and-concurrency-contract`).
- Auditing and classifying all 20 required command surfaces F01–F20 (resulting in 3 `ALREADY_COMPLIANT` and 17 `NEEDS_CHANGE` surfaces).
- Specifying PostgreSQL 64-bit SHA-256 derived transaction-scoped advisory locks (`pg_advisory_xact_lock(bigint)`) with a local lock timeout (`SET LOCAL lock_timeout = '2s'`) for atomic admission serialization spanning global (`max_global_jobs = 1`) and project concurrency boundaries.
- Preserving existing correct Stage A–E concurrency mechanisms (Stage D saga resume `FOR UPDATE`, Stage B budget reservation `FOR UPDATE`, Stage B provider probe `FOR UPDATE`, Stage A `LifecycleTransitionAuthority` status CAS).
- Defining exact lock acquisition ordering to prevent known lock-order cycles under the Stage F locking protocol.
- Conducting a nested commit audit across all core call graphs to eliminate intermediate un-scoped commits.
- Defining transaction savepoint / rollback recovery semantics (Pattern A / Pattern B) for expected unique constraint conflicts.
- Defining bounded transaction retry wrapper semantics (maximum 3 total attempts: 1 initial + max 2 retries) without duplicating external side effects.
- Formulating a PostgreSQL-backed adversarial test matrix T01–T15.

## Non-Goals
- **No Production Code Implementation:** This task is DESIGN / CONTRACT ONLY. Production code implementation is strictly prohibited during this stage.
- **No Stage G Execution:** Scheduler tick loop redesign, recovery scanning policies, process daemon loops, and stale run recovery belong strictly to Stage G.
- **No Deployment or Service Activation:** `minime-scheduler.service` must remain disabled. No container previews or production deployments will be performed.
- **No Replacement of Stage A–E Invariants:** Existing correct locks and constraints shall be preserved, not replaced for arbitrary uniformity.
- **No Schema DDL Migrations:** All required invariants map cleanly to existing database constraints and native PostgreSQL advisory locks.
