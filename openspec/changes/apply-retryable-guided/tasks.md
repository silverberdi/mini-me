## 1. Apply outcome evidence

- [ ] 1.1 Inventory `_run_apply` callers and define a structured result carrying completed/pending automatic tasks, candidate identity, errors, blockers, and original human-required question/options.
- [ ] 1.2 Capture changed paths, candidate SHA/tree identity, diff presence, and coordinator-run test results after Apply; keep evidence bound to the candidate.
- [ ] 1.3 Update callers to consume the structured result without changing native OpenSpec workflow invocation.

## 2. Bounded guided recovery

- [ ] 2.1 Implement the three outcome routes: human-required without retry consumption, partial progress retry, and terminal failure escalation.
- [ ] 2.2 Build corrective context from observed state, require evidence-backed `[x]` task marking, preserve valid work, and keep it distinct from reviewer `corrections`.
- [ ] 2.3 Reuse the same Change, branch, worktree, and candidate; select native Continue only when directly resumable, otherwise invoke native Apply.
- [ ] 2.4 Enforce no-progress and hard total attempt limits together with existing correction and budget limits.
- [ ] 2.5 Stop retries on candidate identity changes or detected file, supported-task, or test regression.
- [ ] 2.6 Gate Verify on evidence-backed Apply completion or native readiness.

## 3. Deterministic recovery verification

- [ ] 3.1 Add deterministic orchestration coverage with a simulated partial Apply followed by completion, proving corrective evidence and candidate/worktree identity are retained.
- [ ] 3.2 Cover human-required routing, no-progress and hard limits, regression stop, test/task evidence rules, reviewer-correction separation, and Verify gating.
- [ ] 3.3 Run focused tests and strict OpenSpec validation; record exact commands and outcomes without presenting the simulated runner as real-agent E2E evidence.
