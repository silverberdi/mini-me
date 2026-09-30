# Delta Specification: Transaction and Concurrency Contract

## Requirement: Process-Independent Fresh Scheduler Admission Serialization
The scheduler service SHALL enforce process-independent, database-authoritative admission serialization as the singular fresh-admission authority (`SchedulerService.admit_work_item()`) for work items across independent processes, database transactions, and execution entry points using PostgreSQL 64-bit SHA-256 derived advisory locks (`pg_advisory_xact_lock(bigint)`) and bounded local lock timeouts (`SET LOCAL lock_timeout = '2s'`).

### Scenario: Same-change concurrent admission contention with Savepoint recovery
- **Given** two independent database transactions simultaneously attempt to admit the exact same `(project_id, change_name)` pair
- **When** both callers invoke `admit_work_item()` concurrently
- **Then** PostgreSQL transaction advisory locks SHALL serialize evaluation
- **And** exactly one caller SHALL succeed and create an active `OrchestrationRun`
- **And** if the second caller hits `uq_active_orchestration_run`, Pattern A Savepoint conflict recovery SHALL flush the savepoint (`session.flush()`) and roll back the nested savepoint without aborting the outer transaction
- **And** the second caller SHALL re-read the active run cleanly and receive `AdmissionDecisionKind.WAIT` with refusal code `CHANGE_ALREADY_ACTIVE`
- **And** no raw `IntegrityError` SHALL leak, and no duplicate active run, job, or stage event SHALL be persisted.

### Scenario: Project concurrency limit enforcement under race
- **Given** a project configured with `max_concurrent_jobs = 1` and two distinct READY work items `Change A` and `Change B`
- **When** two independent database transactions simultaneously attempt to admit `Change A` and `Change B`
- **Then** PostgreSQL transaction 64-bit SHA-256 advisory locks (`pg_advisory_xact_lock(derive_project_admission_lock_key(project_id))`) SHALL serialize evaluation
- **And** exactly one work item SHALL be admitted into `RUN` mode
- **And** the losing work item SHALL receive `AdmissionDecisionKind.WAIT` with refusal code `PROJECT_CONCURRENCY_LIMIT`
- **And** active project run count SHALL NOT exceed `max_concurrent_jobs`.

### Scenario: Global scheduler concurrency limit enforcement under race
- **Given** canonical global concurrency limit `max_global_jobs = 1` and two READY work items across separate projects
- **When** two independent database transactions simultaneously attempt admission
- **Then** global transaction 64-bit SHA-256 advisory lock `pg_advisory_xact_lock(derive_global_admission_lock_key())` SHALL serialize evaluation
- **And** exactly one work item SHALL be admitted globally
- **And** the second work item SHALL receive `AdmissionDecisionKind.WAIT` with refusal code `GLOBAL_CONCURRENCY_LIMIT`.

---

## Requirement: Atomic Admission Bundle Persistence
Admission decision, run creation, stage event emission, canonical event persistence, scheduler decision record save, work queue metadata update, and backlog item status CAS transition (`LifecycleTransitionAuthority.transition_backlog_item()`) SHALL execute as one atomic database transaction owned by `SchedulerService.admit_work_item()`.

### Scenario: Admission transaction rollback on failure
- **Given** a work item undergoing fresh admission
- **When** a database failure or exception is raised after `OrchestrationRun` save but before transaction commit
- **Then** the entire transaction SHALL roll back atomically
- **And** zero orphan orchestration runs, stage events, canonical events, decision records, or modified backlog item statuses SHALL remain in PostgreSQL.

---

## Requirement: Preservation of Stage D Saga Concurrency Invariants & Savepoint Recovery
Durable saga resume operations SHALL use row-level locking (`SELECT ... FOR UPDATE`), and concurrent saga creation attempts SHALL use Pattern A Savepoint conflict recovery to adopt existing active sagas deterministically.

### Scenario: Concurrent saga resume attempt
- **Given** an active intake or closure saga
- **When** two independent workers attempt `resume_saga()` simultaneously
- **Then** PostgreSQL `SELECT ... FOR UPDATE` row locking SHALL force sequential execution
- **And** neither worker SHALL corrupt saga state or duplicate execution phases.

