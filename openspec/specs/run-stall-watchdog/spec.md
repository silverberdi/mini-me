# run-stall-watchdog Specification

## Purpose

Detect and explain stalled orchestration runs across projects, apply only bounded mechanical recovery when explicitly enabled and safely proven, and otherwise return control to the operator through existing recovery and gate authorities.

## Requirements

### Requirement: Global Watchdog configuration
The system SHALL expose a global Watchdog/SRE configuration in provider/model administration with a provider/model chosen from the currently registered catalog, a positive inactivity threshold defaulting to 15 minutes, and an operating mode of `Solo diagnóstico` or `Auto-remediación mecánica`. It SHALL persist these settings in PostgreSQL without persisting provider credentials, apply them across projects, and reject invalid or unavailable selections without silently substituting another provider.

#### Scenario: Save global Watchdog settings
- **WHEN** an authorized operator saves a catalog-backed provider/model, a positive inactivity threshold, and an operating mode
- **THEN** the API persists and returns those values as the authoritative global configuration
- **AND** every project uses the same saved settings

#### Scenario: Invalid or unavailable model selection
- **WHEN** a provider/model selection is absent from or unavailable in the registered catalog
- **THEN** the system reports the configuration problem
- **AND** retains the last valid configuration without selecting a fallback or incurring unconfigured spend

#### Scenario: Watchdog model unavailable at runtime
- **WHEN** a stalled run requires diagnosis but its configured Watchdog model is unavailable
- **THEN** the system still evaluates eligible deterministic mechanical playbooks
- **AND** it escalates any cause that cannot be established mechanically through the existing human-gate authority
- **AND** it does not block unrelated runs

### Requirement: Detect inactivity without perturbing progressing runs
The Watchdog SHALL use the existing scheduler/reconciliation cycle and durable stage/activity evidence to detect an active run whose stage has had no new stage event or observable activity for longer than the configured threshold, or whose recorded child process is proven absent while its claim remains. A run with current observable progress SHALL incur no Watchdog model call, remediation, lifecycle mutation, or added wait. Detection SHALL identify project, run, stage, and candidate identity from authoritative persisted state.

#### Scenario: Healthy run continues to progress
- **WHEN** an active run emits new stage events or other existing observable activity within the configured threshold
- **THEN** the Watchdog performs no diagnosis or mutation for that run
- **AND** normal orchestration proceeds through its existing authority

#### Scenario: Inactivity threshold is exceeded
- **WHEN** an active run has no stage event or observable activity beyond the configured threshold
- **THEN** the Watchdog records the observed inactivity and starts at most one diagnosis for that run, stage, and candidate identity
- **AND** it does not create a new pipeline stage or competing scheduler

#### Scenario: Child process is proven absent while claim remains
- **WHEN** process evidence proves that the recorded stage child process has ended but its durable claim remains active
- **THEN** the Watchdog classifies the run for canonical recovery immediately without waiting for the inactivity threshold
- **AND** it preserves the claim and candidate until the canonical recovery authority evaluates them

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

### Requirement: Bounded escalation and durable diagnosis record
The Watchdog SHALL persist a sanitized, structured diagnosis and remediation outcome in PostgreSQL, including project, run, stage, candidate SHA, observed evidence, root-cause classification, attempted action and result, and a passive recurrence-prevention suggestion when supported. A diagnosis SHALL be idempotent for its run, stage, and candidate. After one failed or ineffective remediation attempt, or immediately for a non-mechanical or ambiguous cause, the Watchdog SHALL use the existing `NEEDS_HUMAN`/human-gate mechanism with the current diagnostic question and actionable options; it SHALL NOT create synthetic debate, autonomous GitHub issues, unlimited retries, or bypass an existing human authorization.

#### Scenario: Mechanical recovery succeeds
- **WHEN** one permitted remediation attempt produces observable success through canonical recovery
- **THEN** the persisted record and typed stage event include the action and observed result
- **AND** the same candidate resumes through existing orchestration authority

#### Scenario: First remediation does not resolve the stall
- **WHEN** the same run, stage, and candidate stalls again after its one remediation attempt
- **THEN** the Watchdog stops automatic retries and opens or updates the existing human gate with the evidence and current question
- **AND** it preserves the candidate and prior diagnosis record

#### Scenario: Diagnosis is exposed to operators
- **WHEN** an authorized operator requests diagnosis history for a run
- **THEN** the response returns its sanitized records in chronological order with their candidate identities and outcomes
- **AND** secrets and unrelated project data are not exposed
