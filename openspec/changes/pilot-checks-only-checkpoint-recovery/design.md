## Context

See `proposal.md` for background on Issue #159 and the frozen pilot fixture on Ubuntu (`192.168.0.194`):
- Run: `8e7ebec8-9eff-478b-bae3-cf686ea91be2` (`current_stage=IMPLEMENTING`, `is_active=true`, `active_job_id=b917a9f0-0354-4805-863f-7ab4e7ada559`)
- Job: `b917a9f0-0354-4805-863f-7ab4e7ada559` (`status=CHECKS_FAILED`, `candidate_sha=2fcad0ef73eb4766ca1bb6249a081cb4070ecced`, `base_sha=6c051b87eb9a8f379e9305b62773bf486a7825f5`)
- Historical Diagnostic Evidence: `PermissionError: [Errno 13] Permission denied: '/dev/null'` during `pytest` capture under Bubblewrap.

PR #158 resolved the Bubblewrap `/dev` virtual device mounting and coordinator claim heartbeat renewal. However, invoking standard `minime orchestrate resume` at PR #158 head is unsafe: because the Run stage is `IMPLEMENTING`, the coordinator invokes `pipeline.execute_queued_job`, which skips APPLY only when an existing `CODE_REVIEW` manifest is already in-progress (`resume_frozen_candidate`). For `CHECKS_FAILED`, it falls through to provider model dispatch, re-running OpenSpec APPLY and risking candidate corruption.

## Goals / Non-Goals

**Goals:**
- Provide an explicit, narrow control-plane recovery entry point (`recover_checks_only`) that resumes an orchestration run directly into deterministic checks without implementer invocation or OpenSpec APPLY replay.
- Strictly validate the entire authoritative durable state: `run.run_id`, `job.id`, `project.project_id`, `run.change_name`, `run.base_sha == job.base_sha`, `job.candidate_sha`, `run.current_generation`, and worktree git `HEAD == job.candidate_sha`.
- Honestly characterize the pre-freeze candidate state: the candidate code is committed in the worktree, but no `OrchestrationCandidate` row or review manifest exists yet in PostgreSQL.
- Verify that prior check failure diagnostics for this exact job and candidate substantiate a proven runner environmental fault (`PermissionError: [Errno 13] Permission denied: '/dev/null'` or confinement preflight failure) before authorizing checks-only bypass.
- Execute real deterministic `ChecksRunner` under Bubblewrap in the preserved worktree, materializing candidate manifest evidence so downstream candidate freezing succeeds.
- Enforce single-batch check completeness: every configured check in `project.checks` must pass in that single authorized recovery batch before transitioning `job.status` to `CHECKS_PASSED`; stale results from earlier runs cannot be inherited.
- Maintain single heartbeat ownership across `recover_checks_only -> resume -> drive_coordinator`, passing `manage_heartbeat=False` to the coordinator.
- Stop at a durable review-pending checkpoint immediately after candidate freezing, guaranteeing **zero model inference** (neither implementer nor reviewer/auditor models).
- Enforce strict fail-closed behavior: stop at `NEEDS_HUMAN` if checks fail, and commit zero database writes if the claim fence is lost or superseded.
- Provide a full disposable PostgreSQL + worktree functional E2E test suite covering the exact pilot checkpoint and negative conditions.

**Non-Goals:**
- Modifying PostgreSQL database schema (no new Alembic migrations; uses existing tables).
- Modifying candidate code in the worktree (`sanitize-filename-token` implementation and test files are already authored and preserved).
- Broad or automatic skipping of APPLY when checks fail due to application logic, compilation, or test assertion errors.
- Automatic review or audit model dispatch during this recovery operation (review continuation requires separate human authorization).
- Automatic merging of the candidate (human merge policy remains mandatory).
- Enabling or starting `minime-scheduler.service`.

## Decisions

### Decision 1: Domain State & Authoritative Authority Tuple (P1)
- **Model Constraints**:
  - `Job` in `src/minime/domain/models.py` possesses no `candidate_generation` attribute. Generation authority is sourced strictly from `run.current_generation`.
  - Enum distinctions: `JobStatus.CHECKS_RUNNING` and `OrchestrationStage.RUNNING_CHECKS` are distinct enums. Valid transitions in `PostgresJobRepository.VALID_TRANSITIONS` are:
    `JobStatus.CHECKS_FAILED -> JobStatus.CHECKS_RUNNING -> JobStatus.CHECKS_PASSED / JobStatus.CHECKS_FAILED`.
  - The Run stage transitions from `OrchestrationStage.IMPLEMENTING` to `OrchestrationStage.RUNNING_CHECKS`.
- **Preflight Gating**:
  - `run.is_active` is True and `run.active_job_id == job.id`.
  - `run.base_sha == job.base_sha`.
  - `job.candidate_sha` is non-empty and `git -C <worktree> rev-parse HEAD == job.candidate_sha`.
  - Worktree working tree is clean (`git status --porcelain` is empty).
  - Pre-freeze characterization: verifies that the candidate code exists at `job.candidate_sha` in the worktree, while honestly recognizing that no `OrchestrationCandidate` row or review manifest exists yet.

