# Design: Durable Intake and Closure Sagas

## Architectural Context & Invariants

This design defines Stage D of the Canonical Lifecycle Correction Program (`docs/architecture/CANONICAL_LIFECYCLE_CORRECTION_PROGRAM.md`).

Stage D primarily enforces **Architectural Law 4**:
> Every external side effect is observable, idempotent, and resumable.

It preserves all foundational architectural laws and existing authority boundaries:
1. **Lifecycle transition single writer**: `LifecycleTransitionAuthority` remains the SOLE writer of `Change.status` and `BacklogItem.status`.
2. **Fail-closed evidence**: Missing or unobservable evidence is never interpreted as success (`UNKNOWN` blocks execution).
3. **Non-resurrection**: Observations, projections, or restarted sagas cannot return terminal (`COMPLETED` / `CANCELLED` / `DONE`) work to executable state.
4. **Runtime isolation**: The deployed runtime checkout is never a managed project workspace (`ManagedWorkspaceGuard` authority).
5. **Existing Authority Preservation**: `WorktreeManager` retains worktree cleanup authority; `OrchestrationExternalActionRepository.reconcile_observe_before_repeat()` retains external action state machine authority; Stage B adapters retain `ExternalActionResult`, `ExternalOutcome`, `RetrySafety`, `operation_key`, and observe-before-repeat semantics.

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

1. **Evidence-Based Phase Completion**: A saga phase transitions to complete ONLY when positive durable evidence is recorded in `OrchestrationExternalActionModel` or `evidence_references`.
2. **Safe Reconstruction on Restart**: Upon daemon restart, the saga engine reconstructs the next safe action from persisted DB state plus current external observations.
3. **No Blind Replay**: Phases recorded as `COMPLETED` are never re-executed.
4. **Reconcile Before Retry**: If an action outcome is `UNKNOWN` or `AMBIGUOUS`, reconciliation MUST run via `reconcile_observe_before_repeat()` before repeating any external mutation.

### C. Single External-Action Authority & Exact `ExternalActionStatus` State Machine

Stage D **does NOT create a separate `SagaActionModel` or a parallel action state machine**.

It reuses the canonical `OrchestrationExternalActionModel` (`orchestration_external_actions`) and its exact `ExternalActionStatus` enum values:

- `RESERVED`: Action reserved before external mutation.
- `EXECUTING`: Mutation actively transmitted / executing (where required by adapter protocol).
- `COMPLETED`: Positive observed postcondition or adopted existing remote effect.
- `FAILED`: Authoritative, permanent external execution failure.
- `UNKNOWN`: Unobservable remote read or response.
- `AMBIGUOUS`: Mutating side effect with uncertain remote occurrence.

> **Explicit Confirmation**: `SUCCESS` and `RECONCILED` are NOT persisted lifecycle statuses. `reconciled_at` remains timestamp evidence metadata on the action model.

#### Domain, DB, Repository, and Interface Evolution

To support saga-bound external actions before an orchestration run exists, the `OrchestrationExternalAction` model is updated consistently across ALL layers:
1. **Domain Model (`src/minime/domain/models.py`)**:
   - `run_id: str | None = None`
   - `saga_id: str | None = None`
   - `candidate_sha: str | None = None`
2. **SQLAlchemy Model (`src/minime/db/models.py`)**:
   - `run_id`: `Mapped[str | None] = mapped_column(String(64), ForeignKey("orchestration_runs.id", ondelete="CASCADE"), nullable=True, index=True)`
   - `saga_id`: `Mapped[str | None] = mapped_column(String(64), ForeignKey("durable_sagas.id", ondelete="CASCADE"), nullable=True, index=True)`
   - `candidate_sha`: `Mapped[str | None] = mapped_column(String(64), nullable=True)`
   - `action_key`: `Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)` (globally unique).
3. **Domain/Repository Interfaces (`src/minime/domain/interfaces.py` & `src/minime/db/repository.py`)**:
   - Updated `OrchestrationExternalActionRepository` interface to allow listing by `saga_id` or `run_id`.
   - Updated in-memory test repository, Postgres repository mapping, and serialization/dict conversion functions.
4. **Callers & Mappers**:
   - Updated all callers that previously assumed `run_id` or `candidate_sha` was non-null.

#### Operational Action Ownership Invariant

An external action MUST be durably attributable to at least one valid operational owner/context:
- **Rule**: `run_id is not None or saga_id is not None`.
- **Constraint**: An external action record with neither `run_id` nor `saga_id` is invalid and MUST be rejected during creation/saving.

### D. Inherit Stage B Identities & Delegate to `reconcile_observe_before_repeat()`

