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
The Watchdog SHALL persist a sanitized, structured diagnosis and remediation outcome in PostgreSQL, including project, run, stage, candidate SHA, observed evidence, root-cause classification, attempted action and result, and a passive recurrence-prevention suggestion when supported. Every persisted diagnosis SHALL retain the transition or intervention key that was observed for the event and a stable event identity, including when it is the first diagnosis for that transition. A diagnosis SHALL be idempotent for its event identity and run, stage, and candidate, and recurrence evaluation SHALL use the persisted transition or intervention key without requiring an earlier diagnosis to exist before the first observation can be stored. When semantic analysis produces an improvement suggestion, the suggestion SHALL be stored with the diagnosis and its initial status SHALL be `pending`. After one failed or ineffective remediation attempt, or immediately for a non-mechanical or ambiguous cause, the Watchdog SHALL use the existing `NEEDS_HUMAN`/human-gate mechanism with the current diagnostic question and actionable options; it SHALL NOT create synthetic debate, autonomous GitHub issues, unlimited retries, or bypass an existing human authorization.

#### Scenario: Mechanical recovery succeeds
- **WHEN** one permitted remediation attempt produces observable success through canonical recovery
- **THEN** the persisted record and typed stage event include the action and observed result
- **AND** the same candidate resumes through existing orchestration authority

#### Scenario: First diagnosis is persisted without a prior record
- **WHEN** a run produces a gate or intervention with a transition or intervention key and no prior diagnosis exists for that key
- **THEN** the Watchdog persists the diagnosis with that key, event identity, run, stage, and candidate identity
- **AND** it does not discard the observation or require a prior diagnosis before persistence

#### Scenario: Recurrence finds the correct prior diagnosis
- **WHEN** a later diagnosis refers to a transition or intervention key already persisted for the same supported recurrence
- **THEN** recurrence evaluation finds the matching prior diagnosis by its persisted key and event-linked evidence
- **AND** the later diagnosis is persisted idempotently without duplicating the prior event

#### Scenario: Improvement suggestion is cataloged
- **WHEN** semantic analysis produces a supported recurrence-prevention suggestion for a persisted diagnosis
- **THEN** the diagnosis stores the suggestion in `improvement_suggestion` with status `pending`
- **AND** the suggestion remains linked to the diagnosis, transition or intervention key, event identity, and source run

#### Scenario: First remediation does not resolve the stall
- **WHEN** the same run, stage, and candidate stalls again after its one remediation attempt
- **THEN** the Watchdog stops automatic retries and opens or updates the existing human gate with the evidence and current question
- **AND** it preserves the candidate and prior diagnosis record

#### Scenario: Diagnosis is exposed to operators
- **WHEN** an authorized operator requests diagnosis history for a run
- **THEN** the response returns its sanitized records in chronological order with their candidate identities and outcomes
- **AND** records with an improvement suggestion include that suggestion with status `pending` until an authorized operator changes it
- **AND** secrets and unrelated project data are not exposed

### Requirement: Bounded SRE Unblocker invocation
When an active Run is paused or reaches `HUMAN_REQUIRED` for a technical precondition, mapping, or heuristic ambiguity, the existing Watchdog/orchestration flow SHALL invoke the configured SRE Unblocker role only when the cause is within an explicitly allowlisted, deterministic technical recovery and evidence binds the action to the current Run, stage, candidate, and authorized scope. The Unblocker SHALL use existing native workflows, CLI commands, and recovery authorities, record its action and observed result, and SHALL NOT answer or bypass human authorizations for product/scope decisions, security, exceptional cost, destructive or irreversible actions, implementation merge, or any ambiguous cause. If eligibility or success cannot be proven, the Run SHALL retain the current human-gate question and options.

#### Scenario: Eligible technical blocker is resolved
- **WHEN** the Watchdog identifies a technical blocker covered by an allowlisted idempotent recovery and the Run/candidate evidence is current
- **THEN** it invokes the configured SRE Unblocker role through the existing orchestration authority
- **AND** the recovery result is observed and the same Run resumes only through its canonical lifecycle transition

