## Why

When an agent process dies during a mutating stage (specifically `IMPLEMENTING` / Apply) due to a host reboot or daemon interruption, it leaves partial uncommitted edits and untracked scratch files in the worktree. Currently, although the Watchdog SRE in `mechanical_remediation` mode successfully proves process absence (`child_process_state: GONE`), it erroneously bails out to a spurious human gate (`watchdog_escalation`). When the operator authorizes resumption, the native coordinator strictly rejects the claim because the candidate fingerprint no longer matches the entry candidate (`candidate_matches = False`), falling into `status=PAUSED`. Furthermore, the failed authorization is durably recorded as `COMPLETED: PAUSED` while the gate retains the same `gate_id`, causing an idempotency deadlock where the API serves stale cached paused responses and the scheduler starves the run.

Resolving interrupted workspaces when process absence is mathematically proven is pure deterministic infrastructure hygiene. Asking the human operator violates autonomous operation, and failing to clean the dirty scratch files makes human authorization inoperable. This change adds autonomous mechanical worktree rebaseline and eliminates the spurious gate, while providing deterministic gate renewal to prevent idempotency deadlocks.

## What Changes

* **Autonomous Mechanical Worktree Rebaseline**: In `mechanical_remediation` mode, when process absence is proven (`child_process_state: GONE`) on an interrupted mutating stage (such as `APPLY`):
  - Watchdog and WorktreeManager automatically restore the worktree to the clean entry candidate (`git checkout -f <candidate_sha>`).
  - Cleans untracked debris left by the dead agent while strictly preserving `openspec/changes/<change-name>/`.
  - Recalculates candidate identity so `candidate_matches = True` is guaranteed.
  - Reacquires the stage invocation claim atomically, incrementing `recovery_count` (bounded to 1 automatic recovery attempt).
  - Resumes execution of the implementer without generating any human gate.
* **Erradication of Spurious Gate on Orphaned Processes**: Eliminates opening a `watchdog_escalation` human gate on the first occurrence of an orphaned process under `mechanical_remediation` mode. Human escalation occurs only if the automatic rebaseline + retry was already consumed (`recovery_count >= 1`) or if evidence remains ambiguous.
* **Gate Lifecycle Renewal and Idempotency Anti-Deadlock**:
  - If an operator gate response results in `PAUSED` or fails to effect a stage transition, the active gate renews its `gate_id` (or transitions the operator action to `REQUIRES_RETRY` / `SUPERSEDED`), ensuring subsequent submissions are not swallowed by a stale `COMPLETED` response.
* **Deterministic Real E2E Test**:
  - Adds integration tests (`tests/test_watchdog_dirty_worktree_recovery_e2e.py`) verifying that an interrupted Apply with dirty worktree files is autonomously rebaselined, candidate identity verified, claim reacquired, and the runner resumed without human gates.

## Capabilities

### Modified Capabilities
- `run-stall-watchdog`: Adds autonomous mechanical worktree rebaseline on orphaned mutating stages in `mechanical_remediation` mode, eliminating the spurious human gate on the first proven orphaned process.
- `scheduler-and-recovery-convergence`: Enables atomic reacquisition of stage claim after mechanical worktree restoration where candidate matches the entry candidate.
- `operator-actions-control-plane`: Enforces gate renewal and invalidation of stale `COMPLETED` paused actions so failed gate resolutions do not trap operators in idempotency deadlocks.

## Impact

- `src/minime/services/watchdog_service.py`: Dispatches mechanical worktree rebaseline when child process is GONE in `mechanical_remediation` mode instead of immediately escalating to human gate.
- `src/minime/services/worktree_manager.py`: Adds `rebaseline_stage_worktree(worktree_path, candidate_sha, change_name)` preserving `openspec/changes/<change-name>/`.
- `src/minime/services/orchestration_coordinator.py`: Connects watchdog mechanical rebaseline before stage invocation re-entry so `candidate_matches` is cleanly satisfied.
- `src/minime/api/app.py`: Renews active `gate_id` when an operator action completes without stage transition, preventing cached idempotency blocks.
- `tests/test_watchdog_dirty_worktree_recovery_e2e.py`: Real PostgreSQL E2E test verifying end-to-end recovery of an interrupted Apply stage.
