## Context

See `proposal.md` for motivation. The current coordinator already records proposal-feasibility hashes in `complexity_assessment`, uses native OpenSpec validation, creates durable per-stage claims, and persists the active human-gate payload in the existing Run JSONB state. The candidate commit helper is currently reached after Verify for some paths, while the accepted-gate API schedules a background continuation. The implementation must keep the same Run, candidate branch/worktree, native workflows, PostgreSQL authority, and existing claim/idempotency boundaries.

## Goals / Non-Goals

**Goals:**

- Make a reviewer-approved proposal correction the explicit source of the new proposal-evidence baseline, without accepting changed feasibility merely by refreshing hashes.
- Make the tested candidate SHA immutable and observable before Verify starts.
- Ensure only one existing execution authority dispatches DOC_CLOSING after a gate response.
- Give native Propose a concise scenario-completeness reminder while leaving validation to OpenSpec CLI.
- Explain affected artifacts and operator choices in existing gate projections without changing the choices' authorization effects.

**Non-Goals:**

- Implement or emulate OpenSpec workflows, add a second scheduler/dispatcher, or introduce a new retry policy.
- Weaken strict validation, drift detection, Verify, candidate integrity, or human authorization.
- Add database tables, a new gate engine, or a general diff framework.
- Change merge, production deployment, provider selection, or unrelated orchestration stages.

## Decisions

### Bind proposal evidence to the exact approved revision

After the independent reviewer approves a corrected proposal, derive task/scenario reference hashes from the exact artifacts that were reviewed. Persist the approved review result and refreshed hashes together in the same existing PostgreSQL transaction. Before advancing, run the existing strict OpenSpec validation and feasibility evaluation against those artifacts. If identities, mappings, requirements, or preconditions changed in a feasibility-relevant way, re-evaluate the affected evidence and remain blocked on any unresolved result. Do not reuse the old hashes as a blanket waiver and do not add a new approval role.

### Freeze the candidate at the Apply-to-Verify boundary

Use the existing candidate-commit helper and current branch/worktree after candidate tests pass, but establish and persist the new candidate SHA before the Verify dispatch. Verify must receive and record that SHA. If a correction changes the candidate later, route it through the existing Apply/test path and create a new SHA before another Verify. Commit only the candidate's intended changes; do not include unrelated workspace paths or create an empty commit. A test or Git failure leaves the Run before Verify with its evidence and worktree preserved.

### Reuse the durable stage claim for DOC_CLOSING

Keep the gate response's existing durable action record and idempotency key. The API records the accepted response and makes the same Run eligible; it does not launch the DOC_CLOSING native workflow and returns `ACCEPTED` without waiting for a worker. The PWA immediately shows that the response was received and names the pending stage; it only shows that execution started after the refreshed Run state provides that evidence. On API failure, the unresolved gate and a failure message remain visible. The existing Scheduler/coordinator path claims the Run-stage-candidate tuple with the current durable claim before invoking Sync/Archive. Do not create another queue, lock, scheduler, or dispatch service. A repeated response or a competing worker must reconcile to the same action/claim rather than starting another process.

### Keep Propose native and make the reminder subordinate to the CLI

Add the short requirement reminder to the existing native Propose prompt. Continue to run the installed OpenSpec CLI strict validation and use its actual result as the gate. Do not create a Python parser, semantic scenario checker, or substitute artifact generator.

### Extend the existing human-gate projection additively

Use the current `human_payload`/`stop_details` JSONB and existing gate display. Add only the evidence needed to identify affected tasks/requirements and show their observed before/after change, plus action/consequence explanations associated with the existing stable option values. Treat `diff`, `affected_items`, and `option_explanations` as optional end-to-end: old payloads and gates without those fields must render as they do today. Preserve native wording and option order/value; any Spanish explanation must not be submitted as a different authorization value. For gates without an artifact change, identify the actual blocking evidence and state that a diff does not apply. If the diff cannot be observed, report that explicitly; never synthesize one. Reuse the existing frontend rendering path and add only the minimal rendering needed for these optional fields.

## Risks / Trade-offs

- **[Refreshing a proposal baseline could hide a substantive change]** → Re-run existing strict validation and feasibility checks on the exact reviewer-approved artifacts; block when changed identities or preconditions are not revalidated.
- **[A commit could capture unrelated workspace files or omit candidate changes]** → Compare the intended candidate delta with staged paths, verify the resulting clean state and SHA, and stop before Verify on any mismatch.
- **[The API and Scheduler could both schedule a continuation]** → API acceptance has no workflow side effect; the existing durable stage claim remains the single dispatch fence, with an integration test across competing entry points.
- **[Richer gate text could alter native option semantics or expose sensitive data]** → Keep stable option response values and redaction, derive diffs only from observed artifacts, and render explanations as presentation metadata.

## Migration Plan

No database migration is planned: the Run already stores gate details in JSONB and the existing stage claim and operator-action records provide the required durable authority. Rollback is a code rollback; older Run payloads remain readable because new explanation/evidence fields are optional. Do not rewrite historical Runs or dispatch them during deployment.
