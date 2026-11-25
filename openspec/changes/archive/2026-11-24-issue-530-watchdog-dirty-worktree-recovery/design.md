## Context

See `proposal.md` for motivation. Currently, `NativeOrchestrationCoordinator` has an established pattern for dirty worktree recovery in `DOC_CLOSING` (`_recover_dirty_documentation_invocation`). However, in `IMPLEMENTING` (`APPLY`), when an agent runner dies or is killed by a host/service restart, the partial edits and untracked scratch files remain in the worktree. Because `_stage_candidate_identity` computes a fingerprint over git diff, git status, and untracked files, the dirty worktree produces a mismatched fingerprint (`candidate_matches = False`).

In `mechanical_remediation` mode, Watchdog detects the dead process (`process_absence_proven: True`), but lacking an automated worktree rebaseline, it escalates to `watchdog_escalation`. When the operator answers, the coordinator rejects the dirty candidate and halts in `status=PAUSED`. To compound the issue, the operator action is recorded as `COMPLETED` while the gate retains the same `gate_id`, causing an idempotency deadlock where all subsequent submissions return the cached paused result.

## Goals / Non-Goals

**Goals:**
* Provide an autonomous mechanical worktree rebaseline in `WorktreeManager` and `NativeOrchestrationCoordinator` when process absence is proven on an interrupted mutating stage (`APPLY`).
* Revert tracked files to the candidate entry commit (`git checkout -f <candidate_sha>`) and purge untracked debris while strictly preserving the approved OpenSpec proposal artifacts in `openspec/changes/<change-name>/`.
* Guarantee that `candidate_matches = True` is achieved without human intervention, incrementing `recovery_count` and re-launching the implementer runner.
* Eradicate the spurious `watchdog_escalation` gate on the first occurrence of an orphaned process under `mechanical_remediation` mode.
* Prevent idempotency deadlocks: when any gate response halts in `PAUSED` without stage progression, renew the active `gate_id` so subsequent operator submissions are not blocked by stale cached completions.

**Non-Goals:**
* No unbounded retries: bounded strictly to at most one automatic recovery attempt (`recovery_count < 1`).
* No manual git commands or operator involvement for dead process workspace hygiene.
* No new database tables or UI views.

## Decisions

### Decision 1: Worktree Rebaseline Preserving OpenSpec Change Artifacts
* *Choice*: Implement `WorktreeManager.rebaseline_apply_worktree(worktree_path, candidate_sha, change_name)`.
* *Mechanism*:
  1. Executes `git checkout -f <candidate_sha> -- .` to discard uncommitted modifications to tracked files.
  2. Inspects untracked files via `git ls-files --others --exclude-standard`.
  3. Purges untracked files, explicitly skipping any path inside `openspec/changes/<change-name>/`.
* *Rationale*: A raw `git clean -fd` would wipe out the untracked OpenSpec proposal artifacts (`proposal.md`, `design.md`, `tasks.md`, `specs/...`) generated during the preceding `PROPOSE` stage, corrupting the candidate. Preserving the change directory restores the worktree to the exact verified entry state of the `APPLY` stage.
* *Alternative considered*: Stashing or committing WIP edits. Rejected: edits from a dead agent are unreviewed, partial, and potentially syntactically invalid. The canonical definition of retrying a stage is starting from the stage's approved candidate baseline.

### Decision 2: Pre-Invocation Mechanical Recovery in `_begin_stage_invocation`
* *Choice*: Follow the proven pattern of `_recover_dirty_documentation_invocation` by adding `_recover_dirty_apply_invocation` before candidate identity recalculation in `_begin_stage_invocation`.
* *Mechanism*:
  - If stage is `APPLY`, mode is `mechanical_remediation` (or operator-authorized retry), and prior process is proven absent (`_stage_recovery_is_safe` process check):
  - Execute `rebaseline_apply_worktree`.
  - Recalculate `candidate = await self._stage_candidate_identity(run, worktree_path, stage)`.
  - Verify that `candidate` now matches the entry candidate recorded in `STAGE_INVOCATION_STARTED`.
  - Mark previous invocation `STAGE_INVOCATION_ABANDONED` with reason `"Orphaned Apply process recovered via autonomous mechanical worktree rebaseline"`.
  - Reacquire stage claim, increment `recovery_count = 1`, and return the valid `StageInvocation`.
* *Alternative considered*: Handling it only in the Watchdog service. Rejected: the coordinator is the single canonical authority for stage invocation claims and candidate identity verification.

### Decision 3: Active Gate Renewal on Stalled Outcomes
* *Choice*: In `prepare_gate_response` and `complete_gate_response`, if the resulting coordinator outcome is `status == "PAUSED"` (no stage progression):
  - Invalidate the token binding and generate a fresh `gate_id = str(uuid4())` in `stop_details["human_payload"]`.
  - Mark the operator action as `COMPLETED` with `stalled=True` or `REQUIRES_RETRY`.
* *Rationale*: If an operator submits a gate response and the system cannot proceed, caching that failure permanently under the same idempotency key prevents any subsequent correction from taking effect. Generating a new `gate_id` ensures the operator can re-submit with fresh intent.

## Risks / Trade-offs

* **[Risk]**: Code written by the interrupted agent before crash is lost.  
  → **Mitigation**: An interrupted agent's uncommitted work has no transactional guarantee or review verdict. The authoritative candidate is the approved proposal. Restarting the implementer on a clean worktree produces a deterministic, traceable execution.
* **[Risk]**: Rebaseline loop if implementer crashes repeatedly.  
  → **Mitigation**: Bounded by `recovery_count < 1`. If the agent crashes a second time, mechanical remediation is not repeated and control is escalated with evidence.
