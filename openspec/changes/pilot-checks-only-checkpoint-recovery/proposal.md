## Why

During the first autonomous pilot execution on Ubuntu (Run `8e7ebec8-9eff-478b-bae3-cf686ea91be2`, Job `b917a9f0-0354-4805-863f-7ab4e7ada559`), candidate code (`2fcad0ef73eb4766ca1bb6249a081cb4070ecced`) was successfully generated and committed to the assigned worktree. However, the subsequent deterministic check pass failed because Bubblewrap omitted `--dev /dev`, producing `PermissionError: [Errno 13] Permission denied: '/dev/null'` when `pytest` initialized standard I/O captures. While PR #158 repaired the Bubblewrap sandbox configuration and coordinator heartbeat fencing in the runtime, resuming the run via existing `orchestrate resume` remains unsafe: because the durable Run stage is `IMPLEMENTING` and Job status is `CHECKS_FAILED`, normal continuation unconditionally enters `ExecutionPipelineService.execute_queued_job`, re-dispatching provider models, repeating OpenSpec APPLY, and risking candidate corruption and inferential quota waste.

A narrow, fail-closed recovery capability is required to safely validate the preserved candidate, reconcile the checkpoint without repeating implementation, execute deterministic checks under the repaired sandbox, and progress to complementary review and PR preparation.

## What Changes

- **Narrow Checks-Only Checkpoint Recovery**: Introduce an explicit, fenced control-plane and CLI recovery path (`minime orchestrate recover-checks <run_id>` / `RecoveryConvergenceService.recover_checks_only()`) that resumes execution exclusively at the checks stage without dispatching implementer agents, invoking model inference, or creating new implementer attempts.
- **Exact Authority & Environmental Fault Gating**: Enforce strict fail-closed validation of the full durable tuple (`run_id`, `job_id`, `project_id`, `change_name`, `base_sha`, `candidate_sha`, `current_generation`, and worktree `HEAD`) before execution; verify that prior check failure evidence in PostgreSQL is attributable to a proven sandbox/environmental fault (`/dev/null` or confinement preflight) rather than code logic defects.
- **Durable Checkpoint Reconciliation**: Maintain source-of-truth separation between Run stage `IMPLEMENTING` and Job status `CHECKS_FAILED`, atomically reconciling Job status to `RUNNING_CHECKS` and executing `ChecksRunner` under an active `OperationalHeartbeat` without altering historical attempt evidence.
- **Seamless Governed Stage Continuation**: Upon check passage, record fresh candidate-bound check results, transition Job to `CHECKS_PASSED`, advance Run to `FREEZING_CANDIDATE` / `COMPLEMENTARY_REVIEW`, and continue standard governed delivery through PR preparation without direct merging.
- **Disposable PostgreSQL & Worktree E2E Test Suite**: Provide comprehensive functional E2E tests covering exact pilot checkpoint topology, zero-inference guarantees, claim fence supersession, lease expiry, candidate/base/generation mismatches, worktree drift, and re-run idempotency.

## Capabilities

### Modified Capabilities

- `scheduler-and-recovery-convergence`: Add requirements and scenarios for fenced, checks-only checkpoint recovery of candidates halted by environmental test runner faults, prohibiting implementer replay, validating exact durable worktree identity, and managing claim heartbeat during check execution.
- `orchestration-driver-and-states`: Add requirements and scenarios for transitioning from durable `IMPLEMENTING` with `CHECKS_FAILED` directly into deterministic checks verification and downstream review stages upon authorized checks-only recovery.

## Impact

- **Affected Services**:
  - `src/minime/services/recovery_convergence_service.py`: Add `recover_checks_only()` with authoritative claim acquisition, environmental fault verification, and fenced delegation.
  - `src/minime/services/orchestration_service.py`: Add support for checks-only execution in `resume()` and `drive_coordinator()` to bypass implementer attempt dispatch when recovering an existing candidate.
  - `src/minime/services/execution_pipeline.py`: Expose a deterministic check re-execution path that validates worktree HEAD against `job.candidate_sha` and commits zero new implementer attempts.
  - `src/minime/cli/main.py`: Add `minime orchestrate recover-checks` command with explicit operator parameters and JSON reporting.
- **APIs & Models**: No database schema changes (uses existing `orchestration_runs`, `jobs`, `recovery_claims`, `check_results`, and `evidence_diagnostics` tables and Alembic migrations).
- **Security & Safety**: Enforces zero inference quota consumption, zero candidate code mutation, immutable historical evidence preservation, and strict PostgreSQL CAS claim fencing.
- **Scheduler & Deployment**: Scheduler remains `inactive/disabled`; deployment and pilot resumption remain strictly governed by separate human gates.
