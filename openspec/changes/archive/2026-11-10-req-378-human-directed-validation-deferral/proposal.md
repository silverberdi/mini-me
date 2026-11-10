## Why

An accepted human response that explicitly changes the disposition of a validation criterion is currently liable to be treated as generic Apply clarification. This can repeat the same Apply path without reflecting the operator's decision in OpenSpec, while published-version evidence and candidate evidence remain easy to confuse. The result is repeated operator intervention without a clear, auditable next step.

## What Changes

- Route an explicit human decision to defer or reclassify an existing Change criterion through the configured thinking agent's native OpenSpec `update` workflow before another Apply invocation.
- Preserve the operator's exact decision, the updated Change artifacts, and evidence provenance across the accepted gate response and continuation.
- Keep a deferred criterion pending and distinguish published-version evidence from evidence for the current candidate SHA.
- Continue with native Apply on the same Run, Change, branch, worktree, and candidate only after the updated artifacts are coherent and the candidate identity remains valid; otherwise show the concrete blocker and valid operator choices.

## Capabilities

### New Capabilities

<!-- None: this change extends existing orchestration and Apply behavior. -->

### Modified Capabilities

- `openspec-orchestration-continuity`: preserve the meaning and provenance of an operator's decision that changes a criterion's disposition, and continue from the resulting durable checkpoint.
- `openspec-native-apply-and-verify`: route authorized criterion updates through native OpenSpec `update` before resuming native Apply, without claiming deferred or unsupported validation as complete.

## Impact

- Orchestration and gate-response routing in `src/minime/services/orchestration_coordinator.py` and `src/minime/api/app.py`.
- Existing durable operator-action and run/checkpoint records; schema changes only if inspection during design proves they are necessary.
- Human-gate projection in the existing UI, if needed to show decision, evidence source, and continuation result.
- Focused orchestration tests and a PostgreSQL-backed E2E for response → native Update → Apply continuation and durable evidence.
