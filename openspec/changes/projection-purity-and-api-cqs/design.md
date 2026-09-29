# Design Document: Stage E — Projection Purity and API CQS

## 1. Problem Statement

Stage A established that `LifecycleTransitionAuthority` is the single writer of `Change.status` and `BacklogItem.status`, and prohibited HTTP GET endpoints from mutating canonical lifecycle states. However, an architectural audit of the mini me codebase reveals that read, query, and projection surfaces still perform significant non-lifecycle durable and external side effects:

1. **HTTP GET `/budget/usage` & GET `/projects/{project_id}/budget`:** Calls `uow.budget_policies.get_for_update(project_id)`, acquiring write-intent `SELECT ... FOR UPDATE` row locks during standard HTTP reads.
2. **HTTP GET `/providers/openrouter/status`:** Also invokes `uow.budget_policies.get_for_update(project_id)`, acquiring write locks during query execution.
3. **HTTP GET `/scheduler/status` (`CapacityLifecycleService.get_scheduler_status()`):** Emits `SCHEDULER_MODE_CHANGED` event records and calls `uow.commit()` when mode changes are observed during query calls.
4. **HTTP GET `/providers/health` (`ProviderHealthService.list_all_health()`):** Calls `get_health()` for missing providers, inserting new `ProviderHealth` rows into PostgreSQL and calling `uow.commit()` on pure reads.
5. **Dashboard Overview (`OperationsDashboardService.get_overview()`):** Transitively invokes `get_scheduler_status()` and `list_all_health()`, causing side-effecting event emissions and DB row insertions during GET `/dashboard` rendering.
6. **Readiness Evaluation (`ReadinessService.evaluate_change_readiness()`):** Saves updated `Change` records, emits `READINESS_EVALUATED` events, records `MetricFact` entries, and executes `uow.commit()` during DoR evaluations.
7. **Backlog Projections (`IntakeService.reconcile_backlog_projections()`):** Returns derived lifecycle-looking states (`WorkItemStatus`) using domain enums without an explicit contract demarcating them as non-canonical display values.

These defects violate Command/Query Separation (CQS), introduce DB locking contention, risk deadlocks on HTTP reads, corrupt operational telemetry with query-triggered side effects, and violate non-mutating query invariants.

---

## 2. Scope & Non-Scope

### Scope
- Defining formal CQS laws and authority separation for mini me.
- Auditing and classifying all 24 finite surfaces (Q01–Q24).
- Eliminating `get_for_update()` / `SELECT ... FOR UPDATE` write-intent locks from query paths.
- Eliminating database inserts, updates, event emissions, and transaction commits from query paths.
- Decomposing mixed evaluation services (e.g. `ReadinessService`) into pure query functions and explicit command methods.
- Defining clear boundaries between canonical domain status and display/projection DTO status.
- Enforcing transitive purity across entire GET call graphs.
- Designing AST static guards and adversarial unit tests to guarantee zero query side effects.

### Non-Scope
- **Stage F Transaction/Concurrency Contract:** Multi-worker concurrent admission, atomic row locking for saga resume, isolation levels, and retry policies are explicitly deferred to Stage F.
- **UI Redesign:** Client-facing response formats and PWA/TUI component structures remain unchanged.
- **Production Code Changes:** This execution is limited strictly to OpenSpec contract and design authoring.

---

## 3. Command/Query Separation (CQS) Definitions

### Query
An operation whose externally observable contract is retrieval or observation.
- **Law:** A query MUST be repeatable without altering PostgreSQL state, filesystem state, Git ref state, or external provider state.
- **Allowed Operations:** Reading PostgreSQL; inspecting filesystem state; observing Git refs (`rev-parse`, `status`, `log`); calling read-only external APIs (GitHub GETs); computing metrics in memory; returning explicit `UNKNOWN` or `UNAVAILABLE` observations.
- **Forbidden Operations:** Acquiring `SELECT ... FOR UPDATE` row locks; inserting, updating, or deleting DB rows; calling `uow.commit()`; emitting events; advancing sagas; reconciling state; reserving external actions; probing LLM providers; writing/modifying files.

