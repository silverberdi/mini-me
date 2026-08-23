# agent-reassignment-and-handoff Specification

## Purpose
Governs evidence-driven executor reassignment, anti-ping-pong safeguards, restart-safe structured handoff payload generation, and durable candidate authorship tracking to preserve review integrity.

## Requirements

### Requirement: Evidence-driven executor reassignment
The system SHALL reassign the implementation task to the alternate configured primary executor only when deterministic continuation rules trigger `REASSIGN_AGENT` (corrective retry limit reached with `NO_PROGRESS`, repeated false blocker fingerprint streak reached, unmitigated regression, or policy violation) and an alternative primary executor is eligible.

#### Scenario: Reassignment after repeated premature stops
- **WHEN** an executor reaches `corrective_retries_for_current_executor >= max_corrective_retries` with `NO_PROGRESS`
- **THEN** the continuation engine SHALL decide `REASSIGN_AGENT`, increment `reassignment_count`, and allocate the alternate eligible executor.

#### Scenario: Reassignment rejected when only one attempt failed
- **WHEN** an executor fails a deterministic check on its first attempt with `corrective_retries = 0` and exhibits `GOOD_PROGRESS` or `PARTIAL_PROGRESS`
- **THEN** the system SHALL NOT trigger reassignment and SHALL issue a corrective retry to the same executor instead.

### Requirement: Anti-ping-pong and bounded oscillation protection
The system SHALL track executor reassignment history and enforce a configurable hard ceiling `max_reassignments_per_job` (default: 2). If both configured executors fail to achieve completion verification within this ceiling, the system SHALL halt automated reassignment and transition the job to `NEEDS_HUMAN`.

#### Scenario: Reassignment threshold reached
- **WHEN** a job reaches `reassignment_count = 2` without satisfying completion verification
- **THEN** the system SHALL stop automated agent swapping, transition the job to `NEEDS_HUMAN`, and record an `AGENT_PING_PONG_EXHAUSTED` event.

### Requirement: Restart-safe and idempotent structured handoff generation
The system SHALL generate a durable, structured handoff payload upon executor reassignment containing `project_id`, `change_id`, `job_id`, repository binding, branch, worktree path, base SHA, candidate HEAD SHA, completed OpenSpec tasks, remaining OpenSpec tasks, modified/added/deleted file manifest, deterministic check status, validated/false blocker summaries, established architectural decisions, do-not-redo guidance, and full contribution history. The handoff record SHALL be assigned an immutable `handoff_id` to ensure daemon restart recovery resumes the existing handoff idempotently without duplicate records.

#### Scenario: Structured handoff generated on reassignment
- **WHEN** an implementation job is reassigned from the primary implementer (e.g., Codex) to the alternate executor (e.g., Antigravity)
- **THEN** the system SHALL persist the structured handoff record in PostgreSQL and inject the handoff context into the new executor's invocation prompt.

#### Scenario: Daemon restarts during handoff transition
- **WHEN** the daemon restarts after a `REASSIGN_AGENT` decision but before the new executor starts
- **THEN** the system SHALL load the existing pending handoff by `handoff_id` and resume execution of the assigned new executor without creating a duplicate handoff record.

### Requirement: Continuation of existing valid worktree
The receiving executor SHALL continue execution within the existing candidate worktree and Git branch, preserving all valid files, passing tests, and partial implementation artifacts produced by prior attempts.

#### Scenario: Worktree preserved during takeover
- **WHEN** a new executor begins work following a reassignment handoff
- **THEN** the system SHALL invoke the new executor in the same worktree without running `git clean` or resetting uncommitted candidate modifications.

### Requirement: Candidate authorship and contribution tracking
The system SHALL durably record every agent that materially authored code or modified candidate files across all attempts for a given change. When multiple executors have contributed across attempts, the candidate SHALL be flagged with `is_mixed_authorship = True` alongside the full contribution history.

#### Scenario: Candidate with mixed authorship identified
- **WHEN** a candidate has been authored across multiple attempts by both Codex and Antigravity due to reassignment
- **THEN** the system SHALL record `is_mixed_authorship: true` on the candidate record and attach the contribution breakdown for downstream review validation.
