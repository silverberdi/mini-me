## Context

Change 008 is the coordination layer after archived changes 001–007. Readiness, project/repository binding, worktrees, implementation, continuation governance, checks, complementary review, audit, provider capacity, and evidence integrity already have their own authorities. The design must compose those services while keeping PostgreSQL as operational truth and Git/GitHub as candidate/external evidence.

## Goals / Non-Goals

**Goals:**

- Coordinate one explicitly admitted READY change through deterministic checkpoints.
- Make every stage, candidate generation, external action, and stop reason restart-safe.
- Preserve complementary authorship/reviewer independence, DeepSeek Direct independence, and 006 drain-only policy.
- Prepare an exact audited candidate for a human merge gate with truthful observability.

**Non-Goals:**

- Multi-project scheduling, prioritization, or concurrent orchestration.
- New readiness, implementation, continuation, review, audit, provider, repository, or worktree rules.
- Automatic merge, deployment, OpenSpec archive, Issue/Project closure, or post-merge production work.
- PWA supervision, Qwen integration, provider-policy redesign, budget changes, or Issue #15 cleanup.

## Decisions

### 1. Separate five state authorities

The coordinator reads and writes distinct concepts:

| Authority | Meaning | Owner |
| --- | --- | --- |
| Operational job state | Current execution job lifecycle and provider-facing work | Existing execution pipeline/job services |
| Orchestration stage/checkpoint | Where the one-change coordinator is and the evidence required next | New orchestration coordinator |
| Continuation decision | Retry, correction, reassignment, wait, or escalation after an attempt | 007 continuation governance |
| Capacity mode | `RUN`, `DRAIN`, `WAIT`, plus job-level `WAITING_CAPACITY` | 005/006 capacity services |
| Human gate / stop outcome | `READY_FOR_HUMAN_MERGE`, `WAITING_CAPACITY`, `WAITING_EXTERNAL`, or `NEEDS_HUMAN` outcome and detail | Orchestration/human decision boundary |

`READY_FOR_HUMAN_MERGE` is a human-gate value, not a stage or new `JobStatus`. `WAITING_CAPACITY` remains reserved for canonical 005/006 provider capacity evidence; `WAITING_EXTERNAL` represents a transient non-provider dependency wait; `NEEDS_HUMAN` represents deterministic inability to continue without human intervention. Orchestration stores the reason and resumable checkpoint for each outcome.

### 2. Use a finite stage graph with transactional guards

The durable stage enum is:

`ADMITTED → PREPARING_EXECUTION → IMPLEMENTING → EVALUATING_ATTEMPT → RUNNING_CHECKS → FREEZING_CANDIDATE → COMPLEMENTARY_REVIEW → REVIEW_REMEDIATION → INDEPENDENT_AUDIT → AUDIT_REMEDIATION → PREPARING_PR → PR_PREPARED`.

`PR_PREPARED` is the terminal operational checkpoint. Only after it verifies exact audited candidate identity, reconciled push/PR state, remote PR head equality, and current review/audit authority does the separate human-gate authority become `READY_FOR_HUMAN_MERGE`. `WAITING_CAPACITY`, `WAITING_EXTERNAL`, and `NEEDS_HUMAN` are stop outcomes attached to a resumable stage, not ordinary forward stages. Remediation returns to `EVALUATING_ATTEMPT` or `RUNNING_CHECKS`, then creates a strictly higher candidate generation. A transition guard checks the prior stage, required evidence IDs, current candidate identity, and uniqueness of the run's active lease/transition key in one PostgreSQL transaction. Agent text cannot invoke a transition.

### 3. Add minimum durable orchestration records

The migration chained from `007_continuation_governance` (without modifying migrations 001–007) adds the minimum structures, reusing existing foreign keys and evidence records where possible:

- `orchestration_runs`: immutable run ID, project/change binding, base SHA, current stage, resumable stage, human gate/stop reason, active job ID, timestamps, and active/non-terminal status.
- `orchestration_stage_events`: immutable transition ID/idempotency key, from/to stage, evidence references, actor (`system`), and timestamps.
- `orchestration_candidates`: run ID, generation, base/candidate SHA, manifest ID/hash, authorship summary, frozen status, and supersession relation.
- `orchestration_external_actions`: action key/type, target identity, request fingerprint, status, remote identifier/result, and reconciliation timestamps for push/PR operations.

The exact SQLAlchemy names may follow the existing model conventions. The Alembic revision identifier is at most 32 characters and has `down_revision = "007_continuation_governance"`. Admission uses a transactional PostgreSQL partial unique index/constraint, or an equivalent deterministic guard, so at most one non-terminal/active run exists for a project/change while historical completed/stopped runs remain allowed. Unique action keys prevent duplicate external effects.

### 4. Coordinator invocation and recovery

`orchestrate start <project> <change>` performs admission and then drives the coordinator until a stop gate; `orchestrate status <run>` is read-only; `orchestrate resume <run>` re-enters the same durable coordinator. API endpoints expose the same operations, while clients never invoke providers, Git, or GitHub directly.

At each covered mutating Git/GitHub boundary, the coordinator MUST first durably reserve an external-action identity with target identity and request fingerprint, then execute the mutation, and finally reconcile and persist the result. If reservation cannot be committed, no mutation executes. On restart it locks/reloads the run, inspects PostgreSQL plus managed Git state and GitHub, and chooses only a unique safe action. Existing completed checks/reviews/audits are reused only when candidate generation, base SHA, manifest, and authority policy still match.

### 5. Candidate generations invalidate authority

Freezing captures actual managed-worktree HEAD, registered base SHA, full candidate manifest/hash, and authorship history. Any material remediation creates a new generation and marks prior review/audit authority historical. Audit launch requires the current generation, authoritative review, clean candidate identity, and read-only DeepSeek Direct boundary. Only a full PASS for the current generation can unlock PR preparation.

### 6. GitHub action reconciliation

PR preparation first verifies the durable repository binding and candidate identity, then reserves and commits an action record derived from run ID, project/change binding, branch, generation, candidate SHA, target, and request fingerprint. It pushes only according to project policy, reconciles an existing PR by durable binding, and verifies remote head equals the audited SHA. Ambiguous responses are reconciled before retry; temporary inability to observe remote state becomes `WAITING_EXTERNAL`, while contradictory evidence becomes `NEEDS_HUMAN`.

## Risks / Trade-offs

- **[Risk] Coordinator duplicates existing lifecycle authority.** → **Mitigation:** stage guards reference existing job, continuation, review, audit, capacity, and binding records; no agent result directly advances a stage.
- **[Risk] Crash between an external side effect and its local acknowledgement.** → **Mitigation:** durable action keys plus Git/GitHub reconciliation before retry.
- **[Risk] Candidate changes after a valid review/audit.** → **Mitigation:** immutable generations and SHA/manifest-bound authority; any mismatch invalidates prior evidence.
- **[Risk] GitHub outage delays a fully verified candidate.** → **Mitigation:** preserve internal evidence and stop as `WAITING_EXTERNAL` without reporting the human gate.
- **[Risk] Migration or coordinator deployment leaves active runs at an unknown boundary.** → **Mitigation:** migration is additive and transactional; startup reconciliation treats unknown/ambiguous state as fail-closed human attention, and rollback preserves historical evidence while disabling new admissions.

## Migration Plan

1. Add and apply the single Alembic migration after `007_continuation_governance`; verify constraints and indexes in PostgreSQL.
2. Deploy coordinator/API/CLI code with admission disabled until schema and existing-service compatibility checks pass.
3. Enable one-run admission; exercise restart and external-action reconciliation against deterministic fakes and a PostgreSQL integration environment.
4. Roll back by disabling new orchestration admission and reverting code only if no 008 run is active; preserve orchestration records for investigation. Do not downgrade or mutate migrations 001–007.

## Open Questions

None that change the contract or task breakdown. Existing project policy continues to determine exact GitHub App credentials, branch naming, provider configuration, and repository deployment details; those are not invented by this change.
