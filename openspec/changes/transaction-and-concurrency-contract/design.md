# Design Document: Stage F — Transaction and Concurrency Contract

- **Canonical Base SHA:** `fab5a5e2aa8df9fef83552cf04bdfc4a8cc0a342`
- **Branch:** `architecture/transaction-and-concurrency-contract`
- **OpenSpec Change:** `transaction-and-concurrency-contract`

---

## 1. Problem Statement
In `mini me` Stages A–E, command execution relies on multiple database repositories and service orchestrators. While individual entities employ partial database constraints (such as `uq_active_orchestration_run` on `(project_id, change_name)`) and specific row locks (such as `FOR UPDATE` on saga resume and budget policy reservation), command admission remains vulnerable to read/check/create race conditions.

Specifically, in `SchedulerService.evaluate_admission()`, active orchestration runs are queried via an un-locked `list_runs(is_active=True)` call. The scheduler evaluates three distinct concurrency conditions:
1. Is the same change already active in the project?
2. Does project active run count reach `Project.max_concurrent_jobs`?
3. Does global active run count reach `scheduler.max_global_jobs`?

Following evaluation, `SchedulerService.admit_work_item()` invokes orchestration admission, which inserts an active `OrchestrationRun` and commits the transaction. Because evaluation and insertion occur in separate unlocked read/write operations, two independent processes or API requests executing concurrently can both observe `active_count = 0`, evaluate admission as `RUN`, and both insert active runs.

While the existing `uq_active_orchestration_run` partial unique index prevents duplicate active runs for the *exact same change*, it provides zero protection for:
- Enforcing `Project.max_concurrent_jobs` (e.g. limit = 1 across two different changes in the same project);
- Enforcing global scheduler concurrency limits (`scheduler.max_global_jobs`);
- Atomically updating work queue / backlog item statuses alongside run creation;
- Preventing stale-state race conditions during job, stage, provider health, or worktree ownership mutations.

Stage F establishes a unified, database-authoritative transaction and concurrency architecture that guarantees:
> **Concurrent admission cannot create duplicate active execution.**

---

## 2. Scope & Non-Goals

### In Scope
- Establishing Laws F1–F6 for command-side concurrency boundaries.
- Complete locking and transaction surface audit across surfaces F01–F20 (yielding 3 `ALREADY_COMPLIANT` and 17 `NEEDS_CHANGE` surfaces).
- Establishing `SchedulerService.admit_work_item()` as the SINGULAR canonical fresh-admission entry authority across API, CLI, autonomous intake, and future Stage G scheduler.
- Defining a PostgreSQL 64-bit SHA-256 derived transaction-scoped advisory lock strategy (`pg_advisory_xact_lock(bigint)`) with local lock timeout (`SET LOCAL lock_timeout = '2s'`) for atomic admission serialization covering global (`max_global_jobs = 1`) and project concurrency limits.
- Auditing all nested `uow.commit()` calls in core service call graphs based on canonical code.
- Specifying Pattern A Savepoint Conflict Normalization (`session.begin_nested()`, `session.flush()`, expected constraint filter, savepoint rollback) to guarantee clean transaction recovery on expected unique-constraint collisions.
- Normalizing concurrency conflict exceptions into deterministic domain outcomes (`WAIT`, `NEEDS_HUMAN`, or active run adoption) instead of raw 500 errors.
- Designing a refined bounded transaction retry policy for transient PostgreSQL errors (`40001`, `40P01`, and conditionally `55P03` on coordination paths; maximum 3 total attempts) without duplicating external side effects.
- Formulating a mandatory 15-test PostgreSQL adversarial test suite (T01–T15).

### Non-Goals
- **No Production Code Implementation:** Design and contract specification only. Production code edits are strictly deferred to implementation phase.
- **No Stage G Scheduler/Recovery Redesign:** Scheduler tick loop execution, stale run recovery polling, daemon convergence loops, and restart scanning belong exclusively to Stage G.
- **No Deployment or Service Activation:** `minime-scheduler.service` remains disabled.
- **No Replacement of Valid Stage A–E Locks:** Existing `FOR UPDATE` locks on sagas, budget policy, and provider health are preserved.
- **No Schema DDL Migrations Required:** The concurrency model relies entirely on PostgreSQL native advisory locks, explicit row locking (`FOR UPDATE`), and existing unique indexes.

---

## 3. Preservation of Completed Stages A–E Invariants
Stage F preserves and builds upon all invariants established in prior stages:
- **Stage A (Canonical Lifecycle Authority):** Status transitions (`READY` -> `ADMITTED` -> `RUNNING` -> `COMPLETED`/`FAILED`) remain governed strictly by `LifecycleTransitionAuthority.transition_backlog_item(...)` and `LifecycleTransitionAuthority.transition_change(...)` using atomic CAS (`UPDATE backlog_items ... WHERE status = expected_from_state`). Stage A transition methods persist the lifecycle `Event` in the surrounding transaction without calling `uow.commit()` internally. Concurrency locking re-evaluates canonical state under lock before mutation.
- **Stage B (Fail-Closed External Evidence & Actions):** `OrchestrationExternalActionModel` deterministic action store and reservation rules remain authoritative. `SagaEngine.reserve_action(...)` saves the action and event and commits before external network execution. External side effects MUST NOT occur inside retriable DB loops without prior durable reservation.
- **Stage C (Managed Repository/Runtime Isolation):** Physical workspace isolation and Git worktree bindings are preserved. Concurrent runs MUST NOT claim or share identical workspace paths (`OrchestrationWorktreeOwnershipModel.canonical_worktree_path UNIQUE`).
- **Stage D (Durable Intake & Closure Sagas):** `DurableSagaRepository.get_for_update()` using PostgreSQL `SELECT ... FOR UPDATE` is retained. Partial unique indexes `uq_active_intake_saga` and `uq_active_closure_saga` remain final guards against duplicate active sagas.
- **Stage E (Projection Purity & API CQS):** Read model queries remain side-effect free. Query endpoints NEVER acquire exclusive transaction locks or mutate state.

