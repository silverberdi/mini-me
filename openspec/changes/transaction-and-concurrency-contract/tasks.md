# Task Plan: Stage F — Transaction and Concurrency Contract

## Group 1: Transaction Primitives & Locking Interfaces
- [ ] 1.1 Implement process-independent SHA-256 64-bit PostgreSQL advisory lock key generators (`derive_global_admission_lock_key()`, `derive_project_admission_lock_key(project_id)`) using `hashlib.sha256` and `int.from_bytes(digest[:8], byteorder="big", signed=True)` in `src/minime/db/concurrency.py`.
- [ ] 1.2 Implement `UnitOfWork.acquire_advisory_lock(key)` helper executing `SET LOCAL lock_timeout = '2s'` followed by `SELECT pg_advisory_xact_lock(:key)`.
- [ ] 1.3 Implement Pattern A `SavepointConflictNormalization` helper in `src/minime/db/savepoint.py` executing `session.begin_nested()`, `session.flush()`, constraint filter, and savepoint rollback on `IntegrityError`.
- [ ] 1.4 Author unit test suite `tests/test_concurrency_primitives.py` verifying SHA-256 BIGINT key determinism, lock timeout SQL generation, and Savepoint rollback isolation.

## Group 2: Admission Serialization
- [ ] 2.1 Update `SchedulerService.admit_work_item()` as the singular fresh-admission entry authority to set local lock timeout (`SET LOCAL lock_timeout = '2s'`) and acquire global (`max_global_jobs = 1`) and project 64-bit transaction advisory locks prior to `evaluate_admission()` checks (Surface F01, F03, F04).
- [ ] 2.2 Refactor `OrchestrationService` to expose `_admit_change_in_transaction()` internal method that creates run and events without calling `uow.commit()`, and update public `admit_change()` wrapper to delegate through `SchedulerService.admit_work_item()` (Surface F05).
- [ ] 2.3 Align `LifecycleTransitionAuthority.transition_backlog_item()` status CAS (`UPDATE backlog_items ... WHERE status = READY`) to execute inside the enclosing serialized admission transaction boundary without calling `uow.commit()` internally (Surface F06).
- [ ] 2.4 Apply Pattern A Savepoint conflict recovery on `uq_active_orchestration_run` insertion to re-read active run and return `AdmissionDecision.REFUSED` with `CHANGE_ALREADY_ACTIVE` deterministically (Surface F02).

## Group 3: Orchestration & Run Concurrency
- [ ] 3.1 Implement explicit row locking (`SELECT ... FOR UPDATE` on `OrchestrationRun`) in `OrchestrationService.execute()` before driving execution startup from `ADMITTED` to `RUNNING` (Surface F07).
- [ ] 3.2 Implement `SELECT ... FOR UPDATE` row locking on `OrchestrationRun` in `OrchestrationService.resume()` and continuation commands to prevent dual-worker execution (Surface F18).
- [ ] 3.3 Apply Pattern A Savepoint conflict recovery on `OrchestrationWorktreeOwnershipModel.canonical_worktree_path` UNIQUE constraint to prevent concurrent runs from claiming identical workspace paths (Surface F19).
- [ ] 3.4 Add verification check ensuring active worktree bindings are validated under row lock before workspace preflight.

## Group 4: Saga & Action Concurrency Preservation
- [ ] 4.1 Audit `DurableSagaRepository.get_for_update()` and `SagaEngine.resume_saga()` to ensure PostgreSQL `SELECT ... FOR UPDATE` row locking remains unchanged (Surface F08).
- [ ] 4.2 Apply Pattern A Savepoint conflict recovery on `uq_active_intake_saga`/`uq_active_closure_saga` insertions in `SagaEngine` to adopt existing active sagas deterministically (Surface F09).
- [ ] 4.3 Apply Pattern A Savepoint conflict recovery on `OrchestrationExternalActionModel.action_key` UNIQUE constraint in `SagaEngine.reserve_action()` to adopt existing action reservations deterministically (Surface F10).

## Group 5: Budget & Provider Concurrency Preservation
- [ ] 5.1 Audit `OpenRouterBudgetPolicyModel` `FOR UPDATE` row lock in `BudgetService.reserve_budget()` to ensure row lock is preserved without internal `uow.commit()` (Surface F11).
- [ ] 5.2 Implement atomic row locking (`FOR UPDATE`) on `BudgetReservationModel` during `settle()` and `release()` operations in `BudgetService` to prevent balance skew under concurrent calls (Surface F12).
- [ ] 5.3 Audit `ProviderHealthModel` `FOR UPDATE` row lock in `ProviderHealthService._try_reserve_expensive_probe()` to preserve single probe per window and internal commit before dispatch (Surface F13).

## Group 6: Candidate, Job & Stage Concurrency
- [ ] 6.1 Implement compare-and-swap update logic on `ProviderHealthModel.updated_at` in `ProviderHealthService.update_health()` to prevent stale probe overwrite (Surface F14).
- [ ] 6.2 Apply Pattern A Savepoint conflict recovery on `uq_orchestration_candidate_generation` during candidate freeze to prevent generation collision and return normalized conflict verdict (Surface F15).
- [ ] 6.3 Implement row-locked monotonic stage transitions on `OrchestrationRun` in `OrchestrationService.transition_stage()` (Surface F16).
- [ ] 6.4 Implement `SELECT ... FOR UPDATE` row locking on `JobModel` during status transitions in `PostgresJobRepository` (Surface F17).

## Group 7: Retry & Conflict Normalization
- [ ] 7.1 Implement `TransactionRetryWrapper` in `src/minime/db/retry.py` supporting maximum 3 total attempts (attempt 1 + max 2 retries with exponential backoff) for SQLSTATE `40001`, `40P01`, and conditionally `55P03` on coordination paths (Surface F20).
- [ ] 7.2 Configure `TransactionRetryWrapper` to explicitly exclude `57014` (query_canceled), generic unrelated `55P03`, non-retryable business refusals, lifecycle denials, unique constraint violations, and authentication errors.
- [ ] 7.3 Ensure retriable transaction blocks strictly exclude unreserved external side effects (Git pushes, GitHub API calls, LLM dispatches).

## Group 8: PostgreSQL Adversarial Proving
- [ ] 8.1 Create `tests/test_postgres_scheduler_admission_concurrency.py` executing adversarial tests T01 (same-change Savepoint recovery), T02 (project limit), T03 (global limit = 1), and T04 (project limit > 1) against PostgreSQL.
- [ ] 8.2 Create `tests/test_postgres_admission_bundle_atomicity.py` executing test T05 (failure injection rollback during admission bundle persistence).
- [ ] 8.3 Create `tests/test_postgres_orchestration_run_concurrency.py` executing tests T06 (saga resume), T07 (saga creation Savepoint recovery), T10 (candidate generation Savepoint recovery), T11 (stage transition contention), and T12 (job status stale writer).
- [ ] 8.4 Create `tests/test_postgres_policy_concurrency.py` executing tests T08 (budget contention), T09 (provider probe contention), and T15 (external-effect retry safety).
- [ ] 8.5 Create `tests/test_postgres_transaction_retry.py` executing tests T13 (synthetic DB 40001, 40P01, and Stage F 55P03 retry) and T14 (non-retryable business denial / 57014 fast failure).

## Group 9: Final Verification & OpenSpec Governance
- [ ] 9.1 Run full PostgreSQL concurrency test suite and verify 100% pass rate.
- [ ] 9.2 Validate OpenSpec proposal, design, tasks, and delta spec for complete coherence and archive readiness.
