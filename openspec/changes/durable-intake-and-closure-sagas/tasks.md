# Tasks: Durable Intake and Closure Sagas

## Implementation Sequence

### 1. Domain, DB & Persistence Schema Evolution
- [x] 1.1 Update `OrchestrationExternalAction` domain model in `src/minime/domain/models.py` by making `run_id: str | None = None` and `candidate_sha: str | None = None`, adding `saga_id: str | None = None`, and adding operational ownership invariant validation (`assert run_id is not None or saga_id is not None`).
- [x] 1.2 Update `OrchestrationExternalActionModel` (`orchestration_external_actions`) in `src/minime/db/models.py` by adding optional foreign key `saga_id: Mapped[str | None]`, making `run_id` and `candidate_sha` nullable (`nullable=True`), and preserving globally unique `action_key` index.
- [x] 1.3 Define `DurableSagaModel` (`durable_sagas`) in `src/minime/db/models.py` with attributes (`id`, `saga_type`, `project_id`, `work_item_key`, `change_name`, `run_id`, `job_id`, `generation`, `current_phase`, `status`, `last_observed_outcome`, `blocking_reason`, `evidence_references`, `created_at`, `updated_at`) and partial unique indexes `uq_active_intake_saga` and `uq_active_closure_saga`.
- [x] 1.4 Update `SQLAlchemyOrchestrationExternalActionRepository` in `src/minime/db/repository.py` and in-memory test repositories to support `saga_id` queries, update serialization/mapper functions, and add `SQLAlchemyDurableSagaRepository` interface to `src/minime/domain/interfaces.py`.
- [x] 1.5 Generate Alembic migration script `alembic/versions/*_add_durable_sagas_and_generalize_external_actions.py` creating `durable_sagas` table and updating `orchestration_external_actions` table columns.

### 2. Generic Saga Engine & Delegation to `reconcile_observe_before_repeat()`
- [x] 2.1 Create `SagaEngine` in `src/minime/services/saga_engine.py` to manage saga lifecycle transitions (`start_saga`, `advance_phase`, `block_saga`, `complete_saga`, `fail_saga`).
- [x] 2.2 Implement pre-execution action reservation logic (`reserve_action`) creating/updating `OrchestrationExternalActionModel` records with status `RESERVED` and committing DB transaction BEFORE external adapter execution.
- [x] 2.3 Implement `ReconciliationAuthority` in `src/minime/services/reconciliation_authority.py` delegating to canonical `OrchestrationExternalActionRepository.reconcile_observe_before_repeat()` and enforcing exact Stage B evidence contracts (issue body `<!-- minime-opkey: ... -->` comment marker matching and project item issue URL lookup; forbidding title-only or fuzzy matching).
- [x] 2.4 Implement action result persistence (`record_action_result`) updating action execution status (`COMPLETED`, `FAILED`, `AMBIGUOUS`), setting `reconciled_at = utc_now()`, and updating evidence references. (Confirm `SUCCESS` and `RECONCILED` are NOT persisted statuses).

### 3. Intake Saga Conversion
- [x] 3.1 Refactor `IntakeService.create_work_item()` and `prepare_work_item()` in `src/minime/services/intake_service.py` to instantiate and drive `INTAKE` durable saga.
- [x] 3.2 Implement `INTAKE_CREATED` and `CONTEXT_CHECKED` saga phases in `IntakeService`.
- [x] 3.3 Implement `OPENSPEC_AUTHORED` saga phase with action reservation in `orchestration_external_actions` with `status = RESERVED` before disk writing.
- [x] 3.4 Implement `ISSUE_BOUND` saga phase with action reservation before `GitHubAdapter.create_issue()` and remote reconciliation via exact `<!-- minime-opkey: ... -->` comment marker search on retry. Title-only search strictly forbidden.
- [x] 3.5 Implement `PROJECT_ITEM_BOUND` saga phase with action reservation before `GitHubAdapter.add_issue_to_project()` and remote reconciliation via exact issue URL lookup on retry. Fuzzy title search strictly forbidden.
- [x] 3.6 Implement `READINESS_EVALUATED` and `READY` saga phases, updating `BacklogItem.status` via `LifecycleTransitionAuthority` upon DoR verification.
- [x] 3.7 Verify handoff boundary from `IntakeService` to `SchedulerService.admit_work_item()` operates strictly from `READY` saga checkpoint.

