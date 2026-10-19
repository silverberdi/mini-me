## Context

See `proposal.md` for background and motivation regarding the pilot N01 incident on Ubuntu 192.168.0.194.

Currently:
1. `ChecksRunner` constructs `pycache_dir = Path(tempfile.gettempdir()) / "minime_pycache" / job_id` and executes `pycache_dir.mkdir(parents=True, exist_ok=True)`. In Linux environments where multiple users run commands (such as verification operator `silverman` and daemon service user `minime`), the parent directory `/tmp/minime_pycache` created by one user (mode `0775`) causes an immediate `PermissionError: [Errno 13] Permission denied` when another user attempts to create a job-specific subdirectory.
2. In `AgentProcessConfinement.wrap_command()`, Bubblewrap is invoked with `--ro-bind / /`, `--bind <worktree> <worktree>`, and `--ro-bind <runtime_root> <runtime_root>`. The host `/tmp` is not bound or is hidden, or if an isolated cache is used outside the worktree, it must be explicitly mounted read-write into the container so Python can write compiled bytecode without permission or isolation errors.
3. In `ExecutionPipelineService.run_checks_only()`, the job status transitions from `CHECKS_FAILED` to `CHECKS_RUNNING` prior to calling `checks_runner.run()`. When an unhandled exception occurs (such as the `PermissionError` above), the exception bubbles up to `OrchestrationService.drive_coordinator()`. The coordinator catches it, logs it, and stops the `Run` via `_stop_coordinator_run()` with `stop_outcome=NEEDS_HUMAN` and `human_gate=NEEDS_HUMAN`, but does not update the `Job` status. The `Job` remains trapped in `CHECKS_RUNNING` indefinitely with an empty `error_message`.
4. In `RecoveryConvergenceService._validate_checks_only_eligibility()`, the preflight checks require that `run.is_active == True`, `run.current_stage == IMPLEMENTING`, and `job.status == CHECKS_FAILED`. Because the incident left the system in `RUNNING_CHECKS` / `NEEDS_HUMAN` (`is_active=False`) and `job.status == CHECKS_RUNNING`, the eligibility check fails-closed and blocks recovery, even though the failure was an environmental fault and the preserved candidate is intact.

## Goals / Non-Goals

**Goals:**
- Provide a UID-private, process-isolated, and worktree/runtime-safe bytecode cache directory for `ChecksRunner` that works under Linux for service user `minime` and operator users without permission conflicts or cross-user contamination.
- Ensure Bubblewrap mounts the private cache path read-write into the container when confinement is active, without compromising filesystem isolation.
- Strictly prohibit `chown -R` or `chmod 1777` on shared host directories.
- Ensure that any unhandled pipeline exception during `run_checks_only` transactionally transitions the `Job` to `CHECKS_FAILED` with sanitized error details under claim fencing.
- Permit `RecoveryConvergenceService` to safely and authoritatively validate eligibility and admit a run interrupted in `RUNNING_CHECKS` / `NEEDS_HUMAN` with `CHECKS_FAILED` (or interrupted `CHECKS_RUNNING`) when proven environmental fault evidence is present, preserving candidate SHA `2fcad0ef73eb4766ca1bb6249a081cb4070ecced` intact.
- Enforce zero model invocation / zero inferential quota consumption and zero OpenSpec APPLY re-execution.

**Non-Goals:**
- Do not redesign the overall recovery architecture or introduce multi-stage rewrites.
- Do not modify production database records or production worktrees directly.
- Do not re-enable `minime-scheduler.service` or alter PR #156.
- Do not bypass verification of clean git status, exact candidate SHA, and valid repository binding.

## Decisions

### Decision 1: UID-Private / User-Scoped Bytecode Cache Path
**Rationale:** Rather than placing a shared folder in `/tmp/minime_pycache`, each execution should isolate its cache under a path scoped to the process's effective UID or user runtime directory. Specifically:
- Prefer `os.environ.get("XDG_CACHE_HOME")` or Path `~/.cache/minime/pycache/<job_id>`. For systemd service user `minime`, this maps to `/var/lib/minime/.cache/minime/pycache/<job_id>`, where `minime:minime` has full read-write permissions.
- Fallback for non-home environments: `Path(tempfile.gettempdir()) / f"minime_pycache_{os.getuid()}" / job_id`, ensuring no collision between distinct OS UIDs.
- Directory creation permissions are set to `0700` (`mode=0o700`), guaranteeing private ownership.
- *Alternatives considered:*
  - `chmod 1777 /tmp/minime_pycache`: Rejected by canonical security rules and issue review; shared sticky directories on host paths risk symlink attacks and pollution.
  - Putting `.pycache` inside the worktree: Rejected because the worktree must remain clean and pristine according to candidate integrity checks (`git status --porcelain` must be empty).