### Command
An operation that intentionally requests mutation of durable or external state.
- **Law:** Commands cross explicit governed boundaries and emit audit/event evidence.
- **Allowed Operations:** Executing `LifecycleTransitionAuthority` transitions; admitting work via scheduler; resuming/advancing sagas; persisting budget reservations/settlements; inserting/updating domain records; creating/modifying GitHub issues/PRs; executing provider health probes.
- **Returns:** May return representations/results, but remains a command due to side-effect intent.

### Projection
A derived, disposable representation constructed from canonical authorities.
- **Law:** Projection state MUST be reconstructable from canonical DB authorities at any time and MUST NEVER become an authority for lifecycle, admission, completion, or external action success.

---

## 4. Canonical vs. Projection Authority Model

```
+-----------------------------------------------------------------------+
|                         CANONICAL AUTHORITIES                         |
|  - LifecycleTransitionAuthority (Change.status, BacklogItem.status)   |
|  - DurableSagaModel (Saga state & phase checkpoints)                  |
|  - OrchestrationExternalActionModel (Reserved action state)           |
+-----------------------------------------------------------------------+
                                   |
                                   | (Read-Only Observation)
                                   v
+-----------------------------------------------------------------------+
|                        PROJECTION & DISPLAY LAYER                     |
|  - OperationsDashboardService (Overview & Change Detail DTOs)          |
|  - Backlog Projection (Derived WorkItemStatus display strings)        |
|  - Readiness Evaluation (ReadinessEvaluation DTO)                     |
+-----------------------------------------------------------------------+
                                   |
                                   X (NEVER Write Back / NEVER Resurrect)
                                   v
+-----------------------------------------------------------------------+
|                   FORBIDDEN FEEDBACK MUTATIONS                        |
|  - Projection values MUST NOT mutate Change.status or BacklogItem.status |
|  - Projections MUST NOT resurrect COMPLETED or CANCELLED work         |
+-----------------------------------------------------------------------+
```

---

## 5. Complete Finite Surface Matrix (Q01–Q24)

