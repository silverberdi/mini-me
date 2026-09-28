# Design: Durable Intake and Closure Sagas

## Architectural Context & Invariants

This design defines Stage D of the Canonical Lifecycle Correction Program (`docs/architecture/CANONICAL_LIFECYCLE_CORRECTION_PROGRAM.md`).

Stage D primarily enforces **Architectural Law 4**:
> Every external side effect is observable, idempotent, and resumable.

It preserves all existing architectural laws:
1. **Lifecycle transition single writer**: Only `LifecycleTransitionAuthority` writes `Change.status` and `BacklogItem.status`.
2. **Fail-closed evidence**: Missing or unobservable evidence is never interpreted as success (`UNKNOWN` blocks execution).
3. **Non-resurrection**: Observations, projections, or restarted sagas cannot return terminal (`COMPLETED` / `CANCELLED` / `DONE`) work to executable state.
4. **Runtime isolation**: The deployed runtime checkout is never a managed project workspace (Stage C isolation).

---

## Canonical Invariants

### A. Durable Saga Identity

Every work intake or post-merge closure process is backed by a durable record in PostgreSQL (`DurableSagaModel` / `durable_sagas`).

Durable Saga attributes:
- `saga_id`: Primary Key (UUID string, 64 chars).
- `saga_type`: Enum `SagaType` (`INTAKE`, `CLOSURE`).
- `project_id`: Foreign key to `projects.id`.
- `work_item_key`: Backlog item key (nullable for closure sagas).
- `change_name`: OpenSpec change name.
- `run_id`: Foreign key to `orchestration_runs.id` (nullable for intake sagas).
- `job_id`: Foreign key to `jobs.id` (nullable for intake sagas).
- `generation`: Attempt counter (Integer, default 1).
- `current_phase`: Enum string representing current checkpoint.
- `status`: Enum `SagaStatus` (`IN_PROGRESS`, `BLOCKED`, `COMPLETED`, `FAILED`, `CANCELLED`).
- `last_observed_outcome`: Canonical `ExternalOutcome` enum string (`SUCCESS`, `FAILURE`, `UNKNOWN`, `NEEDS_HUMAN`, `TIMEOUT`).
- `blocking_reason`: Text description when blocked or waiting.
- `evidence_references`: JSON payload recording IDs, SHAs, URLs, and verify tokens.
- `created_at` / `updated_at`: UTC timestamps with tz.

**Logical Identity Rule**: A retry or resume operation MUST bind to the existing logical saga record for that `(project_id, work_item_key)` or `(project_id, change_name)`. Retries do not create redundant saga records unless an explicit new generation is authorized by domain contract.

### B. Durable Phase / Checkpoint Model

1. **Evidence-Based Phase Completion**: A saga phase transitions to complete ONLY when positive durable evidence is recorded in `SagaActionModel` or `evidence_references`.
2. **Safe Reconstruction on Restart**: Upon daemon restart, the saga engine reconstructs the next safe action from persisted DB state plus current external observations.
3. **No Blind Replay**: Phases recorded as `SUCCESS` are never re-executed.
4. **Reconcile Before Retry**: If an action outcome is `UNKNOWN` or `AMBIGUOUS`, reconciliation MUST run before repeating any external mutation.

### C. Durable External-Action Identity

Every non-idempotent or externally observable side effect reserves a `SagaActionModel` record in PostgreSQL BEFORE invoking external adapters.

Durable Action attributes:
- `action_id`: Primary Key (UUID string, 64 chars).
- `saga_id`: Foreign key to `durable_sagas.id`.
- `action_key`: Unique string key (e.g. `intake:issue_create:proj1:feat-a:gen1`).
- `action_type`: Enum `SagaActionType` (`GITHUB_ISSUE_CREATE`, `GITHUB_PROJECT_ITEM_ADD`, `OPENSPEC_CHANGE_AUTHOR`, `GITHUB_ISSUE_CLOSE`, `GITHUB_PROJECT_ITEM_DONE`, `OPENSPEC_SPEC_SYNC`, `OPENSPEC_ARCHIVE`, `WORKTREE_CLEANUP`, `BRANCH_CLEANUP`, `LOCK_RELEASE`).
- `target_identity`: Resource locator (e.g. `repo:silverberdi/mini-me`, `issue:#42`, `path:openspec/changes/feat-a`).
- `request_fingerprint`: Deterministic hash of mutation parameters.
- `attempt_number`: Attempt counter.
- `execution_state`: Enum `SagaActionState` (`NOT_STARTED`, `REQUESTED`, `IN_FLIGHT`, `SUCCESS`, `FAILURE`, `AMBIGUOUS`).
- `observed_result_identity`: External ID (e.g. issue number `42`, project item ID `PVTI_123`, archive path).
- `result_payload`: JSON response data.
- `error_message`: Error text.
- `reserved_at` / `reconciled_at` / `updated_at`: UTC timestamps.

