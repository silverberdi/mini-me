## 1. Trace the existing gate and evidence lifecycle

- [x] 1.1 Trace the accepted gate response from API through `OperatorActionRecord`, native stage-invocation evidence, checkpoint, and Apply dispatch; identify existing idempotency and recovery writers/readers.
- [x] 1.2 Trace how task disposition, published-version evidence, candidate SHA/fingerprint, and gate diagnostics are currently captured and projected; record any missing persistence needed by the specs.

## 2. Route authorized criterion decisions through native Update

- [x] 2.1 Route an accepted Apply-gate response that explicitly changes an existing criterion's disposition to the configured thinking agent's native OpenSpec `update` workflow before any Apply invocation.
- [x] 2.2 Validate updated Change artifacts strictly and preserve the same Run, Change, branch, and worktree; capture before/after candidate snapshots and fail closed on identity changes, invalid artifacts, missing workflow, or unauthorized scope expansion.
- [x] 2.3 Make replay and interruption recovery observe the existing operator action and Update invocation/result before continuing, preventing duplicate Update or Apply dispatch.

## 3. Preserve deferred status and evidence provenance

- [x] 3.1 Record published-version evidence with its source identity and immutable SHA when verifiable; never use missing or mismatched SHA evidence to complete a candidate-specific task.
- [x] 3.2 Ensure an authorized deferral remains visibly deferred/pending, does not count as completed Apply work, and only permits Apply/Verify/PR progression when the strictly validated Change allows it.
- [x] 3.3 Project the Update result, evidence source, remaining candidate evidence, and concrete blocker through the existing human-gate and Run status surfaces without introducing a parallel task-state model.

## 4. Verify the end-to-end recovery

- [x] 4.1 Add focused regression tests for native Update routing, ambiguous/unauthorized responses, strict validation failure, replay/interruption idempotency, deferred-task handling, and evidence provenance.
- [x] 4.2 Run a PostgreSQL-backed E2E observing accepted response → native Update invocation/result → strict validation → native Apply continuation or explicit gate, including durable action, checkpoint, and candidate snapshots; label deterministic agent simulations as simulated.
- [x] 4.3 Run relevant repository and strict OpenSpec validation, and capture the command, exit code, output, and exact candidate SHA for the results.