| Surface ID | Code Path / Surface Name | Current Behavior | Category | Allowed Reads | Forbidden Writes/Effects | Change Required | Required Test Evidence |
|---|---|---|---|---|---|---|---|
| **Q01** | `/health` (`src/minime/api/app.py`) | Executes `db_manager.check_health()` (`SELECT 1`). Pure connectivity check. | QUERY | Read DB connection state. | DB writes, saga advance, event commit, schema repair. | ALREADY_COMPLIANT | HTTP GET `/health` before/after DB snapshot byte-identical, 0 commits. |
| **Q02** | `/status` (`StatusService.get_system_status()`) | Aggregates DB health, project list, recent events, GitHub App config facts. Pure observation. | QUERY | Read DB health, Project, Change, Event tables. | Write-intent locks, DB inserts/updates, event emission. | ALREADY_COMPLIANT | HTTP GET `/status` before/after DB state identical, 0 write locks. |
| **Q03** | `/scheduler/status` (`CapacityLifecycleService.get_scheduler_status()`) | Evaluates active jobs & provider health. Emits `SCHEDULER_MODE_CHANGED` event + `uow.commit()` if mode changes! | MIXED / MUST_SPLIT | Read Jobs, Projects, ProviderHealth. | Event persistence on GET, `uow.commit()`, mode change side-effect emission. | NEEDS_CHANGE | Pure GET `/scheduler/status` emits 0 events, performs 0 DB commits. |
| **Q04** | `/providers/health` (`ProviderHealthService.list_all_health()`) | Lists provider health. If provider row missing in DB, `get_health()` inserts and commits it! | MIXED / MUST_SPLIT | Read existing ProviderHealth rows or return unpersisted defaults. | DB insert on missing health row, `uow.commit()` on GET. | NEEDS_CHANGE | GET `/providers/health` for uninitialized provider does not insert row into DB. |
| **Q05** | `/budget/usage` (`src/minime/api/app.py` / `BudgetService`) | Uses `uow.budget_policies.get_for_update(project_id)` on GET `/budget/usage`! | MIXED / MUST_SPLIT | Read BudgetPolicy, BudgetReservation, BudgetLedger without row locking. | `get_for_update()`, `SELECT ... FOR UPDATE`, write-intent locking on GET. | NEEDS_CHANGE | HTTP GET `/budget/usage` uses standard read (`get_by_project_id`), zero `FOR UPDATE` lock calls. |
| **Q06** | `/providers/openrouter/status` (`src/minime/api/app.py` / `BudgetService`) | Uses `uow.budget_policies.get_for_update(project_id)` on GET `/providers/openrouter/status`! | MIXED / MUST_SPLIT | Read OpenRouter budget policy, headroom, allowed models. | `get_for_update()`, write-intent row locks on GET. | NEEDS_CHANGE | HTTP GET `/providers/openrouter/status` uses non-locking read, zero `FOR UPDATE` calls. |
| **Q07** | Dashboard Overview (`OperationsDashboardService.get_overview()`) | Reads overview. Transitively invokes `get_scheduler_status()` and `list_all_health()`, causing event/row commits! | MIXED / MUST_SPLIT | Read Jobs, Runs, Projects, ProviderHealth, Events, Git HEAD sha. | Transitive event emission, health row insertion, `uow.commit()`. | NEEDS_CHANGE | HTTP GET `/dashboard` overview before/after DB state byte-identical, 0 events, 0 commits. |
| **Q08** | Dashboard Change Detail (`OperationsDashboardService.get_change_detail()`) | Reads change detail DTO. Formats pipeline phases & DTO display states. | PROJECTION | Read Change, Run, Job, Review, Audit, GitHub PR binding. | Mutating canonical Change/Run/Job state, resurrection of terminal work. | ALREADY_COMPLIANT | Projection query returns derived DTO; canonical Change.status unchanged. |
| **Q09** | Backlog Projection (`IntakeService.reconcile_backlog_projections()`) | Projects backlog item status based on runs/archived changes. Does not write DB, but uses lifecycle-like status enums. | PROJECTION | Read BacklogItem, Run, Change, disk archive folders. | Persistence, emitting events, calling `LifecycleTransitionAuthority`, altering readiness. | NEEDS_CHANGE | `reconcile_backlog_projections` performs 0 DB writes, 0 events, 0 LifecycleTransitionAuthority calls. |
| **Q10** | Readiness Evaluation (`ReadinessService.evaluate_change_readiness()`) | Evaluates DoR. If readiness state changed or missing, saves `Change`, `Event`, `MetricFact`, and calls `uow.commit()`! | MIXED / MUST_SPLIT | Read Project, Binding, OpenSpec files, Git identity. | Saving Change, Event, MetricFact on pure evaluation; `uow.commit()`. | NEEDS_CHANGE | Split pure `evaluate_change_readiness_pure` (query) from `evaluate_and_persist_change_readiness` (command). |
| **Q11** | Provider Capacity Views (`ProviderHealthService` & `CapacityLifecycleService`) | Read endpoints for capacity windows & provider health states. | QUERY | Read ProviderHealth, CapacityWindow rows. | Lazy refresh probes on GET, updating TTL, updating health rows on GET. | ALREADY_COMPLIANT | Capacity queries read recorded DB state without firing network probes or updating TTLs. |
| **Q12** | Efficiency Telemetry Views (`EfficiencyTelemetryService`) | `get_efficiency_view()` & `get_project_efficiency_summary()` read metrics facts. | QUERY | Read ProviderEfficiencyMetrics, MetricFact rows. | Recalculating/materializing metrics into DB during GET, updating telemetry rows. | ALREADY_COMPLIANT | Telemetry view queries perform read-only aggregate calculations, zero `save()` or `commit()`. |
| **Q13** | Project GET/List Surfaces (`ProjectService` & `app.py`) | Reads project list and details. | QUERY | Read Project, ProjectBinding, ProjectManagedRepositoryBinding. | Updating `last_seen`, re-verifying binding into DB, updating timestamps. | ALREADY_COMPLIANT | GET `/projects` and GET `/projects/{id}` perform zero DB updates. |
| **Q14** | Change/Run/Job/History Reads (`OrchestrationService` & `app.py`) | Lists/gets runs, jobs, logs, execution history. | QUERY | Read Change, OrchestrationRun, Job, JobLog, Review, Audit. | Auto-reconciling stuck runs, repairing flags, closing runs, emitting events on GET. | ALREADY_COMPLIANT | History/detail GET routes perform 0 DB updates or stage transitions. |
| **Q15** | Control-Plane Read Surfaces (`ControlPlaneService`) | `get_available_actions()` discovers allowed operator actions. | QUERY | Read Run, Project, PreviewSession, Job. | Triggering operator action execution, saga resume, retry, state mutation on read. | ALREADY_COMPLIANT | `get_available_actions()` evaluates action descriptors without side effects. |
| **Q16** | API HTTP Method Contract (FastAPI routes in `app.py`) | All HTTP GET and HEAD routes across FastAPI application. | QUERY | HTTP GET/HEAD requests. | Any state mutation, lock acquisition, external adapter write on GET/HEAD. | NEEDS_CHANGE | AST/Route audit test proves 100% of GET/HEAD routes call only pure query services. |
| **Q17** | Filesystem Observation (`OpenSpecAdapter`, `ManagedWorkspaceGuard`) | Observes OpenSpec directories, tasks.md, proposal.md, design.md, spec.md. | QUERY | `os.path.exists`, `stat`, `is_dir`, `read_text`. | `mkdir`, file write, file deletion, `unlink`, `rename`, `git checkout`. | ALREADY_COMPLIANT | Filesystem read queries use only observational IO, no file creation or deletion. |
| **Q18** | Git Observation (`ManagedWorkspaceGuard`, `GitAdapter`) | Observes git repository identity, HEAD SHA, merge-base. | QUERY | `git rev-parse`, `git status` (read), `git log`, `git diff`, `git merge-base`. | `git fetch` (mutating remote refs), `git checkout`, `git reset`, `git worktree add/remove`. | ALREADY_COMPLIANT | Git observation uses non-mutating sub-commands; remote fetches isolated to commands. |
| **Q19** | GitHub Observation (`GitHubAdapter`) | Validates issue bindings and PR state via HTTP GET. | QUERY | GitHub API GET `/repos/{owner}/{repo}/issues/{id}`, GET `/pulls/{id}`. | POST/PATCH/DELETE API calls, creating issues, PR comments, changing labels. | ALREADY_COMPLIANT | Remote GitHub queries invoke GET endpoints only, zero POST/PATCH adapter calls. |
| **Q20** | Provider Observation (`ProviderAdapter`) | Reads recorded provider health and static configuration. | QUERY | Read ProviderHealth, local adapter config facts. | Executing expensive LLM inference probes on GET, consuming API token quota. | ALREADY_COMPLIANT | Provider queries read persisted health; expensive probes restricted to commands/schedulers. |
| **Q21** | Event/Timeline Projection (`OperationsDashboardService.get_timeline()`) | Reads timeline events for runs and changes. | PROJECTION | Read Event, OrchestrationStageEvent rows. | Event normalization persistence, event emission on read, event log cleanup. | ALREADY_COMPLIANT | Event timeline reads transform Event rows to DTOs in memory, 0 new events emitted. |
| **Q22** | Durable Saga/Read Model Surfaces (`SagaEngine`, `app.py`) | Reads durable saga state and checkpoint history. | QUERY | Read DurableSaga, OrchestrationExternalAction rows. | `get_for_update()`, resuming saga, advancing phase, changing saga status. | ALREADY_COMPLIANT | Saga read APIs return saga DTOs without acquiring `FOR UPDATE` or executing steps. |
| **Q23** | Repository Read Interfaces (`minime.db.repository`) | `get`, `list_all`, `get_by_id`, `find` methods on UoW repositories. | QUERY | SQL `SELECT` queries without locking. | `get_for_update()`, `save()`, `update()`, `delete()`, `commit()`. | NEEDS_CHANGE | Remove/disallow `get_for_update()` calls from all read query modules/services. |
| **Q24** | Nested Query Purity (Transitive call graph analysis) | Entire transitive call graph from FastAPI GET route down to DB/adapters. | QUERY | Transitive read-only operations across all layers. | Any transitive side effect anywhere in call graph. | NEEDS_CHANGE | Static AST guard and adversarial tests verify zero transitive mutations on any GET. |