### 4. Closure Saga Conversion (Squash-Merge Aware)
- [x] 4.1 Refactor `PostMergeReconciliationService.reconcile_post_merge()` in `src/minime/services/post_merge_service.py` to instantiate and drive `CLOSURE` durable saga.
- [x] 4.2 Implement `MERGE_OBSERVED` phase recording PR merge details.
- [x] 4.3 Implement `MERGED_DELIVERY_VERIFIED` phase supporting both normal/ancestry-preserving merges (`git merge-base --is-ancestor`) and squash merges (verifying PR `is_merged == True`, exact repo/base identity, candidate SHA matching PR head SHA, and `merge_commit_sha` presence on base branch).
- [x] 4.4 Implement `RUN_JOB_RECONCILED` phase transitioning `OrchestrationRun` and `Job` to `POST_MERGE_RECONCILING`.
- [x] 4.5 Implement `ISSUE_CLOSED` saga phase with action reservation (`status = RESERVED`) before `GitHubAdapter.close_issue()` and remote issue status reconciliation on retry.
- [x] 4.6 Implement `PROJECT_ITEM_DONE` saga phase with action reservation before `GitHubAdapter.update_project_item_status()` and status reconciliation on retry.
- [x] 4.7 Implement `SPEC_SYNCED` and `SYNC_VERIFIED` saga phases with action reservation before `OpenSpecSyncService.sync_change_specs()` and verification check.
- [x] 4.8 Implement `SPEC_ARCHIVED` and `ARCHIVE_VERIFIED` saga phases with action reservation before `OpenSpecSyncService.archive_change()` and filesystem destination reconciliation on retry.
- [x] 4.9 Implement `WORKTREE_CLEANED`, `BRANCH_CLEANED`, and `LOCKS_RELEASED` saga phases with action reservation and Stage C 4-way postcondition verification.
- [x] 4.10 Implement `FINAL_CLOSED` saga phase triggering `LifecycleTransitionAuthority.transition_change()` to `DONE` and `transition_backlog_item()` to `COMPLETED` ONLY when all 12 closure phases are durably proven complete.
- [x] 4.11 Implement terminal domain reconciliation mode for closure sagas: if Change/Backlog/Run/Job is already terminal but closure evidence is incomplete, do NOT infer success and do NOT resurrect work; enter reconciliation-only mode to verify missing postconditions and complete saga only when full evidence exists.

### 5. Restart Recovery & Control-Plane Integration
- [x] 5.1 Update `RestartRecoveryService.reconcile_on_startup()` in `src/minime/services/restart_recovery_service.py` to query `durable_sagas` for `IN_PROGRESS` or `BLOCKED` sagas and invoke `SagaEngine.resume_saga()`.
- [x] 5.2 Implement terminal identity protection check in `RestartRecoveryService` preventing re-opening or re-admission of completed/cancelled changes or backlog items during intake.
- [x] 5.3 Integrate `ControlPlaneService` in `src/minime/services/control_plane_service.py` with `resume_saga()` endpoint allowing manual operator trigger with row-locking idempotency.

### 6. Observability & Audit Events
- [x] 6.1 Register new `EventType` enums (`DURABLE_SAGA_STARTED`, `DURABLE_SAGA_PHASE_ADVANCED`, `DURABLE_SAGA_ACTION_RESERVED`, `DURABLE_SAGA_ACTION_RECONCILED`, `DURABLE_SAGA_BLOCKED`, `DURABLE_SAGA_COMPLETED`, `DURABLE_SAGA_FAILED`) in `src/minime/domain/enums.py`.
- [x] 6.2 Emit atomic event records in PostgreSQL transaction during saga phase transitions and action reservations.

### 7. Targeted Adversarial Tests & Verification
- [x] 7.1 Implement unit and integration tests in `tests/test_durable_sagas.py` covering all 20 targeted verification scenarios (intake restart at every phase, closure restart at every phase, Stage B comment marker deduplication, Stage B project item URL lookup, squash merge delivery verification, terminal domain flag + incomplete saga evidence != closure success, single external action authority verification, action ownership invariant, canonical status verification, repeated resume idempotency, complete closure evidence requirement).
- [x] 7.2 Run strict OpenSpec validation (`openspec validate durable-intake-and-closure-sagas`).
