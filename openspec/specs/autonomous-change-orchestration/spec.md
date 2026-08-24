# autonomous-change-orchestration Specification

## Purpose
Coordinates one already-READY OpenSpec change across existing implementation, evidence, review, audit, and GitHub authorities with durable checkpoints and safe human stopping points.

## Requirements

### Requirement: Single-change admission
The system SHALL start an orchestration run only for one explicitly selected project/change pair whose durable repository binding and existing readiness authority both validate as READY.

#### Scenario: READY change is admitted
- **WHEN** the operator starts orchestration for a durably bound READY project/change pair
- **THEN** the system creates one immutable `orchestration_run_id`, records the bound project/change/base identity, and enters the first persisted orchestration stage.

#### Scenario: Ineligible change is refused
- **WHEN** the selected change is not READY, has ambiguous/missing binding, or fails repository/workspace preflight
- **THEN** no executable orchestration run is created and the refusal contains a structured reason.

#### Scenario: Duplicate active run is refused
- **WHEN** an active orchestration already exists for the same project/change pair
- **THEN** the new start request fails closed and returns the existing run identity without starting another job, worktree, branch, or provider action.

#### Scenario: Historical run does not block a later run
- **WHEN** prior orchestration runs for the same project/change are terminal and no non-terminal run exists
- **THEN** a new explicitly admitted run may be created while historical run records remain queryable.

### Requirement: Durable deterministic orchestration lifecycle
The system SHALL persist a finite, ordered orchestration stage and checkpoint for every run, and SHALL advance it only after the required authoritative evidence for that stage is committed.

#### Scenario: Successful path reaches the human gate
- **WHEN** implementation/continuation completes, checks pass, the candidate is frozen, complementary review is authoritative, the final full DeepSeek Direct audit passes, and repository identity is valid
- **THEN** the system advances the operational stage to `PR_PREPARED` only after push/PR reconciliation proves the remote PR head equals the exact audited candidate, then records `READY_FOR_HUMAN_MERGE` as the separate human gate and stops.

#### Scenario: Stage advancement is not agent-controlled
- **WHEN** an implementer, reviewer, or auditor claims that a stage is complete without the required deterministic evidence
- **THEN** the orchestration stage does not advance and the claim is recorded only as attempt/review/audit evidence.

#### Scenario: Temporary capacity blocks progress
- **WHEN** an existing pipeline authority reports a safe temporary capacity wait
- **THEN** the operational job remains or becomes `WAITING_CAPACITY`, the orchestration checkpoint records the resumable stage and handoff, and the run stops without becoming `NEEDS_HUMAN` solely for capacity.

#### Scenario: Temporary external dependency blocks progress
- **WHEN** a transient non-provider dependency such as GitHub is unavailable or an external action result cannot yet be observed
- **THEN** the orchestration run stops with `WAITING_EXTERNAL`, preserves its resumable checkpoint, and does not change the job to `WAITING_CAPACITY` or `NEEDS_HUMAN` solely for the transient outage.

#### Scenario: Unresolvable invariant blocks progress
- **WHEN** binding, worktree identity, candidate identity, evidence authority, provider/model independence, or external-action outcome cannot be proven uniquely
- **THEN** the run records a structured stop reason and enters `NEEDS_HUMAN` unless the existing capacity authority proves `WAITING_CAPACITY` or the external dependency is transiently unobservable and qualifies for `WAITING_EXTERNAL`, without speculative continuation.

### Requirement: Existing pipeline coordination
The system SHALL invoke existing implementation, 007 continuation, deterministic-check, complementary-review, and DeepSeek Direct audit authorities in their defined order and SHALL preserve their decisions and diagnostics.

#### Scenario: Corrective implementation is governed by 007
- **WHEN** an implementation attempt is premature, falsely blocked, structurally blocked, or otherwise incomplete
- **THEN** the run delegates correction, reassignment, waiting, and escalation to the existing continuation governance and resumes from its persisted result.