### Finite Matrix Classification Totals
- **Total Surfaces Audited:** 24
- **ALREADY_COMPLIANT:** 14 (Q01, Q02, Q08, Q11, Q12, Q13, Q14, Q15, Q17, Q18, Q19, Q20, Q21, Q22)
- **NEEDS_CHANGE:** 10 (Q03, Q04, Q05, Q06, Q07, Q09, Q10, Q16, Q23, Q24)
- **OUT_OF_SCOPE:** 0

---

## 6. Query Allowed / Forbidden Effects Matrix

| Category | Allowed Read Effects | Forbidden Query Side Effects |
|---|---|---|
| **Database (PostgreSQL)** | `SELECT` queries, reading rows, joining tables, filtering, sorting. | `INSERT`, `UPDATE`, `DELETE`, `SELECT ... FOR UPDATE`, `get_for_update()`, `uow.commit()`, `session.flush()`. |
| **Events & Auditing** | Reading historical `Event` rows, counting events. | `events.save()`, emitting `SCHEDULER_MODE_CHANGED`, `READINESS_EVALUATED`, or audit events on GET. |
| **Metrics & Telemetry** | Reading `MetricFact` rows, computing averages in memory. | `metrics.save()`, materializing telemetry snapshots to DB on GET. |
| **Sagas & Intake** | Reading `DurableSaga` status, inspecting phase checkpoints. | Advancing saga phase, calling `start_saga()`, reserving `OrchestrationExternalAction` records. |
| **Lifecycle Authority** | Observing `Change.status` or `BacklogItem.status`. | Calling `LifecycleTransitionAuthority`, altering readiness state, resurrecting terminal work. |
| **Filesystem** | `os.path.exists`, `stat`, `is_dir`, `read_text`. | `mkdir`, file write, file deletion, `unlink`, `rename`, archiving files. |
| **Git Operations** | `git rev-parse`, `git status`, `git log`, `git diff`, `git merge-base`. | `git fetch`, `git checkout`, `git reset`, `git branch`, `git worktree add/remove`. |
| **External Providers** | Reading persisted `ProviderHealth` rows, checking static config. | Executing LLM inference probes, consuming token quota, updating capacity windows on read. |

