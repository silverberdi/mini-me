# Tasks

## 1. PostgreSQL Schema Evolution & Models for Jobs
- [ ] 1.1 Add SQLAlchemy models for `JobModel`, `JobLogModel`, `CheckResultModel` and corresponding domain entities.
- [ ] 1.2 Create Alembic migration `002_jobs_pipeline` and verify offline SQL migration generation.
- [ ] 1.3 Implement PostgreSQL job repository and atomic unit-of-work state transition methods.

## 2. Git Worktree Lifecycle Engine
- [ ] 2.1 Implement `WorktreeManager` service to create, validate, and isolate candidate worktrees under `.minime/worktrees/<job_id>`.
- [ ] 2.2 Implement candidate branch creation from base branch, head SHA extraction, and clean worktree removal.
- [ ] 2.3 Add unit and integration tests for worktree creation, collision rejection, and cleanup safety.

## 3. Primary Implementer Process Runner
- [ ] 3.1 Define `ImplementerRunnerInterface` and implement child process execution with `asyncio.create_subprocess_exec`.
- [ ] 3.2 Add process group isolation, timeout enforcement with SIGTERM/SIGKILL termination, and exit code capture.
- [ ] 3.3 Implement stream capture with regex secret redaction streaming into `job_logs` and event emitters.
- [ ] 3.4 Implement mock implementer runner for fast, deterministic testing.

## 4. Deterministic Checks Runner
- [ ] 4.1 Implement `ChecksRunner` service to sequentially execute configured project verification commands inside the candidate worktree.
- [ ] 4.2 Capture stdout, stderr, exit codes, and execution duration per check, storing records in `check_results`.
- [ ] 4.3 Handle check failure early-exit and emit corresponding `CHECKS_PASSED` / `CHECKS_FAILED` events.

## 5. OpenSpec Task Awareness & Pipeline Orchestration
- [ ] 5.1 Implement `OpenSpecTaskTracker` to parse `tasks.md` items and checkboxes without mutating OpenSpec files with runtime data.
- [ ] 5.2 Build `ExecutionPipelineService` coordinating worktree setup, implementer execution, task verification, and checks runner.
- [ ] 5.3 Implement atomic job state machine transitions (`QUEUED` → `RUNNING` → `CHECKS_RUNNING` → `CHECKS_PASSED` / `CHECKS_FAILED` / `FAILED` / `CANCELLED`) with duration metrics.

## 6. Observability, API, CLI & Acceptance Verification
- [ ] 6.1 Expose FastAPI endpoints for listing and inspecting jobs (`/projects/{id}/jobs`, `/jobs/{id}`, `/jobs/{id}/logs`).
- [ ] 6.2 Implement CLI commands (`minime run`, `minime jobs list`, `minime jobs show`).
- [ ] 6.3 Add automated end-to-end acceptance tests covering successful runs, check failures, timeout termination, and clean worktree recovery.
- [ ] 6.4 Run `openspec validate --all` and record evidence.
