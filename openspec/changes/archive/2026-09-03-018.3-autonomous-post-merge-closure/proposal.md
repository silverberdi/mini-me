# Proposal: 018.3 Autonomous Post-Merge Closure

## Why
In the mini me autonomous software development lifecycle, human merge authorization remains mandatory, but all operational tasks after merge authorization must be completely autonomous. Currently, after a human authorizes and executes a merge on GitHub, manual supervisor intervention is required to recognize the merge, reconcile Run and Job state in PostgreSQL, close the GitHub Issue, mark the GitHub Project V2 item as Done, synchronize OpenSpec delta specs to main specs, archive the OpenSpec change directory, clean up local/remote branches and isolated worktrees, and release locks. This gap leaves active orchestration runs in limbo (`PR_PREPARED` / `READY_FOR_HUMAN_MERGE`) and requires manual bookkeeping.

## What Changes
- Implement `PostMergeReconciliationService` / `PostMergeDriver` to autonomously execute the post-merge lifecycle:
  1. **Merge Recognition & Executor Classification**: Detect merged PR status, merge commit SHA, merge timestamp, and executor identity via GitHub API.
  2. **Ancestry & Head Verification**: Verify that the candidate SHA is a verified ancestor of the updated base branch.
  3. **Terminal Run & Job Reconciliation**: Transition `OrchestrationRun` to `current_stage=COMPLETED`, `stop_outcome=COMPLETED`, `is_active=False`, and `Job` to `status=COMPLETED`.
  4. **GitHub Issue Closure**: Close linked GitHub Issue with `state_reason=completed` via GitHub App integration.
  5. **GitHub Project Item Closure**: Update GitHub Project V2 item status to "Done".
  6. **Native OpenSpec Sync**: Parse delta specs from `openspec/changes/{change}/specs/` and merge into `openspec/specs/` with strict validation.
  7. **Native OpenSpec Archive**: Validate task completion in `tasks.md` and move change directory to `openspec/changes/archive/{YYYY-MM-DD}-{change}`.
  8. **Clean Resource Teardown**: Remove managed worktree, prune/delete local candidate branch, delete remote candidate branch if policy permits, teardown preview container, and release locks.
  9. **Post-Merge Telemetry**: Persist post-merge metric facts and timing telemetry in PostgreSQL.
  10. **Idempotency**: Ensure rerunning the post-merge driver on an already closed change produces deterministic no-op behavior with zero duplicate external mutations.
- Integrate post-merge reconciliation into `SchedulerService.tick()`, `OrchestrationService`, and `ControlPlaneService`.
- Extend domain models and enums (`OrchestrationStage.POST_MERGE_RECONCILING`, `OrchestrationStage.COMPLETED`, `JobStatus.COMPLETED`, `OrchestrationStopOutcome.COMPLETED`, `EventType.POST_MERGE_COMPLETED`, etc.).

## Non-Goals
- Eliminating the human authorization merge gate (human merge is mandatory in MVP).
- Redesigning the TUI or PWA UI shells.
- Future roadmap work for 018.4 (metrics aggregation and multi-change proving).