---

## 7. Command/Query Split Decisions

### Split 1: Readiness Evaluation (`ReadinessService`)
- **Query (Pure):** `ReadinessService.evaluate_change_readiness_pure(project_id, change_name, project_root)`
  - Computes all DoR criteria, verifies artifacts, checks schema.
  - Returns `ReadinessEvaluation` DTO.
  - Performs **zero** database writes, emits **zero** events, executes **zero** commits.
  - Used by: HTTP GET routes, dashboard status views, read-only readiness probes.
- **Command (Mutating):** `ReadinessService.evaluate_and_persist_change_readiness(project_id, change_name, project_root)`
  - Invokes `evaluate_change_readiness_pure`.
  - Saves updated `Change` record, emits `READINESS_EVALUATED` event, saves `MetricFact`, and calls `uow.commit()`.
  - Used by: Intake preparation commands, background scheduler ticks, explicit operator refresh commands.

### Split 2: Provider Health (`ProviderHealthService`)
- **Query (Pure):** `ProviderHealthService.list_existing_health()` / `get_existing_health()`
  - Reads existing `ProviderHealth` rows from PostgreSQL.
  - For uninitialized providers, returns an in-memory `ProviderHealth` DTO with `status=AVAILABLE` or `UNKNOWN` without calling `save()` or `commit()`.
  - Used by: HTTP GET `/providers/health`, GET `/dashboard` overview.
- **Command (Mutating):** `ProviderHealthService.probe_and_update_provider_health(provider)`
  - Dispatches health probe, records result, updates `ProviderHealth` row in DB, emits event, and commits transaction.
  - Used by: Scheduler probe ticks, operator force-probe commands.

### Split 3: Scheduler Status (`CapacityLifecycleService`)
- **Query (Pure):** `CapacityLifecycleService.get_scheduler_status_pure(project_id=None)`
  - Evaluates current scheduler mode and capacity availability in memory.
  - Returns `SchedulerStatus` DTO.
  - Does **not** check `self._last_mode`, emits **zero** `SCHEDULER_MODE_CHANGED` events, calls **zero** `uow.commit()`.
  - Used by: HTTP GET `/scheduler/status`, GET `/dashboard` overview.
- **Command (Mutating):** `CapacityLifecycleService.evaluate_and_record_scheduler_mode_change(project_id=None)`
  - Evaluates mode; if `_last_mode` changed, saves `SCHEDULER_MODE_CHANGED` event to PostgreSQL and calls `uow.commit()`.
  - Used by: Scheduler daemon loop ticks.

