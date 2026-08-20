# Tasks

## 1. PostgreSQL Schema Evolution & Review Persistence Models
- [x] 1.1 Add SQLAlchemy models for `ReviewModel` and `ReviewFindingModel` with foreign keys, indexes, and corresponding domain models.
- [x] 1.2 Create Alembic migration `003_review_pipeline` and verify offline SQL migration generation for PostgreSQL.
- [x] 1.3 Implement PostgreSQL review repository and review finding repository with transactional unit-of-work methods.

## 2. Reviewer Execution Contract & Process Runner
- [x] 2.1 Define `ReviewerRunnerInterface` and structured prompt context payload builder containing explicit change ID, candidate SHA, base SHA, worktree path, spec context, and check evidence.
- [x] 2.2 Implement `CliReviewerRunner` using `asyncio.create_subprocess_exec` with `start_new_session=True`, timeout enforcement (SIGTERM/SIGKILL escalation), and secret redaction.
- [x] 2.3 Implement `MockReviewerRunner` for deterministic testing of verdicts, timeouts, and malformed outputs.

## 3. Complementary Policy & Candidate Integrity Guards
- [x] 3.1 Implement complementary reviewer policy validator (verifying Codex ↔ Antigravity separation, disallowing self-review, and preventing runtime role switching).
- [x] 3.2 Implement pre-review candidate integrity validation (verifying candidate worktree presence, HEAD SHA matching `job.candidate_sha`, base SHA matching project base, and check evidence).
- [x] 3.3 Implement post-review read-only authority boundary validation (checking clean `git status --porcelain` and unchanged HEAD SHA).

## 4. Structured Review Verdict Parser & Findings Extractor
- [x] 4.1 Implement `ReviewVerdictParser` to extract, validate, and serialize machine-readable verdicts (`READY_TO_MERGE`, `CHANGES_REQUIRED`).
- [x] 4.2 Parse structured findings with severities (`BLOCKER`, `MAJOR`, `MINOR`), location, violated requirement, and expected correction.
- [x] 4.3 Implement safe error handling that transitions review to `REVIEW_FAILED` on missing, unparseable, or ambiguous reviewer output.

## 5. Pipeline Orchestration & State Machine Integration
- [x] 5.1 Extend `ExecutionPipelineService` to launch review stage after deterministic checks pass (`CHECKS_PASSED` → `REVIEW_RUNNING`).
- [x] 5.2 Implement atomic state transitions to `READY_TO_MERGE`, `CHANGES_REQUIRED`, `REVIEW_FAILED`, and `REVIEW_TIMED_OUT`, emitting corresponding events and phase duration metrics.
- [x] 5.3 Implement clean worktree teardown in `finally` block on all review terminal states.

## 6. API, CLI Observability & Automated Test Verification
- [x] 6.1 Expose FastAPI endpoints for reviewing job status and detailed findings (`GET /jobs/{id}/review`).
- [x] 6.2 Implement CLI commands for review inspection (`minime jobs review <job_id>`).
- [x] 6.3 Add automated unit and acceptance tests covering complementary pairing, self-review rejection, explicit change propagation, candidate SHA mismatch, `READY_TO_MERGE`, `CHANGES_REQUIRED`, timeout handling, malformed output fallback, and non-mutation enforcement.
- [x] 6.4 Validate all OpenSpec specs and change artifacts with `openspec validate --all`.
