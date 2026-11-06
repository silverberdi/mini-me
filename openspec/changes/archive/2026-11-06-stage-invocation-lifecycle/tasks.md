## 1. Durable Invocation Evidence

- [x] 1.1 Define stable candidate identity and attempt evidence using current run, worktree/branch, generation, and candidate SHA where available; distinguish invocation event types from stage-transition events.
- [x] 1.2 Persist append-only invocation start and terminal events with attempt identity, run, stage, candidate, start/finish timestamps, duration, and the native workflow's observed result/handoff, preserving question/options as received.
- [x] 1.3 Update dashboard timeline projection and any other identified event consumer to treat only transition event types as transitions; add a regression test for invocation-event filtering.

## 2. Atomic Dispatch and Recovery

- [x] 2.1 Claim each run/stage/candidate invocation in PostgreSQL before workflow dispatch, renew its lease during execution, and fence stale workers before they can record results or advance the run.
- [x] 2.2 Apply the claim lifecycle to native stage dispatches, including Verify; an existing active invocation must prevent scheduler or worker re-entry from dispatching again.
- [x] 2.3 Preserve the native HUMAN_REQUIRED handoff, close the invocation while retaining its gate, pass an accepted response as context to the same native stage workflow, and block dispatch until acceptance; cover Apply/Verify handoffs without changing native workflow semantics.
- [x] 2.4 Capture and persist coordinator PID/host-boot/process-start identity at invocation start and spawned workflow process-group identity immediately after process creation; terminate and fail the dispatch if process evidence cannot be persisted, and durably mark recovery unavailable when the OS cannot provide a stable identity.
- [x] 2.5 On lease expiry, fence the old claim and allow one native re-invocation only after proving the old coordinator process and workflow process group are absent and run/worktree/stage/generation/candidate identity is unchanged; missing, live, ambiguous, or unsupported process identity stops for operator intervention. Test live process, absent process, PID reuse, missing evidence, unsupported platform, and second interruption.

## 3. Durable Human Response Idempotency

- [x] 3.1 Persist acceptance of a gate response against the current gate using existing operator-action storage; repeated submission for the same gate and response, including after restart or completion, must resolve to the existing action and schedule only one continuation.
- [x] 3.2 Preserve the accepted response needed for continuation without adding a UI redesign or changing gate decision semantics; verify a later distinct gate remains independently answerable.

## 4. Verification Evidence

- [x] 4.1 Add unit tests for invocation outcome records, claim contention, fencing, candidate identity changes, HUMAN_REQUIRED blocking, and bounded recovery decisions.
- [x] 4.2 Add PostgreSQL integration coverage with the real coordinator proving concurrent dispatch yields at most one active invocation, duplicate gate responses dispatch once and forward the accepted response, Verify reentry is suppressed, and recovery requires observed coordinator/process-group termination and is bounded. Label mocked workflow calls as integration/unit evidence, not real OpenSpec E2E.
- [x] 4.3 Run focused tests and the relevant full test/build checks required by the repository workflow; retain exact commands and results as evidence, and run `git diff --check`.

### Evidence

- PostgreSQL integration ran against the isolated, migrated `minime_test` database as `minime_app`; the test URL was derived from the service URL only in the test process. `minime` production database was not used. `tests/test_stage_invocation_lifecycle_postgres_e2e.py` exercises the real coordinator and PostgreSQL claims, heartbeat renewal, fencing, process-exit proof, same-candidate recovery, and the one-retry ceiling. `tests/test_human_gate_current_payload_postgres_e2e.py` exercises the persisted API response, duplicate scheduling suppression, accepted response forwarding, and replay after completion. These use a mocked workflow scheduler/agent boundary where noted; they are PostgreSQL/API integration evidence, not a real OpenSpec E2E.
- Exact focused backend command: `python -m pytest -p no:cacheprovider -q tests/test_agent_runtime_confinement.py tests/test_doc_closing_idempotency.py tests/test_human_gate_current_payload.py tests/test_human_gate_current_payload_postgres_e2e.py tests/test_orchestration_continuity.py tests/test_stage_invocation_lifecycle.py tests/test_stage_invocation_lifecycle_postgres_e2e.py tests/test_dashboard_cost_postgres_e2e.py` — **82 passed**, 2 deprecation warnings.
- Focused lifecycle command: `python -m pytest -p no:cacheprovider -q tests/test_stage_invocation_lifecycle.py tests/test_stage_invocation_lifecycle_postgres_e2e.py tests/test_human_gate_current_payload.py tests/test_human_gate_current_payload_postgres_e2e.py` — **31 passed**, 2 deprecation warnings.
- `npm --prefix frontend test` — **28 passed**. `npm --prefix frontend run build` — **passed**; Angular emitted optional-chain warnings and the initial bundle exceeded its configured 512 kB budget by 5.88 kB.
- `python -m ruff check --no-cache` on the changed Python implementation and test files — **All checks passed**. Python syntax compilation in memory — **232 files compiled**. (`compileall` against the temporary server copy could not write bytecode because that copy is owned by the SSH user; no source compilation errors were reported.)
- `openspec validate stage-invocation-lifecycle --strict` — **valid**. `git diff --check` — **clean**.
