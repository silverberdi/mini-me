# Tasks: Durable Intake and Closure Sagas

## Implementation Sequence

### 1. Persistence Models & Alembic Migration
- [ ] 1.1 Define `DurableSagaModel` (`durable_sagas`) in `src/minime/db/models.py` with attributes (`id`, `saga_type`, `project_id`, `work_item_key`, `change_name`, `run_id`, `job_id`, `generation`, `current_phase`, `status`, `last_observed_outcome`, `blocking_reason`, `evidence_references`, `created_at`, `updated_at`) and partial unique indexes `uq_active_intake_saga` and `uq_active_closure_saga`.
- [ ] 1.2 Define `SagaActionModel` (`saga_actions`) in `src/minime/db/models.py` with attributes (`id`, `saga_id`, `action_key`, `action_type`, `target_identity`, `request_fingerprint`, `attempt_number`, `execution_state`, `observed_result_identity`, `result_payload`, `error_message`, `reserved_at`, `reconciled_at`, `created_at`, `updated_at`).
- [ ] 1.3 Add `SQLAlchemyDurableSagaRepository` and `SQLAlchemySagaActionRepository` interfaces to `src/minime/db/repository.py` and register them on `PersistenceUnitOfWork` in `src/minime/domain/interfaces.py`.
- [ ] 1.4 Generate Alembic migration script `alembic/versions/*_add_durable_sagas_and_actions.py` creating `durable_sagas` and `saga_actions` tables and indexes.

### 2. Generic Saga Engine & Reconciliation Authority
- [ ] 2.1 Create `SagaEngine` in `src/minime/services/saga_engine.py` to manage saga lifecycle transitions (`start_saga`, `advance_phase`, `block_saga`, `complete_saga`, `fail_saga`).
- [ ] 2.2 Implement pre-execution action reservation logic (`reserve_action`) enforcing status `REQUESTED` and committing DB transaction BEFORE external adapter execution.
- [ ] 2.3 Implement `ReconciliationAuthority` in `src/minime/services/reconciliation_authority.py` with `reconcile_action_before_retry()` checking remote/external targets via adapter query functions before re-executing mutations.
- [ ] 2.4 Implement action result persistence (`record_action_result`) updating action execution state (`SUCCESS`, `FAILURE`, `AMBIGUOUS`) and evidence references.

### 3. Intake Saga Conversion
- [ ] 3.1 Refactor `IntakeService.create_work_item()` and `prepare_work_item()` in `src/minime/services/intake_service.py` to instantiate and drive `INTAKE` durable saga.
- [ ] 3.2 Implement `INTAKE_CREATED` and `CONTEXT_CHECKED` saga phases in `IntakeService`.
- [ ] 3.3 Implement `OPENSPEC_AUTHORED` saga phase with action reservation before disk writing.
- [ ] 3.4 Implement `ISSUE_BOUND` saga phase with action reservation before `GitHubAdapter.create_issue()` and remote reconciliation via issue search on retry.
- [ ] 3.5 Implement `PROJECT_ITEM_BOUND` saga phase with action reservation before `GitHubAdapter.add_issue_to_project()` and remote reconciliation on retry.
- [ ] 3.6 Implement `READINESS_EVALUATED` and `READY` saga phases, updating `BacklogItem.status` via `LifecycleTransitionAuthority` upon DoR verification.
- [ ] 3.7 Verify handoff boundary from `IntakeService` to `SchedulerService.admit_work_item()` operates strictly from `READY` saga checkpoint.

### 4. Closure Saga Conversion
- [ ] 4.1 Refactor `PostMergeReconciliationService.reconcile_post_merge()` in `src/minime/services/post_merge_service.py` to instantiate and drive `CLOSURE` durable saga.
- [ ] 4.2 Implement `MERGE_OBSERVED`, `ANCESTRY_VERIFIED`, and `RUN_JOB_RECONCILED` saga phases with PR merge observation evidence.
- [ ] 4.3 Implement `ISSUE_CLOSED` saga phase with action reservation before `GitHubAdapter.close_issue()` and remote issue status reconciliation on retry.
- [ ] 4.4 Implement `PROJECT_ITEM_DONE` saga phase with action reservation before `GitHubAdapter.update_project_item_status()` and status reconciliation on retry.
- [ ] 4.5 Implement `SPEC_SYNCED` and `SYNC_VERIFIED` saga phases with action reservation before `OpenSpecSyncService.sync_change_specs()` and verification check.
- [ ] 4.6 Implement `SPEC_ARCHIVED` and `ARCHIVE_VERIFIED` saga phases with action reservation before `OpenSpecSyncService.archive_change()` and filesystem destination reconciliation on retry.
- [ ] 4.7 Implement `WORKTREE_CLEANED`, `BRANCH_CLEANED`, and `LOCKS_RELEASED` saga phases with action reservation and postcondition verification.
- [ ] 4.8 Implement `FINAL_CLOSED` saga phase triggering `LifecycleTransitionAuthority.transition_change()` to `DONE` and `transition_backlog_item()` to `COMPLETED` ONLY when all 12 closure phases are durably proven complete.

### 5. Restart Recovery & Control-Plane Integration
- [ ] 5.1 Update `RestartRecoveryService.reconcile_on_startup()` in `src/minime/services/restart_recovery_service.py` to query `durable_sagas` for `IN_PROGRESS` or `BLOCKED` sagas and invoke `SagaEngine.resume_saga()`.
- [ ] 5.2 Implement terminal identity protection check in `RestartRecoveryService` preventing re-execution of completed/cancelled changes or backlog items.
- [ ] 5.3 Integrate `ControlPlaneService` in `src/minime/services/control_plane_service.py` with `resume_saga()` endpoint allowing manual operator trigger.

### 6. Observability & Audit Events
- [ ] 6.1 Register new `EventType` enums (`DURABLE_SAGA_STARTED`, `DURABLE_SAGA_PHASE_ADVANCED`, `DURABLE_SAGA_ACTION_RESERVED`, `DURABLE_SAGA_ACTION_RECONCILED`, `DURABLE_SAGA_BLOCKED`, `DURABLE_SAGA_COMPLETED`, `DURABLE_SAGA_FAILED`) in `src/minime/domain/enums.py`.
- [ ] 6.2 Emit atomic event records in PostgreSQL transaction during saga phase transitions and action reservations.

### 7. Targeted Adversarial Tests & Verification
- [ ] 7.1 Implement unit and integration tests in `tests/test_durable_sagas.py` covering all 17 targeted verification scenarios (intake restart at every phase, closure restart at every phase, duplicate issue/project item prevention, reconciliation adoption, fail-closed unobservable state, terminal identity protection, repeated resume idempotency, complete closure evidence requirement).
- [ ] 7.2 Run strict OpenSpec validation (`openspec validate durable-intake-and-closure-sagas`).
