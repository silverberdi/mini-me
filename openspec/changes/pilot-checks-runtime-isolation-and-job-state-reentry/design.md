## Context

See `proposal.md` for background and motivation regarding the pilot N01 incident on Ubuntu 192.168.0.194.

Currently:
1. **Runner Path and Sandbox Mounts (C04)**: `ChecksRunner` constructs `pycache_dir = Path(tempfile.gettempdir()) / "minime_pycache" / job_id` and executes `pycache_dir.mkdir(parents=True, exist_ok=True)`. In Linux environments where multiple users run commands (such as verification operator `silverman` and daemon service user `minime`), the parent directory `/tmp/minime_pycache` created by one user (mode `0775`) causes an immediate `PermissionError: [Errno 13] Permission denied` when another user attempts to create a job-specific subdirectory. Merely using `0700` with predictable names in `/tmp` is vulnerable to pre-creation and symlink attacks.
2. **Exception Rollback Boundaries and Job Trapping (C02)**: In `ExecutionPipelineService.run_checks_only()`, the job status transitions from `CHECKS_FAILED` to `CHECKS_RUNNING` prior to calling `checks_runner.run()`. When an unhandled exception occurs (such as the `PermissionError` above), an outer `except Exception: self.uow.rollback(); raise` in `run_checks_only()` can erase internal job updates. The exception bubbles up to `OrchestrationService.drive_coordinator()`, which stops the `Run` via `_stop_coordinator_run()` with `stop_outcome=NEEDS_HUMAN` and `human_gate=NEEDS_HUMAN`, leaving the `Job` in an orphaned `CHECKS_RUNNING` status without an error message.
3. **Latest Environmental Fault Proof (C03)**: In `RecoveryConvergenceService._validate_checks_only_eligibility()`, the preflight checks require that `run.is_active == True`, `run.current_stage == IMPLEMENTING`, and `job.status == CHECKS_FAILED`. The observed production tuple is `RUNNING_CHECKS` / `NEEDS_HUMAN` (`is_active=False`) and `job.status == CHECKS_RUNNING`. The preflight check must recognize the latest pre-check environmental failure (`CHECKS_ONLY_PIPELINE_EXCEPTION` with `PermissionError` before any `CheckResult` was saved), rather than relying on stale `/dev/null` failures from older attempts, while fail-closing against application code errors.
4. **Missing Checks Execution Branch at RUNNING_CHECKS (C01)**: In `OrchestrationService.drive_coordinator()`, `pipeline.run_checks_only()` is only invoked when `stage == OrchestrationStage.IMPLEMENTING` and `checks_only=True`. The `RUNNING_CHECKS` stage branch (~lines 2026–2080) assumes that checks have ALREADY been executed and stored in the database. When a run resumes from `RUNNING_CHECKS` with `checks_only=True`, the coordinator attempts to validate the current batch, fails because no batch was written, and immediately fail-closes with `INCOMPLETE_AUTHORITATIVE_CHECKS` without ever running the runner.
5. **One-Shot Governance and State Freezing (C05)**: The recovery edge must hold strictly at `NEEDS_HUMAN` / `REVIEW_AUTHORIZATION_PENDING` upon checks success, without advancing to model review, implementer replay, or automated merge.

## Goals / Non-Goals

**Goals:**
- Provide a secure, UID-scoped or securely generated private bytecode cache path with no-follow and ownership verification, mounted read-write into Bubblewrap without broad writable host paths or `chmod 1777` on shared directories (C04).
- Ensure explicit transaction boundaries so that non-fence runner exceptions commit both `Job=CHECKS_FAILED` and `Run=NEEDS_HUMAN` under active claim fence, while claim fence loss triggers full rollback with zero database writes (C02).
- Authenticate the latest failure as a proven runner environmental fault (`Run.stop_details.code == CHECKS_ONLY_PIPELINE_EXCEPTION` and allowlisted exception type), rejecting application code errors, and require explicit one-shot human authorization (C03).
- Implement an explicit checks-only replay edge when resuming at `RUNNING_CHECKS` that invokes `pipeline.run_checks_only()` to execute a fresh checks batch, binds results to the frozen candidate SHA, validates batch completeness, and stops at `REVIEW_AUTHORIZATION_PENDING` (C01).
- Prevent duplicate/unapproved recovery attempts, maintain monotonic fencing, and guarantee zero model calls (C05).

**Non-Goals:**
- Do not redesign the overall recovery architecture or introduce multi-stage rewrites.
- Do not modify production database records or production worktrees directly.
- Do not re-enable `minime-scheduler.service` or alter PR #156.
- Do not bypass verification of clean git status, exact candidate SHA, and valid repository binding.

## Decisions

### Decision 1: Secure Cache Identity and Bubblewrap Mount (C04)
**Rationale:** Rather than using predictable paths in `/tmp` like `/tmp/minime_pycache_<uid>`, `ChecksRunner` will resolve a private directory:
1. Primary: `~/.cache/minime/pycache/<job_id>`. For user `minime`, this resolves to `/var/lib/minime/.cache/minime/pycache/<job_id>`.
2. Fallback: If `HOME` or `XDG_CACHE_HOME` is not usable or unwritable, generate a secure temporary directory using `tempfile.mkdtemp(prefix=f"minime_cache_{os.getuid()}_")`.
3. Validation: Verify that the path exists, is NOT a symlink (`os.path.islink(path) == False`), is owned by the current process UID (`os.stat(path).st_uid == os.getuid()`), and has permissions restricted to `0700`. If invalid or contaminated, reject fail-closed and create a secure fallback.
4. Confinement Mount: In `AgentProcessConfinement.wrap_command()`, accept `cache_bind_path: str | Path | None` (or infer from runtime state) and add `--dir <cache_path>` and `--bind <cache_path> <cache_path>` to Bubblewrap. Prohibit arbitrary, unrestricted caller-supplied bind paths.