---

## 4. Transaction Ownership Law
Command execution in Stage F MUST strictly adhere to the following core concurrency laws:

- **F1. Single Concurrency Boundary:** Any command whose correctness depends on durable state MUST (1) acquire concurrency authority, (2) read/re-read state, (3) evaluate decisions, (4) perform authorized mutations, and (5) commit within one defined transaction boundary. Stale pre-lock evaluations may be used for early filtering but SHALL NOT authorize mutation.
- **F2. Database as Final Concurrency Authority:** In-process locks, Python mutexes, single-worker assumptions, or scheduler tick timing SHALL NOT be relied upon for correctness. Correctness MUST hold across independent processes, PostgreSQL sessions, and concurrent API/CLI callers.
- **F3. Explicit & Minimal Lock Scope:** Every lock MUST explicitly state its protected invariant, lock key, acquisition order, release boundary, and timeout behavior. Table locks are prohibited. Locks MUST NOT wait indefinitely; bounded local lock timeouts MUST be configured (`SET LOCAL lock_timeout = '2s'`).
- **F4. Unprotected Side Effect Prohibition:** A transaction that may be automatically retried MUST NOT contain an unprotected external side effect (Git operations, GitHub API calls, LLM dispatches). External effects MUST follow Stage B/D reservation-commit-call patterns.
- **F5. Classified Transaction Retries:** Automatic retry MAY cover explicitly classified PostgreSQL transient errors (`40001` serialization failure, `40P01` deadlock, and conditionally `55P03` lock timeout on coordination paths). Maximum attempt limit is strictly 3 total attempts (attempt 1 initial + max 2 retries). Automatic retries MUST NOT cover generic `57014` query cancellations, policy refusals, budget limits, or authentication errors.
- **F6. Terminal State Inviolability:** Concurrency retries or re-reads MAY transition a command from `RUN` to `WAIT`/denied, but MUST NOT override Stage A lifecycle truth or resurrect terminal states (`COMPLETED`, `CANCELLED`, `FAILED`).

---

## 5. Lock Authority Model & Fresh Admission Entry Point
To enforce process-independent concurrency without deadlocks, `mini me` establishes a singular admission authority and three distinct database lock authorities:

### Singular Fresh Admission Authority
`SchedulerService.admit_work_item()` is the ONLY authorized public fresh-admission entry point for API, CLI, autonomous intake, and future Stage G scheduler calls.
`OrchestrationService` provides an internal transaction primitive `_admit_change_in_transaction(...)` which executes run and event creation without calling `uow.commit()`. If `OrchestrationService.admit_change()` is called directly (e.g. in legacy tests), it MUST delegate through `SchedulerService.admit_work_item()` to prevent bypass of admission locks.

### Database Lock Authorities
1. **Transaction-Scoped Advisory Locks (`pg_advisory_xact_lock(bigint)`):**
   - Used for non-row coordination boundaries such as global admission capacity (`max_global_jobs`) and project admission capacity (`max_concurrent_jobs`).
   - Automatically acquired at transaction start (with `SET LOCAL lock_timeout = '2s'`) and released by PostgreSQL upon transaction commit or rollback.
2. **Explicit Row Locks (`SELECT ... FOR UPDATE`):**
   - Used for existing durable entity instances: `OrchestrationRun`, `DurableSagaModel`, `OpenRouterBudgetPolicyModel`, `ProviderHealthModel`, `JobModel`, and `BacklogItem`.
   - Blocks concurrent transactions from reading or mutating the locked row until transaction commit/rollback.
3. **Database Unique Constraints (Final Invariant Guard):**
   - Unique constraints (`uq_active_orchestration_run`, `uq_active_intake_saga`, `uq_active_closure_saga`, `action_key UNIQUE`, `uq_orchestration_candidate_generation`, `canonical_worktree_path UNIQUE`).
   - Serves as the immutable database safety net enforcing zero-duplication guarantees even if application locking is bypassed. Service layer MUST handle constraint collisions via Pattern A Savepoint Conflict Normalization.

---

## 6. Required Locking / Transaction Surface Matrix (F01–F20)

