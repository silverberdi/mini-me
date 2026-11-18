## 1. Detect and explain the lost checkpoint

- [x] 1.1 Map the persisted Apply snapshot, accepted operator action, native Update invocation/validation, current task dispositions, and candidate identity used by the recovery path; reuse existing PostgreSQL records and fail closed when any evidence is absent or contradictory.
- [x] 1.2 Build the current human-gate explanation from those persisted records, showing the prior snapshot, current dispositions, accepted action, validated Update, later no-op Update, and exact Run/Change/branch/worktree/generation/SHA identity.

## 2. Persist authorized rebaseline and resume safely

- [x] 2.1 Add an explicit single-use rebaseline response to the existing human-gate path; re-read and strictly validate the current Change, verify the same candidate identity, and confirm there is no active invocation before acceptance.
- [x] 2.2 In one PostgreSQL transaction, consume the accepted action, record the separate current-state baseline and append-only recovery evidence while preserving prior snapshots, decisions, and invocation events; do not add a table or mutate state manually.
- [x] 2.3 Resume through the existing stage claim and dispatch path at most once on the same Run, Change, branch, worktree, generation, and SHA; replays observe the recorded action and invocation, while mismatch or ambiguity leaves the human gate active with preserve/cancel choices.
- [x] 2.4 Preserve all current task dispositions and source provenance; do not mark pending or deferred tasks complete or treat published-version evidence with unknown/different SHA as candidate evidence.

## 3. Verify transactional and fail-closed behavior

- [x] 3.1 Add focused coordinator tests for evidenced lost-checkpoint recovery, missing/ambiguous evidence, identity mismatch, active invocation, invalid strict validation, pending/deferred disposition preservation, and action replay without duplicate Apply.
- [x] 3.2 Add PostgreSQL/API integration coverage proving the recovery event, authorization, and baseline persist atomically and the API presents the evidence and valid options; label deterministic agent simulation as simulated, not a real invocation.
- [x] 3.3 Run focused tests and strict OpenSpec validation; retain command output and bind the results to the immutable implementation SHA.

## 4. Final-batch live Run evidence

- [ ] 4.1 [DEFERRED] Recover the identified pre-deployment Run `fd1f92b5-e0d6-40cd-a2ab-e46f65fe40ab` through the deployed API and native Apply workflow, with no direct database edits or new Run. Capture the accepted rebaseline, exact same candidate identity, one actual Apply invocation/result/effects, preserved prior history, and pending/deferred task states. **Deferred until the final validation batch after deployment by the project's CI/CD.** If the original Run or identity is no longer safely available, stop and report the observed blocker without substituting a different Run.