### Scenario: Concurrent saga creation collision with Savepoint recovery
- **Given** an active saga for `(project_id, work_item_key)` matching predicate `status IN ('IN_PROGRESS', 'BLOCKED')`
- **When** a second process attempts to insert a duplicate active saga hitting `uq_active_intake_saga` or `uq_active_closure_saga`
- **Then** Pattern A Savepoint conflict recovery SHALL flush inside the savepoint (`session.flush()`) and roll back the nested savepoint
- **And** the outer transaction SHALL remain clean and usable
- **And** the application SHALL re-read the existing active saga and adopt it deterministically without failing the workflow.

---

## Requirement: Budget and Provider Probe Lock Preservation
Budget reservations and provider health probes SHALL preserve row-level lock serialization under concurrent execution.

### Scenario: Concurrent budget reservation under cap limit
- **Given** a project budget policy with remaining capacity for 1 reservation
- **When** two concurrent requests attempt budget reservation in `BudgetService.reserve_budget()`
- **Then** `uow.budget_policies.get_for_update(project_id)` SHALL serialize callers
- **And** exactly one caller SHALL be granted reservation while the second caller is refused without oversubscribing the budget cap
- **And** the caller transaction SHALL commit the reservation prior to provider dispatch.

### Scenario: Concurrent provider health probe execution
- **Given** a provider health probe window requiring refreshed capacity status
- **When** multiple concurrent requests check provider health
- **Then** `ProviderHealthModel` row lock `SELECT ... FOR UPDATE` in `ProviderHealthService._try_reserve_expensive_probe()` SHALL ensure exactly one expensive network probe executes and commits its reservation
- **And** secondary callers SHALL await lock release and consume the resulting status.

---

## Requirement: Monotonic Stage and Job State Transitions
Stage transitions on `OrchestrationRun` and status transitions on `JobModel` SHALL use row locking or conditional compare-and-swap checks to prevent stale overwrites.

### Scenario: Dual-worker stage transition contention
- **Given** an active run in stage `ADMITTED`
- **When** two independent worker processes attempt to transition the run to `RUNNING`
- **Then** `OrchestrationRun` row locking SHALL serialize the transition
- **And** exactly one worker SHALL record the stage event `ADMITTED -> RUNNING`
- **And** the second worker SHALL observe the updated stage `RUNNING` cleanly without attempting a duplicate transition.

---

## Requirement: Bounded Transaction Retry for Transient Concurrency Conflicts
The system SHALL provide a bounded transaction retry wrapper for classified transient PostgreSQL concurrency errors (`40001`, `40P01`, and conditionally `55P03` lock timeout on coordination paths) up to maximum 3 total attempts while strictly prohibiting retries of `57014` query cancellations, business denials, or unprotected external side effects.

### Scenario: Transient PostgreSQL serialization/deadlock error recovery
- **Given** a database transaction executing a concurrency-safe state update
- **When** PostgreSQL raises SQLSTATE `40001` (`serialization_failure`) or `40P01` (`deadlock_detected`)
- **Then** `TransactionRetryWrapper` SHALL execute `uow.rollback()`
- **And** it SHALL retry the transaction up to 3 total attempts (attempt 1 initial + max 2 retries) with exponential backoff and jitter
- **And** each retry SHALL re-establish a clean transaction boundary, reacquire all locks (`SET LOCAL lock_timeout = '2s'`), re-read authoritative state, and retain exact command identity.

### Scenario: Conditional lock timeout retry classification
- **Given** a transaction acquiring admission coordination locks with `SET LOCAL lock_timeout = '2s'`
- **When** PostgreSQL raises SQLSTATE `55P03` (`lock_not_available`) originating from the known Stage F coordination path
- **Then** `TransactionRetryWrapper` SHALL classify the `55P03` as retryable and execute bounded retry
- **And** generic unrelated `55P03` errors from un-coordinated paths SHALL NOT be automatically retried.

### Scenario: Fast failure on non-retryable business refusals and query cancellations
- **Given** an admission evaluation resulting in policy refusal (`NOT_READY` or `CAPACITY_EXHAUSTED`) or a query cancellation (`57014`)
- **When** the command executes
- **Then** the system SHALL NOT attempt transaction retries
- **And** it SHALL return the refusal result or fail fast immediately.

### Scenario: Prohibition of side-effect duplication during transaction retry
- **Given** a transactional command path that issues external side effects (Git/GitHub API calls)
- **When** the database transaction wrapper is configured
- **Then** external side effects SHALL be executed strictly outside retriable database blocks
- **And** retrying a database transaction SHALL NEVER re-execute an already issued remote side effect.
