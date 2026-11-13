## Context

See `proposal.md` for the incident and desired recovery. The current coordinator already stores Apply snapshots, a current human gate, the latest Apply-gate Update checkpoint, single-use operator actions, stage-invocation claims, and append-only `orchestration_stage_events`. The current Run view renders the generic gate question, Spanish explanation, and response options; a new screen or endpoint is not needed.

The old disposition detail cannot be reconstructed from a later no-op Update. The safe operation is therefore an operator-approved baseline of the Change's current strictly validated task dispositions, bound to the exact existing candidate. Recovery must preserve the old evidence and must not turn missing published-version evidence into candidate proof.

## Goals / Non-Goals

**Goals:** reuse the existing PostgreSQL Run, operator-action, claim, stage-event, and gate paths; make the evidence comparison understandable in the current human gate; commit the authorization and rebaseline evidence atomically; dispatch at most one Apply for the same verified candidate.

**Non-Goals:** reconstruct lost task dispositions by inference, repair state with direct SQL, change Apply counters or retry policy, create another Run, add a generic checkpoint-repair framework, add a new endpoint or UI route, deploy the project, or mark pending/deferred validation complete.

## Decisions

1. **Recognize only the evidenced legacy failure.** Reuse the existing Apply snapshot, accepted human action, native Update stage-invocation result and strict-validation result, current Change task dispositions, and candidate identity. Classify the checkpoint as lost only when these records establish the same Run, Change, branch, worktree, generation, and SHA, and a later same-action Update is a no-op without the original disposition details. Do not infer the missing details or offer rebaseline for unrelated/malformed Apply state.

2. **Present the comparison through the existing gate.** Reuse the current `human_payload` fields (`question`, `explanation_es`, and `options`). The explanation identifies the before snapshot, current task dispositions, accepted action, both Update results, and candidate identity with their persisted evidence references. Offer the explicit rebaseline decision and the existing preserve/cancel choices. This avoids a parallel gate UI and preserves the current response/idempotency flow.

3. **Record a separate baseline without replacing history.** On an accepted, single-use action, re-read the Change and candidate, run native strict validation, and confirm there is no active stage invocation. In one PostgreSQL transaction, consume the operator action, store a separate `apply_checkpoint_recovery` baseline in the Run, and append an `orchestration_stage_events` record containing the prior snapshot, current task dispositions, evidence references, authorization identity, and exact candidate identity. Keep the prior `apply_snapshot`, Update checkpoint, accepted responses, and invocation events intact. Do not add a table unless the existing event and Run records cannot enforce this transaction and idempotency.

4. **Resume through existing Apply dispatch controls.** Commit the recovery record before dispatch. Revalidate the same Run/Change/branch/worktree/generation/SHA and observe claims/invocations immediately before Apply. Use the existing stage claim and operator-action identity to permit one dispatch; a replay observes the committed recovery and invocation instead of creating another. Any mismatch, active invocation, failed strict validation, or ambiguous history leaves the Run gated with no Apply.

5. **Keep task truth and deployment boundaries unchanged.** The baseline copies only current strictly validated dispositions. Pending and deferred tasks remain so; published-version evidence counts only if its immutable SHA matches the candidate. Existing Verify and readiness checks continue to block while required evidence is missing. Project deployment remains the project's CI/CD responsibility.

## Risks / Trade-offs

- [Persisted evidence is insufficient to distinguish a lost checkpoint from an unrelated failure] → Fail closed; do not offer rebaseline and preserve/cancel through the existing gate.
- [A repeated response creates more than one baseline or Apply invocation] → Bind the single-use action, unique event key, baseline, and stage claim to the same Run and candidate; test replay against PostgreSQL.
- [The comparison implies that pending work was completed] → Show dispositions explicitly and keep pending/deferred tasks and SHA provenance in the baseline and UI explanation.
- [A concurrent worker starts Apply while rebaseline is being accepted] → Check active invocation/claim and commit the baseline with accepted-action consumption before dispatch; a conflict leaves the gate intact.

## Migration Plan

No schema migration is planned. The implementation uses the existing Run JSON, single-use operator action, stage invocation claim, and append-only stage-event journal. If the existing transaction cannot atomically retain the baseline and event, stop and update this Change before introducing persistence.

## Open Questions

None. The recovery is limited to the evidence and authorization already defined by Issue #387.
