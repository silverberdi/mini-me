## 1. Contracts, models, and persistence

- [x] 1.1 Define orchestration stage, human-gate, candidate-generation, stop-reason, and external-action domain schemas without adding orchestration phases to `JobStatus`; verify serialization and fail-closed validation.
- [x] 1.2 Add PostgreSQL/SQLAlchemy models and repositories for runs, stage events, candidate generations, and idempotent external actions, including an active-only uniqueness guard that permits historical runs and action-key constraints.
- [x] 1.3 Add Alembic migration `007_continuation_governance` → 008 using an identifier no longer than 32 characters; verify upgrade/downgrade and leave migrations 001–007 unchanged. (Verified on disposable PostgreSQL database `minime_008_verify`; database dropped after verification.)

## 2. Admission and deterministic coordinator

- [x] 2.1 Implement one-change admission that reuses readiness, durable binding, worktree, and capacity authorities; prove refusal for non-READY, ambiguous binding, failed preflight, and duplicate active runs.
- [x] 2.2 Implement the finite stage graph ending at `PR_PREPARED`, with separate `READY_FOR_HUMAN_MERGE` human-gate state and resumable `WAITING_CAPACITY`/`WAITING_EXTERNAL`/`NEEDS_HUMAN` stops plus evidence requirements for every advancement.
- [x] 2.3 Implement coordinator invocation of the existing implementation pipeline and 007 continuation governance, preserving attempts, decisions, handoffs, diagnostics, and provider policy rather than interpreting agent prose.
- [x] 2.4 Implement stage checkpoint persistence before/after each existing checks, review, audit, and remediation boundary with correlation IDs and deterministic transition events.

## 3. Candidate, review, and audit coordination

- [x] 3.1 Implement candidate freeze/generation recording from the actual managed worktree HEAD, registered base SHA, manifest/hash, and authorship history; reject unexpected identity changes.
- [x] 3.2 Implement complementary-review loop integration that accepts only the existing authoritative verdict for the current candidate and routes `CHANGES_REQUIRED` through 007 remediation.
- [x] 3.3 Implement DeepSeek Direct audit loop integration with full current-candidate SHA/base binding, read-only boundary, blocking-finding rules, and mandatory full re-audit after remediation.
- [x] 3.4 Add integration tests covering successful path, partial implementation correction, false blocker/reassignment, review remediation, audit remediation, stale authority rejection, and model-independence policy.

## 4. Restart and external-action reconciliation

- [x] 4.1 Extend startup recovery and resume to reconstruct the next safe coordinator action from PostgreSQL, Git, and provider state at every specified orchestration boundary.
- [x] 4.2 Implement idempotent push/PR preparation and reconciliation by reserving and committing durable action identity, target identity, and request fingerprint before each mutation; verify exact audited head SHA, repository/base identity, existing PR adoption, and fail-closed remote mismatch handling.
- [x] 4.3 Add failure-injection tests for restart after admission, attempts, decisions, handoffs, capacity wait, checks, freeze, review PASS/CHANGES_REQUIRED, audit PASS/FAIL, and before/after PR creation, asserting no duplicate side effects.

## 5. API, CLI, and observability

- [x] 5.1 Add `minime orchestrate start <project> <change>`, `status <run>`, and `resume <run>` with automatic driving to `PR_PREPARED` plus one of the four legitimate outcomes and no direct client-side provider/Git/GitHub execution.
- [x] 5.2 Add API/read models for run status, stage history, current job/executor, candidate/review/audit bindings, capacity, counters, PR identity, human gate, `WAITING_EXTERNAL`, and structured stop detail with secret redaction.
- [x] 5.3 Add CLI/API tests for admission refusal, `WAITING_CAPACITY`/`WAITING_EXTERNAL` waiting and resume, `READY_FOR_HUMAN_MERGE`, `NEEDS_HUMAN`, candidate-bound evidence, and redaction.

## 6. Acceptance and evidence closure

- [x] 6.1 Run a real coordinator integration path across existing implementation, continuation, checks, review, and audit services using PostgreSQL and deterministic Git/GitHub adapters; retain logs and database evidence. (Verified against disposable PostgreSQL database `minime_008_verify`.)
- [x] 6.2 Run all 14 acceptance scenarios from the proposal/request, including temporary capacity versus human escalation and OpenRouter remaining drain-only; record pass/fail evidence tied to the candidate/run.
- [x] 6.3 Run focused unit tests, orchestration integration/restart/idempotency tests, PostgreSQL transaction tests, Git fake tests, GitHub reconciliation tests, Ruff, and the project validation commands; attach deterministic results to the change evidence. (PostgreSQL-backed 008 integration tests: 4 passed.)
