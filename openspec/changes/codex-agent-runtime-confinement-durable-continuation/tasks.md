## 1. Private confined agent runtime

- [x] 1.1 Build one shared private per-attempt writable runtime for implementer and reviewer processes; preserve fail-closed OS confinement and cleanup on exit, timeout, cancellation, and launch failure. Evidence: shared `AgentProcessConfinement.runtime_session`; unit tests plus Linux Bubblewrap timeout/cancellation cleanup.
- [x] 1.2 Project only the already-authorized Codex auth file into the private runtime; prevent persistent credential mutation and detect unsupported credential rotation. Evidence: mode/symlink checks, private copy and output scrubbing tests, rotation detection/no-copyback regression.
- [x] 1.3 Add Linux Bubblewrap tests proving permitted worktree/runtime writes and denied host/runtime/managed/other-worktree/home/temp writes. Evidence: `test_real_bubblewrap_write_boundaries_and_ephemeral_cleanup` passes in Linux container.
- [x] 1.4 Run the real Codex CLI app-server initialize handshake without a turn request and with network isolated where supported. Evidence: Codex CLI 0.153.0 returned JSON-RPC initialize response under Bubblewrap with network namespace unshared; no `turn/start` sent.

## 2. Environment failure semantics

- [x] 2.1 Classify only evidenced sandbox/runtime filesystem initialization failures as `ENVIRONMENT_UNAVAILABLE`, preserving authentication, quota, rate-limit, policy, and unknown-error precedence. Evidence: parser precedence and unknown-error regression tests.
- [x] 2.2 Prove environment failures do not degrade provider health, consume corrective retry budget, or cause reassignment. Evidence: PostgreSQL-backed CONTINUE pipeline records `WAIT_EXTERNAL`, zero corrective retries, no reassignment, and unchanged AVAILABLE health.

## 3. Durable continuation

- [x] 3.1 Reconstruct a deleted execution worktree only from canonical Run/Job, ownership, repository binding, branch/base, recovery snapshot, and published-artifact evidence. Evidence: `WorktreeManager` rejects missing/contradictory ownership, recovery-branch, base, snapshot, and artifact evidence before recreating the canonical path.
- [x] 3.2 Exercise canonical PostgreSQL-backed Control Plane `CONTINUE` using the same Run/Job IDs and preserve prior attempt evidence without provider invocation. Evidence: isolated PostgreSQL end-to-end test uses the real Control Plane, claim/recovery, orchestration, WorktreeManager, and confined CLI runner with a local diagnostic executable that emits a controlled environment stop; no provider/model is invoked.
- [x] 3.3 Permit safe reconstruction after a consistent, authoritative descendant main advance while retaining original base B in all durable and returned ownership identities. Evidence: PostgreSQL/Git integration advances remote `main` B→C while managed `main` remains at B; authenticated fetch observes C without moving the canonical local branch, CONTINUE rebuilds the same recovery snapshot, and Run, Job, ownership, marker, and `WorktreeInfo` retain B. A second remote-only descendant is accepted; local divergence, remote rewrite, mismatched snapshot event, branch tampering, candidate evidence, contradictory identities, and terminal state are refused.
- [x] 3.4 Report the persisted Run and linked Job outcomes from CONTINUE without implying execution is active when it stopped. Evidence: the PostgreSQL continuation test asserts that the action result/payload report `run_active=true`, `execution_active=false`, `WAITING_CAPACITY` Run outcome and Job status; unit idempotency regression rejects the prior “resumed successfully” wording.

## 4. Verification

- [x] 4.1 Run focused confinement, runner, outcome, worktree, and continuation tests; run the isolated PostgreSQL integration test. Evidence: focused suite passes locally; Linux Bubblewrap/Codex suite passes in the isolated Linux validation container.
- [x] 4.2 Run Ruff, strict OpenSpec validation, and `git diff --check`; review the scoped diff and record any environment limitation. Evidence: Ruff and OpenSpec strict pass; `git diff --check` passes. The pre-existing `tests/test_stage_c_isolation.py` file is not Ruff-format-clean at base; changed Python source and new tests are formatted.
- [x] 4.3 Validate B→C continuation, truthful Control Plane results, Linux confinement regressions, formatting, and strict OpenSpec after the post-review remediation. Evidence: 130 focused macOS tests passed (2 Linux-only tests skipped there); isolated PostgreSQL B→C test and CONTINUE unit tests pass; Linux Bubblewrap/Codex CLI confinement suite passes 12/12; Ruff, applicable formatting, strict OpenSpec, and `git diff --check` pass.