### D. Reconcile Before Retry

When an action is found in `REQUESTED`, `IN_FLIGHT`, or `AMBIGUOUS` state following a restart or failure:
1. **DO NOT** immediately repeat the external mutation.
2. Query the remote/external system using `target_identity` and `request_fingerprint` evidence (e.g. query GitHub Issues by label/title, inspect GitHub Project items by issue URL, check filesystem for archived directories).
3. If external occurrence is positively confirmed: record `observed_result_identity`, mark action `SUCCESS`, and advance saga phase.
4. If non-occurrence is positively confirmed: execute the mutation safely.
5. If external state remains unobservable: mark action `AMBIGUOUS`, set saga `status = BLOCKED`, emit `RECOVERY_BLOCKED` event, and wait for operator intervention.

### E. Intake Saga Lifecycle

Intake tracks preparation of backlog items up to scheduler admission eligibility:

```text
[INTAKE_CREATED] -> [CONTEXT_CHECKED] -> [OPENSPEC_AUTHORED] -> [ISSUE_BOUND] -> [PROJECT_ITEM_BOUND] -> [READINESS_EVALUATED] -> [READY]
```

- Phase 1 `INTAKE_CREATED`: Backlog item persisted in DB.
- Phase 2 `CONTEXT_CHECKED`: Project context sources validated.
- Phase 3 `OPENSPEC_AUTHORED`: `OpenSpecGenerator` writes `proposal.md`, `design.md`, `tasks.md`, `specs/spec.md`. Action reserved before disk write.
- Phase 4 `ISSUE_BOUND`: GitHub Issue created/bound via `GitHubAdapter`. Action reserved before HTTP call. Reconciles via issue search on retry.
- Phase 5 `PROJECT_ITEM_BOUND`: GitHub Project v2 item added via `GitHubAdapter`. Action reserved before GraphQL call. Reconciles via project item query on retry.
- Phase 6 `READINESS_EVALUATED`: Definition of Ready (DoR) evaluated by `ReadinessService`.
- Phase 7 `READY`: `BacklogItem.status` updated to `READY` via `LifecycleTransitionAuthority`. Handoff boundary to `SchedulerService.admit_work_item`.

### F. Closure Saga Lifecycle

Closure tracks post-human-merge SDLC finalization:

```text
[MERGE_OBSERVED] -> [ANCESTRY_VERIFIED] -> [RUN_JOB_RECONCILED] -> [ISSUE_CLOSED] -> [PROJECT_ITEM_DONE] -> [SPEC_SYNCED] -> [SYNC_VERIFIED] -> [SPEC_ARCHIVED] -> [ARCHIVE_VERIFIED] -> [WORKTREE_CLEANED] -> [BRANCH_CLEANED] -> [LOCKS_RELEASED] -> [FINAL_CLOSED]
```