| Surface ID | Command / Service | Current Mechanism | Protected Invariant | Concurrency Risk | Required Authority | Lock Key / Scope | Retry Classification | DB Constraint Involved | Implementation Classification | Required Test Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| **F01** | `SchedulerService.admit_work_item()` | `evaluate_admission()` reads `list_runs(is_active=True)` without lock | Global concurrency, project concurrency, same-change uniqueness, DoR preconditions | Count-then-insert race allows oversubscribed admission across concurrent transactions | PostgreSQL transaction 64-bit SHA-256 advisory lock + bounded local lock timeout `SET LOCAL lock_timeout = '2s'` | `pg_advisory_xact_lock(bigint)` (Global key + Project SHA-256 key) | Non-retryable on policy refusal; retryable on DB lock timeout/serialization failure | `uq_active_orchestration_run` | `NEEDS_CHANGE` | T01, T02, T03, T04, T05 |
| **F02** | Same-Change Active Run Protection | `OrchestrationRunModel.uq_active_orchestration_run` | Exactly 1 active run per change in same project | Unhandled DB `IntegrityError` on `uq_active_orchestration_run` aborts transaction without deterministic `WAIT` response | PostgreSQL partial unique index + Pattern A Savepoint conflict normalization | Partial index on `(project_id, change_name)` WHERE `is_active=true` | Pattern A Savepoint conflict recovery: re-read active run, return `WAIT`/`CHANGE_ALREADY_ACTIVE` | `uq_active_orchestration_run` | `NEEDS_CHANGE` | T01 |
| **F03** | Project Concurrency Limit (`project.max_concurrent_jobs`) | Unlocked `list_runs` count in `evaluate_admission()` | Active project run count <= `max_concurrent_jobs` | Two transactions observe count < limit and both admit | Transaction 64-bit advisory lock on project namespace | `pg_advisory_xact_lock(project_bigint_key)` | Non-retryable limit refusal; conditionally retryable on `55P03` lock timeout | None (count-based authority) | `NEEDS_CHANGE` | T02, T04 |
| **F04** | Global Concurrency Limit Authority | Unlocked `list_runs` count in `evaluate_admission()` | Active global run count <= `max_global_jobs` (canonical production limit = 1) | Two transactions observe global count < limit and both admit | Transaction 64-bit advisory lock on global namespace | `pg_advisory_xact_lock(global_bigint_key)` | Non-retryable limit refusal; conditionally retryable on `55P03` lock timeout | None (count-based authority) | `NEEDS_CHANGE` | T03 |
| **F05** | `OrchestrationService.admit_change()` → planned internal `_admit_change_in_transaction()` | Current `admit_change()` performs internal `uow.commit()`; Stage F introduces internal no-commit primitive | Atomic run creation, stage event, canonical event, decision record | Split atomic bundle if intermediate commit succeeds but caller fails | Enclosing UoW transaction boundary owned by scheduler admission caller | Enclosing transaction + project/global advisory lock | Non-retryable on business denial | `uq_active_orchestration_run` | `NEEDS_CHANGE` | T05 |
| **F06** | Backlog READY -> ADMITTED Transition | `LifecycleTransitionAuthority.transition_backlog_item()` | Valid lifecycle transition from READY to ADMITTED without stale overwrite | Preserved Stage A CAS (`UPDATE backlog_items ... WHERE status = READY`); needs participation in outer admission transaction | Enclosing admission transaction boundary + Stage A CAS authority | Atomic CAS update on `BacklogItem` status | Non-retryable lifecycle error | Primary key / status check | `NEEDS_CHANGE` | T01, T05 |
| **F07** | ADMITTED -> RUNNING / execution startup | `OrchestrationService.execute()` / pipeline startup | Exactly 1 worker drives execution startup for an admitted run | Two callers drive startup for same admitted run concurrently | `OrchestrationRun` row lock `SELECT ... FOR UPDATE` before stage mutation | `OrchestrationRun` row lock (`run_id`) | Retryable DB conflict; non-retryable if already RUNNING | Primary key | `NEEDS_CHANGE` | T07, T11 |
| **F08** | Saga Resume | `DurableSagaRepository.get_for_update()` | Exactly 1 worker resumes active saga | Preserved: `SELECT ... FOR UPDATE` row locking prevents dual saga resume | PostgreSQL row lock (`FOR UPDATE`) | `DurableSagaModel` row lock (`saga_id`) | Retryable DB conflict | Primary key / partial unique index | `ALREADY_COMPLIANT` | T06 |
| **F09** | Saga Creation Conflict Normalization | Partial unique index `uq_active_intake_saga` / `uq_active_closure_saga` | Max 1 active intake / closure saga per `(project_id, work_item_key)` | Concurrent saga creation raises raw `IntegrityError` aborting transaction | DB partial unique index + Pattern A Savepoint conflict recovery | Partial index `(project_id, work_item_key)` | Pattern A Savepoint rollback; re-read active saga and adopt deterministically | `uq_active_intake_saga`, `uq_active_closure_saga` | `NEEDS_CHANGE` | T07 |
| **F10** | External Action Reservation | `OrchestrationExternalActionModel.action_key` UNIQUE | Exactly 1 reservation per external action key | Concurrent reservation attempt raises un-normalized `IntegrityError` | PostgreSQL unique constraint + Pattern A Savepoint conflict recovery | `action_key UNIQUE` constraint | Pattern A Savepoint rollback; re-read existing action reservation | `OrchestrationExternalActionModel.action_key` | `NEEDS_CHANGE` | T15 |
| **F11** | Budget Reservation Policy Lock | `OpenRouterBudgetPolicy.get_for_update(project_id)` | Budget caps strictly enforced under concurrent reservation | Preserved: `FOR UPDATE` serializes budget reservation requests | PostgreSQL row lock (`FOR UPDATE`) | `OpenRouterBudgetPolicyModel` row lock (`project_id`) | Retryable transient DB conflict | Primary key (`project_id`) | `ALREADY_COMPLIANT` | T08 |
| **F12** | Budget Settlement / Release | `BudgetService.settle()` / `release()` | Atomic settlement / release without over-releasing or duplicate settlement | Concurrent settlement/release causes balance skew | Row lock (`FOR UPDATE`) or atomic status transition | `BudgetReservationModel` row lock (`reservation_id`) | Retryable transient DB conflict | Primary key / status constraint | `NEEDS_CHANGE` | T08 |
| **F13** | Provider Probe Reservation | Provider health probe `FOR UPDATE` row lock in `ProviderHealthService._try_reserve_expensive_probe` | Max 1 active probe per provider window | Preserved: row lock `FOR UPDATE` prevents duplicate expensive probes and commits reservation | PostgreSQL row lock (`FOR UPDATE`) | `ProviderHealthModel` row lock (`provider`) | Retryable transient DB conflict | `ProviderHealthModel.provider UNIQUE` | `ALREADY_COMPLIANT` | T09 |
| **F14** | Provider Health Mutation | `ProviderHealthService.update_health()` | Provider health updates apply in strict chronological order | Stale probe result overwrites newer status update | Compare-and-swap on `updated_at` / row lock `FOR UPDATE` | `ProviderHealthModel` row lock (`provider`) | Retryable transient DB conflict | `ProviderHealthModel.provider UNIQUE` | `NEEDS_CHANGE` | T09 |
| **F15** | Candidate Generation Freeze Race | `uq_orchestration_candidate_generation` on `(run_id, generation)` | Unique generation index per run | Concurrent freeze attempt raises un-normalized `IntegrityError` | PostgreSQL unique constraint + Pattern A Savepoint conflict recovery | `uq_orchestration_candidate_generation` | Pattern A Savepoint rollback; re-read current generation or fail gracefully | `uq_orchestration_candidate_generation` | `NEEDS_CHANGE` | T10 |
| **F16** | Orchestration Stage Transition | `OrchestrationService.transition_stage()` | Stage transition advances monotonically from `current_stage` to target stage | Two workers independently advance run from same initial stage | Row lock `SELECT ... FOR UPDATE` on `OrchestrationRun` or conditional UPDATE | `OrchestrationRun` row lock (`run_id`) | Non-retryable invalid stage transition; retryable DB lock conflict | Primary key | `NEEDS_CHANGE` | T11 |
| **F17** | Job State Transition | `PostgresJobRepository.transition_job_status()` | Job status follows valid state machine transitions | Read-modify-save without lock allows stale overwrite | Row lock `SELECT ... FOR UPDATE` on `JobModel` or `UPDATE ... WHERE status = expected` | `JobModel` row lock (`job_id`) | Non-retryable invalid state transition; retryable DB lock conflict | Primary key | `NEEDS_CHANGE` | T12 |
| **F18** | Resume / Continue Command | `OrchestrationService.resume()` / continuation API | Single worker drives resumption of an active run | Two callers concurrently resume same run | Row lock `SELECT ... FOR UPDATE` on `OrchestrationRun` before resumption logic | `OrchestrationRun` row lock (`run_id`) | Retryable DB conflict | Primary key | `NEEDS_CHANGE` | T06, T11 |
| **F19** | Worktree Ownership Claim | `OrchestrationWorktreeOwnershipModel.canonical_worktree_path` UNIQUE | Unique active workspace claim per worktree path | Concurrent orchestration runs attempt to use same workspace path | DB `canonical_worktree_path UNIQUE` constraint + Pattern A Savepoint recovery | `canonical_worktree_path UNIQUE` constraint | Non-retryable workspace collision; Savepoint rollback | `OrchestrationWorktreeOwnershipModel.canonical_worktree_path` | `NEEDS_CHANGE` | T05 |
| **F20** | Transaction Retry Boundary | Daemon transactional command wrapper | Bounded retry (max 3 total attempts) for transient DB concurrency failures | Retrying transactions with unreserved external side effects | Transaction wrapper with SQLSTATE filtering (`40001`, `40P01`, conditional `55P03`) | Transaction level | Bounded retry (max 3 total attempts) for 40001, 40P01, conditional 55P03; forbidden for 57014 and business refusals | DB transaction isolation | `NEEDS_CHANGE` | T13, T14, T15 |

