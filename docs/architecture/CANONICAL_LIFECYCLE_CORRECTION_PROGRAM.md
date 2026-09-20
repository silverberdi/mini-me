# mini me — Canonical Lifecycle Correction Program

Baseline audited: `8f132791131986c5b793b9e93bccf7e5e23e2df0`

## Five architectural laws

1. A lifecycle transition has one writer.
2. Missing or unavailable evidence is never interpreted as success.
3. Observations and projections cannot resurrect terminal work.
4. Every external side effect is observable, idempotent, and resumable.
5. The deployed runtime checkout is never the mutable workspace of a managed project.

## Authority matrix

| Domain | Authority | May establish | Must not establish |
|---|---|---|---|
| Git | Git repository | commits, diff, ancestry, branches, candidate identity | operational lifecycle |
| GitHub | GitHub remote | Issue/PR/Project remote state | operational lifecycle |
| OpenSpec | versioned OpenSpec in Git | behavior contract, tasks, archive contractual state | execution success |
| PostgreSQL | mini me operational DB | lifecycle, attempts, decisions, sagas, evidence refs | unobserved external facts |
| Providers | observed provider result | outcome/capacity/model evidence | lifecycle directly |
| Queue/read models | projections | ordering/observability | admission authority |
| PWA/TUI/dashboard | API/read models | observability + governed commands | direct lifecycle mutation |

## Program stages

A. `canonical-lifecycle-transition-authority`
   - Single transition authority for `Change` and `BacklogItem` lifecycle using existing enums.
   - Persistence-level bypass protection (generic `save()` cannot mutate status; atomic CAS required).
   - Strict `ChangeStatus` matrix (`DISCOVERED`, `READY`, `IN_PROGRESS`, `BLOCKED`, `DONE`, `CANCELLED`).
   - Strict `WorkItemStatus` matrix (`BACKLOG`, `CONTEXT_CHECK`, `PREPARING`, `NEEDS_HUMAN`, `READY`, `ADMITTED`, `RUNNING`, `BLOCKED`, `COMPLETED`, `CANCELLED`).
   - Phase separation: `READY -> ADMITTED` (admission authority) and `ADMITTED -> RUNNING` (execution start).
   - Non-destructive cancellation (`delete_work_item` performs transition to `CANCELLED` without hard DB delete).
   - `PostMergeService` integrated as mandatory authority caller for `Change.DONE` and `BacklogItem.COMPLETED`.
   - Orthogonality: `COMPLETED` does not force or fabricate `readiness_state = READY`.
   - `UNKNOWN` evaluation results fail closed and block state progression.
   - Atomic lifecycle transition events in the same DB transaction.
   - Read/GET surfaces and queue rebuilds perform zero lifecycle writes.

B. `fail-closed-external-evidence-and-actions`
C. `managed-repository-runtime-isolation`
D. `durable-intake-and-closure-sagas`
E. `projection-purity-and-api-cqs`
F. `transaction-and-concurrency-contract`
G. `scheduler-and-recovery-convergence`
H. `canonical-docs-openspec-agent-convergence`
I. `adversarial-invariant-proving`
J. `production-truth-preflight`

Only A is authored as an active OpenSpec change in this package. B–J remain program stages until A is delivered.

## Cross-program invariants

- Terminal Change/Backlog identities cannot automatically return to executable state.
- Queue/read models are disposable and rebuildable without changing canonical lifecycle.
- Readiness/discovery/integrity are observations/evaluations, not lifecycle writers.
- UNKNOWN blocks when required evidence is unavailable.
- Production adapters never fabricate IDs or success.
- External effects have durable identity and reconcile before retry after ambiguity.
- Closure is phase-based evidence, never inferred from one terminal flag.
- `/opt/minime/app` is deployment, never managed workspace.
- Deployment does not implicitly authorize autonomous execution.
- Fresh execution has one admission gate.
- Recovery resumes only from proven safe checkpoints.
- Events audit canonical transitions; events do not substitute current state.
- GET/read operations do not perform lifecycle writes.
- Agent execution envelopes explicitly bind project/change/worktree/base/candidate/role/scope.

## Correction program exit criteria

The program is complete only when:
- no path can resurrect terminal work;
- no production adapter can fabricate success;
- no GET mutates lifecycle;
- no projection owns lifecycle;
- deployed checkout is never a managed workspace;
- ambiguous external effects cannot be blindly duplicated;
- closure cannot be inferred from one terminal flag;
- no fresh-admission bypass exists;
- recovery never guesses success;
- concurrent admission cannot create duplicate active execution;
- docs/OpenSpec/code/agent contracts agree;
- production truth preflight returns `SAFE_TO_RUN`;
- one trivial and one real greenfield complete under the corrected model.

## Non-goals

Do not opportunistically implement provider/model capability selection, adaptive routing, local-worker routing,
AI operations dashboards, unrelated UI redesign, or unrelated dependency upgrades.