### Decision 2: Durable Job+Run Consistency Under Exceptions (C02)
**Rationale:** Transaction boundaries must distinguish between fence loss and runner exceptions:
1. In `ExecutionPipelineService.run_checks_only()`:
   - Catch runner exceptions in a dedicated `except Exception as runner_exc:` block BEFORE the outer fence check.
   - Re-check claim fence: `validate_claim_context_authoritative(self.uow, claim_context, for_update=True)`.
   - If claim is valid: transition `job` to `JobStatus.CHECKS_FAILED` with `error_message=redact_secrets(str(runner_exc))`, persist an `EvidenceDiagnostic` with `candidate_sha=job.candidate_sha` and `candidate_generation=candidate_generation`, flush to database, and re-raise.
   - If claim fence was lost or heartbeat failed: execute `self.uow.rollback()` and raise `StaleClaimError`.
2. In `OrchestrationService.drive_coordinator()`:
   - If `StaleClaimError`: rollback immediately (`self.uow.rollback()`) and exit with ZERO database writes.
   - If non-fence runner exception: verify that `job.status` is `CHECKS_FAILED`. Commit `_stop_coordinator_run(run, stop_outcome=NEEDS_HUMAN, human_gate=NEEDS_HUMAN, ...)` in the same transaction as the job failure.

### Decision 3: Proven Latest Pre-Check Environmental Fault (C03)
**Rationale:** In `RecoveryConvergenceService._validate_checks_only_eligibility()`:
1. Check candidate and worktree integrity: candidate SHA must match worktree HEAD, worktree must be porcelain-clean, base SHA must match, and managed repository binding must be valid.
2. Accept `run.current_stage == OrchestrationStage.RUNNING_CHECKS` with `run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN` and `run.human_gate == HumanGate.NEEDS_HUMAN`, with `job.status` in `[JobStatus.CHECKS_FAILED, JobStatus.CHECKS_RUNNING]`.
3. Inspect the LATEST attempt / stop reason:
   - If failure occurred before `CheckResult` records were published: verify `run.stop_details.get("code") == "CHECKS_ONLY_PIPELINE_EXCEPTION"` and `run.stop_details.get("exception_type") in ALLOWLISTED_ENVIRONMENTAL_EXCEPTIONS` (e.g. `"PermissionError"`, `"AgentConfinementError"`), with error message detailing runner path or permissions.
   - If checks ran: verify that all non-zero exit codes in the latest execution batch have proven environmental faults (e.g. sandbox preflight failure, `/dev/null` permission denied).
   - Reject if any application code error is present (e.g. `AssertionError`, `SyntaxError`, `TypeError`, pytest failure).
4. Require separate explicit human one-shot authorization before `recover_checks_only` executes.

### Decision 4: Fresh Checks Batch Execution at RUNNING_CHECKS (C01)
**Rationale:** In `OrchestrationService.drive_coordinator()`:
1. When `stage == OrchestrationStage.RUNNING_CHECKS` and `checks_only=True`:
   - Inspect whether a valid passing check batch exists for the current candidate SHA and generation.
   - If NO passing batch exists (as in the interrupted runner incident where checks never executed or failed): invoke `self.pipeline.run_checks_only(job.job_id, candidate_generation=run.current_generation, claim_context=claim_context)` directly from `RUNNING_CHECKS`.
   - This executes the runner, writes fresh `CheckResult` records with current timestamps, validates batch completeness, transitions `Job` to `CHECKS_PASSED`, freezes the candidate, and stops at `NEEDS_HUMAN` / `REVIEW_AUTHORIZATION_PENDING`.
   - Prevents `drive_coordinator` from treating missing checks as `INCOMPLETE_AUTHORITATIVE_CHECKS` on re-entry.
   - Ensures `pipeline.run_checks_only()` is executed exactly once per authorized recovery cycle.

### Decision 5: One-Shot Governance and Adversarial Protection (C05)
**Rationale:**
- Claim acquisition increments monotonic fence token, rendering stale workers obsolete.
- Re-entry stops immediately after freezing candidate at `REVIEW_AUTHORIZATION_PENDING`.
- No model inference is configured or called anywhere in the checks-only pipeline.
- Tests will assert rejection for dirty worktrees, mismatched candidate SHA, missing binding, stale claims, and application code errors.

## Risks / Trade-offs

- **[Risk]** `~/.cache` might not exist or might be mounted read-only in unusual container environments.
  - **Mitigation:** Fallback to securely generated `tempfile.mkdtemp` with strict 0700 permissions and UID ownership verification.
- **[Risk]** Two rapid `recover-checks` invocations by an operator could race.
  - **Mitigation:** Serialized and fenced by PostgreSQL row lock on the recovery claim (`validate_claim_context_authoritative(..., for_update=True)`).
- **[Risk]** A previous run might have failed from an application bug, but the operator attempts to bypass via `recover-checks`.
  - **Mitigation:** Strict allowlist in `_validate_checks_only_eligibility` fail-closes against application error patterns in `stop_details` and check outputs.

## Removal Ledger

- **Replaced**: Hardcoded `/tmp/minime_pycache` in `src/minime/services/checks_runner.py`.
- **Replaced by**: UID-scoped verified private path (`~/.cache/minime/pycache/<job_id>` or `mkdtemp` with 0700 permissions).
- **Removed**: Assumption in `drive_coordinator()` that `RUNNING_CHECKS` only validates pre-existing batches.
- **Replaced by**: Replay edge invoking `run_checks_only` when resuming an interrupted run at `RUNNING_CHECKS`.
