## MODIFIED Requirements

### Requirement: Native OpenSpec Sync and Archive
The orchestrator SHALL synchronize delta specs to main specs and archive the change directory without external CLI dependencies, SHALL verify that sync completed successfully by confirming canonical specs contain synchronized requirements before declaring sync done, and SHALL verify that the archive operation removed the change from active changes and preserved the archive artifact intact before declaring archive done.

#### Scenario: Autonomous Spec Sync and Change Archival
- GIVEN an OpenSpec change with delta specs and completed tasks in `tasks.md`,
- WHEN post-merge reconciliation executes,
- THEN the system SHALL:
  1. Synchronize all delta specs in `specs/` into `openspec/specs/`,
  2. Validate that synchronized main specs contain all delta requirements and scenarios,
  3. Move the change directory to `openspec/changes/archive/{YYYY-MM-DD}-{change_name}`,
  4. Record sync and archive events in PostgreSQL.

#### Scenario: Sync failure blocks completion

- GIVEN an OpenSpec change whose delta spec synchronization fails due to a merge conflict, missing main spec directory, or filesystem error
- WHEN post-merge reconciliation executes the sync phase
- THEN the system SHALL record the sync failure with the specific error
- AND SHALL NOT advance to the archive phase
- AND SHALL NOT transition the run or job to COMPLETED
- AND the run SHALL remain recoverable for retry.

#### Scenario: Archive verification confirms change removed from active

- GIVEN a change whose archive operation has completed
- WHEN post-merge reconciliation verifies the archive
- THEN the system SHALL confirm the change directory no longer exists under `openspec/changes/`
- AND SHALL confirm the archive artifact exists at `openspec/changes/archive/{YYYY-MM-DD}-{change_name}/`
- AND SHALL record the archive verification result before declaring the phase complete.

#### Scenario: Archive target collision detected

- GIVEN a change whose archive target directory already exists
- WHEN the archive operation executes
- THEN the system SHALL fail the archive with a structured error identifying the collision
- AND SHALL NOT overwrite the existing archive
- AND the change SHALL remain active and recoverable.

### Requirement: Terminal State Reconciliation
The orchestrator SHALL transition the `OrchestrationRun` and execution `Job` to terminal completed states only after all required post-merge phases have completed with verified evidence, and SHALL require sync and archive verification evidence before declaring terminal completion.

#### Scenario: Autonomous Terminal State Transition
- GIVEN a verified merge for an active `OrchestrationRun`,
- WHEN post-merge reconciliation executes and all phases complete with verified evidence,
- THEN the system SHALL:
  1. Transition `OrchestrationRun.current_stage` to `COMPLETED`,
  2. Set `OrchestrationRun.stop_outcome` to `COMPLETED`,
  3. Set `OrchestrationRun.is_active` to `False`,
  4. Set `Job.status` to `COMPLETED`,
  5. Record stage transition and completion events.

#### Scenario: Terminal state blocked by missing sync evidence

- GIVEN a verified merge for an active `OrchestrationRun` where the sync phase produced no evidence or was skipped
- WHEN post-merge reconciliation attempts terminal state transition
- THEN the system SHALL NOT transition to `COMPLETED`
- AND SHALL stop with the specific missing evidence identified
- AND the run SHALL remain recoverable for retry.

#### Scenario: Terminal state blocked by missing archive evidence

- GIVEN a verified merge and successful sync where the archive phase produced no evidence or failed
- WHEN post-merge reconciliation attempts terminal state transition
- THEN the system SHALL NOT transition to `COMPLETED`
- AND SHALL stop with the specific missing evidence identified
- AND the run SHALL remain recoverable for retry.