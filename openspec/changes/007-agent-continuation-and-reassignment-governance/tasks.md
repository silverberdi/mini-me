## 1. Domain Models, Enums & Schemas

- [ ] 1.1 Define domain enums (`ExecutionOutcome`, `ContinuationDecision`, `ProgressClassification`, `BlockerValidationVerdict`, `EvidenceDiagnosticStatus`, `JobStatus.NEEDS_HUMAN`) in `src/minime/domain/enums.py`.
- [ ] 1.2 Define domain interfaces and Pydantic schemas for execution attempts, structured blocker claims, deterministic blocker fingerprints, handoff payloads, candidate manifests, evidence diagnostics, and authorship records in `src/minime/domain/models.py`.
- [ ] 1.3 Create JSON schemas for structured blocker claims, candidate manifests, and evidence diagnostics in `schemas/`.

## 2. Database Models & Alembic Migration

- [ ] 2.1 Update SQLAlchemy models in `src/minime/db/models.py` for `JobAttempt`, `BlockerClaim`, `JobHandoff`, `CandidateManifest`, `EvidenceDiagnostic`, and update `ExecutionJob` columns.
- [ ] 2.2 Create Alembic migration `007_continuation_governance.py` in `alembic/versions/` for the new tables, altered columns, and updated enums.
- [ ] 2.3 Update repository methods in `src/minime/db/repository.py` for atomic attempt management, blocker claims, handoffs, candidate manifests, evidence diagnostics, and idempotent recovery queries.

## 3. Outcome Governance & Completion Verification

- [ ] 3.1 Implement `OutcomeGovernanceService` in `src/minime/services/outcome_governance.py` to parse executor results, enforce fail-closed completion verification against OpenSpec tasks and git state, and classify normalized outcomes.
- [ ] 3.2 Implement progress evaluation logic calculating task deltas, candidate file deltas, and deterministic check deltas (`GOOD_PROGRESS`, `PARTIAL_PROGRESS`, `NO_PROGRESS`, `REGRESSION`).
- [ ] 3.3 Add unit tests for outcome classification, fail-closed completion verification, and progress evaluation.

## 4. Blocker Validation, Fingerprinting & Continuation Engine

- [ ] 4.1 Implement `BlockerValidationService` in `src/minime/services/blocker_validation.py` to validate structured blocker claims against OpenSpec artifacts, registered integration points, and dependencies, computing deterministic blocker fingerprints.
- [ ] 4.2 Implement `ContinuationEngine` in `src/minime/services/continuation_engine.py` evaluating outcome rules A through L with configurable hard ceilings (`max_corrective_retries_per_executor = 2`, `max_reassignments_per_job = 2`, `max_same_outcome_streak = 2`, `max_same_false_blocker_streak = 2`).
- [ ] 4.3 Implement targeted corrective instruction prompt generation for `CORRECT_AND_RETRY` without full context dumps.
- [ ] 4.4 Add unit tests for narrow blocker validation, fingerprinting, continuation decision rules, and anti-ping-pong hard limits.

## 5. Agent Reassignment, Handoff & Authorship Tracking

- [ ] 5.1 Implement `HandoffManager` in `src/minime/services/handoff_manager.py` to generate restart-safe structured handoffs preserving existing worktrees, task progress, check summaries, and architectural guidance.
- [ ] 5.2 Implement authorship tracking in `src/minime/services/authorship_service.py` to record multi-agent contributions, compute mixed authorship flags, and attach review disclosure records.
- [ ] 5.3 Add unit tests for structured handoff generation, worktree preservation, and mixed authorship tracking.

## 6. Candidate Manifest & Evidence Diagnostics

- [ ] 6.1 Implement `CandidateManifestService` in `src/minime/services/candidate_manifest.py` to construct complete file manifests (tracked, staged, untracked, deleted) prior to review.
- [ ] 6.2 Update reviewer harness in `src/minime/services/reviewer_runner.py` and `src/minime/services/reviewer_view.py` to verify reviewer visibility of all manifest items, recording `REVIEW_ENVIRONMENT_INVALID` diagnostic on blindness without creating a parallel job state.
- [ ] 6.3 Update deterministic checks runner in `src/minime/services/checks_runner.py` to classify and record evidence diagnostics (`PASS`, `FAIL`, `SKIPPED_BY_POLICY`, `ENVIRONMENT_UNAVAILABLE`, `EVIDENCE_NOT_REPRODUCIBLE`).
- [ ] 6.4 Add unit tests for candidate manifests, reviewer visibility verification, and evidence diagnostics.

## 7. Execution Pipeline Integration & Restart Recovery

- [ ] 7.1 Refactor `ExecutionPipeline` in `src/minime/services/execution_pipeline.py` to drive multi-attempt continuation loops, integrate outcome governance, handle agent reassignment, and manage `NEEDS_HUMAN` escalation.
- [ ] 7.2 Update `RestartRecoveryService` in `src/minime/services/restart_recovery_service.py` to resume pending reassignments, handoffs, and continuation decisions idempotently.
- [ ] 7.3 Add integration tests simulating premature stops, false blockers, corrective retries, agent takeover (Codex -> Antigravity), reviewer visibility validation, and human escalation.

## 8. Observability, REST API & CLI Commands

- [ ] 8.1 Update FastAPI endpoints in `src/minime/api/routes/jobs.py` to expose attempt history, blocker fingerprints, continuation decisions, evidence diagnostics, handoffs, and escalation details with secret redaction.
- [ ] 8.2 Update CLI commands in `src/minime/cli/main.py` for `minime jobs attempts <job_id>`, `minime jobs handoff <job_id>`, and formatted job list/status displays.
- [ ] 8.3 Add end-to-end and regression tests for API endpoints and CLI commands.