---

## 8. Current Confirmed Violations & Remediation Plan

1. **GET `/budget/usage` `get_for_update()` Usage:**
   - *Current Code:* `app.py:477` calls `policy = uow.budget_policies.get_for_update(project_id)`.
   - *Fix:* Replace with non-locking `uow.budget_policies.get_by_project_id(project_id)`.
2. **GET `/providers/openrouter/status` `get_for_update()` Usage:**
   - *Current Code:* `app.py:509` calls `policy = uow.budget_policies.get_for_update(project_id)`.
   - *Fix:* Replace with non-locking `uow.budget_policies.get_by_project_id(project_id)`.
3. **GET `/scheduler/status` Mode Event Emission & Commit:**
   - *Current Code:* `CapacityLifecycleService:104-117` saves event and commits transaction.
   - *Fix:* Update HTTP GET route to use `get_scheduler_status_pure()`.
4. **GET `/providers/health` Lazy Row Insertion & Commit:**
   - *Current Code:* `ProviderHealthService:88-89` saves default health and commits transaction if row missing.
   - *Fix:* Update `list_all_health()` to return in-memory DTOs for missing records without saving/committing.
5. **GET `/dashboard` Transitive Mutation:**
   - *Current Code:* `OperationsDashboardService:358,362` calls `cap_service.get_scheduler_status()` and `health_service.list_all_health()`.
   - *Fix:* Update dashboard overview to call pure query variants (`get_scheduler_status_pure()`, `list_existing_health()`).
6. **Readiness Evaluation Auto-Persistence on Read:**
   - *Current Code:* `ReadinessService:484,512,523` saves `Change`, `Event`, `MetricFact`, and commits transaction during DoR evaluation.
   - *Fix:* Split into `evaluate_change_readiness_pure()` and `evaluate_and_persist_change_readiness()`.

---

## 9. Transaction Boundary & Stage F Deferral

Stage E defines **semantic CQS boundaries only**:
- Queries must never intentionally request write locks (`SELECT ... FOR UPDATE`).
- Queries must never issue mutating DML or commit transactions.
- Queries execute within standard read-only transaction semantics.

**Stage F Deferral Notice:**
The following concurrency and transaction mechanics belong strictly to **Stage F — transaction-and-concurrency-contract** and MUST NOT be implemented in Stage E:
- Advisory locks (`pg_advisory_lock`);
- Multi-worker concurrent admission race prevention;
- Deadlock detection and automatic transaction retry loops;
- Isolation level tuning (`SERIALIZABLE` / `REPEATABLE READ`);
- Saga resume row-locking idempotency (`SELECT ... FOR UPDATE` inside `SagaEngine.resume_saga`).

---

## 10. Migration & Data Impact Assessment

- **Database Schema Impact:** None. No Alembic schema migrations are required for Stage E. Existing PostgreSQL tables (`durable_sagas`, `orchestration_external_actions`, `changes`, `provider_health`, `events`, `metrics`) remain unchanged.
- **Data Preservation:** Zero data migration required. Existing records in PostgreSQL are preserved as-is.
- **Backwards Compatibility:** API contracts, JSON responses, and HTTP status codes remain 100% backwards-compatible.

---

## 11. Query Failure Semantics

When a query encounters an unobservable, degraded, or missing dependency:
1. **Database Connection Unavailable:** Return HTTP 503 Service Unavailable with `{"status": "degraded", "database": {"healthy": false}}`. Do not attempt schema repair or connection retry loops.
2. **Missing Repository / Filesystem:** Return `is_runtime_isolated = False` with diagnostic detail. Do not attempt `mkdir` or `git checkout`.
3. **Remote Provider / GitHub Error:** Mark check as failed or `UNKNOWN`. Do not create dummy issues or mutate bindings.
4. **Stale Information:** Report `stale = True` or `evaluated_at` timestamp. Do not trigger automatic background refresh during GET.

---

## 12. Test Matrix