### Surface Matrix Summary
- **Total Surfaces:** 20
- **ALREADY_COMPLIANT Count:** 3 (F08, F11, F13)
- **NEEDS_CHANGE Count:** 17 (F01, F02, F03, F04, F05, F06, F07, F09, F10, F12, F14, F15, F16, F17, F18, F19, F20)
- **OUT_OF_SCOPE Count:** 0
- **PostgreSQL-Backed Proof Count:** 15 (T01–T15)
- **Schema Migrations Proposed:** 0
- **New Transaction/Locking Primitives Proposed:** `pg_advisory_xact_lock(bigint)` admission serialization, SHA-256 BIGINT key derivation, local lock timeout `SET LOCAL lock_timeout = '2s'`, `TransactionRetryWrapper` with refined SQLSTATE classification, and Savepoint Conflict Normalization (Pattern A).

---

## 7. Required Admission Serialization Design

### Selected Strategy: PostgreSQL 64-Bit SHA-256 Advisory Locks (`pg_advisory_xact_lock(bigint)`)
To serialize fresh admission across independent processes without modifying database schemas, `SchedulerService.admit_work_item()` MUST acquire PostgreSQL transaction-scoped advisory locks using a 64-bit signed integer derived deterministically via SHA-256.

### Key Derivation Scheme (Process-Independent & Cryptographically Collision-Resistant)
Python built-in `hash()` is **FORBIDDEN** because Python randomizes hash seeds per process (`PYTHONHASHSEED`), violating Law F2. Key derivation uses SHA-256 bytes converted deterministically to signed 64-bit BIGINT integers:

```python
import hashlib

def derive_advisory_lock_key(namespace_string: str) -> int:
    """Derive process-independent signed 64-bit integer for pg_advisory_xact_lock(bigint)."""
    digest = hashlib.sha256(namespace_string.encode("utf-8")).digest()
    # Interpret first 8 bytes as big-endian signed 64-bit integer
    return int.from_bytes(digest[:8], byteorder="big", signed=True)

# 1. Global Admission Lock Key (Canonical Namespace):
GLOBAL_ADMISSION_LOCK_KEY = derive_advisory_lock_key("minime:admission:global")

# 2. Project Admission Lock Key (Canonical Project Identity):
def derive_project_admission_lock_key(project_id: str) -> int:
    return derive_advisory_lock_key(f"minime:admission:project:{project_id}")
```

### Global Concurrency Limit Authority
For production command execution, the canonical Stage F global concurrency limit is fixed at `1` (`max_global_jobs = 1`). Constructor parameters in `SchedulerService` serve solely as test-only overrides for non-1 limit testing. No schema migration is required.

### Bounded Advisory Lock Acquisition Timeout
To prevent indefinite lock waiting, every admission transaction MUST configure a local PostgreSQL lock timeout prior to acquiring advisory locks:

```sql
BEGIN;
SET LOCAL lock_timeout = '2s';
SELECT pg_advisory_xact_lock(:global_key);
SELECT pg_advisory_xact_lock(:project_key);
```

If lock acquisition exceeds 2 seconds, PostgreSQL raises SQLSTATE `55P03` (`lock_not_available`), which is caught by the Stage F retry wrapper for bounded transaction retry.

### Lock Duration & Scope
- **Duration:** Held strictly within the single admission database transaction (typically minimal observational duration).
- **Scope:** Covers only:
  `BEGIN` -> `SET LOCAL lock_timeout` -> `Acquire Advisory Locks` -> `Re-read State & Active Counts` -> `Evaluate Policy & Readiness` -> `Persist Atomic Admission Bundle` -> `COMMIT`.
- **Prohibition:** Lock MUST NOT be held during Git worktree cloning, LLM execution, GitHub API calls, or subprocess runs.

---

## 8. Exact Lock Ordering & Deadlock Prevention Strategy
To prevent known lock-order cycles under the Stage F locking protocol, locks MUST always be acquired in strict hierarchical order:

1. **Global Admission Coordination Lock:** `pg_advisory_xact_lock(GLOBAL_ADMISSION_LOCK_KEY)`
2. **Project Admission Coordination Lock:** `pg_advisory_xact_lock(PROJECT_ADMISSION_LOCK_KEY)`
3. **Entity Row Locks (ordered by Primary Key):** `SELECT ... FOR UPDATE` on `ProjectModel`, `BacklogItem`, `OrchestrationRun`.
4. **Database Constraint Invariants:** `uq_active_orchestration_run` verification upon insertion.

Locks auto-release automatically at PostgreSQL transaction termination (commit or rollback). PostgreSQL deadlocks (`40P01`) remain possible in the larger system and are handled by the classified retry engine.

---

## 9. Nested Commit Audit Table & Call-Graph Classification

| Call Graph Path | Internal Commit Found | Classification | Required Architectural Correction |
|---|---|---|---|
| `SchedulerService.admit_work_item()` | `self.uow.commit()` on decision record save | Owns Outer Admission Transaction | Single commit at end of atomic admission bundle persistence. No intermediate commits. |
| `OrchestrationService._admit_change_in_transaction()` | None (internal method) | Participates in Caller Transaction | Creates OrchestrationRun, initial stage Event, and canonical Event; does NOT call `uow.commit()`. |
| `LifecycleTransitionAuthority.transition_backlog_item()` / `transition_change()` | None | Participates in Caller Transaction | Executes status CAS (`UPDATE ... WHERE status = expected`) and saves Event; does NOT call `uow.commit()`. |
| `BudgetService.reserve_budget()` | None | Participates in Caller Transaction | Locks policy `FOR UPDATE`, saves `BudgetReservation` and `Event`; does NOT call `uow.commit()`. Execution runner caller commits before provider dispatch. |
| `ProviderHealthService._try_reserve_expensive_probe()` | `self.uow.commit()` at line 425 | Owns Pre-Effect Probe Reservation Transaction | Locks `ProviderHealthModel` `FOR UPDATE`, updates window counters, calls `uow.commit()` to persist reservation before expensive probe dispatch. |
| `SagaEngine.reserve_action()` | `self.uow.commit()` at line 291 | Owns Pre-Effect Action Reservation Transaction | Saves `OrchestrationExternalAction` and `Event`, calls `uow.commit()` to persist reservation before remote execution. |