- Phase 1 `MERGE_OBSERVED`: Merged PR details retrieved (`is_merged == True`).
- Phase 2 `ANCESTRY_VERIFIED`: Candidate SHA verified as ancestor of `base_branch` or merge commit SHA.
- Phase 3 `RUN_JOB_RECONCILED`: `OrchestrationRun` and `Job` transitioned to `POST_MERGE_RECONCILING`.
- Phase 4 `ISSUE_CLOSED`: Remote GitHub Issue closed. Action reserved before API PATCH.
- Phase 5 `PROJECT_ITEM_DONE`: Remote GitHub Project item status updated to "Done". Action reserved before GraphQL call.
- Phase 6 `SPEC_SYNCED`: `OpenSpecSyncService` syncs delta specs to main specs in `openspec/specs/`.
- Phase 7 `SYNC_VERIFIED`: `OpenSpecSyncService` verifies synced capabilities exist in main specs.
- Phase 8 `SPEC_ARCHIVED`: `OpenSpecSyncService` archives change to `openspec/changes/archive/`. Action reserved before filesystem move. Reconciles directory location on retry.
- Phase 9 `ARCHIVE_VERIFIED`: Verification confirms active change path is gone and archive path exists.
- Phase 10 `WORKTREE_CLEANED`: `WorktreeManager` cleans job worktree (Stage C 4-way reconciliation).
- Phase 11 `BRANCH_CLEANED`: Local and remote candidate branches deleted with postcondition checks.
- Phase 12 `LOCKS_RELEASED`: Ephemeral preview and execution locks released.
- Phase 13 `FINAL_CLOSED`: `LifecycleTransitionAuthority` transitions `Change` to `DONE` and `BacklogItem` to `COMPLETED`, `OrchestrationRun` to `COMPLETED`, `Job` to `COMPLETED`.

### G. Terminal Identity Protection

A completed or cancelled `Change` or `BacklogItem` CANNOT be resurrected or re-executed.
- `LifecycleTransitionAuthority` transition matrices enforce that `DONE` and `CANCELLED` (for Change) and `COMPLETED` and `CANCELLED` (for BacklogItem) have ZERO allowed outgoing transitions.
- Saga recovery checks `Change` and `BacklogItem` status first; if terminal, saga execution terminates immediately with `TERMINAL_SUCCESS` or `TERMINAL_FAILURE`.

### H. Recovery Semantics

Recovery decisions map to canonical safety classifications:
- `SAFE_TO_RETRY`: Action non-occurrence positively proven; safe to execute.
- `RECONCILE_FIRST`: Action in `REQUESTED`, `IN_FLIGHT`, or `AMBIGUOUS`; must query external state before action execution.
- `WAIT_EXTERNAL`: Waiting for external dependency (e.g., PR merge by human operator).
- `NEEDS_HUMAN`: Ambiguity cannot be resolved automatically; requires human operator intervention.
- `TERMINAL_SUCCESS`: Saga complete; all required evidence verified.
- `TERMINAL_FAILURE`: Saga unrecoverably failed or work item cancelled.

---

## Finite Discovery Matrix (25 Surfaces)