The Stage D `ReconciliationAuthority` delegates directly to canonical `OrchestrationExternalActionRepository.reconcile_observe_before_repeat()` semantics and inherits exact Stage B external resource identity rules:

1. **GitHub Issue Creation (`GITHUB_ISSUE_CREATE`)**:
   - Deterministic `operation_key` (`issue_create:{project_id}:{change_name}`) is authoritative.
   - Issue body carries exact comment marker: `<!-- minime-opkey: <operation_key> -->`.
   - Reconciliation scans issues in repository for this exact comment marker via `GitHubAdapter.list_issues()`.
   - Title-only deduplication is **FORBIDDEN**.

2. **GitHub Project Item Addition (`GITHUB_PROJECT_ITEM_ADD`)**:
   - Deterministic `operation_key` (`project_item_add:{project_id}:{change_name}`).
   - Reconciled using exact project identity (`project_number`, `owner`) + bound issue URL.
   - Fuzzy or title matching is **FORBIDDEN**.

3. **OpenSpec Change Authoring (`OPENSPEC_CHANGE_AUTHOR`)**:
   - Resource identity: `project_id` + `openspec_change_name` + filesystem paths (`proposal.md`, `design.md`, `tasks.md`, `specs/spec.md`).
   - Reconciled by checking exact file existence and non-empty content inside `openspec/changes/{change_name}`.

4. **OpenSpec Spec Sync & Verification (`OPENSPEC_SPEC_SYNC`)**:
   - Resource identity: `project_id` + `openspec_change_name` + requirement capability entries in `openspec/specs/`.
   - Reconciled via `OpenSpecSyncService.verify_sync()`.

5. **OpenSpec Archive & Verification (`OPENSPEC_ARCHIVE`)**:
   - Resource identity: `project_id` + `openspec_change_name` + archive folder path `openspec/changes/archive/{folder_name}`.
   - Reconciled by verifying active change path is absent and target archive path exists.

6. **Worktree Cleanup (`WORKTREE_CLEANUP`)**:
   - Resource identity: `job_id` / `run_id` + canonical worktree path.
   - Reconciled via Stage C 4-way verification (`OrchestrationWorktreeOwnershipModel`, canonical path, `git worktree list`, marker).

7. **Branch Cleanup (`BRANCH_CLEANUP`)**:
   - Resource identity: branch names (`minime/{change_name}` and `minime/{change_name}-{job_id}`).
   - Reconciled via `git show-ref` exit code 1 (local) and GitHub REST API 404 (remote).

When an action is found in `RESERVED`, `EXECUTING`, or `AMBIGUOUS` state:
- If external occurrence is positively confirmed by Stage B identity matching: record `remote_identifier`, transition action status to `COMPLETED` (setting `reconciled_at = utc_now()`), and advance saga phase.
- If non-occurrence is positively confirmed: execute the mutation safely.
- If external state remains unobservable: mark action `AMBIGUOUS`, set saga `status = BLOCKED`, emit `DURABLE_SAGA_BLOCKED` event, and wait for operator intervention.

### E. Intake Saga Lifecycle

Intake tracks preparation of backlog items up to scheduler admission eligibility:

```text
[INTAKE_CREATED] -> [CONTEXT_CHECKED] -> [OPENSPEC_AUTHORED] -> [ISSUE_BOUND] -> [PROJECT_ITEM_BOUND] -> [READINESS_EVALUATED] -> [READY]
```

- Phase 1 `INTAKE_CREATED`: Backlog item persisted in DB.
- Phase 2 `CONTEXT_CHECKED`: Project context sources validated.
- Phase 3 `OPENSPEC_AUTHORED`: `OpenSpecGenerator` writes `proposal.md`, `design.md`, `tasks.md`, `specs/spec.md`. Action reserved before disk write.
- Phase 4 `ISSUE_BOUND`: GitHub Issue created/bound via `GitHubAdapter`. Action reserved with `status = RESERVED` before HTTP call. Reconciles via `<!-- minime-opkey: ... -->` marker search on retry. Title-only deduplication forbidden.
- Phase 5 `PROJECT_ITEM_BOUND`: GitHub Project v2 item added via `GitHubAdapter`. Action reserved with `status = RESERVED` before GraphQL call. Reconciles via issue URL lookup on retry.
- Phase 6 `READINESS_EVALUATED`: Definition of Ready (DoR) evaluated by `ReadinessService`.
- Phase 7 `READY`: `BacklogItem.status` updated to `READY` via `LifecycleTransitionAuthority`. Handoff boundary to `SchedulerService.admit_work_item`.

### F. Closure Saga Lifecycle (Squash-Merge Aware)

