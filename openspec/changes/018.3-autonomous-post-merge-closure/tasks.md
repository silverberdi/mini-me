# Tasks: 018.3 Autonomous Post-Merge Closure

## 1. Domain Enums and Models
- [x] 1.1 Add post-merge enum values to `OrchestrationStage`, `JobStatus`, `OrchestrationStopOutcome`, and `EventType`
- [x] 1.2 Update domain models and unit tests for enum compatibility

## 2. GitHub Adapter Extensions
- [x] 2.1 Implement PR merge inspection in `GitHubAdapter` (`get_pull_request_details`)
- [x] 2.2 Implement issue closure (`close_issue`) and remote branch deletion (`delete_branch`)
- [x] 2.3 Implement Project V2 status updates (`update_project_item_status`)

## 3. Native OpenSpec Synchronization and Archive
- [x] 3.1 Implement native markdown delta spec synchronizer (`OpenSpecSyncService`)
- [x] 3.2 Implement OpenSpec archive manager with task completion verification

## 4. Post-Merge Reconciliation Service
- [x] 4.1 Implement `PostMergeReconciliationService` orchestrating the 12-phase post-merge closure
- [x] 4.2 Implement candidate ancestry verification with git merge-base
- [x] 4.3 Implement worktree, branch, preview, and lock cleanup
- [x] 4.4 Implement terminal state transitions for `OrchestrationRun` and `Job`
- [x] 4.5 Implement post-merge efficiency and timing telemetry persistence

## 5. Scheduler and Control Plane Integration
- [x] 5.1 Integrate post-merge detection and reconciliation into `SchedulerService.tick()`
- [x] 5.2 Add `RECONCILE_POST_MERGE` operator action to `ControlPlaneService`

## 6. Verification and Acceptance
- [x] 6.1 Unit tests for `PostMergeReconciliationService` and GitHub adapter methods
- [x] 6.2 Idempotency and crash-recovery simulation tests
- [x] 6.3 Run pytest and ruff check suite to verify clean pass
