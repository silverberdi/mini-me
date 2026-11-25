## 1. Mechanical Worktree Rebaseline in WorktreeManager

- [x] 1.1 Implement `rebaseline_apply_worktree(worktree_path, candidate_sha, change_name)` in `src/minime/services/worktree_manager.py` that reverts tracked repository files to `candidate_sha` and purges untracked files while strictly preserving `openspec/changes/<change-name>/`.
- [x] 1.2 Add unit tests in `tests/test_watchdog_worktree_recovery.py` verifying that `rebaseline_apply_worktree` correctly restores clean candidate status and preserves OpenSpec change artifacts.

## 2. Autonomous Stage Recovery in NativeOrchestrationCoordinator

- [x] 2.1 Implement `_recover_dirty_apply_invocation` in `src/minime/services/orchestration_coordinator.py` to execute before candidate identity verification in `_begin_stage_invocation` when the prior process is proven absent and mechanical remediation is active.
- [x] 2.2 Record `STAGE_INVOCATION_ABANDONED` citing mechanical worktree rebaseline, increment `recovery_count = 1`, reacquire the stage claim, and resume the implementer without generating a human gate.
- [x] 2.3 Suppress opening a spurious `watchdog_escalation` human gate in `WatchdogService` and `NativeOrchestrationCoordinator` when `mode == "mechanical_remediation"` and `recovery_count == 0`.

## 3. Human Gate Lifecycle and Idempotency Anti-Deadlock

- [x] 3.1 Update `prepare_gate_response` and `complete_gate_response` in `src/minime/api/app.py` so that an operator response resolving a gate that results in `PAUSED` or fails to advance stage lifecycle forces renewal of the active `gate_id` in `stop_details["human_payload"]`.
- [x] 3.2 Verify that subsequent operator submissions generate fresh idempotency tokens and are not rejected by a stale `COMPLETED` action record in `operator_action_records`.

## 4. Integration, E2E Verification & Audit

- [x] 4.1 Implement `tests/test_watchdog_dirty_worktree_recovery_e2e.py` with real PostgreSQL simulating an interrupted Apply invocation with dirty worktree files, asserting autonomous mechanical restoration, candidate match, and runner re-dispatch without human gates.
- [x] 4.2 Execute targeted test verification: `pytest tests/test_watchdog_dirty_worktree_recovery_e2e.py tests/test_watchdog_worktree_recovery.py tests/test_watchdog_service.py`.