Closure tracks post-human-merge SDLC finalization:

```text
[MERGE_OBSERVED] -> [MERGED_DELIVERY_VERIFIED] -> [RUN_JOB_RECONCILED] -> [ISSUE_CLOSED] -> [PROJECT_ITEM_DONE] -> [SPEC_SYNCED] -> [SYNC_VERIFIED] -> [SPEC_ARCHIVED] -> [ARCHIVE_VERIFIED] -> [WORKTREE_CLEANED] -> [BRANCH_CLEANED] -> [LOCKS_RELEASED] -> [FINAL_CLOSED]
```

- Phase 1 `MERGE_OBSERVED`: Merged PR details retrieved (`is_merged == True`).
- Phase 2 `MERGED_DELIVERY_VERIFIED`: Delivery verification distinguishes merge strategies:
  - **Normal / Ancestry-Preserving Merge**: Candidate SHA is verified as an ancestor of target base branch (`git merge-base --is-ancestor candidate_sha base_ref`).
  - **Squash Merge**: Verifies PR `is_merged == True`, repository/base identity is exact, PR head SHA equals audited candidate SHA, observed `merge_commit_sha` exists, and canonical base branch contains `merge_commit_sha`. Candidate non-ancestry after a verified squash merge is NOT a verification failure.
- Phase 3 `RUN_JOB_RECONCILED`: `OrchestrationRun` and `Job` transitioned to `POST_MERGE_RECONCILING`.
- Phase 4 `ISSUE_CLOSED`: Remote GitHub Issue closed. Action reserved with `status = RESERVED` before API PATCH.
- Phase 5 `PROJECT_ITEM_DONE`: Remote GitHub Project item status updated to "Done". Action reserved before GraphQL call.
- Phase 6 `SPEC_SYNCED`: `OpenSpecSyncService` syncs delta specs to main specs in `openspec/specs/`.
- Phase 7 `SYNC_VERIFIED`: `OpenSpecSyncService` verifies synced capabilities exist in main specs.
- Phase 8 `SPEC_ARCHIVED`: `OpenSpecSyncService` archives change to `openspec/changes/archive/`. Action reserved before filesystem move. Reconciles directory location on retry.
- Phase 9 `ARCHIVE_VERIFIED`: Verification confirms active change path is gone and archive path exists.
- Phase 10 `WORKTREE_CLEANED`: `WorktreeManager` cleans job worktree (Stage C 4-way reconciliation).
- Phase 11 `BRANCH_CLEANED`: Local and remote candidate branches deleted with postcondition checks.
- Phase 12 `LOCKS_RELEASED`: Ephemeral preview and execution locks released.
- Phase 13 `FINAL_CLOSED`: `LifecycleTransitionAuthority` transitions `Change` to `DONE` and `BacklogItem` to `COMPLETED`, `OrchestrationRun` to `COMPLETED`, `Job` to `COMPLETED`.

### G. Terminal Domain State != Saga Closure

Closure completion requires the complete required durable evidence set. A single terminal domain flag (`Change.DONE`, `BacklogItem.COMPLETED`, `Run.COMPLETED`) NEVER automatically proves `ClosureSaga` completion.

1. **Intake Terminal Rule**: If work identity is terminal (`COMPLETED`, `DONE`, `CANCELLED`):
   - Never reopen.
   - Never re-admit.
   - Never restart intake preparation.

2. **Closure Terminal Reconciliation Rule**: If Change, BacklogItem, Run, or Job is already terminal BUT `ClosureSaga` evidence is incomplete:
   - **DO NOT** resurrect work.
   - **DO NOT** infer closure success.
   - Enter **reconciliation-only mode**: inspect/check missing closure postconditions.
   - Adopt already-completed external effects where proven.
   - Complete saga ONLY after complete required evidence set exists.
   - If evidence cannot be safely reconstructed, remain `BLOCKED` / `NEEDS_HUMAN`.

### H. Stage F Boundary Separation

Stage D scope guarantees:
- Durable saga identity (`DurableSagaModel`).
- Deterministic action identity (`action_key` global uniqueness constraint).
- Sequential and repeated resume idempotency (`resume_saga()` acquires row lock).
- Reconcile-before-repeat protocol.
- Crash recovery from persisted checkpoints.

**Stage F Scope Deferral**: Comprehensive multi-worker concurrency race proving, distributed lock manager convergence, and high-frequency parallel worker admission contracts are explicitly deferred to `Stage F — transaction-and-concurrency-contract`. Row locking (`SELECT ... FOR UPDATE`) in Stage D serves as a minimal prerequisite mechanism, not full Stage F closure.

