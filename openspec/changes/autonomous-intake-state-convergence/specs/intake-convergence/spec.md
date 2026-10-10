# Autonomous Intake State Convergence Specification

## ADDED Requirements

### Requirement: Backlog Lifecycle Convergence
Prior to autonomous intake sweep during scheduler execution, the system MUST evaluate present evidence and converge persisted BacklogItem states to their authoritative lifecycle state via `LifecycleTransitionAuthority`.

#### SCENARIO: Delivered or Archived Change Convergence
- **GIVEN** a BacklogItem in state `READY`, `RUNNING`, `PREPARING`, or `BLOCKED`
- **WHEN** the corresponding OpenSpec change is archived on disk (matched by exact canonical change name), marked `ChangeStatus.DONE`, or associated with a completed OrchestrationRun
- **THEN** the system MUST transition the BacklogItem state to `COMPLETED` via `LifecycleTransitionAuthority` with reason `canonical_completion_evidence`.

#### SCENARIO: Cancelled Change Convergence
- **GIVEN** a BacklogItem in a non-terminal state
- **WHEN** the corresponding OpenSpec change is marked `ChangeStatus.CANCELLED` or the latest OrchestrationRun is cancelled
- **THEN** the system MUST transition the BacklogItem state to `CANCELLED` via `LifecycleTransitionAuthority` with reason `canonical_cancellation_evidence`.

#### SCENARIO: Physical Active Artifact Absence and Stale READY Convergence
- **GIVEN** a BacklogItem in state `READY` whose active OpenSpec change directory does not exist on disk in the canonical location or whose `readiness_state` is not `READY`
- **WHEN** backlog lifecycle convergence executes and the change is not archived, completed, or cancelled
- **THEN** the system MUST transition the BacklogItem state from `READY` to `BLOCKED` via `LifecycleTransitionAuthority` with reason `stale_ready_artifacts_missing`. Physical artifact absence MUST NOT be overridden by a persisted `ReadinessState.READY`.

#### SCENARIO: Exact Synthetic Stale-Artifact Retry Eligibility Allow-List
- **GIVEN** a BacklogItem in state `BLOCKED`
- **WHEN** autonomous intake sweep evaluates retry eligibility via `is_blocked_retry_eligible()`
- **THEN** the system MUST return `True` ONLY if `unmet_readiness_reasons` contains EXACTLY the single normalized element `["stale_ready_artifacts_missing"]`. If any additional or different blocker is present (including auth, budget, capacity, human, or dependency blockers), the system MUST return `False`.

#### SCENARIO: Single-Cycle Re-evaluation and Infinite Loop Prevention
- **GIVEN** a `BLOCKED` BacklogItem with `unmet_readiness_reasons = ["stale_ready_artifacts_missing"]` that is swept into `PREPARING`
- **WHEN** `prepare_work_item()` runs Definition of Ready (DoR) evaluation and DoR fails
- **THEN** the system MUST overwrite `unmet_readiness_reasons` with the specific failed DoR reasons, clearing `stale_ready_artifacts_missing`, ensuring subsequent scheduler ticks DO NOT autonomously re-sweep the item into `PREPARING`.

#### SCENARIO: Exact Archive Identity Matching
- **GIVEN** an archived directory in `openspec/changes/archive/` (e.g. `2026-10-08-provider-safety`)
- **WHEN** archive matching executes
- **THEN** the system MUST parse the 10-character date prefix to extract the canonical change name (`provider-safety`) and evaluate exact equality against the backlog item name. Suffix matching (e.g. `endswith("-safety")`) and fuzzy matching MUST NOT be performed.

#### SCENARIO: Authoritative Completion Evidence Requirement
- **GIVEN** a caller attempting to transition a BacklogItem to `COMPLETED` via `LifecycleTransitionAuthority`
- **WHEN** `transition_backlog_item` is invoked
- **THEN** the system MUST enforce that `to_state == COMPLETED` requires an authoritative completion `reason_code` (`canonical_completion_evidence`, `post_merge_completion`, `post_merge_reconciled`, or `manual_completion_authority`).

#### SCENARIO: Adapter Dependency Safety
- **GIVEN** `SchedulerService` initialization with an explicit concrete adapter, fake adapter, wrapper, protocol implementation, or bare mock
- **WHEN** adapter references are resolved
- **THEN** the system MUST preserve intentionally supplied adapter objects without requiring concrete production inheritance, while preventing bare `MagicMock` instances from auto-synthesizing unconstrained child mock adapters.
