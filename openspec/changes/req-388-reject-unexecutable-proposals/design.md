## Context

See `proposal.md` for motivation. The coordinator already runs native Propose and strict CLI validation before its structured thinking-agent assessment. That assessment is persisted with proposal artifact and Request-context hashes, giving a natural place to bind a stage-aware feasibility report without a separate state table or another provider role. Project CI/CD deployment is external to Mini Me, and repo configuration alone does not prove that an exact candidate is available when a task actually requires pre-merge validation.

## Goals / Non-Goals

**Goals:** prevent mandatory work with no authorized path from entering the workflow; distinguish prerequisites for the next transition from outputs and later-stage work; verify task coverage for every acceptance criterion; retain a concrete, hash-bound blocker report that the operator can understand and resolve.

**Non-Goals:** implement project deployment, have Mini Me perform human physical tests, accept free-text as proof that a dependency exists, create a generic capability registry, or alter OpenSpec artifacts outside native workflows.

## Decisions

1. **Keep semantic assessment with the configured thinking role; keep orchestration small.** Extend the existing structured assessment rather than adding a provider stage or a parallel reasoning engine. The assessment must map each task to its execution stage, responsible actor, capabilities, dependencies required before that stage, and completion evidence. A small, stateless `ProposalFeasibilityEvaluator` owns evidence collection and structural verification: it reads task IDs through the existing `OpenSpecTaskTracker`, acceptance scenarios through the native `OpenSpecAdapter` JSON view, and configured/installed capabilities from project/runtime state. It validates task/stage coverage and cited evidence without creating or editing OpenSpec artifacts. The coordinator owns dispatch, durable Run state, and gates; the evaluator performs no provider calls, persistence writes, or deployment actions. Missing IDs or stage mappings and malformed evidence are invalid; a capability needed only by a later stage is not evidence that the current transition is impossible. This binds feasibility to the same artifact/context hashes as the existing assessment.

2. **Verify evidence at the stage that consumes it.** Repository paths must exist within the confined candidate, configured agent/workflow capabilities must match installed profiles, and external capabilities must have an evidenced authorized owner/path and be verified before their stage begins. An output created by Apply is not required to exist before Apply. A preview is usable only when a pre-merge path for the exact candidate SHA is observable; a production deployment triggered after merge cannot satisfy a task that explicitly requires pre-merge validation. An agent's assertion or an assumed future CI/CD action without supporting evidence is insufficient.

3. **Use the existing gate at the correct transition.** Persist the feasibility report in the Run's existing PostgreSQL `stop_details`, bound to the artifact/context hashes. Hold only when a missing dependency is required before the next transition, or when mandatory work has no authorized path anywhere in the plan. Report later-stage tasks as pending and re-evaluate them before their stage; do not block Apply solely because those tasks are not yet executable. A human response cannot override a real unmet dependency. When the operator selects the gate's explicit native-Update option, resume the same Run and Change through the installed OpenSpec Update workflow, passing the full persisted structured task/scenario assessment and its candidate/artifact/context identities alongside the blocker summary. This lets the native workflow correct specific invalid references or scenario mappings rather than receiving only an aggregate paraphrase. Strictly validate the resulting artifacts and reassess against their new hashes; selecting the evidence option must continue to require observed evidence. Free text alone cannot clear a blocker.

4. **Keep the external deployment boundary.** Mini Me does not deploy or change project CI/CD. The absence of a preview blocks only a transition that requires pre-merge candidate validation; it does not block an earlier stage that can produce the candidate or other deliverables. Adding preview deployment remains a separate project-owned change.

5. **Bind previews to a clean candidate.** A preview session is evidence only when its recorded head SHA equals the candidate head and the candidate worktree has no tracked or untracked changes. A matching base SHA cannot prove behavior from uncommitted proposal or implementation changes.

## Risks / Trade-offs

- [The thinking agent omits a task or criterion] → Compare its returned IDs against tasks and all strict-validated acceptance scenarios; fail closed on any omission or extra entry.
- [The agent invents capability evidence] → Verify repository paths and configured/installed workflows mechanically; require authoritative external evidence for project services and physical participants.
- [The coordinator grows into a second semantic engine] → Keep reasoning in the configured thinking role and isolate only evidence collection/structural validation in the stateless evaluator; reuse the installed OpenSpec CLI and existing task reader.
- [A candidate preview is transient or stale] → Bind evidence to candidate SHA and its observed deployment/run identity; treat unknown or mismatched identity as unavailable.
- [A future-stage dependency is mistaken for a current prerequisite] → Bind each dependency to its consuming stage and gate only before that stage; keep the task pending until its evidence is observed.
- [An operator responds but does not update the Request, task plan, or capability evidence] → Keep the gate at the affected transition and do not let text alone satisfy a dependency; reassess only after source evidence changes.

## Migration Plan

No database migration is expected. New assessments are persisted in existing Run state. Existing Runs without a feasibility record are evaluated before their next transition to Apply; when evidence cannot establish executability, they stay at the gate with the exact missing preconditions. Rollback is the normal application rollback and does not require rewriting saved Runs.