### 1. HTTP Query Purity Test Suite (`test_api_cqs_purity.py`)
- Capture full database snapshot (row count & field values across all tables) before executing HTTP GET.
- Invoke GET `/health`, `/status`, `/scheduler/status`, `/providers/health`, `/budget/usage`, `/providers/openrouter/status`, `/dashboard`, `/projects`.
- Assert before and after database snapshots are byte-for-byte and field-for-field identical.
- Assert 0 database commits and 0 event emissions occurred.

### 2. Lock Inspection Test Suite (`test_no_query_write_locks.py`)
- Instrument SQLAlchemy session / Unit of Work to intercept `get_for_update()` and `SELECT ... FOR UPDATE` calls.
- Execute all FastAPI GET routes.
- Assert 0 write-intent lock calls occurred, specifically verifying `/budget/usage` and `/providers/openrouter/status`.

### 3. Service Decomposition Test Suite (`test_readiness_cqs_split.py`)
- Invoke `ReadinessService.evaluate_change_readiness_pure()`.
- Assert DoR result is calculated accurately.
- Assert `uow.changes.save`, `uow.events.save`, `uow.metrics.save`, and `uow.commit` were invoked **0 times**.
- Invoke `ReadinessService.evaluate_and_persist_change_readiness()`.
- Assert `Change`, `Event`, `MetricFact` records are persisted and `uow.commit` is called **1 time**.

### 4. Projection Non-Resurrection Test Suite (`test_projection_non_resurrection.py`)
- Set `Change.status = DONE` or `BacklogItem.status = COMPLETED`.
- Execute `IntakeService.reconcile_backlog_projections()` and `OperationsDashboardService.get_overview()`.
- Assert canonical DB statuses remain `DONE` and `COMPLETED`.
- Assert 0 `LifecycleTransitionAuthority` calls occurred.

### 5. AST Static Guard (`test_cqs_ast_guards.py`)
- Inspect FastAPI GET route handlers and designated query services (`StatusService`, `OperationsDashboardService`, pure query methods).
- Assert forbidden symbols (`get_for_update`, `SELECT FOR UPDATE`, `uow.commit`, `events.save`, `LifecycleTransitionAuthority.transition`) do not exist in GET call paths.

---

## 13. Implementation Sequence

1. **Phase 1: Query Locking Removal:** Remove `get_for_update()` from GET `/budget/usage` and GET `/providers/openrouter/status` in `src/minime/api/app.py`.
2. **Phase 2: Service Decomposition:** Split `CapacityLifecycleService`, `ProviderHealthService`, and `ReadinessService` into pure query methods and explicit command methods.
3. **Phase 3: Dashboard & API Purity Alignment:** Update `OperationsDashboardService` and `app.py` GET routes to use pure query service methods.
4. **Phase 4: Projection Boundary Safeguards:** Update `IntakeService.reconcile_backlog_projections()` to explicitly isolate derived display states from canonical DB state.
5. **Phase 5: Automated Verification & AST Guards:** Implement `test_api_cqs_purity.py`, `test_no_query_write_locks.py`, and AST static guard suite.

---

## 14. Rollback & Compatibility Considerations

- **Rollback Safety:** If Stage E changes are reverted, system reverts to previous behavior where GET requests may acquire write locks or lazily insert health rows. No database schema migration rollback is required.
- **API Compatibility:** All JSON response payloads retain existing schema keys. Frontends (PWA / TUI) observe zero breaking changes.

---

## 15. Exit Criteria

Stage E implementation is complete only when all criteria are satisfied:
1. Every HTTP GET and HEAD endpoint across FastAPI is proven 100% side-effect-free.
2. `get_for_update()` / `SELECT ... FOR UPDATE` write locks are completely removed from GET `/budget/usage` and GET `/providers/openrouter/status`.
3. GET `/scheduler/status` emits 0 events and executes 0 commits.
4. GET `/providers/health` inserts 0 DB rows and executes 0 commits for missing providers.
5. GET `/dashboard` overview is transitively pure, causing zero DB writes or event emissions.
6. `ReadinessService` is cleanly split into `evaluate_change_readiness_pure` (query) and `evaluate_and_persist_change_readiness` (command).
7. Projection status values never feed back into canonical persistence or resurrect terminal work.
8. AST static guards and adversarial test suites pass cleanly.
9. All Stage A, B, C, D architectural invariants remain intact.
10. Stage F concurrency concerns remain explicitly un-implemented.
