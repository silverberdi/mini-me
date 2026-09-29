# Tasks: Stage E — Projection Purity and API CQS

## 1. CQS Contracts & Interfaces

- [ ] **Task 1.1: Define CQS Purity Contracts and Interfaces**
  - Define formal CQS query purity guidelines and interface contracts in `src/minime/domain/interfaces.py`.
  - Document that query methods MUST NOT insert/update DB rows, emit events, acquire write locks, or call `uow.commit()`.
  - *Verification Evidence:* Code review & type annotations in `interfaces.py`.

- [ ] **Task 1.2: Establish Explicit Projection DTO Status Boundaries**
  - Define explicit projection status DTO structures in `src/minime/domain/models.py` and `src/minime/services/dashboard_service.py`.
  - Ensure display/projection status values are clearly demarcated from canonical `ChangeStatus` and `WorkItemStatus`.
  - *Verification Evidence:* Unit test verifying projection DTOs do not serialize back into canonical DB domain models.

---

## 2. Repository Read Semantics & Locking Removal

- [ ] **Task 2.1: Audit Repository Read Methods for Zero Lock Usage**
  - Audit `src/minime/db/repository.py` to ensure all `get`, `list`, `find`, and read-model methods execute standard `SELECT` queries without locking.
  - Verify `get_for_update()` is restricted exclusively to governed command paths (e.g. saga engine).
  - *Verification Evidence:* Unit test inspecting repository read query execution.

- [ ] **Task 2.2: Remove Write Lock from GET `/budget/usage` Route**
  - Modify `@app.get("/budget/usage")` and `@app.get("/projects/{project_id}/budget")` in `src/minime/api/app.py`.
  - Replace `uow.budget_policies.get_for_update(project_id)` with non-locking `uow.budget_policies.get_by_project_id(project_id)`.
  - *Verification Evidence:* Instrument session to verify zero `SELECT ... FOR UPDATE` calls on GET `/budget/usage`.

- [ ] **Task 2.3: Remove Write Lock from GET `/providers/openrouter/status` Route**
  - Modify `@app.get("/providers/openrouter/status")` in `src/minime/api/app.py`.
  - Replace `uow.budget_policies.get_for_update(project_id)` with non-locking `uow.budget_policies.get_by_project_id(project_id)`.
  - *Verification Evidence:* Instrument session to verify zero `SELECT ... FOR UPDATE` calls on GET `/providers/openrouter/status`.

---

## 3. Mixed Service Decomposition

- [ ] **Task 3.1: Decompose ReadinessService into Pure Query and Command Variants**
  - Refactor `ReadinessService` in `src/minime/services/readiness_service.py`.
  - Create `evaluate_change_readiness_pure()` for side-effect-free DoR calculation returning `ReadinessEvaluation` DTO with 0 DB writes or events.
  - Create `evaluate_and_persist_change_readiness()` command method that explicitly saves `Change`, emits `READINESS_EVALUATED`, and commits.
  - *Verification Evidence:* Unit test in `tests/test_readiness_cqs_split.py` proving `evaluate_change_readiness_pure` invokes 0 DB saves or commits.

- [ ] **Task 3.2: Make ProviderHealthService Health Listing Side-Effect-Free**
  - Refactor `ProviderHealthService.list_all_health()` in `src/minime/services/provider_health_service.py`.
  - Ensure querying health for an uninitialized provider returns an in-memory `ProviderHealth` DTO without calling `uow.provider_health.save()` or `uow.commit()`.
  - *Verification Evidence:* Unit test verifying querying uninitialized provider health leaves DB row count unchanged.

- [ ] **Task 3.3: Decompose CapacityLifecycleService Scheduler Status Evaluation**
  - Refactor `CapacityLifecycleService.get_scheduler_status()` in `src/minime/services/capacity_lifecycle_service.py`.
  - Create `get_scheduler_status_pure()` which evaluates mode in memory without checking `_last_mode`, emitting `SCHEDULER_MODE_CHANGED` events, or committing.
  - Retain `evaluate_and_record_scheduler_mode_change()` command for the background scheduler loop.
  - *Verification Evidence:* Unit test proving `get_scheduler_status_pure` emits 0 events and calls `uow.commit()` 0 times.

---

## 4. API GET Purity & Endpoint Audit

- [ ] **Task 4.1: Audit and Align GET `/health` Endpoint**
  - Verify `@app.api_route("/health")` in `src/minime/api/app.py` executes only `db_manager.check_health()`.
  - Ensure DB connectivity check executes zero schema repair or record mutations.
  - *Verification Evidence:* Integration test verifying HTTP GET `/health` before/after DB snapshot is identical.

- [ ] **Task 4.2: Align GET `/scheduler/status` Endpoint to Pure Query**
  - Update `@app.get("/scheduler/status")` in `src/minime/api/app.py` to invoke `CapacityLifecycleService.get_scheduler_status_pure()`.
  - *Verification Evidence:* HTTP test verifying GET `/scheduler/status` emits 0 events.

- [ ] **Task 4.3: Align GET `/providers/health` Endpoint to Pure Query**
  - Update `@app.get("/providers/health")` in `src/minime/api/app.py` to invoke pure provider health listing.
  - *Verification Evidence:* HTTP test verifying GET `/providers/health` performs zero DB inserts.

- [ ] **Task 4.4: Audit Project Read Endpoints for Query Purity**
  - Audit GET `/projects`, GET `/projects/{project_id}`, and project diagnostic endpoints in `src/minime/api/app.py`.
  - Ensure project read routes execute zero updates to `last_seen` or binding tables.
  - *Verification Evidence:* HTTP test verifying GET `/projects` executes 0 DB updates.

