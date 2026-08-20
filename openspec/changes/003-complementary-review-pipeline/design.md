# Design: 003-complementary-review-pipeline

## Context
Stage 0 (`001-foundation`) provided durable PostgreSQL persistence, project registration, and OpenSpec readiness validation. Stage 1 (`002-implementation-pipeline`) established the execution engine: isolated Git worktrees, primary implementer invocation, and sequential deterministic checks.

Stage 2 (`003-complementary-review-pipeline`) designs the complementary review stage that follows successful deterministic checks. See [proposal.md](file:///Users/silveriobernal/Documents/Code/Development/mini-me/openspec/changes/003-complementary-review-pipeline/proposal.md) for motivation and non-goals.

## Goals / Non-Goals

**Goals:**
- Provide a provider-neutral reviewer runner invoking the complementary primary agent (Codex or Antigravity) with explicit change identity and SHA bindings.
- Enforce strict complementary pairing policy (no self-review; no runtime role switching).
- Persist durable review lifecycle states, verdicts (`READY_TO_MERGE` / `CHANGES_REQUIRED`), and structured findings in PostgreSQL via Alembic migrations.
- Guard candidate integrity pre-review and enforce read-only non-mutation boundaries post-review.
- Provide API and CLI observability surfaces for inspecting review outcomes and findings.

**Non-Goals:**
- DeepSeek Direct read-only audit (Stage 3).
- OpenRouter capacity drain fallback and quota drain logic (Stage 4).
- Automatic fix/re-review remediation loops (stops deterministically at `CHANGES_REQUIRED` in 003).
- Containerized preview and human UI validation (Stage 5).
- GitHub PR creation, human merge coordination, and deployment (Stage 6).

## Decisions

### Decision 1: Reviewer Subprocess Adapter and Structured Prompt Contract
- **Approach**: Define `ReviewerRunnerInterface` with `CliReviewerRunner` (executing `agy` or `codex` with `start_new_session=True`) and `MockReviewerRunner` for testing. The runner constructs an explicit structured review prompt containing:
  - `project_id`, `change_id`, `job_id`, `worktree_path`
  - `candidate_sha` and `base_sha`
  - Preceding deterministic check outcomes
  - OpenSpec artifact paths (`proposal.md`, `specs/`, `design.md`, `tasks.md`)
  - Instructions requiring the reviewer to output a structured JSON verdict conforming to `ReviewVerdictPayload`.
- **Rationale**: Keeps reviewer execution provider-neutral and isolated from host process memory while enforcing explicit immutable change and candidate identity.
- **Alternatives Considered**:
  - *Direct LLM API invocation in core*: Rejected because primary agents operate through their respective agentic CLI tooling.
  - *Free-form text review summary only*: Rejected because downstream pipeline stages require deterministic machine-readable verdicts.

### Decision 2: PostgreSQL Schema Evolution for Reviews and Findings
- **Approach**: Add Alembic migration `003_review_pipeline.py` creating:
  - `reviews`: `id` (UUID PK), `job_id` (FK to `jobs.id`, `ondelete="CASCADE"`), `project_id`, `change_name`, `reviewer_role`, `candidate_sha`, `base_sha`, `status` (`REVIEW_PENDING`, `REVIEW_RUNNING`, `REVIEW_COMPLETED`, `REVIEW_FAILED`, `REVIEW_TIMED_OUT`), `verdict` (`READY_TO_MERGE`, `CHANGES_REQUIRED`, nullable), `summary`, `error_message`, `created_at`, `updated_at`.
  - `review_findings`: `id` (UUID PK), `review_id` (FK to `reviews.id`, `ondelete="CASCADE"`), `severity` (`BLOCKER`, `MAJOR`, `MINOR`), `location` (nullable), `violated_requirement`, `expected_correction`, `created_at`.
- **Rationale**: Fulfills the PostgreSQL-only canonical persistence rule, provides first-class relational queryability for findings, and supports atomic state + event persistence.
- **Alternatives Considered**:
  - *Storing findings as unstructured JSON blob on jobs table*: Rejected because individual findings require structured filtering, reporting, and future remediation correlation.

### Decision 3: Pre-Review and Post-Review Candidate Integrity Guard
- **Approach**:
  - *Pre-review*: The pipeline validates that the candidate worktree exists, `git rev-parse HEAD` exactly matches `job.candidate_sha`, and deterministic checks succeeded against that exact SHA.
  - *Post-review*: The pipeline runs `git status --porcelain` and `git rev-parse HEAD` in the worktree. If uncommitted edits or new commit SHAs are found, the review is marked `REVIEW_FAILED` with an `UNAUTHORIZED_REVIEWER_MUTATION` event.
- **Rationale**: Protects candidate reproducibility and enforces the non-negotiable rule that the reviewer is strictly read-only.
- **Alternatives Considered**:
  - *Mounting worktree read-only at filesystem level*: Rejected due to platform-specific complexity and tooling dependencies across macOS/Linux.

### Decision 4: Pipeline Integration & Deterministic Stopping Boundary
- **Approach**: Extend the job state machine transitions:
  `QUEUED` → `RUNNING` → `CHECKS_RUNNING` → `CHECKS_PASSED` → `REVIEW_RUNNING` → `READY_TO_MERGE` (terminal) / `CHANGES_REQUIRED` (terminal stop) / `CHECKS_FAILED` / `FAILED` / `CANCELLED`.
  When a review results in `CHANGES_REQUIRED`, the pipeline safely halts and persists all findings.
- **Rationale**: Delivers a clean, verifiable Stage 2 milestone without prematurely entangling automatic remediation loops, which belong in subsequent iterations.
- **Alternatives Considered**:
  - *Immediate automatic re-invocation of implementer*: Deferred to a later change to keep this review stage scope focused and independently testable.

### Decision 5: Strict Verdict Parsing and Defensive Fallback
- **Approach**: Parse reviewer output using regular expressions and Pydantic validation to extract the structured verdict and findings array. If output cannot be parsed or contains ambiguous verdict tokens, the pipeline transitions the review to `REVIEW_FAILED` and records `MALFORMED_REVIEW_OUTPUT`.
- **Rationale**: Guarantees that a defective or silent reviewer run never passes through as `READY_TO_MERGE`.

## Risks / Trade-offs

- **[Risk] Reviewer child process hangs or stalls** → **Mitigation**: Launch processes with `start_new_session=True` and terminate process groups with `SIGTERM` followed by `SIGKILL` escalation upon timeout.
- **[Risk] Reviewer outputs unstructured markdown commentary without valid JSON block** → **Mitigation**: Implement robust fence/block extraction with defensive fallback to `REVIEW_FAILED` and actionable diagnostic logging.
- **[Risk] Reviewer attempts to modify code or task checkboxes** → **Mitigation**: Run post-review `git status --porcelain` and SHA comparison, rejecting mutated outcomes.

## Migration Plan
- Apply Alembic migration `003_review_pipeline` to the operational PostgreSQL database.
- Migration is non-breaking to existing tables (`projects`, `project_bindings`, `changes`, `events`, `metric_facts`, `jobs`, `job_logs`, `check_results`).
- Downward migration drops `review_findings` and `reviews` cleanly.
