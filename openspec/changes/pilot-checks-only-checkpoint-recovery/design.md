## Context

See `proposal.md` for background on Issue #159 and the frozen pilot fixture on Ubuntu (`192.168.0.194`):
- Run: `8e7ebec8-9eff-478b-bae3-cf686ea91be2` (`current_stage=IMPLEMENTING`, `is_active=true`, `active_job_id=b917a9f0-0354-4805-863f-7ab4e7ada559`)
- Job: `b917a9f0-0354-4805-863f-7ab4e7ada559` (`status=CHECKS_FAILED`, `candidate_sha=2fcad0ef73eb4766ca1bb6249a081cb4070ecced`)
- Historical Diagnostic Evidence: `PermissionError: [Errno 13] Permission denied: '/dev/null'` during `pytest` capture under Bubblewrap.

PR #158 resolved the Bubblewrap `/dev` virtual device mounting and coordinator claim heartbeat renewal. However, invoking standard `minime orchestrate resume` at PR #158 head is unsafe: because the Run stage is `IMPLEMENTING`, the coordinator invokes `pipeline.execute_queued_job`, which skips APPLY only when an existing `CODE_REVIEW` manifest is already in-progress (`resume_frozen_candidate`). For `CHECKS_FAILED`, it falls through to provider model dispatch, re-running OpenSpec APPLY and risking candidate corruption.

## Goals / Non-Goals

**Goals:**
- Provide an explicit, narrow control-plane recovery entry point (`recover_checks_only`) that resumes an orchestration run directly into deterministic checks without implementer invocation or OpenSpec APPLY replay.
- Strictly validate the entire durable identity tuple (`run_id`, `job_id`, `project_id`, `change_name`, `base_sha`, `candidate_sha`, `current_generation`, and worktree git `HEAD`).
- Verify that prior check failure diagnostics substantiate a proven sandbox/environmental runner fault (`/dev/null` permission error or confinement preflight failure) before authorizing checks-only bypass.
- Execute real deterministic `ChecksRunner` under Bubblewrap in the preserved worktree, persisting fresh check results and diagnostics.
- On check passage, seamlessly advance the run to candidate freezing (`FREEZING_CANDIDATE`), manifest generation, and complementary code review (`COMPLEMENTARY_REVIEW`).
- Enforce strict fail-closed behavior: stop at `NEEDS_HUMAN` if checks fail, and commit zero database writes if the claim fence is lost or superseded.
- Provide a full disposable PostgreSQL + worktree functional E2E test suite covering the exact pilot checkpoint and negative conditions.

**Non-Goals:**
- Modifying PostgreSQL database schema (no new Alembic migrations; uses existing tables).
- Modifying candidate code in the worktree (`sanitize-filename-token` implementation and test files are already authored and preserved).
- Broad or automatic skipping of APPLY when checks fail due to application logic, compilation, or test assertion errors.
- Automatic merging of the candidate (human merge policy remains mandatory).
- Enabling or starting `minime-scheduler.service`.

## Decisions

### Decision 1: Explicit Control-Plane & CLI Entry Point (`recover_checks_only`)
- **Approach**:
  - Add `RecoveryConvergenceService.recover_checks_only(run_id, project_root, force=False)` which:
    1. Acquires a durable recovery claim (`run:<run_id>`) with monotonic fencing and active lease heartbeat (`OperationalHeartbeat`).
    2. Executes `_validate_checks_only_eligibility(run, job, worktree_path)`.
    3. Reconciles Job status in memory and passes `checks_only=True` to `OrchestrationService.resume()`.
  - Add CLI command `minime orchestrate recover-checks <run_id> --path <project_root>`.
- **Rationale**: Isolates the checks-only path from routine `orchestrate resume` or scheduler tick workflows, preventing accidental or silent bypass of APPLY in general development.
- **Alternatives Considered**:
  - *Adding `--checks-only` flag to `orchestrate resume`*: Viable, but a distinct command `recover-checks` makes the operation's narrow recovery semantics and safety contract unmistakable in operator workflows and audit logs. Adding the flag to resume is supported as an alias.

