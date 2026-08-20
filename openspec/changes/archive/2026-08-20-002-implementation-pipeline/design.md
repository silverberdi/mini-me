# Design: 002-implementation-pipeline

## Context
Foundation (Stage 0) established PostgreSQL durable storage, project registration, OpenSpec readiness verification, and GitHub control plane primitives. Stage 1 (`002-implementation-pipeline`) implements the core execution engine that transitions a `READY` OpenSpec change into an active implementation inside an isolated Git worktree, executes the configured primary implementer agent, runs deterministic checks, and captures verifiable evidence.

See [proposal.md](file:///Users/silveriobernal/Documents/Code/Development/mini-me/openspec/changes/002-implementation-pipeline/proposal.md) for motivation and non-goals.

## Goals / Non-Goals

**Goals:**
- Provide a robust, asynchronous execution pipeline in core/daemon for registered projects.
- Manage isolated Git worktrees (`.minime/worktrees/<job_id>`) with candidate branch creation and clean deletion.
- Persist job state machine transitions, event logs, and timing metrics in PostgreSQL with Alembic migrations.
- Support child process execution of configured primary implementer agents (Codex or Antigravity) with timeouts and output redaction.
- Execute project-configured deterministic checks (`ruff`, `pytest`) inside the candidate worktree and store structured outcomes.
- Provide API and CLI interfaces for triggering, monitoring, and inspecting execution jobs.

**Non-Goals:**
- Reviewer orchestration and complementary review handoffs (Stage 2).
- DeepSeek Direct independent audit (Stage 3).
- OpenRouter capacity drain fallback (Stage 4).
- Containerized preview and human UI validation (Stage 5).
- GitHub PR submission, human merge, and production deployment (Stage 6).
- Multi-project fairness/concurrency scheduling or remote PWA (Post-MVP).

## Decisions

### Decision 1: Daemon-Owned Asynchronous Worktree and Process Execution
- **Approach**: The daemon's `ExecutionPipelineService` manages Git worktrees and spawns child processes using `asyncio.create_subprocess_exec`. The main worktree is never modified during implementation; all candidate code changes occur in `.minime/worktrees/<job_id>`.
- **Rationale**: Keeps execution completely isolated, preventing working tree corruption and allowing safe failure recovery. Clients (FastAPI/CLI) trigger and observe jobs asynchronously without touching Git directly.
- **Alternatives Considered**:
  - *In-place main worktree modification*: Rejected because failed executions would leave dirty uncommitted working trees.
  - *Celery/Redis worker daemon*: Rejected as unnecessary external infrastructure complexity for a single-installation Linux daemon.

### Decision 2: PostgreSQL Schema Evolution for Pipeline Jobs and Evidence
- **Approach**: Add Alembic migration `002_jobs_pipeline.py` creating:
  - `jobs`: `job_id` (UUID PK), `project_id`, `change_name`, `status` (`QUEUED`, `RUNNING`, `CHECKS_RUNNING`, `CHECKS_PASSED`, `CHECKS_FAILED`, `FAILED`, `CANCELLED`), `implementer_role`, `candidate_sha`, `base_sha`, `error_message`, `created_at`, `updated_at`.
  - `job_logs`: `id`, `job_id`, `stream` (`stdout`/`stderr`/`system`), `message` (redacted), `timestamp`.
  - `check_results`: `id`, `job_id`, `check_name`, `command`, `exit_code`, `duration_ms`, `output_snippet`, `created_at`.
- **Rationale**: Fulfills the PostgreSQL-only canonical rule, enables transactionally atomic state + event persistence, and provides rich auditability.
- **Alternatives Considered**:
  - *File-based logs only*: Rejected because structured queries across jobs and status endpoints require database-backed metadata.

### Decision 3: Implementer Process Adapter with Strict Timeout and Output Redaction
- **Approach**: Define `ImplementerRunnerInterface` with implementations for CLI subprocess execution (`CodexRunner`, `AntigravityRunner`, and `MockImplementerRunner` for deterministic testing). The runner prepares prompt context (spec paths, `tasks.md`), executes the CLI inside the candidate worktree root, applies a configurable execution timeout, and routes all output through `RedactingLogFormatter`.
- **Rationale**: Respects the agent contract boundary where Codex and Antigravity operate via their authorized toolsets while protecting secrets from log leakage.
- **Alternatives Considered**:
  - *Direct LLM API streaming inside core*: Rejected because Codex and Antigravity primary agents run via their agentic CLI tooling.

### Decision 4: Sequential Deterministic Checks Engine
- **Approach**: Project check commands configured in `minime.yaml` (e.g. `ruff check .`, `pytest`) run sequentially inside the candidate worktree via `asyncio.create_subprocess_shell`. If any check fails (exit code != 0), execution halts immediately, output is captured, and the job transitions to `CHECKS_FAILED`.
- **Rationale**: Prevents CPU/port thrashing from parallel test suites and ensures early exit upon regression.
- **Alternatives Considered**:
  - *Parallel check execution*: Rejected due to potential race conditions on local test ports and temp files.

### Decision 5: Non-Destructive OpenSpec Task Inspection
- **Approach**: `OpenSpecAdapter` parses task items and checkboxes from `openspec/changes/<name>/tasks.md`. The pipeline checks that all tasks are `- [x]` after implementer completion. Runtime job metadata (durations, job IDs, retry attempts) is stored exclusively in PostgreSQL.
- **Rationale**: Preserves OpenSpec as the human/agent contract and source-of-truth for behavioral design, preventing ephemeral operational noise from polluting version control.

## Risks / Trade-offs

- **[Risk] Implementer child process hangs or leaks background sub-processes** → **Mitigation**: Launch processes with `start_new_session=True` (process group) and issue `os.killpg(pid, signal.SIGTERM)` followed by `SIGKILL` upon timeout or cancellation.
- **[Risk] Disk exhaustion from abandoned worktrees after failures** → **Mitigation**: Implement automated worktree pruning and cleanup routines on job completion/failure, plus a `minime worktrees cleanup` maintenance command.
- **[Risk] Secret leakage in implementer logs** → **Mitigation**: Log streams pass through regex redaction matching database URLs, tokens, and SSH keys before persistence.

## Migration Plan
- Apply Alembic migration `002_jobs_pipeline` to the operational PostgreSQL database.
- Migration is non-breaking to Foundation tables (`projects`, `project_bindings`, `changes`, `events`, `metric_facts`).
- Downward migration drops `check_results`, `job_logs`, and `jobs` cleanly.
