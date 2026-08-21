# Process Restart Recovery Specification

## Purpose

Provides daemon startup reconciliation, crash recovery, orphaned job state resolution, and safe worktree lock verification across restarts.

## Requirements

### Requirement: Daemon restart in-flight job reconciliation
The system SHALL scan PostgreSQL upon daemon startup to reconcile active non-terminal jobs (`RUNNING`, `CHECKS_RUNNING`, `REVIEW_RUNNING`, `AUDIT_RUNNING`) interrupted by a crash or restart.

#### Scenario: Interrupted in-flight job detected on startup
- **WHEN** the daemon starts and finds a job left in a non-terminal execution state from a previous runtime instance
- **THEN** the system marks the interrupted execution attempt as `INTERRUPTED`, persists a `DAEMON_RESTARTED` event, and transitions the job to `WAITING_CAPACITY` or a resumable state without data loss.

#### Scenario: Completed phases preserved without duplicate execution
- **WHEN** an interrupted job had already passed deterministic checks, completed review, or finished audit before the restart
- **THEN** on startup recovery, the existing verified check results, review verdicts, and audit records remain valid and the system SHALL NOT re-run completed expensive phases.

#### Scenario: Mid-provider interruption requires verifiable evidence
- **WHEN** a job was interrupted mid-agent execution (`RUNNING`, `REVIEW_RUNNING`, or `AUDIT_RUNNING`) without a recorded completion payload
- **THEN** the system SHALL NOT infer successful agent completion, records the interruption, and marks the attempt failed/interrupted.

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