---

## Finite Discovery Matrix (25 Surfaces)

| # | Surface / Entry Point | Current Durable State | External Mutations | Existing Op ID | Retry Behavior | Reconciliation | Checkpoint / Evidence | Duplicate Risk | Crash Window | Current Writer | Required Stage D Correction | Stage D Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Intake API entry points (`src/minime/api/app.py`) | `BacklogItemModel` status | GitHub Issue, Project item, OpenSpec files | None in API | Reruns `prepare_work_item` | None in API layer | API params | High | Post-remote / pre-DB | `IntakeService` | Wrap API intake in `IntakeSaga` handle | `NEEDS_CHANGE` |
| 2 | `IntakeService` (`src/minime/services/intake_service.py`) | `backlog_items` DB table | GitHub Issue, Project item, OpenSpec files | In-memory keys | Retries start from step 1 | In-memory check | `readiness_state` | High | Across phases | `IntakeService` | Refactor into phase-checkpointed `IntakeSaga` | `NEEDS_CHANGE` |
| 3 | Context / discovery preparation (`context_discovery_service.py`) | `changes` DB table (`DISCOVERED`) | Read-only scan of `docs/ROADMAP.md` | None | Safe re-scan | Overwrites/reads files | `discovered_at` | Low | Safe | `DiscoveryService` | Align as Intake Saga phase `DISCOVERY_CHECK` | `ALREADY_COMPLIANT` |
| 4 | Backlog / work-item persistence (`db/repository.py`) | `backlog_items` DB table | None (PostgreSQL DB) | `item_key` + `project_id` | Atomic DB CAS | DB rowcount verification | `WorkItemStatus` | None | DB transaction | `LifecycleTransitionAuthority` | Standard DB repository pattern | `ALREADY_COMPLIANT` |
| 5 | GitHub Issue creation/binding (`prepare_work_item`) | `BacklogItem.github_issue_number` | Remote GitHub REST API `POST /issues` | Deterministic `operation_key` | Calls `create_issue` again | `<!-- minime-opkey: ... -->` comment marker search | `github_issue_number` | High | Post-HTTP / pre-DB | `IntakeService` + `GitHubAdapter` | Reserve `OrchestrationExternalAction` BEFORE call; reconcile via comment marker on retry. Title-only forbidden. | `NEEDS_CHANGE` |
| 6 | GitHub Project item creation/binding (`prepare_work_item`) | `BacklogItem.github_project_item_id` | Remote GitHub GraphQL API `addProjectV2Item` | Deterministic `operation_key` | Calls `add_issue_to_project` again | Exact issue URL + project number lookup | `github_project_item_id` | Medium/High | Post-GraphQL / pre-DB | `IntakeService` + `GitHubAdapter` | Reserve `OrchestrationExternalAction` BEFORE call; query project item on retry. Fuzzy matching forbidden. | `NEEDS_CHANGE` |
| 7 | OpenSpec change authoring (`prepare_work_item`) | OpenSpec files on disk & `ChangeModel` | Filesystem writes in `openspec/changes/{change}` | `openspec_change_name` | Overwrites files (`overwrite=True`) | Checks file existence | `ChangeModel` in DB | Low | Partial file write | `OpenSpecGenerator` + `IntakeService` | Reserve `OrchestrationExternalAction` for authoring phase; verify file integrity | `NEEDS_CHANGE` |
| 8 | Readiness/preparation completion (`prepare_work_item`) | `BacklogItem.readiness_state` | Read-only DoR evaluation | None | Safe re-evaluation | Re-checks DoR rules | `ReadinessEvaluation` | None | Safe | `ReadinessService` | Checkpoint readiness evidence reference in `IntakeSaga` | `NEEDS_CHANGE` |
| 9 | Scheduler handoff boundary (`start_work_item`) | `BacklogItem.status`, `OrchestrationRunModel` | DB record creation | `run_id`, DB index | Reuses active run | DB unique index check | `uq_active_orchestration_run` | None | DB transaction | `SchedulerService` | Clean handoff boundary from `IntakeSaga` to `SchedulerService` | `ALREADY_COMPLIANT` |
| 10 | Merge observation (`post_merge_service.py`) | `Event` (`MERGE_DETECTED`) | Read-only GitHub REST API query | `pr_number` / branch | Safe re-query | Queries PR details (`is_merged`) | `pr_details` dict | None | Safe | `PostMergeReconciliationService` | Bind PR merge observation as Phase 1 of `ClosureSaga` | `NEEDS_CHANGE` |
| 11 | `PostMergeReconciliationService` (`post_merge_service.py`) | `OrchestrationRun.current_stage` | Issue close, Project item, Spec sync/archive, cleanups | Linear in-memory execution | Retries rerun uncheckpointed steps | Partial phase string checks | `stage == COMPLETED` | High | Across closure steps | `PostMergeReconciliationService` | Refactor into phase-checkpointed `ClosureSaga` | `NEEDS_CHANGE` |
| 12 | Run terminal reconciliation (`reconcile_post_merge`) | `OrchestrationRunModel` (`COMPLETED`) | None (PostgreSQL DB) | `run_id` | Checks `stage == COMPLETED` | Returns `already_closed` | `OrchestrationRunModel` | Low | Pre-DB commit | `PostMergeReconciliationService` | Transition run to `COMPLETED` only after `ClosureSaga` phase verification | `NEEDS_CHANGE` |
| 13 | Job terminal reconciliation (`reconcile_post_merge`) | `JobModel` (`COMPLETED`) | None (PostgreSQL DB) | `job_id` | Idempotent DB update | Sets status `COMPLETED` | `JobModel.status` | None | DB transaction | `PostMergeReconciliationService` | Align Job status update with Closure Saga final checkpoint | `NEEDS_CHANGE` |
| 14 | Change terminal transition (`_reconcile_change...`) | `ChangeModel.status` (`DONE`) | DB update + Event emission | `Change.id` CAS update | Idempotent CAS | Atomic CAS query | `ChangeStatus.DONE` | None | DB transaction | `LifecycleTransitionAuthority` | Invoked by Closure Saga upon closure verification | `ALREADY_COMPLIANT` |
| 15 | BacklogItem terminal transition (`_reconcile_change...`) | `BacklogItemModel.status` (`COMPLETED`) | DB update + Event emission | `BacklogItem.id` CAS update | Idempotent CAS | Atomic CAS query | `WorkItemStatus.COMPLETED` | None | DB transaction | `LifecycleTransitionAuthority` | Invoked by Closure Saga upon closure verification | `ALREADY_COMPLIANT` |
| 16 | GitHub Issue closure (`reconcile_post_merge`) | `Event` (`ISSUE_CLOSED`) | Remote GitHub REST API `PATCH /issues/{num}` | None reserved | Retries `close_issue` | None | API response bool | Low/Medium | Post-HTTP / pre-event | `PostMergeReconciliationService` + `GitHubAdapter` | Reserve `OrchestrationExternalAction` for `ISSUE_CLOSE`; query issue state on retry | `NEEDS_CHANGE` |
| 17 | GitHub Project item completion (`reconcile_post_merge`) | `Event` (`PROJECT_ITEM_DONE`) | Remote GitHub GraphQL API status update | None reserved | Retries GraphQL update | None | API response bool | Low/Medium | Post-GraphQL / pre-event | `PostMergeReconciliationService` + `GitHubAdapter` | Reserve `OrchestrationExternalAction` for `PROJECT_ITEM_DONE`; query status on retry | `NEEDS_CHANGE` |
| 18 | OpenSpec Spec Sync (`reconcile_post_merge`) | Main spec files on disk | Filesystem writes in `openspec/specs/` | None reserved | Re-executes spec sync | Syncs delta specs into main specs | `sync_res.data` | Medium | Partial file write | `OpenSpecSyncService` | Reserve `OrchestrationExternalAction` for `SPEC_SYNC`; verify sync idempotency | `NEEDS_CHANGE` |
| 19 | OpenSpec Spec Sync Verification (`reconcile_post_merge`) | `Event` (`POST_MERGE_SYNC_VERIFIED`) | Read-only check of main spec files | None | Safe re-verification | Verifies delta specs in main specs | `verify_sync_res.data` | None | Safe | `OpenSpecSyncService` | Checkpoint sync verification evidence in `ClosureSaga` | `NEEDS_CHANGE` |
| 20 | OpenSpec Archive (`reconcile_post_merge`) | Directory move (`changes` -> `archive`) | Filesystem move (`shutil.move`) | None reserved | Rerun fails if source moved | Checks archive folder | `archive_res.data` | High | Post-move / pre-DB | `OpenSpecSyncService` | Reserve `OrchestrationExternalAction` for `SPEC_ARCHIVE`; reconcile archive path on retry | `NEEDS_CHANGE` |
| 21 | OpenSpec Archive Verification (`reconcile_post_merge`) | `Event` (`POST_MERGE_ARCHIVE_VERIFIED`) | Read-only check of filesystem | None | Safe re-verification | Verifies source gone & archive exists | `verify_arc_res.data` | None | Safe | `OpenSpecSyncService` | Checkpoint archive verification evidence in `ClosureSaga` | `NEEDS_CHANGE` |
| 22 | Worktree cleanup (`_clean_worktrees`) | `OrchestrationWorktreeOwnershipModel` | Filesystem delete + `git worktree remove` | `job_id` worktree path | Returns `ALREADY_ABSENT` if missing | Verifies path non-existence | Path check | Low | Post-delete / pre-DB | `WorktreeManager` | Checkpoint `WORKTREE_CLEANUP` phase in `ClosureSaga` | `ALREADY_COMPLIANT` |
| 23 | Branch cleanup (`_delete_local_branch`) | `Event` (`BRANCH_CLEANED`) | `git branch -D` & API delete | None | Local check uses `git show-ref` | Postcondition via `git show-ref` | `show-ref` exit code 1 | Low | Post-delete / pre-event | `PostMergeReconciliationService` + `GitHubAdapter` | Checkpoint `BRANCH_CLEANUP` phase in `ClosureSaga` | `ALREADY_COMPLIANT` |
| 24 | Recovery / startup integration (`restart_recovery_service.py`) | `Event` (`DAEMON_RESTARTED`) | Removes orphaned Git locks (with proof) | `recovery_cycle_id` | Safe startup reconciliation | Inspects active jobs and runs | `active_jobs`, `active_runs` | Low | Safe | `RestartRecoveryService` | Recover & resume pending `IntakeSaga` & `ClosureSaga` from DB checkpoints | `NEEDS_CHANGE` |
| 25 | Control-plane / manual resume paths (`control_plane_service.py`) | `OperatorActionRecordModel` | Invokes `resume()` or updates states | `action_request_id` | Operator action recorded | Checks precondition stage/gate | `precondition_stage` / `gate` | Low | Pre-dispatch | `ControlPlaneService` | Integrate control-plane resume to trigger `SagaEngine.resume_saga(saga_id)` | `NEEDS_CHANGE` |