| # | Surface / Entry Point | Current Durable State | External Mutations | Existing Operation Identity | Retry Behavior | Reconciliation Behavior | Checkpoint / Evidence Used | Duplicate-Effect Risk | Crash Window | Current Writer / Authority | Required Stage D Correction | Stage D Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Intake API entry points (`src/minime/api/app.py`) | `BacklogItemModel` status | GitHub Issue, Project item, OpenSpec files | None in API router | Retries invoke `prepare_work_item` again | None in API layer | API parameters | High | Post-remote call / pre-DB commit | `IntakeService` | Wrap API intake in `IntakeSaga` handle | `NEEDS_CHANGE` |
| 2 | `IntakeService` (`src/minime/services/intake_service.py`) | `backlog_items` DB table | GitHub Issue, Project item, OpenSpec files | In-memory string operation keys | Retries start `prepare_work_item` from beginning | Partial in-memory check | `BacklogItem.readiness_state` | High | Across phase transitions | `IntakeService` | Refactor into phase-checkpointed `IntakeSaga` | `NEEDS_CHANGE` |
| 3 | Context / discovery preparation (`context_discovery_service.py`) | `changes` DB table (`DISCOVERED`) | Read-only file scan of docs/ROADMAP.md | None | Safe re-scan | Overwrites/reads files | `ChangeModel.discovered_at` | Low | Safe to re-run | `DiscoveryService` | Align as Intake Saga phase `DISCOVERY_CHECK` | `ALREADY_COMPLIANT` |
| 4 | Backlog / work-item persistence (`db/repository.py`) | `backlog_items` DB table | None (PostgreSQL DB) | `item_key` + `project_id` | Atomic DB CAS | DB rowcount verification | `WorkItemStatus` | None | Handled by DB transaction | `LifecycleTransitionAuthority` | Standard DB repository pattern | `ALREADY_COMPLIANT` |
| 5 | GitHub Issue creation/binding (`IntakeService.prepare_work_item`) | `BacklogItem.github_issue_number` | Remote GitHub REST API `POST /issues` | In-memory key `issue_create:...` | Calls `create_issue` again if issue_number is NULL | In-memory `_seen_operations` only | `github_issue_number` | High | Post-HTTP response / pre-DB commit | `IntakeService` + `GitHubAdapter` | Reserve `SagaAction` BEFORE call; query remote by fingerprint on retry | `NEEDS_CHANGE` |
| 6 | GitHub Project item creation/binding (`prepare_work_item`) | `BacklogItem.github_project_item_id` | Remote GitHub GraphQL API `addProjectV2Item` | In-memory key `project_item_add:...` | Calls `add_issue_to_project` again | In-memory cache only | `github_project_item_id` | Medium/High | Post-GraphQL response / pre-DB commit | `IntakeService` + `GitHubAdapter` | Reserve `SagaAction` BEFORE call; query project item on retry | `NEEDS_CHANGE` |
| 7 | OpenSpec change authoring (`prepare_work_item`) | OpenSpec files on disk & `ChangeModel` | Filesystem writes in `openspec/changes/{change}` | `openspec_change_name` | Overwrites files (`overwrite=True`) | Checks file existence | `ChangeModel` in DB | Low | Partial file write on crash | `OpenSpecGenerator` + `IntakeService` | Reserve `SagaAction` for authoring phase; verify file integrity | `NEEDS_CHANGE` |
| 8 | Readiness/preparation completion (`prepare_work_item`) | `BacklogItem.readiness_state` | Read-only DoR evaluation | None | Safe re-evaluation | Re-checks DoR rules | `ReadinessEvaluation` model | None | Safe to re-run | `ReadinessService` | Checkpoint readiness evidence reference in `IntakeSaga` | `NEEDS_CHANGE` |
| 9 | Scheduler handoff boundary (`start_work_item`) | `BacklogItem.status`, `OrchestrationRunModel` | DB record creation | `run_id`, `uq_active_orchestration_run` | Reuses existing active run | DB unique index check | `uq_active_orchestration_run` DB index | None | Handled by DB transaction | `SchedulerService` | Clean handoff boundary from `IntakeSaga` to `SchedulerService` | `ALREADY_COMPLIANT` |
| 10 | Merge observation (`post_merge_service.py`) | `Event` (`MERGE_DETECTED`) | Read-only GitHub REST API query | `pr_number` / branch name | Safe re-query | Queries PR details (`is_merged`) | `pr_details` dictionary | None | Safe to retry | `PostMergeReconciliationService` | Bind PR merge observation as Phase 1 of `ClosureSaga` | `NEEDS_CHANGE` |
| 11 | `PostMergeReconciliationService` (`post_merge_service.py`) | `OrchestrationRun.current_stage` | Issue close, Project item, Spec sync/archive, cleanups | Linear in-memory execution | Retries rerun all uncheckpointed steps | Partial phase string checks | `run.current_stage == COMPLETED` | High | Across any closure step | `PostMergeReconciliationService` | Refactor into phase-checkpointed `ClosureSaga` | `NEEDS_CHANGE` |
| 12 | Run terminal reconciliation (`reconcile_post_merge`) | `OrchestrationRunModel` (`COMPLETED`) | None (PostgreSQL DB) | `run_id` | Single flag check `run.current_stage == COMPLETED` | Returns `already_closed=True` | `OrchestrationRunModel` fields | Low | Pre-DB commit | `PostMergeReconciliationService` | Transition run to `COMPLETED` only after `ClosureSaga` phase verification | `NEEDS_CHANGE` |
| 13 | Job terminal reconciliation (`reconcile_post_merge`) | `JobModel` (`COMPLETED`) | None (PostgreSQL DB) | `job_id` | Idempotent DB update | Sets status `COMPLETED` | `JobModel.status` | None | Handled by DB transaction | `PostMergeReconciliationService` | Align Job status update with Closure Saga final checkpoint | `NEEDS_CHANGE` |
| 14 | Change terminal transition (`_reconcile_change...`) | `ChangeModel.status` (`DONE`) | DB update + Event emission | `Change.id` CAS update | Idempotent CAS via transition authority | Atomic CAS query | `ChangeStatus.DONE` | None | Handled by DB transaction | `LifecycleTransitionAuthority` | Invoked by Closure Saga upon closure verification | `ALREADY_COMPLIANT` |
| 15 | BacklogItem terminal transition (`_reconcile_change...`) | `BacklogItemModel.status` (`COMPLETED`) | DB update + Event emission | `BacklogItem.id` CAS update | Idempotent CAS via transition authority | Atomic CAS query | `WorkItemStatus.COMPLETED` | None | Handled by DB transaction | `LifecycleTransitionAuthority` | Invoked by Closure Saga upon closure verification | `ALREADY_COMPLIANT` |
| 16 | GitHub Issue closure (`reconcile_post_merge`) | `Event` (`ISSUE_CLOSED`) | Remote GitHub REST API `PATCH /issues/{num}` | None reserved | Retries `close_issue` | None; relies on API idempotency | API response boolean | Low/Medium | Post-HTTP PATCH / pre-event emission | `PostMergeReconciliationService` + `GitHubAdapter` | Reserve `SagaAction` for `ISSUE_CLOSE`; query issue state on retry | `NEEDS_CHANGE` |
| 17 | GitHub Project item completion (`reconcile_post_merge`) | `Event` (`PROJECT_ITEM_DONE`) | Remote GitHub GraphQL API status update | None reserved | Retries GraphQL update | None | API response boolean | Low/Medium | Post-GraphQL response / pre-event emission | `PostMergeReconciliationService` + `GitHubAdapter` | Reserve `SagaAction` for `PROJECT_ITEM_DONE`; query status on retry | `NEEDS_CHANGE` |
| 18 | OpenSpec Spec Sync (`reconcile_post_merge`) | Main spec files modified on disk | Filesystem writes in `openspec/specs/` | None reserved | Re-executes spec sync | Syncs delta specs into main specs | `sync_res.data` (capabilities) | Medium | Partial file write during sync | `OpenSpecSyncService` | Reserve `SagaAction` for `SPEC_SYNC`; verify sync idempotency | `NEEDS_CHANGE` |
| 19 | OpenSpec Spec Sync Verification (`reconcile_post_merge`) | `Event` (`POST_MERGE_SYNC_VERIFIED`) | Read-only check of main spec files | None | Safe re-verification | Verifies delta requirements exist in main specs | `verify_sync_res.data == True` | None | Safe to re-run | `OpenSpecSyncService` | Checkpoint sync verification evidence in `ClosureSaga` | `NEEDS_CHANGE` |
| 20 | OpenSpec Archive (`reconcile_post_merge`) | Directory move on disk (`changes` -> `archive`) | Filesystem move (`shutil.move`) | None reserved | Rerun fails if source directory moved | Checks archive folder | `archive_res.data` (archived path) | High | Between directory move and DB commit | `OpenSpecSyncService` | Reserve `SagaAction` for `SPEC_ARCHIVE`; reconcile archive path on retry | `NEEDS_CHANGE` |
| 21 | OpenSpec Archive Verification (`reconcile_post_merge`) | `Event` (`POST_MERGE_ARCHIVE_VERIFIED`) | Read-only check of filesystem | None | Safe re-verification | Verifies source gone & archive path exists | `verify_arc_res.data == True` | None | Safe to re-run | `OpenSpecSyncService` | Checkpoint archive verification evidence in `ClosureSaga` | `NEEDS_CHANGE` |
| 22 | Worktree cleanup (`_clean_worktrees`) | `OrchestrationWorktreeOwnershipModel` | Filesystem delete + `git worktree remove` | `job_id` worktree path | Returns `ALREADY_ABSENT` if path missing | Verifies path non-existence after removal | Path non-existence check | Low | Post-deletion / pre-DB update | `WorktreeManager` | Checkpoint `WORKTREE_CLEANUP` phase in `ClosureSaga` | `ALREADY_COMPLIANT` |
| 23 | Branch cleanup (`_delete_local_branch`) | `Event` (`BRANCH_CLEANED`) | `git branch -D` (local) & API delete (remote) | None | Local check uses `git show-ref`; remote 404 handled | Postcondition check via `git show-ref` | `show-ref` exit code 1 | Low | Post-deletion / pre-DB event | `PostMergeReconciliationService` + `GitHubAdapter` | Checkpoint `BRANCH_CLEANUP` phase in `ClosureSaga` | `ALREADY_COMPLIANT` |
| 24 | Recovery / startup integration (`restart_recovery_service.py`) | `Event` (`DAEMON_RESTARTED`) | Removes orphaned Git locks (with proof) | `recovery_cycle_id` | Safe startup reconciliation | Inspects in-flight jobs and active runs | `active_jobs`, `active_runs` | Low | Safe to rerun on startup | `RestartRecoveryService` | Recover & resume pending `IntakeSaga` & `ClosureSaga` from DB checkpoints | `NEEDS_CHANGE` |
| 25 | Control-plane / manual resume paths (`control_plane_service.py`) | `OperatorActionRecordModel` | Invokes `resume()` or updates states | `action_request_id` | Operator action recorded; rerun executes action | Checks precondition stage/gate | `precondition_stage` / `gate` | Low | Pre-dispatch crash | `ControlPlaneService` | Integrate control-plane resume to trigger `SagaEngine.resume_saga(saga_id)` | `NEEDS_CHANGE` |

