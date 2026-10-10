# Design: Autonomous Intake Persisted State Convergence

## Architecture & Design Decisions

### 1. WorkItem Lifecycle Transition Matrix & Evidence Enforcement
In `LifecycleTransitionAuthority` (`src/minime/services/lifecycle_transition_authority.py`):
Extend `ALLOWED_WORK_ITEM_TRANSITIONS[WorkItemStatus.READY]` and `[WorkItemStatus.BLOCKED]` to include `WorkItemStatus.COMPLETED`.
Enforce that any transition to `WorkItemStatus.COMPLETED` requires an authoritative completion `reason_code`:
- `canonical_completion_evidence`
- `post_merge_completion`
- `post_merge_reconciled`
- `manual_completion_authority`

Arbitrary string reason codes for completion transitions are rejected with `LifecycleInvalidTransitionError`.

### 2. Backlog Lifecycle Convergence & Evidence Precedence
In `IntakeService` (`src/minime/services/intake_service.py`):
Implement `reconcile_and_persist_backlog_items(project_id: str | None = None) -> list[BacklogItem]`:
- Iterates backlog items for the given project(s).
- Evaluates evidence in strict authoritative precedence:
  1. Delivered / Archive / `ChangeStatus.DONE` evidence -> `COMPLETED`
  2. Cancellation evidence (`ChangeStatus.CANCELLED` or cancelled run) -> `CANCELLED`
  3. Physical active change directory absence or invalid readiness for `READY` items -> `BLOCKED` (`stale_ready_artifacts_missing`)
- Physical artifact presence and archive directories are checked at `_resolve_project_root(project) / project.openspec_path / ...`, which uses `managed_repository_root` from the canonical project binding when present and valid, falling back to `self.project_root` for unmanaged/legacy/test scenarios.

### 3. Exact Archive Identity Matching
In `IntakeService.reconcile_and_persist_backlog_items()`:
- Archive directories in `openspec/changes/archive/` are parsed using `extract_canonical_archived_change_name()`:
  - If directory name follows `YYYY-MM-DD-change-name` (10-char date prefix), the canonical change name `change-name` is extracted.
  - Otherwise the exact folder name is used.
- Matching performs strict exact equality (`change_name == archived_name`). Suffix matching (`endswith`) and fuzzy matching are forbidden to prevent identity collisions (e.g. `provider-safety` vs `safety`).

### 4. Structural Allow-List Retry Eligibility & Loop Prevention
In `IntakeService.is_blocked_retry_eligible(item)`:
- Returns `True` ONLY if `unmet_readiness_reasons` contains EXACTLY `["stale_ready_artifacts_missing"]`.
- Returns `False` if any other blocker, combination of blockers, or empty set is present.
- Prevents infinite loops: After re-preparation, if DoR evaluation fails, specific DoR reasons replace `stale_ready_artifacts_missing`, making the item ineligible for further autonomous sweeps.

### 5. Safe Adapter Dependency Resolution
In `SchedulerService.__init__` (`src/minime/services/scheduler_service.py`):
- Accepts optional explicit `openspec_adapter` and `github_adapter` parameters.
- Uses `resolve_explicit_adapter(target_service, attr_name)` helper to inspect `readiness_service`:
  - For `Mock`/`MagicMock` instances: returns the attribute ONLY if explicitly assigned (in `_mock_children` or `__dict__`), preventing bare `MagicMock` instances from auto-synthesizing child mocks.
  - For non-`Mock` objects (concrete instances, custom fake classes, wrappers, protocols): returns standard `getattr` without enforcing concrete inheritance.

### 6. Scheduler Execution Ordering
In `SchedulerService.tick()` (`src/minime/services/scheduler_service.py`):
1. `0.0` Provider health probe
2. `0.01` Recovery convergence cycle (`recovery_convergence_service.reconcile_cycle()`)
3. `0.02` Backlog lifecycle convergence (`intake_service.reconcile_and_persist_backlog_items()`)
4. `0.1` Autonomous intake sweep (`intake_service.sweep_unprepared_backlog_items()`)
5. `1.0` Work discovery (`discovery_service.discover_work()`)
6. `2.0 - 4.0` Ranking and admission evaluation