**Summary Matrix Counts**:
- `ALREADY_COMPLIANT`: **7** (Surfaces 3, 4, 9, 14, 15, 22, 23)
- `NEEDS_CHANGE`: **18** (Surfaces 1, 2, 5, 6, 7, 8, 10, 11, 12, 13, 16, 17, 18, 19, 20, 21, 24, 25)
- `OUT_OF_SCOPE`: **0**

---

## Database Design

### 1. New Table: `DurableSagaModel` (`durable_sagas`)

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

    external_actions: Mapped[list[OrchestrationExternalActionModel]] = relationship(
        "OrchestrationExternalActionModel", back_populates="saga", cascade="all, delete-orphan"
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

### 2. Schema Evolution for Single External Action Authority (`OrchestrationExternalActionModel`)

```python
class OrchestrationExternalActionModel(Base):
    __tablename__ = "orchestration_external_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Generalization: run_id made nullable to support saga-bound actions without runs
    run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Generalization: saga_id added to associate actions with durable sagas
    saga_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("durable_sagas.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    action_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Generalization: candidate_sha made nullable for intake actions
    candidate_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="RESERVED", nullable=False, index=True) # RESERVED, EXECUTING, COMPLETED, FAILED, UNKNOWN, AMBIGUOUS
    remote_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
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

    run: Mapped[OrchestrationRunModel | None] = relationship(
        "OrchestrationRunModel", back_populates="external_actions"
    )
    saga: Mapped[DurableSagaModel | None] = relationship(
        "DurableSagaModel", back_populates="external_actions"
    )
```

---

## Transaction Boundaries

To guarantee Architectural Law 4 without holding open long database locks across external network calls, every saga action step MUST follow this exact 6-step transactional protocol:

1. **Step 1 — Action Reservation (DB Commit)**:
   - Create/update `OrchestrationExternalActionModel` with `action_key`, `target_identity`, `request_fingerprint`, `saga_id`, and `status = RESERVED`.
   - Update `DurableSagaModel` with `updated_at`.
   - **COMMIT DB TRANSACTION**.

2. **Step 2 — External Mutation Invocation (No DB Lock)**:
   - Option A: For simple calls, invoke adapter directly.
   - Option B: For tracked adapter calls, update action status to `EXECUTING` -> invoke remote adapter.

3. **Step 3 — Observation & Result Verification**:
   - If response received successfully: parse external outcome, extract `remote_identifier`.
   - If network call timed out or threw unhandled error: enter RECONCILE BEFORE RETRY phase by calling `OrchestrationExternalActionRepository.reconcile_observe_before_repeat()` using target identity and Stage B exact markers (`<!-- minime-opkey: ... -->`).

4. **Step 4 — Result Persistence (DB Commit)**:
   - Begin DB transaction.
   - Update `OrchestrationExternalActionModel` with `status = COMPLETED` (or `FAILED` / `AMBIGUOUS`), `remote_identifier`, `result_payload`, and `reconciled_at = utc_now()`.
   - **COMMIT DB TRANSACTION**.

5. **Step 5 — Saga Checkpoint Advancement (DB Commit)**:
   - Begin DB transaction.
   - Update `DurableSagaModel` `current_phase` to next phase and update `evidence_references`.
   - Save corresponding `Event` record (`DURABLE_SAGA_PHASE_ADVANCED`) in same transaction.
   - **COMMIT DB TRANSACTION**.

6. **Step 6 — Final Saga Closure Gate (DB Commit)**:
   - When all required phases reach `COMPLETED` action evidence:
   - Invoke `LifecycleTransitionAuthority.transition_change()` and `transition_backlog_item()` to update terminal states atomically.
   - Update `DurableSagaModel` `status = COMPLETED`.
   - **COMMIT DB TRANSACTION**.

---

## Crash-Window Analysis (8 Explicit Cases Using Canonical Statuses)

1. **Case 1: Crash after reservation but before external call**:
   - *State*: `OrchestrationExternalActionModel` is `RESERVED` in DB, but external HTTP request was not sent.
   - *Recovery*: Saga engine reads `RESERVED` action on startup. Delegates to `reconcile_observe_before_repeat()` against external target using Stage B comment marker / URL. Search returns non-occurrence. Saga engine proceeds to execute external mutation safely.

2. **Case 2: Remote effect occurred but response/result persistence was lost**:
   - *State*: GitHub API created issue #42 with `<!-- minime-opkey: issue_create:proj1:feat-a -->` in body, but daemon crashed before receiving HTTP response body or saving result.
   - *Recovery*: `OrchestrationExternalActionModel` is `RESERVED` or `EXECUTING`. On restart, `reconcile_observe_before_repeat()` searches GitHub repo for issues containing `<!-- minime-opkey: issue_create:proj1:feat-a -->`. Finds issue #42. Adopts issue #42 as `remote_identifier`, updates action status to `COMPLETED` (setting `reconciled_at`), advances checkpoint without creating a duplicate issue. Title-only search is forbidden.

3. **Case 3: External effect positively observed**:
   - *State*: External call succeeded or reconciliation observed pre-existing resource.
   - *Recovery*: Action status transitions to `COMPLETED`, `remote_identifier` is recorded, `reconciled_at` timestamp is saved, and saga advances phase. `COMPLETED` action is never re-executed.

4. **Case 4: Completed action with saga phase not advanced**:
   - *State*: `OrchestrationExternalActionModel` is saved as `COMPLETED` with issue #42, but `DurableSagaModel.current_phase` is still `OPENSPEC_AUTHORED`.
   - *Recovery*: On restart, saga engine inspects `OrchestrationExternalActionModel` for phase `ISSUE_BOUND`, sees `status == COMPLETED`, skips remote mutation entirely, advances `DurableSagaModel.current_phase` to `ISSUE_BOUND`, and proceeds to next phase (`PROJECT_ITEM_BOUND`).

5. **Case 5: Restart after phase advancement**:
   - *State*: `DurableSagaModel.current_phase` is `SPEC_ARCHIVED`.
   - *Recovery*: On restart, saga engine loads `DurableSagaModel`, sees `current_phase == SPEC_ARCHIVED`, skips all preceding completed phases (spec sync, archive), and resumes at phase `ARCHIVE_VERIFIED` -> `WORKTREE_CLEANED`.

6. **Case 6: Repeated resume command**:
   - *State*: Operator triggers `/api/v1/control-plane/sagas/{saga_id}/resume` multiple times concurrently or sequentially.
   - *Recovery*: `SagaEngine` acquires row lock on `DurableSagaModel` using atomic `SELECT ... FOR UPDATE`. If saga is already `COMPLETED` or active on worker, subsequent calls execute sequentially and return current status idempotently.

7. **Case 7: Effect cannot be determined (unobservable)**:
   - *State*: GitHub API returns 503 Service Unavailable or times out during reconciliation.
   - *Recovery*: Saga engine CANNOT establish occurrence or non-occurrence. Action `status` becomes/remains `AMBIGUOUS` (or `UNKNOWN` for read failures). `DurableSagaModel.status` transitions to `BLOCKED` with `blocking_reason`. Emits `DURABLE_SAGA_BLOCKED` event. Daemon does NOT fabricate success or retry blindly; waits for next scheduled sweep or operator resume.

8. **Case 8: Terminal domain flag with incomplete saga evidence**:
   - *State*: `ChangeModel` is `DONE` or `JobModel` is `COMPLETED`, but `ClosureSaga` evidence is incomplete (e.g. OpenSpec spec sync or archive was interrupted).
   - *Recovery*: Saga engine DOES NOT infer closure completion and DOES NOT reopen terminal domain entities. It enters **reconciliation-only mode**: checks missing closure postconditions, adopts already-completed effects where proven, and completes saga ONLY when complete required evidence set exists; if evidence cannot be safely reconstructed, saga remains `BLOCKED` / `NEEDS_HUMAN`.

---

## Test Strategy

Targeted verification scenarios to implement in `tests/test_durable_sagas.py`:

1. **Intake Restart Between Every Phase**: Test daemon restart after each of the 7 intake phases; verify saga resumes from exact persisted checkpoint without repeating prior steps.
2. **Closure Restart Between Every Phase**: Test daemon restart after each of the 13 closure phases; verify saga resumes from exact persisted checkpoint without repeating prior steps.
3. **Duplicate Issue Prevention via Stage B Comment Marker**: Simulate crash post-GitHub Issue creation; verify retry reconciles existing issue via `<!-- minime-opkey: ... -->` marker search and creates ZERO duplicate issues. Title-only deduplication failure tested.
4. **Duplicate Project Item Prevention via Exact Issue URL**: Simulate crash post-GraphQL project item creation; verify retry adopts existing project item via exact issue URL lookup without duplicate addition. Fuzzy title matching failure tested.
5. **Squash Merge Delivery Verification**: Test closure saga delivery verification when PR was squash merged; verify `MERGED_DELIVERY_VERIFIED` checks `is_merged == True`, exact repo/base identity, candidate SHA matching PR head SHA, and presence of `merge_commit_sha` on base branch without raising non-ancestry failure.
6. **Ancestry-Preserving Merge Delivery Verification**: Test closure saga delivery verification when PR was fast-forward or normal merged; verify `git merge-base --is-ancestor candidate_sha base_ref` passes.
7. **Terminal Domain Flag + Incomplete Saga Evidence != Closure Success**: Test change marked `DONE` in DB with incomplete `ClosureSaga` evidence; verify saga DOES NOT infer closure success, enters reconciliation-only mode, and remains `BLOCKED` until all 12 closure phase evidence records exist.
8. **Terminal Domain Work Never Re-opened During Intake**: Test intake preparation trigger on `COMPLETED` backlog item; verify request is rejected with `POLICY_DENIED`.
9. **Single External Action Authority & Ownership Invariant Verification**: Verify all saga actions reserve records in `orchestration_external_actions` table with deterministic `action_key` uniqueness constraint, and no separate `saga_actions` table exists. Verify creating an action with neither `run_id` nor `saga_id` raises a validation error.
10. **Canonical Status Verification**: Verify action status transitions follow `RESERVED` -> `COMPLETED` / `FAILED` / `AMBIGUOUS`, and `SUCCESS` / `RECONCILED` are NOT persisted status values.
11. **Fail-Closed on Unobservable State**: Verify HTTP 500/503 during reconciliation sets action to `AMBIGUOUS` and saga to `BLOCKED` without guessing success.
12. **Completed Phases Not Re-executed**: Verify completed phases with `COMPLETED` action records are skipped during saga resume.
13. **Repeated Resume Idempotency**: Verify calling `resume_saga()` multiple times sequentially produces identical final state without side effects.
14. **Partially Completed Closure Blocked**: Verify closure saga lacking required phase evidence (e.g. sync unverified) stops at `WAIT_EXTERNAL` or `BLOCKED` and does NOT transition Change to `DONE`.
15. **Idempotent OpenSpec Spec Sync**: Verify retrying OpenSpec spec sync phase does not duplicate spec sections in `openspec/specs/`.
16. **Idempotent OpenSpec Archive**: Verify retrying OpenSpec archive when active change directory is already moved reconciles archive destination safely without raising `FileNotFoundError`.
17. **Worktree Cleanup Idempotency**: Verify worktree cleanup returns `ALREADY_ABSENT` safely when worktree directory is already deleted.
18. **Branch Cleanup Idempotency**: Verify local and remote branch cleanup handle `ALREADY_ABSENT` gracefully on retry.
19. **Daemon Startup Recovery Sweep**: Test `RestartRecoveryService.reconcile_on_startup()` discovering and resuming interrupted `INTAKE` and `CLOSURE` sagas.
20. **Control-Plane Saga Resume Integration**: Test triggering manual saga resume via `ControlPlaneService` endpoint.
