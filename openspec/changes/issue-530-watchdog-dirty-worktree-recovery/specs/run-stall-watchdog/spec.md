## MODIFIED Requirements

### Requirement: Evidence-bound diagnosis and bounded mechanical recovery
Every diagnosis SHALL be bound to the observed project, run, stage, candidate SHA, and evidence used. In `Solo diagnóstico` mode the Watchdog SHALL not mutate worktree or run state. In `Auto-remediación mecánica` mode it MAY make at most one idempotent remediation attempt for the same run, stage, and candidate, and only through existing recovery, claim/fencing, process-ownership, and managed-worktree authorities. When an active mutating stage (such as `APPLY`) is interrupted and its runner process is proven absent, mechanical remediation SHALL restore the worktree to its candidate entry state before canonical recovery re-evaluates the candidate, eliminating the need for a spurious human gate on the first occurrence. Unknown, conflicting, or incomplete evidence SHALL fail closed and preserve the candidate and worktree.

#### Scenario: Recover proven orphaned process
- **WHEN** the canonical recovery authority verifies that the prior stage process is absent, the candidate and stage still match, and the current fenced claim permits recovery
- **THEN** the Watchdog requests the existing recovery path to record the abandoned invocation and retry the same candidate and stage
- **AND** it does not directly edit claims or dispatch a second recovery authority

#### Scenario: Restore worktree changes made by interrupted apply attempt before retry
- **WHEN** the Watchdog in `mechanical_remediation` mode proves that the prior stage runner process is absent for an interrupted mutating stage (`APPLY`)
- **AND** the managed worktree contains uncommitted or untracked modifications left by the dead process
- **THEN** the Watchdog executes autonomous mechanical worktree restoration to the entry candidate SHA
- **AND** it preserves `openspec/changes/<change-name>/` while removing uncommitted/untracked code debris
- **AND** it requests canonical recovery to re-evaluate the restored candidate without generating a human gate
- **AND** it records the successful mechanical remediation in `watchdog_diagnoses` and emits `WATCHDOG_WORKTREE_REMEDIATED`.

#### Scenario: Remove a proven orphaned Git lock
- **WHEN** a lock is inside the exact mini me-managed worktree and existing lock-recovery checks prove there is no owning process
- **THEN** the Watchdog delegates removal to the existing safe worktree lock recovery behavior
- **AND** it records the observed lock and outcome
- **AND** it never removes a lock outside that managed worktree or with uncertain ownership

#### Scenario: Restore worktree changes made by the stalled verification attempt
- **WHEN** the exact run-owned worktree and immutable candidate are verified, the Verify process is proven absent, and every changed path is attributable to that Verify attempt's recorded baseline and generated test artifacts
- **THEN** the Watchdog requests restoration through the existing managed-worktree cleanup boundary before canonical recovery retries the same candidate
- **AND** it preserves the test evidence and any path whose ownership or origin is uncertain
- **AND** it never runs an unrestricted `git checkout -- .` or equivalent cleanup against an unverified worktree

#### Scenario: Remediation is disabled or evidence is ambiguous
- **WHEN** mode is `Solo diagnóstico`, or worktree/process/candidate ownership cannot be proven
- **THEN** the Watchdog performs no destructive or lifecycle mutation
- **AND** it records the evidence gap and escalates through the existing human-gate flow when operator action is required
