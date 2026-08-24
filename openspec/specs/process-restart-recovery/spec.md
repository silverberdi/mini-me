# Process Restart Recovery Specification

## Purpose

Provides daemon startup reconciliation, crash recovery, orphaned job state resolution, and safe worktree lock verification across restarts.

## Requirements

### Requirement: Daemon restart in-flight job reconciliation
The system SHALL scan PostgreSQL, Git, and reconciliable GitHub evidence upon daemon startup to recover active orchestration runs and non-terminal jobs from the last committed checkpoint, preserving completed authoritative evidence and resuming only a uniquely safe next action.

#### Scenario: Orchestration boundary survives restart
- **WHEN** the daemon restarts after any committed admission, attempt, continuation, reassignment, capacity wait, check, candidate freeze, review, audit, or PR checkpoint
- **THEN** recovery resumes the same orchestration run from that checkpoint without duplicating completed provider work or external side effects.

#### Scenario: Ambiguous recovery fails closed
- **WHEN** PostgreSQL, Git, or GitHub evidence cannot identify one safe next action or an external action has an ambiguous result
- **THEN** recovery records the ambiguity and stops in `WAITING_EXTERNAL` when remote evidence is temporarily unavailable, or `NEEDS_HUMAN` when evidence is contradictory/irreconcilable, rather than retrying blindly.

#### Scenario: PR accepted before local acknowledgement
- **WHEN** GitHub evidence shows a matching PR created after the last local transaction
- **THEN** recovery adopts the existing PR binding after verifying repository, base SHA, and audited head SHA, and does not create a duplicate.

#### Scenario: Interrupted in-flight job detected on startup
- **WHEN** startup finds a job left in a non-terminal execution state from a previous runtime instance
- **THEN** the system records the interruption using existing recovery/outcome semantics, preserves durable state, and resumes or classifies the attempt from a uniquely safe checkpoint without implying `WAITING_CAPACITY`.

#### Scenario: Interruption with independently proven capacity shortage
- **WHEN** an interrupted job is recovered and canonical provider/capacity evidence independently proves the required provider unavailable
- **THEN** the existing capacity lifecycle may place the job into `WAITING_CAPACITY`; the daemon interruption alone never does so.

#### Scenario: Completed phases preserved without duplicate execution
- **WHEN** an interrupted run had already passed checks, completed review, or finished audit
- **THEN** the committed evidence remains valid for its candidate and recovery does not rerun the completed expensive phase.

#### Scenario: Mid-provider interruption requires verifiable evidence
- **WHEN** a provider process was interrupted without a recorded completion payload
- **THEN** the system does not infer success, records the attempt as interrupted, and lets the coordinator apply its existing continuation policy.

### Requirement: Safe worktree Git lock recovery
The system SHALL remove a `.git/index.lock` file upon recovery ONLY when ownership and safety can be conclusively verified within a mini me-managed worktree with no active owning process, and SHALL fail closed otherwise.

#### Scenario: Stale lock in managed worktree with no owning operation
- **WHEN** startup recovery finds an `.git/index.lock` in a mini me-managed worktree and verifies there is no running mini me-owned Git process or active lock owner
- **THEN** the system safely removes the stale lock, logs a `WORKTREE_LOCK_RECOVERED` event, and proceeds with workspace reconciliation.

#### Scenario: Lock with active or uncertain ownership is not removed
- **WHEN** an `.git/index.lock` is present and the system cannot conclusively verify that the owning process is dead or mini me-owned
- **THEN** the system SHALL NOT remove the lock, marks the job recovery as `RECOVERY_BLOCKED`, and exposes the lock path and reason through observability for operator intervention.

#### Scenario: Lock outside managed worktree is never removed
- **WHEN** a lock file exists in a base repository or location outside the specific mini me-managed worktree
- **THEN** the system SHALL NEVER delete the external lock file and fails closed with a safety violation.