- [ ] **Task 4.5: Audit Orchestration Run & History Read Endpoints**
  - Audit GET `/orchestration/runs`, GET `/jobs`, and log/history endpoints in `src/minime/api/app.py`.
  - Ensure run/job detail queries execute zero auto-reconciliation or status mutations on GET.
  - *Verification Evidence:* HTTP test verifying GET `/orchestration/runs` executes 0 DB updates.

---

## 5. Dashboard & Read-Model Projection Purity

- [ ] **Task 5.1: Align OperationsDashboardService Overview to Pure Query Services**
  - Refactor `OperationsDashboardService.get_overview()` in `src/minime/services/dashboard_service.py`.
  - Replace calls to mutating service helpers with pure query variants (`get_scheduler_status_pure()`, `list_existing_health()`).
  - *Verification Evidence:* Unit test verifying `get_overview()` executes 0 DB commits and emits 0 events.

- [ ] **Task 5.2: Audit OperationsDashboardService Detail Projection for Purity**
  - Audit `OperationsDashboardService.get_change_detail()` and nested DTO formatters.
  - Ensure candidate history, check items, review/audit summaries, and timeline events are constructed purely in memory.
  - *Verification Evidence:* Unit test verifying `get_change_detail()` leaves canonical DB state untouched.

- [ ] **Task 5.3: Ensure Backlog Projection Purity in IntakeService**
  - Refactor `IntakeService.reconcile_backlog_projections()` in `src/minime/services/intake_service.py`.
  - Guarantee that backlog item projection returns in-memory DTOs without writing DB rows, emitting lifecycle events, or calling `LifecycleTransitionAuthority`.
  - *Verification Evidence:* Unit test in `test_projection_non_resurrection.py` proving `reconcile_backlog_projections()` performs 0 DB writes.

---

## 6. External Observation Purity (Filesystem, Git, GitHub, Providers)

- [ ] **Task 6.1: Enforce Read-Only Filesystem Inspection in OpenSpec Adapter**
  - Audit `OpenSpecAdapter.evaluate_artifacts()` and file helpers.
  - Ensure artifact evaluation uses only read-only filesystem calls (`os.path.exists`, `stat`, `read_text`).
  - *Verification Evidence:* Mock filesystem test asserting 0 file write or deletion calls during artifact evaluation.

- [ ] **Task 6.2: Enforce Observational Git Commands in Workspace Guard & Git Adapter**
  - Audit `ManagedWorkspaceGuard` and `GitAdapter` observational helpers.
  - Ensure Git queries execute only non-mutating sub-commands (`git rev-parse`, `git status`, `git merge-base`) and zero mutating sub-commands (`git fetch`, `git checkout`).
  - *Verification Evidence:* Unit test verifying Git query helpers invoke only observational git sub-commands.

- [ ] **Task 6.3: Enforce Read-Only API Calls in GitHub Adapter Query Paths**
  - Audit GitHub issue/PR verification methods called from query paths.
  - Ensure query paths invoke only GitHub HTTP GET endpoints and zero POST/PATCH/DELETE endpoints.
  - *Verification Evidence:* Mock adapter test asserting zero POST/PATCH calls during readiness/status checks.

- [ ] **Task 6.4: Enforce Read-Only Provider Observation**
  - Audit provider observation helpers in `ProviderHealthService` and capacity views.
  - Ensure display queries read persisted DB records without dispatching expensive LLM inference probes or updating capacity TTLs.
  - *Verification Evidence:* Mock provider adapter test asserting 0 inference probes fired during health queries.

---

## 7. Adversarial Test Suite

- [ ] **Task 7.1: Implement HTTP Query Purity Integration Test Suite**
  - Create `tests/test_api_cqs_purity.py`.
  - Capture DB row snapshots before/after calling all FastAPI GET routes (`/health`, `/status`, `/scheduler/status`, `/providers/health`, `/budget/usage`, `/providers/openrouter/status`, `/dashboard`, `/projects`).
  - Assert DB snapshots are field-for-field identical and 0 commits occurred.
  - *Verification Evidence:* Test execution output showing 100% pass for GET purity tests.

- [ ] **Task 7.2: Implement Write-Lock Inspection Test Suite**
  - Create `tests/test_no_query_write_locks.py`.
  - Instrument SQLAlchemy session / UoW to assert zero `get_for_update()` or `SELECT ... FOR UPDATE` calls during any GET endpoint execution.
  - *Verification Evidence:* Test execution output showing 0 write locks across all GET routes.

- [ ] **Task 7.3: Implement Projection Non-Resurrection & Service Split Tests**
  - Create `tests/test_readiness_cqs_split.py` and `tests/test_projection_non_resurrection.py`.
  - Test pure vs command readiness methods, and verify backlog/dashboard projections never alter terminal `Change.status` or `BacklogItem.status`.
  - *Verification Evidence:* Test execution output showing 100% pass for projection non-resurrection.

---

## 8. AST Static Guards & Final Verification

- [ ] **Task 8.1: Implement AST Static Guard Test Suite**
  - Create `tests/test_cqs_ast_guards.py`.
  - Parse AST of FastAPI GET route functions and designated query modules (`status_service.py`, `dashboard_service.py`, pure query helpers).
  - Assert forbidden write/lock function calls do not exist in query AST nodes.
  - *Verification Evidence:* AST static guard test passing cleanly.

- [ ] **Task 8.2: Execute Final OpenSpec Validation and Change Contract Sign-Off**
  - Run `openspec validate projection-purity-and-api-cqs`.
  - Verify proposal, design, tasks, and delta specs are fully coherent and aligned.
  - Verify working tree is clean.
  - *Verification Evidence:* `openspec validate` output returning PASS.