**Summary Matrix Counts**:
- `ALREADY_COMPLIANT`: 7 (Surfaces 3, 4, 9, 14, 15, 22, 23)
- `NEEDS_CHANGE`: 18 (Surfaces 1, 2, 5, 6, 7, 8, 10, 11, 12, 13, 16, 17, 18, 19, 20, 21, 24, 25)
- `OUT_OF_SCOPE`: 0

---

## Database Design

Two generic SQLAlchemy models in `src/minime/db/models.py` (and corresponding Alembic migration):

### 1. `DurableSagaModel` (`durable_sagas`)

```python
class DurableSagaModel(Base):
    __tablename__ = "durable_sagas"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    saga_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True) # INTAKE, CLOSURE
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_item_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    change_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("orchestration_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_phase: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="IN_PROGRESS", nullable=False, index=True) # IN_PROGRESS, BLOCKED, COMPLETED, FAILED, CANCELLED
    last_observed_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    blocking_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_references: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        Index(
            "uq_active_intake_saga",
            "project_id",
            "work_item_key",
            unique=True,
            postgresql_where=text("status IN ('IN_PROGRESS', 'BLOCKED') AND saga_type = 'INTAKE'"),
            sqlite_where=text("status IN ('IN_PROGRESS', 'BLOCKED') AND saga_type = 'INTAKE'"),
        ),
        Index(
            "uq_active_closure_saga",
            "project_id",
            "change_name",
            unique=True,
            postgresql_where=text("status IN ('IN_PROGRESS', 'BLOCKED') AND saga_type = 'CLOSURE'"),
            sqlite_where=text("status IN ('IN_PROGRESS', 'BLOCKED') AND saga_type = 'CLOSURE'"),
        ),
    )
```

