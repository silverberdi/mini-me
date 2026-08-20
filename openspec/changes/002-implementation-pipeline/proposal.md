# Proposal: 002-implementation-pipeline

## Why
With Foundation (Stage 0) complete, mini me has durable PostgreSQL persistence, project registration, OpenSpec readiness verification, and GitHub control-plane integration. However, mini me cannot yet execute an OpenSpec change.

Stage 1 (`002-implementation-pipeline`) introduces the core execution pipeline: taking a `READY` OpenSpec change, creating an isolated Git worktree, invoking the project's configured primary implementer (Codex or Antigravity), running configured deterministic checks, and recording execution evidence in PostgreSQL.

## What Changes
- **Isolated Worktree Lifecycle**: Automated creation, safety validation, cleanup, and candidate SHA capture for dedicated Git worktrees attached to registered projects.
- **Execution Job State Machine**: PostgreSQL-backed job tracking with atomic transitions (`QUEUED`, `RUNNING`, `CHECKS_RUNNING`, `CHECKS_PASSED`, `CHECKS_FAILED`, `FAILED`, `CANCELLED`), timing metrics, and event log capture.
- **Primary Implementer Runner**: Subprocess-based invocation of the configured primary agent (Codex or Antigravity) with environment isolation, timeout enforcement, secret redaction, and failure handling.
- **Deterministic Checks Engine**: Execution of project-configured verification commands (e.g. `ruff`, `pytest`) within the candidate worktree, recording pass/fail facts.
- **OpenSpec Task Tracking**: Task-aware execution that supplies active OpenSpec tasks to the implementer and inspects task completion status without polluting OpenSpec files with runtime mutable data.
- **CLI and API Pipeline Surfaces**: FastAPI endpoints and Typer CLI commands to start execution jobs, inspect progress, and view structured execution logs and check results.

### Non-Goals (Explicitly Excluded)
- Reviewer orchestration (Codex ↔ Antigravity review - Stage 2).
- DeepSeek Direct independent audit (Stage 3).
- OpenRouter drain fallback and multi-provider quota drain (Stage 4).
- Containerized preview and guided UI human validation (Stage 5).
- GitHub PR automation, human merge coordination, and production deployment (Stage 6).
- Multi-project concurrency/fairness queues and PWA/TUI (Post-MVP).

## Capabilities

### New Capabilities
- `worktree-lifecycle`: Isolated Git worktree creation, validation, base branch syncing, candidate SHA extraction, and cleanup safety.
- `execution-jobs`: Durable PostgreSQL job state machine, transition events, timing metrics, and lifecycle management.
- `primary-implementer-execution`: Subprocess execution adapter for the configured primary implementer with timeout, redaction, and error capture.
- `deterministic-checks-runner`: Runner for project-configured verification commands in candidate worktrees with exit code and evidence retention.
- `openspec-task-tracking`: Task progress parsing, prompt context formatting, and non-destructive task verification for OpenSpec changes.
- `pipeline-observability`: CLI and API surfaces for initiating jobs, polling status, and streaming/inspecting job logs and evidence.

### Modified Capabilities
*(None. Main specs will receive these capabilities upon archival).*

## Impact
- **Database Schema**: New Alembic migration adding `jobs`, `job_logs`, and `check_results` tables in PostgreSQL.
- **Dependencies**: No external runtime additions needed; uses Python `asyncio.subprocess`, `sqlalchemy`, and existing core libraries.
- **Security**: Worktree processes run strictly within the project worktree; credentials from `dev.env` / host secrets are redacted from captured stdout/stderr.
- **Repository Safety**: Execution occurs exclusively in temporary candidate worktrees (`.minime/worktrees/<job_id>`), leaving main worktree intact.
