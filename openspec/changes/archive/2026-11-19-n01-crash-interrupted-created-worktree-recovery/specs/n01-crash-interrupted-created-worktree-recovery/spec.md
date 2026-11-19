## Purpose

Safely continue an existing execution after host interruption when durable evidence proves its CREATED recovery worktree and unfinished attempt remain authoritative.

## ADDED Requirements

### Requirement: Crash-interrupted CREATED recovery continuation
The system MUST accept an unfinished `PREMATURE_STOP` attempt for historical recovery only when the exact canonical worktree ownership is `CREATED`, the latest attempt has no completion time or duration and is exactly one attempt ahead of the persisted finalized job counter, and durable interruption and recovery evidence for the linked Job and Run postdates that attempt. The system MUST preserve the attempt record, job counter, original base, snapshot, publication identity, and Run/Job identities, and MUST continue through the existing fenced CONTINUE path and all existing Git and published-artifact checks. The system MUST NOT apply this exception to `DELETED` worktrees or ordinary/finalized `PREMATURE_STOP` outcomes.

#### Scenario: Continue after an evidenced host interruption
- **GIVEN** a canonical `CREATED` worktree with valid ownership, snapshot event, branch, original base and published artifact identity
- **AND** its latest attempt is `PREMATURE_STOP`, incomplete, and one greater than the persisted finalized job attempt count
- **AND** matching `JOB_INTERRUPTED`, `JOB_RECOVERED`, and `ORCHESTRATION_RECOVERED` events prove recovery after that attempt for the linked Job and Run
- **AND** the canonical CONTINUE claim is valid, no candidate exists, and Git contains no unauthorized staged, untracked, or out-of-scope changes
- **WHEN** the operator continues that existing Run
- **THEN** the same Run, Job, CREATED worktree, original base and snapshot are adopted and the diagnostic execution path is reached without rewriting the attempt or counter history

#### Scenario: Reject an unfinished attempt without restart recovery proof
- **GIVEN** a CREATED recovery worktree whose latest attempt is incomplete `PREMATURE_STOP`
- **AND** one or more required post-attempt interruption/recovery events are absent, mistimed, contradictory, or bound to another identity
- **WHEN** canonical continuation validates the worktree
- **THEN** the worktree is rejected before execution and no Run, Job, attempt, ownership, snapshot, or publication identity is rewritten

#### Scenario: Reject finalized or ordinary premature-stop attempts
- **GIVEN** a `PREMATURE_STOP` attempt with a completion timestamp, duration, or inconsistent attempt-number relationship
- **OR** a `DELETED` worktree with no permitted environment/provider initialization failure outcome
- **WHEN** recovery validation runs
- **THEN** the narrow crash-interruption exception is denied

#### Scenario: Reject unauthorized Git and candidate state
- **GIVEN** an otherwise evidenced crash-interrupted recovery
- **AND** a candidate exists or the worktree has staged, untracked, or out-of-scope modifications, or its snapshot/publication evidence differs
- **WHEN** continuation validates the recovery state
- **THEN** continuation fails closed using the existing recovery and artifact checks without changing Git or durable execution history
