# Proposal: 007 Agent Continuation and Reassignment Governance

## Why

mini me must not rely on an AI executor to truthfully or accurately determine whether its implementation is complete, whether it is genuinely blocked, whether another attempt is useful, or whether another agent should take over. Real failure modes observed during 006 (such as premature stops, false blockers from imagined file paths, diminishing returns on repeated corrective prompts, reviewer blindness to untracked candidate files, and test failures caused by environment unavailability rather than code defects) require an independent, deterministic orchestration governance layer.

Supervising imperfect AI behavior with deterministic evidence, validated blocker contracts, structured handoffs, candidate manifests, and bounded continuation/reassignment policies transforms mini me from a naive prompt dispatcher into a resilient, autonomous SDLC orchestrator.

## What Changes

- **Normalized Execution Outcome Classification**: Introduce a structured outcome model (`COMPLETED`, `CHANGES_REQUIRED`, `PREMATURE_STOP`, `FALSE_BLOCKER`, `REAL_BLOCKER`, `NO_PROGRESS`, `POLICY_VIOLATION`, `MALFORMED_RESULT`, `PROVIDER_FAILURE`, `PROVIDER_EXHAUSTED`, `ENVIRONMENT_UNAVAILABLE`, `EVIDENCE_INSUFFICIENT`) persisted durably in PostgreSQL per attempt.
- **Fail-Closed Completion Verification**: Independently verify executor completion claims against OpenSpec task states, worktree status, required artifacts, deterministic checks, and candidate identity rather than trusting natural language affirmations.
- **Narrowed Deterministic Blocker Validation & Fingerprinting**: Enforce structured blocker claims and deterministically validate them against OpenSpec contracts, explicit repository metadata, and known integration points without free-form LLM inference. Derive deterministic blocker fingerprints to detect repeated blocking assertions.
- **Deterministic Continuation Decision Engine & Progress Evaluation**: Evaluate hard evidence counters and deltas (`completed_openspec_task_delta`, `remaining_openspec_task_count`, `candidate_file_delta_count`, `deterministic_checks_pass_delta`, `deterministic_checks_fail_delta`, `acceptance_evidence_delta`, `blocker_resolution_delta`, `regression_detected`, `policy_violation`) to classify progress (`GOOD_PROGRESS`, `PARTIAL_PROGRESS`, `NO_PROGRESS`, `REGRESSION`) and choose rule-based continuation actions (`CONTINUE_SAME_AGENT`, `CORRECT_AND_RETRY`, `REASSIGN_AGENT`, `WAIT_EXTERNAL`, `NEEDS_HUMAN`).
- **Configurable Hard Ceilings & Anti-Ping-Pong Governance**: Enforce explicit configurable limits (`max_corrective_retries_per_executor = 2`, `max_reassignments_per_job = 2`, `max_same_outcome_streak = 2`, `max_same_false_blocker_streak = 2`) preventing infinite retries or agent oscillation, escalating deterministically to `NEEDS_HUMAN`.
- **Targeted Corrective Retry Generation**: Produce structured, minimal corrective prompts when retrying with the same executor without resending excessive context.
- **Executor Reassignment & Structured Handoff**: Enable seamless work takeover between configured primary executors (Codex/Antigravity) with a comprehensive handoff manifest preserving valid candidate work in the existing worktree.
- **Candidate Review Manifest & Visibility Verification**: Build a complete candidate manifest (tracked, staged, untracked candidate files, deletions) and verify reviewer snapshot visibility before review execution. Record `REVIEW_ENVIRONMENT_INVALID` as an evidence diagnostic (prohibiting authoritative review) rather than a job status.
- **Evidence & Review Diagnostic Model**: Support machine-readable diagnostics (`PASS`, `FAIL`, `SKIPPED_BY_POLICY`, `ENVIRONMENT_UNAVAILABLE`, `EVIDENCE_NOT_REPRODUCIBLE`, `REVIEW_ENVIRONMENT_INVALID`), cleanly separating execution diagnostics from job lifecycle states.
- **Authorship & Review Integrity**: Track multi-attempt and multi-agent contribution boundaries, disclose mixed authorship on candidate reviews, and maintain DeepSeek Direct independent audit and human merge boundaries.
- **Restart & Idempotency Safety**: Persist stable attempt, decision, and handoff identifiers to ensure daemon restarts safely resume pending decisions without duplicate execution or state corruption.
- **Governance Observability**: Expose attempt histories, outcomes, blocker validations, continuation decisions, diagnostics, handoff manifests, and escalation details across REST API and CLI commands.

## Capabilities

### New Capabilities
- `agent-execution-outcome-governance`: Structured normalization of executor outcomes, fail-closed completion verification against deterministic evidence, and durable attempt lifecycle tracking.
- `blocker-validation-and-continuation`: Structured blocker claims, narrow repository-aware blocker validation, deterministic blocker fingerprinting, progress evaluation, and evidence-driven continuation decisions (`CONTINUE_SAME_AGENT`, `CORRECT_AND_RETRY`, `REASSIGN_AGENT`, `WAIT_EXTERNAL`, `NEEDS_HUMAN`) with configurable hard ceilings.
- `agent-reassignment-and-handoff`: Evidence-driven executor reassignment, anti-ping-pong bounds, restart-safe structured handoff generation preserving valid worktrees, and candidate authorship tracking.
- `candidate-evidence-integrity`: Pre-review candidate worktree manifest generation, reviewer visibility verification, and machine-readable evidence diagnostics (`REVIEW_ENVIRONMENT_INVALID`, `ENVIRONMENT_UNAVAILABLE`).

### Modified Capabilities
- `complementary-reviewer-policy`: Enforce mixed authorship tracking and disclosure for candidates authored across multiple reassigned executors, preserving reviewer independence and DeepSeek Direct audit integrity.
- `execution-jobs`: Extend execution job states and transitions to support multi-attempt execution loops, continuation transitions, and structured `NEEDS_HUMAN` escalation while keeping evidence diagnostics separate from job statuses.
- `pipeline-observability`: Expose execution attempts, normalized outcome classifications, blocker validation records, continuation decisions, evidence diagnostics, handoffs, and escalation details via API and CLI.

## Impact

- **Domain & Database Models**: New tables/columns for job execution attempts, blocker claims, job handoffs, candidate manifests, and authorship records via Alembic migration 007.
- **Services & Pipeline**: Extensions to `ExecutionPipeline`, new `OutcomeGovernanceService`, `BlockerValidationService`, `ContinuationEngine`, `HandoffManager`, and `CandidateManifestService`.
- **Integrations & Contracts**: Updated implementer and reviewer invocation harnesses to build manifests, verify reviewer visibility, and pass structured corrective/handoff prompts.
- **API & CLI**: Extended `/jobs/{job_id}` endpoints, new `/jobs/{job_id}/attempts` and `/jobs/{job_id}/handoff` endpoints, and `minime jobs attempts`, `minime jobs escalate` CLI subcommands.
- **Compatibility**: Preserves all existing 001–006 invariants (PostgreSQL state, DeepSeek Direct audit, OpenRouter DRAIN fallback, provider resilience, human merge).