### 2. `SagaActionModel` (`saga_actions`)

```python
class SagaActionModel(Base):
    __tablename__ = "saga_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    saga_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("durable_sagas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    execution_state: Mapped[str] = mapped_column(String(32), default="NOT_STARTED", nullable=False, index=True) # NOT_STARTED, REQUESTED, IN_FLIGHT, SUCCESS, FAILURE, AMBIGUOUS
    observed_result_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    saga: Mapped[DurableSagaModel] = relationship("DurableSagaModel", backref="actions")
```

---

## Transaction Boundaries

To guarantee Architectural Law 4 without holding open long database locks across external network calls, every saga action step MUST follow this exact 6-step transactional protocol:

1. **Step 1 — Action Intention Reservation (DB Commit)**:
   - Create/update `SagaActionModel` with `action_key`, `target_identity`, `request_fingerprint`, and `execution_state = REQUESTED`.
   - Update `DurableSagaModel` with `updated_at`.
   - **COMMIT DB TRANSACTION**.

2. **Step 2 — External Mutation Invocation (No DB Lock)**:
   - Invoke remote external mutation (e.g. GitHub REST/GraphQL call, OpenSpec filesystem edit).
   - Receive response or catch network exception.

3. **Step 3 — Observation & Result Verification**:
   - If response received successfully: parse external outcome, extract `observed_result_identity`.
   - If network call timed out or threw unhandled error: enter RECONCILE BEFORE RETRY phase by querying external system using `target_identity` and `request_fingerprint`.

