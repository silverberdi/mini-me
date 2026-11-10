## Context

See proposal.md - Why. The API currently stores accepted gate responses in the existing durable `OperatorActionRecord` and dispatches them back through `execute_project_request`. The coordinator already records native stage invocations and has a thinker-backed OpenSpec `UPDATE` path for proposal correction/review findings. Apply exhaustion responses currently resume the Apply path; there is no explicit handoff that applies an operator-authorized change to an existing criterion first.

The rector contract assigns OpenSpec artifact authorship to agents, requires idempotent human-gate handling, and keeps Apply recovery on the active Change/worktree with evidence-based fail-closed checks. Existing specs already define gate diagnostics, accepted-response cycle reset, and partial Apply recovery; this Change adds only the missing criterion-disposition transition and evidence provenance.

## Goals / Non-Goals

**Goals:**

- Reuse the accepted gate action, native stage invocation records, configured thinking-agent role, OpenSpec `update` workflow, and strict Change validation.
- Ensure an explicit operator decision about a criterion is applied to the active Change before Apply resumes.
- Preserve the same Run, Change, branch, and worktree; capture an immutable evidence snapshot before and after an Update that changes tracked files.
- Keep published-version evidence distinct from evidence for the current candidate.
- Make the disposition of deferred work visible and let the validated Change determine whether Apply may continue and whether Verify/PR remains blocked.

**Non-Goals:**

- Changing Apply attempt limits, cycle reset semantics, or general retry strategy (Issues #259 and #375).
- Replacing the existing human-gate UI or its general diagnostic payload (Issue #321).
- Having mini me author OpenSpec content, infer human authorization, mark unsupported work complete, or deploy a project.
- Adding a parallel task-status engine, work queue, or database history model.

## Decisions

1. **Use the configured thinking agent and native OpenSpec Update.** The accepted response remains the operator's exact input. The thinker determines whether it explicitly changes an existing criterion's disposition and, when authorized, updates only the active Change using the installed native `update` workflow. This reuses the existing Update invocation path used for proposal corrections. A bespoke classifier or direct coordinator edit would either duplicate agent reasoning or violate OpenSpec ownership.

2. **Keep the existing Run and gate action as the durable identity.** Bind the Update invocation/result and validation checkpoint to the accepted operator-action identity and current gate fingerprint. Observe that action and any started/completed invocation after replay or restart before dispatching anything. Do not add a new Run, queue, or state table. Add a migration only if tracing the existing action/invocation records proves they cannot represent this lifecycle.

3. **Validate before dispatching Apply.** Run the existing strict OpenSpec Change validation after native Update. If the workflow is missing, the agent asks for material clarification, or validation fails, preserve the worktree and surface the concrete blocker; do not consume an Apply attempt or fall through to a generic retry.

4. **Preserve candidate lineage and snapshot changes honestly.** Keep Run, Change, branch, and worktree identity fixed. Capture Git HEAD and worktree/diff evidence before and after Update. If the authorized artifact edit changes tracked content, record a new immutable snapshot in the same candidate lineage; never label evidence from the previous snapshot as evidence for the new one.

5. **Treat deferral as a disposition, not completion.** The native Update records the authorized deferral in the Change artifacts without marking missing validation evidence complete. Apply may continue with other work only when the updated Change permits it. If the updated acceptance criteria still require the deferred evidence, Verify/PR readiness remains blocked and the gate must say exactly why.

6. **Record provenance from the evidence source.** Store the reported version/source and a verified immutable SHA when available. A missing or mismatched published SHA can be retained as baseline context, but cannot satisfy a criterion tied to the candidate SHA.

## Risks / Trade-offs

- [The thinker could broaden the operator's requested update] → Constrain the native Update to the explicit response and active Change; validate the resulting diff and strict artifacts; require a human decision for ambiguity or material changes not authorized by the response.
- [An Update may alter the worktree snapshot] → Record before/after Git identity and preserve both invocation histories; fail closed if Run, Change, branch, or worktree identity changes.
- [Published evidence may lack a verifiable SHA] → Preserve it as operator-reported baseline evidence with unknown identity and state plainly that it does not validate the candidate.
- [Provider capacity may be unavailable] → Preserve the accepted response and checkpoint in the existing durable action records; report capacity wait without starting Apply or losing the decision.

## Migration Plan

No schema migration is planned. First trace the existing operator-action, stage-invocation, run checkpoint, and evidence records. Reuse them if they preserve the response, gate identity, Update result, and before/after candidate snapshots. If the trace proves a durable field is missing, add only that field through a conservative Alembic migration and include forward/backward data-safety evidence. Release through the normal PR and CI path; do not deploy or mutate a production Run as part of this Change.
