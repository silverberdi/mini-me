# Spec: Autonomous Post-Merge Closure

## Requirement: Merge Detection and Ancestry Proof
The orchestrator SHALL autonomously detect when an active PR is merged, extract merge details, and verify candidate ancestry against the base branch.

### Scenarios

#### Scenario: Merged PR Detection and Ancestry Verification
- GIVEN an active `OrchestrationRun` in `READY_FOR_HUMAN_MERGE` with an open PR on GitHub,
- WHEN the human merges the PR on GitHub and the post-merge service executes,
- THEN the system SHALL:
  1. Query GitHub for the PR merge status and confirm `merged == True`,
  2. Extract `merged_by`, `merged_at`, and `merge_commit_sha`,
  3. Verify via `git merge-base --is-ancestor` that the candidate SHA is an ancestor of the base branch or merge commit,
  4. Persist durable merge detection evidence in PostgreSQL.

## Requirement: Terminal State Reconciliation
The orchestrator SHALL transition the `OrchestrationRun` and execution `Job` to terminal completed states.

### Scenarios

#### Scenario: Autonomous Terminal State Transition
- GIVEN a verified merge for an active `OrchestrationRun`,
- WHEN post-merge reconciliation executes,
- THEN the system SHALL:
  1. Transition `OrchestrationRun.current_stage` to `COMPLETED`,
  2. Set `OrchestrationRun.stop_outcome` to `COMPLETED`,
  3. Set `OrchestrationRun.is_active` to `False`,
  4. Set `Job.status` to `COMPLETED`,
  5. Record stage transition and completion events.

## Requirement: External Work Management Closure
The orchestrator SHALL close the linked GitHub Issue and update the linked GitHub Project item to Done.

### Scenarios

#### Scenario: GitHub Issue Closure and Project Item Update
- GIVEN an active work binding with a linked GitHub Issue number and Project item ID,
- WHEN post-merge reconciliation executes,
- THEN the system SHALL:
  1. Close the GitHub Issue with state `closed` and reason `completed`,
  2. Update the GitHub Project V2 item status field to `Done`,
  3. Record completion events with zero errors.

## Requirement: Native OpenSpec Sync and Archive
The orchestrator SHALL synchronize delta specs to main specs and archive the change directory without external CLI dependencies.

### Scenarios

#### Scenario: Autonomous Spec Sync and Change Archival
- GIVEN an OpenSpec change with delta specs and completed tasks in `tasks.md`,
- WHEN post-merge reconciliation executes,
- THEN the system SHALL:
  1. Synchronize all delta specs in `specs/` into `openspec/specs/`,
  2. Validate that synchronized main specs contain all delta requirements and scenarios,
  3. Move the change directory to `openspec/changes/archive/{YYYY-MM-DD}-{change_name}`,
  4. Record sync and archive events in PostgreSQL.

## Requirement: Resource Cleanup and Idempotent Execution
The orchestrator SHALL clean up candidate worktrees, branches, and locks, and handle repeated executions idempotently.

### Scenarios

#### Scenario: Clean Teardown and Idempotent Re-execution
- GIVEN a completed post-merge run,
- WHEN the cleanup steps execute,
- THEN the system SHALL:
  1. Remove the managed candidate worktree,
  2. Delete local candidate branches and remote candidate branches where permitted,
  3. Release all associated database and filesystem locks,
  4. On any subsequent invocation of post-merge reconciliation on the same change, return immediately with `already_closed=True` without making duplicate external mutations.