4. **Step 4 — Result Persistence (DB Commit)**:
   - Begin DB transaction.
   - Update `SagaActionModel` with `execution_state = SUCCESS` (or `FAILURE` / `AMBIGUOUS`), `observed_result_identity`, `result_payload`, and `reconciled_at`.
   - **COMMIT DB TRANSACTION**.

5. **Step 5 — Saga Checkpoint Advancement (DB Commit)**:
   - Begin DB transaction.
   - Update `DurableSagaModel` `current_phase` to next phase and update `evidence_references`.
   - Save corresponding `Event` record (`DURABLE_SAGA_PHASE_ADVANCED`) in same transaction.
   - **COMMIT DB TRANSACTION**.

6. **Step 6 — Final Saga Closure Gate (DB Commit)**:
   - When all required phases reach `SUCCESS` evidence:
   - Invoke `LifecycleTransitionAuthority.transition_change()` and `transition_backlog_item()` to update terminal states atomically.
   - Update `DurableSagaModel` `status = COMPLETED`.
   - **COMMIT DB TRANSACTION**.

---

## Crash-Window Analysis (8 Explicit Cases)

1. **Case 1: Crash before external call**:
   - *State*: `SagaActionModel` is `REQUESTED` in DB, but external HTTP request was not sent.
   - *Recovery*: Saga engine reads `REQUESTED` action on startup. Executes RECONCILE FIRST check against external target using `request_fingerprint`. External target search returns non-occurrence. Saga engine proceeds to execute external mutation safely.

2. **Case 2: Crash after remote accepted mutation but before response**:
   - *State*: GitHub API created issue #42, but daemon crashed before receiving HTTP response body.
   - *Recovery*: `SagaActionModel` is `REQUESTED`. On restart, saga engine executes RECONCILE FIRST check: searches GitHub repo for issues matching `request_fingerprint` or change title. Finds issue #42. Adopts issue #42 as `observed_result_identity`, updates `SagaActionModel` to `SUCCESS`, advances checkpoint without creating a duplicate issue.