---

## 10. Database Constraint Audit & Schema Invariants
All required Stage F invariants map directly to existing constraints in `src/minime/db/models.py` on canonical `main`. **0 DDL schema migrations are required.**

### Canonical Constraint Inventory Verified:
1. `uq_active_orchestration_run`: Partial unique index on `orchestration_runs(project_id, change_name)` WHERE `is_active = true`.
2. `uq_active_intake_saga`: Partial unique index on `durable_sagas(project_id, work_item_key)` WHERE `saga_type = 'INTAKE' AND status IN ('IN_PROGRESS', 'BLOCKED')`.
3. `uq_active_closure_saga`: Partial unique index on `durable_sagas(project_id, work_item_key)` WHERE `saga_type = 'CLOSURE' AND status IN ('IN_PROGRESS', 'BLOCKED')`.
4. `OrchestrationExternalActionModel.action_key`: Unique constraint on `orchestration_external_actions(action_key)`.
5. `uq_orchestration_candidate_generation`: Unique index on `orchestration_candidates(run_id, generation)`.
6. `orchestration_stage_events.transition_key`: Unique index on `orchestration_stage_events(transition_key)`.
7. `ProviderHealthModel.provider`: `id` is Primary Key; `provider` is UNIQUE + indexed on `provider_health(provider)`.
8. `OpenRouterBudgetPolicyModel`: Table `openrouter_budget_policies` with `project_id` Primary Key.
9. `OrchestrationWorktreeOwnershipModel.canonical_worktree_path`: Unique constraint on `orchestration_worktree_ownerships(canonical_worktree_path)`.

---

## 11. Conflict Result Semantics & Pattern A Savepoint Conflict Normalization

After an `IntegrityError`, PostgreSQL aborts the current transaction. Querying within an aborted transaction raises `InFailedSqlTransaction`. The Stage F service layer MUST use Pattern A Savepoint Conflict Normalization to guarantee that the constraint violation materializes INSIDE the savepoint boundary:

### Pattern A Savepoint Conflict Normalization Protocol:
```python
try:
    with uow.session.begin_nested():
        repository.save(entity)
        uow.session.flush()  # GUARANTEES constraint violation occurs INSIDE savepoint!
except IntegrityError as exc:
    if not is_expected_constraint_violation(exc, EXPECTED_CONSTRAINT_NAME):
        raise  # Unexpected IntegrityError is re-raised!
    
    # Savepoint was rolled back by context manager context exit; outer transaction remains CLEAN.
    canonical_winner = repository.re_read_canonical_winner(key)
    return build_normalized_domain_result(canonical_winner)
```

### Mandatory Requirements for Pattern A:
1. Nested `SAVEPOINT` active via `session.begin_nested()`.
2. Conflicting `INSERT`/`UPDATE` issued and explicitly flushed (`session.flush()`) INSIDE savepoint.
3. Expected named unique constraint violation caught.
4. `SAVEPOINT` rolled back automatically on error; outer transaction remains usable.
5. Canonical winner re-read ONLY after savepoint recovery.
6. ONLY the expected constraint collision is normalized; unexpected `IntegrityError` is re-raised.

---

## 12. Transaction Retry Policy & Classification

### Retriable SQLSTATE Classes:
- `40001`: `serialization_failure` (always retryable when command body is retry-safe)
- `40P01`: `deadlock_detected` (always retryable when command body is retry-safe)
- `55P03`: `lock_not_available` (conditionally retryable ONLY when originating from Stage F database coordination/lock acquisition path with `SET LOCAL lock_timeout`)

### Non-Retryable Error Classes (Fails Fast Immediately):
- `57014`: `query_canceled` (EXCLUDED from automatic retry list; represents statement timeouts, administrative cancellations, or process interrupts)
- Unique constraint violations (`23505` `unique_violation` - handled via Pattern A Savepoint recovery, not retried)
- Policy refusals (`NOT_READY`, `CAPACITY_EXHAUSTED`, `LIFECYCLE_BLOCKED`)
- Authentication / misconfiguration errors
- Budget exhaustion / provider unavailable errors

### Bounded Retry Parameters:
- **Maximum Attempt Count:** Exactly 3 total attempts (attempt 1 initial execution + at most 2 retries).
- **Backoff Strategy:** Exponential backoff with random jitter (Attempt 1: initial; Attempt 2: 50ms ± 15ms; Attempt 3: 150ms ± 30ms).
- **Mandatory Retry Steps:** Each retry MUST (1) rollback failed transaction, (2) open clean transaction boundary, (3) reacquire all locks (`SET LOCAL lock_timeout` + advisory locks), (4) re-read all authoritative state, and (5) retain exact command identity.

---

