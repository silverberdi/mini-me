## 1. Inspect and define the cycle boundary

- [x] 1.1 Trace Apply counter readers/writers, accepted human-response dispatch, operator-action idempotency, invocation history, and Run status projections; record the exact existing persistence used for each.
- [x] 1.2 Confirm the configured hard limit and no-progress limit remain unchanged, and document how the current-cycle count is distinguished from immutable prior invocation evidence.

## 2. Implement the accepted-response transition

- [x] 2.1 On an accepted continuation of the active Apply exhaustion gate, start exactly one new Apply cycle at 0/3 attempts and zero no-progress attempts on the same Run, Change, candidate, branch, and worktree.
- [x] 2.2 Bind the cycle reset to the durable operator-action identity so duplicate or crash-retried submissions cannot reset or dispatch a second time; preserve all previous action and invocation records.
- [x] 2.3 Keep cancellation, other gate types, candidate snapshot, regression checks, provider capacity/budget enforcement, and native Apply semantics unchanged.
- [x] 2.4 Project the active cycle's attempt count and hard limit consistently through the Run API and Trabajo actual UI, including 0/3 before the first invocation in a newly authorized cycle.

## 3. Verify cycle behavior and evidence

- [x] 3.1 Add focused tests proving an accepted Apply gate response resets the current cycle, executes within the same candidate identity, and preserves prior attempt history.
- [x] 3.2 Add regression tests proving a duplicate response does not create another cycle or invocation, cancellation and unrelated gates do not reset Apply counters, and the three-attempt and no-progress limits still stop a cycle.
- [ ] 3.3 Run a PostgreSQL-backed API/coordinator E2E that observes the accepted action, cycle transition, invocation result, and retained Run/candidate identity; label any deterministic runner as simulated and do not claim real-agent evidence from it.
- [x] 3.4 Run relevant repository validation and OpenSpec validation, then capture the resulting evidence against the exact candidate SHA; report any provider-backed E2E separately and only when an authorized test environment is available.