3. **Case 3: Crash after response but before DB result persistence**:
   - *State*: GitHub API returned 201 Created (issue #42), but daemon crashed before committing `SagaActionModel` state `SUCCESS` to PostgreSQL.
   - *Recovery*: Same as Case 2. On restart, RECONCILE FIRST check queries remote GitHub API, finds issue #42, records `SUCCESS` in DB, advances saga phase.

4. **Case 4: Crash after result persisted but before phase advancement**:
   - *State*: `SagaActionModel` is saved as `SUCCESS` with issue #42, but `DurableSagaModel.current_phase` is still `OPENSPEC_AUTHORED`.
   - *Recovery*: On restart, saga engine inspects `SagaActionModel` for phase `ISSUE_BOUND`, sees `execution_state == SUCCESS`, skips remote call entirely, advances `DurableSagaModel.current_phase` to `ISSUE_BOUND`, and proceeds to next phase (`PROJECT_ITEM_BOUND`).

5. **Case 5: Restart after phase advancement**:
   - *State*: `DurableSagaModel.current_phase` is `SPEC_ARCHIVED`.
   - *Recovery*: On restart, saga engine loads `DurableSagaModel`, sees `current_phase == SPEC_ARCHIVED`, skips all preceding completed phases (spec sync, archive), and resumes at phase `ARCHIVE_VERIFIED` -> `WORKTREE_CLEANED`.

6. **Case 6: Repeated resume command**:
   - *State*: Operator triggers `/api/v1/control-plane/sagas/{saga_id}/resume` multiple times concurrently or sequentially.
   - *Recovery*: `SagaEngine` acquires row lock on `DurableSagaModel` using atomic SELECT ... FOR UPDATE. If saga is already `COMPLETED` or `IN_PROGRESS` on active worker, subsequent calls are no-ops returning current status idempotently.

7. **Case 7: External system temporarily unavailable during reconciliation**:
   - *State*: GitHub API returns 503 Service Unavailable or times out during RECONCILE FIRST check.
   - *Recovery*: Saga engine CANNOT establish occurrence or non-occurrence. Action `execution_state` transitions to `AMBIGUOUS`. `DurableSagaModel.status` transitions to `BLOCKED` with `blocking_reason = "GitHub API 503 during action reconciliation"`. Emits `RECOVERY_BLOCKED` event. Daemon does NOT fabricate success or retry blindly; waits for next scheduled sweep or operator resume.

8. **Case 8: Stale projection disagrees with durable saga state**:
   - *State*: `WorkQueueSnapshotModel` or `BacklogItemModel` read model projects status `PREPARING`, but `DurableSagaModel` is `COMPLETED` and `ChangeModel` is `DONE`.
   - *Recovery*: Architectural Law Matrix dictates PostgreSQL canonical saga state and `LifecycleTransitionAuthority` supersede read models. `IntakeService.reconcile_backlog_projections()` refreshes read models from canonical saga state; projections CANNOT re-open or re-execute completed sagas.

---

## Test Strategy

Targeted verification scenarios to implement in `tests/test_durable_sagas.py`:

1. **Intake Restart Between Every Phase**: Test daemon restart after each of the 7 intake phases; verify saga resumes from exact persisted checkpoint without repeating prior steps.
2. **Closure Restart Between Every Phase**: Test daemon restart after each of the 13 closure phases; verify saga resumes from exact persisted checkpoint without repeating prior steps.
3. **Duplicate Issue Prevention on Retry**: Simulate crash post-GitHub Issue creation; verify retry reconciles existing issue #42 and creates ZERO duplicate issues.
4. **Duplicate Project Item Prevention on Retry**: Simulate crash post-GraphQL project item creation; verify retry adopts existing project item without duplicate addition.
5. **Adoption of Externally Completed Effect**: Verify `RECONCILE_FIRST` successfully discovers and adopts remote side effects when action state is `REQUESTED` or `AMBIGUOUS`.
6. **Fail-Closed on Unobservable State**: Verify HTTP 500/503 during reconciliation sets action to `AMBIGUOUS` and saga to `BLOCKED` without guessing success.
7. **Completed Phases Not Re-executed**: Verify completed phases with `SUCCESS` action records are skipped during saga resume.
8. **Terminal Identity Protection**: Verify attempting to start an intake or closure saga for a `COMPLETED` / `DONE` item fails closed immediately.
9. **Repeated Resume Idempotency**: Verify calling `resume_saga()` multiple times concurrently or sequentially produces identical final state without side effects.
10. **Partially Completed Closure Blocked**: Verify closure saga lacking required phase evidence (e.g. sync unverified) stops at `WAIT_EXTERNAL` or `BLOCKED` and does NOT transition Change to `DONE`.
11. **Idempotent OpenSpec Spec Sync**: Verify retrying OpenSpec spec sync phase does not duplicate spec sections in `openspec/specs/`.
12. **Idempotent OpenSpec Archive**: Verify retrying OpenSpec archive when active change directory is already moved reconciles archive destination safely without raising `FileNotFoundError`.
13. **Worktree Cleanup Idempotency**: Verify worktree cleanup returns `ALREADY_ABSENT` safely when worktree directory is already deleted.
14. **Branch Cleanup Idempotency**: Verify local and remote branch cleanup handle `ALREADY_ABSENT` gracefully on retry.
15. **Final Closure Evidence Requirement**: Verify `Change.DONE` and `BacklogItem.COMPLETED` transitions require complete 13-phase evidence set.
16. **Daemon Startup Recovery Sweep**: Test `RestartRecoveryService.reconcile_on_startup()` discovering and resuming interrupted `INTAKE` and `CLOSURE` sagas.
17. **Control-Plane Saga Resume Integration**: Test triggering manual saga resume via `ControlPlaneService` endpoint.