### Decision 2: Fail-Closed Environmental Fault & Authority Gating
- **Approach**:
  Before checks-only execution begins, the service verifies:
  1. `run.is_active` is True, `run.active_job_id` matches `job.id`, and `run.current_generation == job.candidate_generation`.
  2. `job.status == JobStatus.CHECKS_FAILED` and `job.candidate_sha` is present and non-empty.
  3. Worktree exists on disk, and `git -C <worktree> rev-parse HEAD` strictly equals `job.candidate_sha`.
  4. Project durable repository binding matches the managed root.
  5. The job's preexisting `evidence_diagnostics` or `check_results` in PostgreSQL contain verifiable proof of a sandbox/runner environmental fault:
     - Output snippet or diagnostic reason matches `Errno 13`, `Permission denied: '/dev/null'`, `Process confinement failed`, or `Confinement capability unavailable`.
     - Rejects any run where checks failed due to assertion errors, syntax errors, or test failures.
- **Rationale**: Prevents developers or automated loops from using checks-only recovery to circumvent genuine test failures that require code modification.

### Decision 3: Coordinator Direct Transition to `RUNNING_CHECKS`
- **Approach**:
  - Update `OrchestrationService.resume()` and `drive_coordinator()` to accept `checks_only: bool = False`.
  - In `drive_coordinator()`, when `checks_only=True`:
    1. If `stage == OrchestrationStage.IMPLEMENTING` and `job.status == JobStatus.CHECKS_FAILED`:
       - Do NOT execute `pipeline.execute_queued_job`.
       - Atomically advance the run to `OrchestrationStage.RUNNING_CHECKS`.
    2. In `OrchestrationStage.RUNNING_CHECKS`:
       - Invoke `ChecksRunner.run(...)` directly on the preserved worktree.
       - If checks pass: transition `job.status = JobStatus.CHECKS_PASSED`, commit, and advance to `FREEZING_CANDIDATE`.
       - If checks fail: transition `job.status = JobStatus.CHECKS_FAILED`, commit fresh diagnostics, and stop at `NEEDS_HUMAN` (`stop_details={"code": "CHECKS_FAILED"}`).
- **Rationale**: Reuses the coordinator's existing deterministic checks execution, candidate freezing, manifest generation, review gating, and PR preparation machinery without duplicating downstream workflow logic.

### Decision 4: Immutable Historical Evidence & Atomic Point-of-Persistence Fencing
- **Approach**:
  - Preexisting `check_results` and `evidence_diagnostics` from prior attempts are never deleted or updated; new check execution appends fresh records linked to `job_id`, `candidate_sha`, and `candidate_generation`.
  - Claim heartbeat renews continuously during checks execution.
  - Final decision persistence and claim release use atomic compare-and-swap fencing verified in PR #158.

## Risks / Trade-offs

- **[Risk] Environmental fault marker spoofing**: An operator could theoretically attempt to run checks-only recovery on a legitimate test failure.  
  $\rightarrow$ **Mitigation**: The diagnostic search strictly inspects existing database rows persisted during the prior attempt, requiring unambiguous sandbox markers (`Errno 13`, `/dev/null`, confinement preflight).
- **[Risk] Stale candidate git status**: The worktree might have untracked or unstaged edits left by previous processes.  
  $\rightarrow$ **Mitigation**: Preflight checks assert `git status --porcelain` is clean in the worktree and `git rev-parse HEAD == job.candidate_sha`.
- **[Risk] Contention during checks re-execution**: A slow check run could exceed lease duration.  
  $\rightarrow$ **Mitigation**: `OperationalHeartbeat` is active during `recover_checks_only` and coordinator checks execution, renewing the lease every 15 seconds.