### Decision 2: Explicit Read-Write Bind Mount in Bubblewrap for Private Cache
**Rationale:** Bubblewrap mounts `/` as read-only (`--ro-bind / /`). Any directory that Python needs to write `.pyc` files into must be mounted read-write.
- `AgentProcessConfinement` will accept an optional `extra_bind_paths` or `pycache_path` argument, or `ChecksRunner` will pass the private cache path to `wrap_command()`.
- Bubblewrap will add `--dir <cache_path>` and `--bind <cache_path> <cache_path>` so the sandboxed Python process has write access to its private bytecode cache.
- *Alternatives considered:*
  - Setting `PYTHONDONTWRITEBYTECODE=1`: While this avoids writing `.pyc` files, large pytest runs against complex codebases and imports suffer performance penalties, and pytest/tools may still attempt to create temporary directories if not strictly isolated. Providing a clean, confined private cache path preserves performance and isolates the subprocess safely.

### Decision 3: Atomic Claim-Fenced Job Error Transition
**Rationale:** In `run_checks_only()`, if `checks_runner.run()` raises an unhandled exception before returning a `CheckRunResult`:
- The exception is caught within `run_checks_only()`.
- Validate that the recovery claim is still held (`validate_claim_context_authoritative(self.uow, claim_context, for_update=True)`).
- Transition the `Job` to `JobStatus.CHECKS_FAILED` with `error_message=redact_secrets(str(exc))`.
- Persist an `evidence_diagnostic` record documenting the runner exception and candidate SHA.
- Re-raise the exception (or return the failed job) so `OrchestrationService` can stop the `Run` into `NEEDS_HUMAN` coherently.
- *Alternatives considered:*
  - Letting the coordinator only update the Run: Rejected because it left the Job in `CHECKS_RUNNING`, creating an inconsistent database tuple and blocking recovery.

### Decision 4: Governed Re-Entry Eligibility in RecoveryConvergenceService
**Rationale:** In `_validate_checks_only_eligibility()`:
- Accept `run.current_stage` in `[OrchestrationStage.IMPLEMENTING, OrchestrationStage.RUNNING_CHECKS]`.
- For `RUNNING_CHECKS`, accept `run.is_active == False` provided `run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN` and `run.human_gate == HumanGate.NEEDS_HUMAN`.
- Accept `job.status` in `[JobStatus.CHECKS_FAILED, JobStatus.CHECKS_RUNNING]`. If `CHECKS_RUNNING`, verify that the stop reason or latest evidence records a proven runner environmental fault (such as `PermissionError`, `/dev/null`, or confinement failure), and transition the job to `CHECKS_FAILED` during claim acquisition or eligibility resolution.
- Verify candidate SHA, base SHA, worktree clean status, and managed binding as before.
- In `recover_checks_only()`, re-activate the run (`is_active=True`, clear `stop_outcome` and `human_gate`) only under active claim fence before calling `drive_coordinator()`.
- *Alternatives considered:*
  - Forcing the operator to run `orchestrate resolve --continue-preserved-candidate`: Rejected because there is no frozen candidate manifest for a job that failed before review, and manual SQL mutation is strictly prohibited.

## Risks / Trade-offs

- **[Risk]** `XDG_CACHE_HOME` or `~/.cache` might not be writable if `HOME` is unset or points to an unwritable location in minimal container environments.
  - **Mitigation:** Implement fallback to `Path(tempfile.gettempdir()) / f"minime_pycache_{os.getuid()}" / job_id`, ensuring the directory is always creatable and isolated by UID.
- **[Risk]** Bubblewrap execution might fail if the cache directory does not exist on host before `bwrap` is called.
  - **Mitigation:** `ChecksRunner` creates the host cache directory before invoking `AgentProcessConfinement.wrap_command()`, and `bwrap` receives both `--dir` and `--bind` arguments.
- **[Risk]** Concurrency race during recovery re-entry if another process attempts recovery at the same time.
  - **Mitigation:** Protected by the canonical PostgreSQL recovery claim lock and monotonic fencing token (`validate_claim_context_authoritative(..., for_update=True)`).

## Removal Ledger

- **Replaced**: Unscoped `/tmp/minime_pycache/<job_id>` in `src/minime/services/checks_runner.py`.
- **Replaced by**: UID-scoped / XDG-scoped private directory with 0700 permissions and Bubblewrap read-write bind mount.
- **Removed**: Inflexible check in `_validate_checks_only_eligibility` requiring `IMPLEMENTING` stage only.
- **Replaced by**: Governed check admitting `RUNNING_CHECKS` with environmental fault evidence and candidate integrity validation.
