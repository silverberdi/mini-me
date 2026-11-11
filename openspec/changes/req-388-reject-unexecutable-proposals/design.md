## Context

See `proposal.md` for motivation. The coordinator already runs native Propose and strict CLI validation before its structured thinking-agent complexity assessment. That assessment is persisted with proposal artifact and Request-context hashes, giving a natural place to bind a feasibility report without a separate state table or another provider role. Project CI/CD deployment is external to Mini Me, and repo configuration alone does not prove that the exact candidate is available for pre-merge validation.

## Goals / Non-Goals

**Goals:** prevent a valid-but-unexecutable Change from reaching Apply; verify task coverage for every acceptance criterion; retain a concrete, hash-bound blocker report that the operator can understand and resolve.

**Non-Goals:** implement project deployment, have Mini Me perform human physical tests, accept free-text as proof that a dependency exists, create a generic capability registry, or alter OpenSpec artifacts outside native workflows.

## Decisions

1. **Keep reasoning with the configured thinking role; keep orchestration small.** Extend the existing structured thinking assessment rather than adding a provider stage or heuristic classifier. A small, stateless `ProposalFeasibilityEvaluator` owns only evidence collection and structural verification: it reads task IDs through the existing `OpenSpecTaskTracker`, acceptance scenarios through the native `OpenSpecAdapter` JSON view, and currently configured/installed capabilities from project/runtime state. It validates the thinking agent's task/scenario mapping and cited evidence without creating or editing OpenSpec artifacts. The coordinator remains responsible for dispatch, durable Run state, and gates; the evaluator performs no provider calls, persistence writes, or deployment actions. Missing IDs, missing mappings, unknown status, or malformed evidence make the assessment invalid. This avoids a second LLM round trip and binds both complexity and feasibility to the same artifact/context hashes.

2. **Verify cited evidence before advancing.** Repository paths must exist within the confined candidate, configured agent/workflow capabilities must match installed profiles, and external capabilities must have durable project evidence. A claimed preview deployment is usable only when a pre-merge path for the exact candidate SHA is observable; a production deployment triggered after merge does not satisfy it. An agent's assertion without verifiable evidence is insufficient.

3. **Use the existing persistent human gate for unresolved dependencies.** Persist the feasibility report in the Run's existing PostgreSQL `stop_details`, bound to the artifact/context hashes. If any task or criterion is blocked or unknown, keep the proposal unaccepted at `VALIDATING`, expose the exact blockers and required evidence, and do not start Apply. A human response cannot override the result; changed Request or capability evidence must be observed, native Update and strict validation run when artifacts change, and feasibility is evaluated again.

4. **Keep the external deployment boundary.** Mini Me reports deployment as an unmet external precondition when the project provides no verified preview. It neither deploys nor changes project CI/CD. Adding preview deployment remains a separate project-owned change.

5. **Bind previews to a clean candidate.** A preview session is evidence only when its recorded head SHA equals the candidate head and the candidate worktree has no tracked or untracked changes. A matching base SHA cannot prove behavior from uncommitted proposal or implementation changes.

## Risks / Trade-offs

- [The thinking agent omits a task or criterion] → Compare its returned IDs against tasks and all strict-validated acceptance scenarios; fail closed on any omission or extra entry.
- [The agent invents capability evidence] → Verify repository paths and configured/installed workflows mechanically; require authoritative external evidence for project services and physical participants.
- [The coordinator grows into a second semantic engine] → Keep reasoning in the configured thinking role and isolate only evidence collection/structural validation in the stateless evaluator; reuse the installed OpenSpec CLI and existing task reader.
- [A candidate preview is transient or stale] → Bind evidence to candidate SHA and its observed deployment/run identity; treat unknown or mismatched identity as unavailable.
- [An operator responds but does not update the Request or capability evidence] → Keep the gate active and do not consume Apply attempts until hashed source evidence changes and a new assessment passes.

## Migration Plan

No database migration is expected. New assessments are persisted in existing Run state. Existing Runs without a feasibility record are evaluated before their next transition to Apply; when evidence cannot establish executability, they stay at the gate with the exact missing preconditions. Rollback is the normal application rollback and does not require rewriting saved Runs.