### Decision 2: Canonical Checks-Only Pipeline Execution & Manifest Materialization (P2)
- **Problem**:
  In `drive_coordinator`, the `RUNNING_CHECKS` stage does not invoke `ChecksRunner` directly; it reads persisted `check_results` written by the pipeline. Furthermore, downstream `FREEZING_CANDIDATE` calls `_freeze_candidate_if_needed`, which requires a `CandidateManifest` matching the candidate SHA, base SHA, and generation (`MISSING_AUTHORITATIVE_MANIFEST` failure if absent).
- **Approach**:
  - Add `ExecutionPipelineService.run_checks_only(job_id, candidate_generation, claim_context)`:
    1. Validates worktree HEAD against `job.candidate_sha`.
    2. Materializes and persists a deterministic `CandidateManifest` using `CandidateManifestService.generate_manifest(...)` for the unmutated candidate, bound to `candidate_sha`, `base_sha`, and `candidate_generation`.
    3. Transitions `job.status = JobStatus.CHECKS_RUNNING`.
    4. Executes `ChecksRunner.run(...)` under Bubblewrap on the preserved worktree.
    5. Persists fresh `check_results` and `evidence_diagnostics` bound to `candidate_sha` and `candidate_generation`.
    6. If all checks pass: transitions `job.status = JobStatus.CHECKS_PASSED`.
    7. If any check fails: transitions `job.status = JobStatus.CHECKS_FAILED`.
  - In `drive_coordinator()`:
    When invoked under checks-only recovery, the coordinator transitions from `IMPLEMENTING` directly to `RUNNING_CHECKS`, calls `run_checks_only()`, consumes the verified check results, advances to `FREEZING_CANDIDATE`, materializes the `OrchestrationCandidate` row, and halts at review hold.

### Decision 3: Atomic Recovery Check Batch Completeness & Census (P3)
- **Problem**:
  `PostgresCheckResultRepository.list_by_job` returns all historical records. Filtering by candidate SHA and generation alone could allow a partial re-run to count passing results from a previous run or mix results from distinct attempts.
- **Approach**:
  - Assign a unique batch identifier or batch execution timestamp to the recovery execution.
  - Require a complete census: every check command defined in `project.checks` must have a passing result (return code 0) executed within that **exact recovery check execution**.
  - If a check run crashes or fails midway, `job.status` remains `CHECKS_FAILED`; no check from that run can be combined with subsequent runs.
  - All historical records in `check_results` and `evidence_diagnostics` are retained for audit and lineage.

### Decision 4: Single Heartbeat Ownership & Zero Inference Review Hold (P4)
- **Heartbeat Contract**:
  - `RecoveryConvergenceService.recover_checks_only` acquires the claim (`run:<run_id>`) and runs `OperationalHeartbeat`.
  - It invokes `orchestration_service.resume(..., manage_heartbeat=False, claim_context=claim_context)`.
  - The coordinator does not instantiate an inner heartbeat and does not release the claim.
  - `recover_checks_only` stops the heartbeat cleanly and releases the claim idempotently in its `finally` block (or suppresses release on failure).
- **Zero Inference Guarantee & Review Hold**:
  - This recovery operation guarantees **zero model inference** of any kind (neither implementer nor reviewer/auditor models).
  - Immediately following candidate freezing in `FREEZING_CANDIDATE`, execution stops with `stop_outcome=NEEDS_HUMAN` and `human_gate=REVIEW_PENDING` (or stop details indicating review authorization required).
  - Subsequent complementary review is a separately governed, capacity-aware operation requiring explicit human authorization.
- **Environmental Fault Gating**:
  - Prior failure evidence is verified specifically from the latest attempt diagnostics for this candidate, requiring exact runner fault proof (`PermissionError: [Errno 13] Permission denied: '/dev/null'` or confinement preflight error). Any application test assertion, compilation, or syntax error causes immediate fail-closed rejection.

## Risks / Trade-offs

- **[Risk] Pre-freeze manifest generation integrity**: Generating manifest without re-running implementer.  
  $\rightarrow$ **Mitigation**: `CandidateManifestService.generate_manifest` strictly verifies the uncommitted/committed tree against allowed paths and rejects tracked `.pyc`/bytecode artifacts.
- **[Risk] Accidental reviewer dispatch**: Coordinator advancing past candidate freezing into `COMPLEMENTARY_REVIEW`.  
  $\rightarrow$ **Mitigation**: `drive_coordinator` checks the checks-only directive after `FREEZING_CANDIDATE` and halts at review hold, returning without calling `review_service`.
- **[Risk] Contention or lease expiry during checks**: Slow check execution exceeding lease.  
  $\rightarrow$ **Mitigation**: `OperationalHeartbeat` active throughout `recover_checks_only`, renewing every 15 seconds.
