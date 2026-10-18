## Why

During the first autonomous pilot execution on Ubuntu (Run `8e7ebec8-9eff-478b-bae3-cf686ea91be2`, Job `b917a9f0-0354-4805-863f-7ab4e7ada559`), candidate code (`2fcad0ef73eb4766ca1bb6249a081cb4070ecced`) was successfully authored and committed to the assigned worktree. However, the subsequent deterministic check pass failed because Bubblewrap omitted `--dev /dev`, producing `PermissionError: [Errno 13] Permission denied: '/dev/null'` when `pytest` initialized standard I/O capture. While PR #158 repaired the Bubblewrap sandbox configuration and coordinator claim heartbeat fencing, resuming the run via existing `orchestrate resume` remains unsafe: because the durable Run stage is `IMPLEMENTING` and Job status is `CHECKS_FAILED`, normal continuation unconditionally enters `ExecutionPipelineService.execute_queued_job`, re-dispatching provider models, repeating OpenSpec APPLY, and risking candidate corruption and inferential quota waste.

A narrow, fail-closed recovery capability is required to safely validate the preserved candidate, reconcile the checkpoint without repeating implementation, execute deterministic checks under the repaired sandbox, materialize candidate manifest evidence, and halt at a safe review-pending checkpoint without any model inference.

## What Changes

- **Narrow Checks-Only Checkpoint Recovery**: Introduce an explicit, fenced control-plane and CLI recovery path (`minime orchestrate recover-checks <run_id>` / `RecoveryConvergenceService.recover_checks_only()`) that resumes execution exclusively at the checks stage without dispatching implementer agents, invoking model inference, or creating new implementer attempts.
- **Exact Authority Tuple & Environmental Fault Gating**: Enforce strict fail-closed validation of the authoritative durable state: `run.run_id`, `job.id`, `project.project_id`, `run.change_name`, `run.base_sha == job.base_sha`, `job.candidate_sha`, `run.current_generation`, and worktree git `HEAD == job.candidate_sha` (noting that `Job` has no generation property; generation is sourced from `run.current_generation`). Pre-freeze check failures possess no frozen candidate row or review manifest; the preflight characterizes this state honestly without fabricating nonexistent rows. Verify that prior check failure diagnostics for this exact job and candidate substantiate a proven runner environmental fault (`/dev/null` permission error or confinement preflight failure) and reject regular code/test logic failures.
- **Canonical Checks-Only Execution & Manifest Materialization**: Reconcile Job status using valid domain transitions (`JobStatus.CHECKS_FAILED -> JobStatus.CHECKS_RUNNING -> JobStatus.CHECKS_PASSED / JobStatus.CHECKS_FAILED`) and Run stage `OrchestrationStage.RUNNING_CHECKS`. Re-use existing `ChecksRunner` under Bubblewrap and materialize candidate manifest evidence for the exact SHA/base/generation so downstream `_freeze_candidate_if_needed` succeeds without calling `execute_queued_job`.
- **Durable Check Batch Completeness & Census**: Define a recovery check batch identity ensuring that all configured checks in `project.checks` must execute and exit with code 0 in the **single authorized recovery batch** before transitioning to `CHECKS_PASSED`. Stale passed/failed results from earlier runs cannot satisfy current execution requirements. All historical rows in `check_results` and `evidence_diagnostics` are preserved.
- **Single Heartbeat Ownership & Zero Inference Guarantee**: `recover_checks_only` maintains the single active `OperationalHeartbeat` and passes `manage_heartbeat=False` to the coordinator, preventing duplicate renewal threads or double-release races. The recovery workflow stops cleanly with candidate frozen and status `CHECKS_PASSED` / review pending, guaranteeing **zero model inference** (neither implementer nor reviewer/auditor models). Subsequent review is a separate, capacity-aware human-authorized continuation.
- **Disposable PostgreSQL & Worktree E2E Test Suite**: Provide comprehensive functional E2E tests covering exact pilot checkpoint topology, missing candidate/manifest handling, batch completeness, lease expiry, fence supersession, and zero-inference verification.

## Capabilities

### Modified Capabilities

- `scheduler-and-recovery-convergence`: Add requirements and scenarios for fenced, checks-only checkpoint recovery of candidates halted by environmental test runner faults, verifying the exact authority tuple, ensuring single-batch check completeness, managing single heartbeat ownership, and stopping before review without model inference.
- `orchestration-driver-and-states`: Add requirements and scenarios for transitioning from durable `IMPLEMENTING` with `CHECKS_FAILED` directly into deterministic checks verification, materializing candidate manifest evidence, and stopping at a review-pending gate without implementer loop re-entry or automated review model dispatch.

## Impact

- **Affected Services**:
  - `src/minime/services/recovery_convergence_service.py`: Add `recover_checks_only()` with authoritative claim acquisition, single heartbeat ownership, exact tuple preflight gating, and environmental fault verification.
  - `src/minime/services/execution_pipeline.py`: Add canonical `run_checks_only()` helper that validates worktree HEAD, materializes candidate manifest, runs `ChecksRunner` under Bubblewrap, and persists candidate-bound check results without implementer invocation.
  - `src/minime/services/orchestration_service.py`: Add support for checks-only execution in `resume()` and `drive_coordinator()` to consume the verified check batch, advance to `FREEZING_CANDIDATE`, and stop at review hold.
  - `src/minime/cli/main.py`: Add `minime orchestrate recover-checks` command with explicit operator parameters and JSON reporting.
- **APIs & Models**: No database schema changes (uses existing tables and Alembic migrations).
- **Security & Safety**: Enforces zero model inference (implementer, reviewer, auditor), zero candidate code mutation, immutable historical evidence preservation, and strict PostgreSQL CAS claim fencing.
- **Scheduler & Deployment**: Scheduler remains `inactive/disabled`; deployment and real pilot continuation require separate human gates.