#### Scenario: Unblocker cannot establish a safe technical cause
- **WHEN** evidence is missing, conflicting, outside the allowlist, or the proposed action could change product scope, security, exceptional spend, or irreversible state
- **THEN** the Unblocker performs no action
- **AND** the existing human gate presents the current question, cause, evidence, and available options

#### Scenario: Recovery action fails or does not remove the blocker
- **WHEN** an eligible action fails or its result does not prove that the blocker is resolved
- **THEN** the system records the attempted action and observed failure
- **AND** stops further autonomous attempts for that blocker and escalates through the existing human-gate authority

#### Scenario: PF-03 fallback warning is proven non-blocking
- **WHEN** a PF-03 fallback/precondition warning is backed by local evidence that the fallback is applied and non-blocking, and its required verification scenario is mapped and verified
- **THEN** the Unblocker records the evidence and allows the existing feasibility authority to continue
- **AND** it does not dismiss an unmet required precondition, an unmapped check, or missing CI identity as cosmetic

#### Scenario: MCP OAuth 401 has a configured refresh path
- **WHEN** an MCP connection reports an authentication 401, is configured for OAuth, and the existing credential service confirms a renewable refresh token without exposing credential values
- **THEN** the Unblocker requests renewal through the existing OAuth credential service
- **AND** retries an MCP operation only when evidence proves the rejected request had no effect and the operation is safe to repeat
- **AND** repeatability is proven by the discovered tool metadata explicitly setting `readOnlyHint: true` or `idempotentHint: true`, with `destructiveHint` not set to `true`
- **AND** when that metadata is absent, conflicting, or destructive, it stores the renewed credential but does not replay the operation and escalates with the original gate intact
- **AND** records success or failure without logging tokens

#### Scenario: OAuth refresh is unavailable or fails
- **WHEN** the MCP connection has no usable refresh token/configuration or the provider rejects renewal
- **THEN** the Unblocker does not substitute credentials or retry the protected operation
- **AND** it preserves the failure evidence and escalates through the current human-gate path

#### Scenario: Stale lock is proven to be orphaned
- **WHEN** the lock is inside the exact Run-owned worktree, the candidate SHA and durable ownership match, and the owning process is proven absent
- **THEN** the Unblocker delegates lock removal to the existing managed-worktree recovery authority
- **AND** records the lock digest and observed result without removing files outside the managed worktree

#### Scenario: Business, cost, or scope gate is escalated
- **WHEN** the current gate asks for a business, cost, or product-scope decision
- **THEN** the system preserves the original OpenSpec question text and original options exactly as received
- **AND** attaches the Unblocker's technical diagnosis separately without replacing, paraphrasing, or reordering the original question or options
- **AND** waits for the operator's decision

### Requirement: Immutable intervention evidence
Every SRE Unblocker invocation SHALL append an immutable PostgreSQL intervention fact with timestamp, project, run, stage, trigger, action, observed result, autonomous/operator outcome, root-cause classification, a stable event identity, the transition or intervention key when observed, and any supported improvement reference. Replaying the same event identity SHALL be idempotent; later diagnosis or resolution SHALL be represented by a new fact rather than rewriting the prior record. The record SHALL not contain secrets or unrelated project data.

#### Scenario: Intervention fact is retained
- **WHEN** the Unblocker attempts or completes an action
- **THEN** the system appends a sanitized intervention record linked to the exact Run and stage
- **AND** the record retains its event identity and transition or intervention key when available
- **AND** the record remains unchanged when a later event records resolution or escalation

#### Scenario: Duplicate delivery of the same intervention event
- **WHEN** orchestration retries persistence for an intervention event already recorded
- **THEN** the event identity prevents a duplicate record
- **AND** the original timestamp, transition or intervention key, and evidence remain intact