## 13. Isolation Level Decision & Justification
- **Selected Isolation Level:** Default PostgreSQL `READ COMMITTED`.
- **Justification:** `READ COMMITTED` paired with explicit transaction-scoped advisory locks (`pg_advisory_xact_lock(bigint)`), local lock timeouts (`SET LOCAL lock_timeout = '2s'`), and targeted row locks (`SELECT ... FOR UPDATE`) provides absolute, process-independent serialization for concurrency-sensitive operations. Global `SERIALIZABLE` isolation is rejected because it introduces significant query overhead, frequent serialization aborts across non-conflicting read models, and complex application-wide retry logic without providing additional safety beyond explicit advisory locks.

---

## 14. External Side-Effect Retry Boundary & Stage B/D Synchronization
To satisfy Law F4, retriable database transaction blocks MUST NEVER encapsulate unreserved external side effects.

### Concurrency Sequence for Side-Effect Commands:
```text
[Transaction 1: DB Reservation under Lock]
  └─ Acquire Row Lock / Action Store Reservation (SagaEngine.reserve_action)
  └─ Persist Reserved Record (OrchestrationExternalAction) & Event
  └─ Commit Transaction 1
        │
[External Side Effect Execution]
  └─ Perform Remote Call (Git push, GitHub PR creation, LLM API dispatch)
        │
[Transaction 2: State Reconciliation]
  └─ Acquire Row Lock / Re-read Result
  └─ Update Durable Record Status to COMPLETED / FAILED
  └─ Commit Transaction 2
```
If Transaction 1 aborts due to a DB serialization failure, zero external side effects have occurred, making retry completely safe.

---

## 15. Stage G Recovery & Scheduler Boundary
Stage F governs transactional atomicity and concurrency correctness for active command execution. It explicitly delineates boundaries with Stage G:

- **Stage F Ownership:** DB locking, advisory lock schemes, atomic transaction boundaries, conflict normalization, bounded DB retries, and invariant enforcement.
- **Stage G Ownership (Deferred):** Scheduler tick loop timing, process loop scanning, background recovery tasks, stale run detection, worker thread pool scaling, daemon startup routines, and system convergence.

Stage F components MUST remain usable by Stage G recovery routines without introducing scheduler loop dependencies into Stage F primitives.

---

## 16. Migration & Schema Impact Analysis
- **Alembic DB Migrations Required:** 0
- **Schema DDL Changes Required:** None. All required unique constraints and indexes exist in the canonical `main` schema.
- **Runtime Dependencies:** Standard Python standard library `hashlib.sha256` for 64-bit integer key derivation; SQLAlchemy 2.x `with_for_update()` and `pg_advisory_xact_lock()` SQL execution.

---

## 17. PostgreSQL-Backed Test Matrix (T01–T15)

All concurrency claims MUST be verified using real PostgreSQL containers via `pytest`. In-memory UoW tests are insufficient for concurrency proofs.

| Test ID | Test Scenario | Execution Condition | Expected Deterministic Outcome |
|---|---|---|---|
| **T01** | Same-change concurrent admission | Two independent PostgreSQL sessions concurrently invoke `admit_work_item()` for identical change | Exactly 1 active run created. Loser transaction uses Pattern A Savepoint rollback, re-reads active run, receives `CHANGE_ALREADY_ACTIVE` `WAIT` result cleanly. Outer transaction remains usable. No raw `IntegrityError` leak. |
| **T02** | Two changes same project (`max_concurrent_jobs=1`) | Two independent PostgreSQL sessions concurrently admit Change A and Change B for same project | Advisory lock serializes. Exactly 1 run admitted. Second change gets `PROJECT_CONCURRENCY_LIMIT` `WAIT` result. |
| **T03** | Two projects (`max_global_jobs=1`) | Two independent sessions concurrently admit changes across Project 1 and Project 2 using canonical global limit source | Global 64-bit advisory lock serializes. Exactly 1 run admitted globally. Second change gets `GLOBAL_CONCURRENCY_LIMIT` `WAIT` result. |
| **T04** | Project limit > 1 (`max_concurrent_jobs=2`) | Three sessions concurrently admit Change A, B, C for same project | Exactly 2 runs admitted. Third change gets `PROJECT_CONCURRENCY_LIMIT` `WAIT` result. |
| **T05** | Atomic admission bundle failure injection | Failure injected before commit during `admit_work_item()` persistence | Complete rollback. Zero orphan runs, stage events, canonical events, scheduler decision records, or backlog status changes remain. |
| **T06** | Saga resume contention | Two worker processes attempt `resume_saga()` simultaneously on same saga ID | `SELECT ... FOR UPDATE` serializes workers. Saga executes sequentially without state corruption. |
| **T07** | Active saga creation race | Two sessions attempt `start_intake_saga()` for same project/key | `uq_active_intake_saga` constraint enforced. Loser uses Pattern A Savepoint rollback, re-reads active saga, and adopts it cleanly. |
| **T08** | Budget reservation contention | Concurrent callers request budget allocations exceeding project cap | `FOR UPDATE` serializes reservations. Cap is strictly respected; no oversubscription. |
| **T09** | Provider probe reservation contention | Multiple requests trigger provider health check simultaneously | `FOR UPDATE` row lock in `_try_reserve_expensive_probe` ensures exactly 1 network probe executes; others reuse result. |
| **T10** | Candidate generation freeze race | Two sessions contend to freeze same candidate generation `N` | `uq_orchestration_candidate_generation` constraint enforced. Loser uses Pattern A Savepoint rollback and re-reads current generation. |
| **T11** | Concurrent stage transition | Two workers attempt `transition_stage()` from `ADMITTED` to `RUNNING` | Row lock ensures exactly 1 transition succeeds; second worker observes updated stage cleanly. |
| **T12** | Job status stale writer | Two transactions modify `JobModel` from identical initial state | Row lock / conditional update prevents stale writer overwrite. |
| **T13** | Transient DB retry matrix (40001, 40P01, conditional 55P03) | Inject synthetic PostgreSQL `40001` (serialization_failure), `40P01` (deadlock_detected), and Stage F lock-acquisition `55P03` (lock_not_available) | Transaction rolls back, retries via backoff, and succeeds cleanly within 3 total attempts. Generic unrelated `55P03` or `57014` fails fast immediately without retry. |
| **T14** | Non-retryable policy refusal | Invoke `admit_work_item()` on non-READY change | Policy refusal fails fast immediately without entering DB retry loop. |
| **T15** | Retriable side-effect safety | Inject DB serialization error into command with external action | Verifies external side effect is executed strictly outside retriable DB block and never duplicated. |

