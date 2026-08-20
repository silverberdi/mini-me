# Proposal: 004-deepseek-independent-audit

## Why

In Stage 2 (`003-complementary-review-pipeline`), mini me implemented the complementary review stage (Codex ↔ Antigravity) that evaluates implementation correctness and returns an authoritative machine-readable review verdict (`READY_TO_MERGE` or `CHANGES_REQUIRED`). However, primary agent pairs (even in complementary roles) can share blind spots, overlook subtle edge cases, or miss specification contradictions.

Stage 3 (`004-deepseek-independent-audit`) introduces DeepSeek Direct as an independent, read-only contradiction and audit layer. Operating strictly after successful deterministic checks and after the authoritative complementary reviewer has returned `READY_TO_MERGE`, DeepSeek Direct inspects the candidate diff and read-only workspace snapshot against active OpenSpec requirements, review verdicts, and check evidence. It detects acceptance mismatches, edge cases, security/privacy risks, concurrency/idempotency gaps, missing test coverage, and risky shared assumptions, formatting its findings in an authoritative, strictly validated schema (`schemas/audit-result.schema.json`) before human attention.

## What Changes

- **Direct DeepSeek Auditor Contract**: Provider-neutral adapter executing direct HTTP API requests to DeepSeek using `DEEPSEEK_API_KEY` loaded from secure host configuration/environment. Under no circumstances is DeepSeek routed or proxied through OpenRouter, nor is any fallback provider or provider substitution permitted.
- **Fail-Closed Structured Audit Result Validation**: Parse and validate auditor responses strictly conforming to `schemas/audit-result.schema.json`. Requires exactly one authoritative structured payload (allowing only stripping of a single optional wrapping markdown code fence), rejecting multiple, ambiguous, or unparseable JSON payloads. Captures overall `risk` (`low`, `medium`, `high`, `critical`), a `summary`, and structured `findings` (`severity`, `category`, `message`, `file`, `location`).
- **Clear Authority Model & Explicit Risk Gating Policy**:
  - Complementary reviewer remains the authoritative judge of implementation compliance.
  - DeepSeek Direct acts solely as an independent contradiction auditor and cannot replace the reviewer or turn `CHANGES_REQUIRED` into approval.
  - Audit is eligible **ONLY** after complementary review produces `READY_TO_MERGE`. Audit never runs after `CHANGES_REQUIRED`, `REVIEW_FAILED`, `REVIEW_TIMED_OUT`, malformed review output, candidate integrity failures, or failed checks.
  - Deterministic risk gating: `low`/`medium` risk with no critical/high findings allows job progression to `READY_TO_MERGE` (ready for human gate); `high`/`critical` risk or critical/high findings block progression by transitioning the job to `AUDIT_BLOCKED`.
  - Human authority remains final.
- **Audit Lifecycle & State Persistence**: PostgreSQL schema additions (`audits` and `audit_findings` tables via versioned Alembic migration `004_deepseek_audit` revising `003_review_pipeline`) tracking audit states (`AUDIT_PENDING`, `AUDIT_RUNNING`, `AUDIT_COMPLETED`, `AUDIT_BLOCKED`, `AUDIT_FAILED`, `AUDIT_TIMED_OUT`) tied immutably to `project_id`, `change_name`, `job_id`, `candidate_sha`, and `base_sha`.
- **Read-Only Reviewer-View Model & Integrity Guarantees**: Reuse the OS-level read-only snapshot manager (`ReviewerViewManager`) and symlink fail-closed verification from 003, ensuring the auditor receives zero writable access to the authoritative candidate worktree. Pre- and post-audit SHA and git cleanliness validations guarantee the candidate is untouched.
- **API & CLI Audit Observability**: REST endpoints (`GET /jobs/{job_id}/audit`) and CLI commands (`minime jobs audit <job_id>`) for inspecting audit risk levels, summaries, auditor metadata, and structured findings with secret redaction (`DEEPSEEK_API_KEY` never exposed).

### Non-Goals (Explicitly Excluded)
- OpenRouter capacity drain fallback and budget drain management (Stage 4).
- Autonomous remediation loops based on audit findings (Post-MVP / later enhancement).
- Containerized preview and human UI validation (Stage 5).
- GitHub PR submission, human merge, and production deployment (Stage 6).
- Multi-project fairness/concurrency scheduling, remote PWA, or local Qwen helper (Post-MVP).

## Capabilities

### New Capabilities
- `deepseek-audit-contract`: Direct DeepSeek API client execution contract with secret isolation, direct endpoint communication, structured prompt generation (delta specs, git diff, check results, review findings), single-payload parsing, and strict schema validation against `schemas/audit-result.schema.json`.
- `audit-state-persistence`: PostgreSQL models, Alembic migration `004_deepseek_audit` (revising `003_review_pipeline`), and repositories for persisting audit lifecycle records, overall risk levels, and structured audit findings.
- `audit-integrity-boundary`: SHA-bound integrity validation pre-audit, read-only snapshot isolation with symlink rejection, and non-mutation enforcement post-audit.

### Modified Capabilities
- `execution-jobs`: Extend job state machine and pipeline transitions to orchestrate DeepSeek audit execution strictly following `READY_TO_MERGE` review verdicts, applying deterministic risk gating (`low`/`medium` -> `READY_TO_MERGE`, `high`/`critical` -> `AUDIT_BLOCKED`).
- `pipeline-observability`: Expose audit lifecycle status, overall risk assessment, summary, and structured findings via FastAPI endpoints and CLI commands.

## Impact
- **Database Schema**: New versioned Alembic migration `004_deepseek_audit` (revising `003_review_pipeline`) adding `audits` and `audit_findings` tables to PostgreSQL.
- **API/CLI**: New endpoint `GET /jobs/{job_id}/audit` and CLI command `minime jobs audit <job_id>`.
- **Agent Policy & Contracts**: DeepSeek Direct acts solely as a read-only independent contradiction auditor. Direct API isolation is enforced with zero routing through OpenRouter.
- **Security & Safety**: Secrets (`DEEPSEEK_API_KEY`) are kept in host configuration and redacted from all persisted prompt logs, events, and audit payloads.
