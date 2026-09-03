# Design: 018.3 Autonomous Post-Merge Closure

## Architecture Overview
The post-merge closure subsystem consists of:
1. `PostMergeReconciliationService` (in `src/minime/services/post_merge_service.py`):
   - Responsible for orchestrating the multi-phase closure workflow.
   - Encapsulates discrete lifecycle steps into testable, idempotent methods.
2. `OpenSpecSyncService` / native OpenSpec utilities:
   - Synchronizes delta markdown specs into main specs under `openspec/specs/`.
   - Validates that requirements match before and after sync.
   - Moves change directory into `openspec/changes/archive/` with date prefix.
3. `GitHubAdapter` extensions:
   - `get_pull_request_details(repository: str, pr_number: int) -> dict[str, Any]` (detects `merged`, `merge_commit_sha`, `merged_by`, `merged_at`).
   - `close_issue(repository: str, issue_number: int, comment: str | None = None) -> bool`.
   - `update_project_item_status(project_number: int, owner: str, item_id: str, status: str = "Done") -> bool`.
   - `delete_branch(repository: str, branch: str) -> bool`.
4. Domain model additions:
   - `OrchestrationStage.POST_MERGE_RECONCILING = "POST_MERGE_RECONCILING"`
   - `OrchestrationStage.COMPLETED = "COMPLETED"`
   - `JobStatus.POST_MERGE_RECONCILING = "POST_MERGE_RECONCILING"`
   - `JobStatus.COMPLETED = "COMPLETED"`
   - `OrchestrationStopOutcome.COMPLETED = "COMPLETED"`
   - `EventType` post-merge event variants.
5. Scheduler and Control Plane integration:
   - `SchedulerService.tick()` inspects active runs waiting at `READY_FOR_HUMAN_MERGE` and checks whether the PR has been merged. If merged, invokes `PostMergeReconciliationService.reconcile_post_merge()`.
   - `ControlPlaneService` exposes `reconcile_post_merge` operator action for manual trigger or status queries.

## Idempotency & Recovery Pattern
- Each step checks the target state before performing mutations:
  - If PR not merged: no-op, remains in `READY_FOR_HUMAN_MERGE`.
  - If Issue already closed: logs and skips PATCH.
  - If Project item already Done: logs and skips GraphQL mutation.
  - If OpenSpec change already archived or specs already synced: skips file operations.
  - If branch or worktree already removed: skips deletion.
  - If run already `COMPLETED`: returns immediately with `already_closed=True`.
- Process interruptions during post-merge can be resumed from the start without duplicate side effects or error cascading.