---

## 18. Implementation Sequence (Phased Roadmap)
Implementation of Stage F shall follow a strict 9-phase sequence once authorized:

1. **Phase 1: Transaction Primitives & Interfaces:** Implement `derive_advisory_lock_key()` using SHA-256 BIGINT conversion and UoW `acquire_advisory_lock()` helper with `SET LOCAL lock_timeout = '2s'`.
2. **Phase 2: Admission Serialization:** Wrap `SchedulerService.admit_work_item()` as singular fresh admission entry point in outer advisory lock boundary and refactor `OrchestrationService._admit_change_in_transaction()` internal method to defer commit.
3. **Phase 3: Savepoint Conflict Recovery Primitives:** Implement Pattern A Savepoint conflict recovery helper (`session.begin_nested()`, `session.flush()`, constraint filter) in `src/minime/db/savepoint.py`.
4. **Phase 4: Orchestration & Run Concurrency:** Implement explicit row locking (`FOR UPDATE`) for run stage transitions and startup execution.
5. **Phase 5: Saga, Action, Budget & Provider Preservation:** Audit and wrap Stage D saga creation, Stage B action reservation, budget settlement, and provider health CAS in Pattern A Savepoint recovery.
6. **Phase 6: Candidate, Job & Stage Concurrency:** Enforce compare-and-swap / row locking on candidate freeze, job status transitions, and stage events.
7. **Phase 7: Retry & Conflict Normalization:** Implement `TransactionRetryWrapper` supporting max 3 total attempts for SQLSTATE `40001`, `40P01`, and conditional `55P03`.
8. **Phase 8: PostgreSQL Adversarial Proving:** Execute PostgreSQL-backed integration test suite T01–T15.
9. **Phase 9: Final Verification & OpenSpec Closure:** Complete evidence verification and OpenSpec artifact sync.

---

## 19. Rollback & Backward Compatibility Strategy
- **Backward Compatibility:** All changes preserve existing service signatures (`admit_work_item()`, `evaluate_admission()`). Advisory locks use isolated SHA-256 BIGINT namespaces (`minime:admission:global`, `minime:admission:project:<id>`), preventing conflicts with external database locks.
- **Rollback Strategy:** If a regression occurs during implementation, disabling advisory lock wrapper calls reverts admission to standard single-transaction behavior without schema changes or data corruption.

---

## 20. Stage F Exit Criteria
Stage F CONTRACT / DESIGN closes when the following criteria are satisfied:
- [x] Problem statement, Laws F1–F6, and scope clearly defined.
- [x] Complete F01–F20 surface matrix audited and classified (3 `ALREADY_COMPLIANT`, 17 `NEEDS_CHANGE`).
- [x] Singular fresh-admission entry authority established (`SchedulerService.admit_work_item()`).
- [x] Process-independent 64-bit SHA-256 PostgreSQL advisory lock admission serialization designed (`pg_advisory_xact_lock(bigint)`).
- [x] Bounded local lock timeout (`SET LOCAL lock_timeout = '2s'`) specified.
- [x] Exact lock ordering defined (Global -> Project -> Entity Rows) to prevent known lock-order cycles under Stage F protocol.
- [x] Nested commit call graphs audited based on canonical code.
- [x] Pattern A Savepoint Conflict Normalization (`session.flush()` inside savepoint) defined for expected unique-constraint collisions.
- [x] Domain-safe conflict result semantics specified (`WAIT`, `NEEDS_HUMAN`, active run adoption).
- [x] Refined transaction retry policy (max 3 total attempts; 40001, 40P01, conditional 55P03; 57014 excluded) defined.
- [x] Side-effect retry boundary specified (Stage B/D synchronization).
- [x] 15 PostgreSQL-backed adversarial tests T01–T15 defined with updated assertions and SQLSTATE proofs.
- [x] 32 finite implementation tasks authored in `tasks.md`.
- [x] OpenSpec proposal, design, tasks, and spec artifacts validated coherent and rebased onto canonical `main` (`fab5a5e2aa8df9fef83552cf04bdfc4a8cc0a342`).