#### Scenario: Review changes require remediation
- **WHEN** the authoritative complementary review returns `CHANGES_REQUIRED`
- **THEN** the run delegates remediation through continuation governance, freezes the resulting candidate as a new generation, and requires fresh authoritative review for that generation.

#### Scenario: Audit failure requires a full fresh audit
- **WHEN** DeepSeek Direct returns a blocking audit result
- **THEN** the run delegates remediation, records the old audit as historical evidence, freezes the new candidate, and requires a full fresh audit before any human-gate transition.

#### Scenario: Medium audit finding blocks advancement
- **WHEN** the current candidate's DeepSeek Direct audit contains one or more MEDIUM findings, regardless of any LOW findings or overall textual PASS claim
- **THEN** the audit cannot authorize progression to `PR_PREPARED` or `READY_FOR_HUMAN_MERGE` and remediation follows existing continuation governance.

### Requirement: Candidate-bound evidence authority
The system SHALL bind each candidate generation to the registered base SHA, actual managed-worktree candidate SHA, manifest identity/hash, authorship history, and the review/audit records that evaluated it.

#### Scenario: Stale review cannot authorize a changed candidate
- **WHEN** remediation changes the candidate HEAD SHA or manifest
- **THEN** review authority for the prior generation is historical only and the run cannot advance until a new authoritative review is recorded for the current generation.

#### Scenario: Stale audit cannot authorize a changed candidate
- **WHEN** remediation occurs after an audit PASS
- **THEN** the prior PASS cannot authorize the new candidate and a full DeepSeek Direct audit of the current candidate is mandatory.

### Requirement: Idempotent human-gate preparation
The system SHALL make branch push and GitHub PR creation/update idempotent, SHALL reserve and persist a durable external-action identity, target identity, and request fingerprint before every covered mutation, and SHALL never push or expose a candidate that is not the current independently audited candidate.

#### Scenario: Restart during PR creation
- **WHEN** the daemon restarts after GitHub accepted a PR creation but before local completion was recorded
- **THEN** recovery reconciles the durable binding and remote evidence, records the existing PR, and does not create a duplicate PR or push an unaudited SHA.

#### Scenario: External mutation requires reservation
- **WHEN** branch push or PR create/update is requested
- **THEN** the system first durably reserves the action identity, target identity, and request fingerprint; if reservation fails, the mutation is not executed and the run stops safely.

#### Scenario: Remote PR head differs
- **WHEN** the existing PR head SHA differs from the current independently audited candidate SHA
- **THEN** the system fails closed with a structured human stop and does not overwrite or merge the PR automatically.

#### Scenario: Ambiguous external action is reconciled before retry
- **WHEN** an external mutation returns an ambiguous result
- **THEN** the system reconciles remote state before any retry; temporary inability to observe remote state produces `WAITING_EXTERNAL`, while contradictory evidence produces `NEEDS_HUMAN`.

### Requirement: Human-gate contract
The system SHALL stop at exactly one of `READY_FOR_HUMAN_MERGE`, `WAITING_CAPACITY`, `WAITING_EXTERNAL`, or `NEEDS_HUMAN` for the run's MVP lifecycle, and SHALL not merge, deploy, archive, or close the change automatically. `READY_FOR_HUMAN_MERGE` is only a human-gate outcome, not an orchestration stage.

#### Scenario: Operator resumes a waiting run
- **WHEN** provider capacity or a recoverable external condition is independently verified as restored/observable
- **THEN** `orchestrate resume` continues the same run from its durable checkpoint without repeating completed authoritative work.

#### Scenario: External wait is not capacity wait
- **WHEN** GitHub or another non-provider dependency is temporarily unavailable
- **THEN** the run uses `WAITING_EXTERNAL`, while `WAITING_CAPACITY` remains reserved for canonical 005/006 capacity evidence.

#### Scenario: Human merge remains mandatory
- **WHEN** a run is `READY_FOR_HUMAN_MERGE`
- **THEN** mini me exposes the exact PR, base SHA, candidate SHA, manifest/audit evidence, and stop reason while taking no merge action.
