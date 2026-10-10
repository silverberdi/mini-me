# Autonomous Intake State Convergence Specification

## ADDED Requirements

### Requirement: Backlog Lifecycle Convergence
Prior to autonomous intake sweep during scheduler execution, the system MUST evaluate present evidence and converge persisted BacklogItem states to their authoritative lifecycle state via `LifecycleTransitionAuthority`.

#### SCENARIO: Delivered or Archived Change Convergence
- **GIVEN** a BacklogItem in state `READY`, `RUNNING`, `PREPARING`, or `BLOCKED`
- **WHEN** the corresponding OpenSpec change is archived on disk, marked `ChangeStatus.DONE`, or associated with a completed OrchestrationRun
- **THEN** the system MUST transition the BacklogItem state to `COMPLETED` via `LifecycleTransitionAuthority`.

#### SCENARIO: Cancelled Change Convergence
- **GIVEN** a BacklogItem in a non-terminal state
- **WHEN** the corresponding OpenSpec change is marked `ChangeStatus.CANCELLED` or the latest OrchestrationRun is cancelled
- **THEN** the system MUST transition the BacklogItem state to `CANCELLED` via `LifecycleTransitionAuthority`.

#### SCENARIO: Stale READY Artifact Disappearance Convergence
- **GIVEN** a BacklogItem in state `READY` with `readiness_state != READY` or whose active OpenSpec change directory no longer exists on disk (and is not archived/delivered)
- **WHEN** backlog lifecycle convergence executes
- **THEN** the system MUST transition the BacklogItem state from `READY` to `BLOCKED` via `LifecycleTransitionAuthority`.

#### SCENARIO: Autonomous Sweep of Converged Blocked Items
- **GIVEN** a BacklogItem in state `BLOCKED` that is eligible for autonomous preparation (e.g., non-ROADMAP or projected READY in ROADMAP)
- **WHEN** autonomous intake sweep executes
- **THEN** the system MUST transition the item from `BLOCKED` to `PREPARING` via `LifecycleTransitionAuthority` and execute `prepare_work_item()`.
