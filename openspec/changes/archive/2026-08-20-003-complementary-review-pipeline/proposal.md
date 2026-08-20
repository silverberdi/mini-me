# Proposal: 003-complementary-review-pipeline

## Why
In Stage 1 (`002-implementation-pipeline`), mini me implemented the core execution pipeline: isolated worktree creation, primary implementer invocation, sequential deterministic checks, and PostgreSQL evidence recording. However, once deterministic checks pass, mini me lacks an automated, authoritative review stage.

Stage 2 (`003-complementary-review-pipeline`) introduces the complementary review pipeline. It extends the execution flow by handing a successfully checked candidate to the complementary primary reviewer (Codex if Antigravity implemented, or Antigravity if Codex implemented) to generate an authoritative, machine-readable review verdict (`READY_TO_MERGE` or `CHANGES_REQUIRED`) with structured findings, candidate SHA integrity binding, read-only boundary guarantees, and full API/CLI observability.

## What Changes
- **Provider-Neutral Reviewer Execution Contract**: Subprocess runner adapter invoking the configured complementary reviewer with explicit immutable change identity, candidate SHA, base SHA, worktree path, spec/tasks context, and check evidence.
- **Complementary Reviewer Policy Enforcement**: Strict pairing verification (Codex ↔ Antigravity) preventing an agent or provider from reviewing its own work, disallowing mid-job reviewer switching, and failing safely if the complementary reviewer is unavailable.
- **Durable Review Lifecycle & Persistence**: PostgreSQL schema additions (`reviews`, `review_findings` tables via Alembic) tracking review states (`REVIEW_PENDING`, `REVIEW_RUNNING`, `REVIEW_COMPLETED`, `REVIEW_FAILED`, `REVIEW_TIMED_OUT`) correlated to project, change, job, candidate SHA, and base SHA.
- **Structured Review Verdict & Findings**: Parsing and validation of machine-readable review outcomes (`READY_TO_MERGE` or `CHANGES_REQUIRED`), capturing structured findings (`severity`: `BLOCKER`/`MAJOR`/`MINOR`, `location`, `violated_requirement`, `expected_correction`), and failing safely if output is ambiguous or malformed.
- **Candidate Integrity & Read-Only Review Boundary**: Pre-review candidate validation (verifying candidate worktree, HEAD SHA, base SHA, and prior passing check evidence) and post-review verification ensuring the reviewer did not mutate candidate files, commits, or OpenSpec artifacts.
- **Pipeline Review Integration**: Pipeline extension advancing jobs from `CHECKS_PASSED` to review execution, stopping deterministically at `READY_TO_MERGE` or `CHANGES_REQUIRED`.
- **API & CLI Review Observability**: Endpoints and CLI commands to inspect review status, reviewer identity, verdict, candidate SHA binding, and structured findings.

### Non-Goals (Explicitly Excluded)
- DeepSeek Direct independent read-only audit (Stage 3).
- OpenRouter capacity drain fallback and provider budget drain management (Stage 4).
- Automatic fix/re-review remediation loops (Post-Stage 2 / later enhancement).
- Containerized preview and human UI validation (Stage 5).
- GitHub PR submission, human merge automation, and production deployment (Stage 6).
- Multi-project fairness/concurrency scheduling, remote PWA, or local Qwen helper (Post-MVP).

## Capabilities

### New Capabilities
- `reviewer-execution-contract`: Provider-neutral execution interface supplying explicit immutable change ID, candidate SHA, base SHA, worktree path, spec context, and check evidence to the reviewer.
- `complementary-reviewer-policy`: Policy enforcement ensuring distinct complementary primary roles (Codex ↔ Antigravity), forbidding self-review, and preventing runtime role mutations.
- `review-state-persistence`: PostgreSQL models, Alembic migrations, and repositories for review lifecycle records and structured review findings.
- `structured-review-verdict`: Schema and validation for machine-readable verdicts (`READY_TO_MERGE`, `CHANGES_REQUIRED`), structured issue severities (`BLOCKER`, `MAJOR`, `MINOR`), and fallback rejection on malformed output.
- `candidate-integrity-verification`: SHA-bound integrity validation pre-review and read-only non-mutation enforcement post-review.

### Modified Capabilities
- `execution-jobs`: Extend job state machine and transitions to orchestrate review stages following successful deterministic checks.
- `pipeline-observability`: Expose review lifecycle status, verdict, candidate SHA, and structured findings via FastAPI endpoints and CLI commands.

## Impact
- **Database Schema**: New Alembic migration adding `reviews` and `review_findings` tables in PostgreSQL.
- **API/CLI**: New endpoint `/jobs/{job_id}/review` and CLI command `minime jobs review <job_id>` for viewing review verdicts and findings.
- **Agent Contracts**: Codex and Antigravity operate under strict complementary role separation; reviewer operates in read-only mode without mutating candidate code or task checkboxes.
- **Security & Safety**: Candidate SHA + base SHA are immutably bound to the review record; all logs pass through secret redaction before persistence.
