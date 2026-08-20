## Context

mini me is a personal single-installation Linux orchestrator for spec-driven development across multiple repositories. Stages 0–2 established PostgreSQL persistence, Alembic migrations, the execution pipeline, deterministic checks, and complementary review (Codex ↔ Antigravity).

Stage 3 (`004-deepseek-independent-audit`) implements DeepSeek Direct as an independent, read-only contradiction auditor that runs strictly after the authoritative complementary reviewer has returned `READY_TO_MERGE`. It evaluates candidate diffs and read-only snapshots against active requirements, check evidence, and prior review findings, returning structured findings (`schemas/audit-result.schema.json`) before human attention.

See `proposal.md` for background and motivation.

## Goals / Non-Goals

**Goals:**
- Implement `DeepSeekAuditorRunner` communicating directly with DeepSeek HTTP API (`https://api.deepseek.com/chat/completions`) using `DEEPSEEK_API_KEY`.
- Enforce strict direct communication policy preventing any routing, proxying, fallback, or provider substitution through OpenRouter.
- Implement `AuditResultParser` with fail-closed validation enforcing exactly one authoritative JSON payload (allowing only stripping of a single optional wrapping markdown code block) conforming strictly to `schemas/audit-result.schema.json`.
- Enforce distinct authority boundaries and deterministic risk gating (`low`/`medium` -> `READY_TO_MERGE`, `high`/`critical` -> `AUDIT_BLOCKED`).
- Add PostgreSQL persistence for `audits` and `audit_findings` tables via Alembic revision `004_deepseek_audit` (revising `003_review_pipeline`).
- Reuse `ReviewerViewManager` and `CandidateIntegrityService` to enforce OS-level read-only snapshot isolation with symlink fail-closed security.
- Integrate audit execution into `ExecutionPipelineService` following successful review (`READY_TO_MERGE`), recording timing metrics in `metric_facts`.
- Expose audit endpoints via FastAPI (`GET /jobs/{job_id}/audit`) and CLI (`minime jobs audit <job_id>`).

**Non-Goals:**
- OpenRouter capacity drain fallback and budget drain management (Stage 4).
- Autonomous remediation loops based on audit findings (Post-MVP).
- Container preview and human UI validation (Stage 5).
- GitHub PR creation, human merge, and deployment (Stage 6).

## Decisions

### 1. Direct DeepSeek API Client & Provider Policy
- **Decision**: Implement a dedicated async HTTP client (`DeepSeekAuditorRunner`) targeting the official direct DeepSeek API endpoint (`https://api.deepseek.com/chat/completions`). It loads `DEEPSEEK_API_KEY` from host environment/config (`/etc/minime/` or environment).
- **Direct Provider Enforcement**: Direct API validation verifies the target host is official DeepSeek; any configuration or attempt to route requests through OpenRouter, proxy gateways, or substitute fallback providers is rejected immediately before making network requests.
- **Rationale**: Preserves the non-negotiable rule: *"DeepSeek Direct is a read-only auditor. Never route DEEPSEEK_API_KEY through OpenRouter."*

### 2. Authority Model & Deterministic Risk-to-Pipeline Gating
- **Authority Boundaries**:
  - **Complementary Reviewer**: Authoritative judge of implementation and spec compliance.
  - **DeepSeek Direct**: Independent read-only contradiction layer focusing on subtle edge cases, security/privacy, concurrency/idempotency, and missing tests. It cannot replace the reviewer or turn `CHANGES_REQUIRED` into approval.
  - **Human Operator**: Final authority for merge, override, or policy exceptions.
- **Pipeline Gating**: DeepSeek audit is eligible **ONLY** when the complementary review verdict is `READY_TO_MERGE`. Audit never executes after `CHANGES_REQUIRED`, `REVIEW_FAILED`, `REVIEW_TIMED_OUT`, malformed review output, candidate integrity failures, or failed checks.
- **Deterministic Risk Gating Policy**:
  - **`low` / `medium` Risk**: Audit passes without blocking. When overall `risk` is `low` or `medium` and no finding has severity `high` or `critical`, audit status is `AUDIT_COMPLETED` and job status transitions to `READY_TO_MERGE` (ready for human attention/gate).
  - **`high` / `critical` Risk**: Audit detects critical contradictions or unacceptable risk. When overall `risk` is `high` or `critical`, OR when any individual finding has severity `high` or `critical`, audit status is recorded with findings and the job transitions to `AUDIT_BLOCKED`, preventing automated advancement to the human merge gate until resolved.
  - **Execution Failures / Timeouts / Schema Violations**: Transitions audit status to `AUDIT_FAILED` or `AUDIT_TIMED_OUT` and job status to `FAILED`.

### 3. Fail-Closed Structured Audit Output Parsing (`AuditResultParser`)
- **Decision**: DeepSeek responses must contain **exactly one** authoritative structured JSON payload adhering to `schemas/audit-result.schema.json`.
- **Parsing Rules**:
  - A single optional wrapping markdown code fence (````json ... ```` or ```` ... ````) is stripped if present.
  - Free-form JSON extraction, regex searching across arbitrary prose, or multiple candidate JSON objects are strictly prohibited and fail closed.
  - Validation against `schemas/audit-result.schema.json`:
    - `risk`: must be one of `["low", "medium", "high", "critical"]`.
    - `summary`: non-empty string.
    - `findings`: array of objects, each with `severity` (`low`|`medium`|`high`|`critical`), `category`, `message`, optional `file`, optional `location`.
    - `additionalProperties`: false.
  - Any validation failure triggers a `MALFORMED_AUDIT_OUTPUT` event and marks the audit as `AUDIT_FAILED`.

### 4. Database Persistence & Alembic Migration (`004_deepseek_audit`)
- **Decision**: Add Alembic migration `004_deepseek_audit.py` with `down_revision = "003_review_pipeline"`, creating:
  - `audits`: `id` (VARCHAR 64 PK), `job_id` (FK `jobs.id` ON DELETE CASCADE), `project_id` (FK `projects.id` ON DELETE CASCADE), `change_name` (VARCHAR 128), `candidate_sha` (VARCHAR 64), `base_sha` (VARCHAR 64), `status` (VARCHAR 32), `risk` (VARCHAR 16 nullable), `summary` (TEXT nullable), `error_message` (TEXT nullable), `created_at`, `updated_at`.
  - `audit_findings`: `id` (VARCHAR 64 PK), `audit_id` (FK `audits.id` ON DELETE CASCADE), `severity` (VARCHAR 16), `category` (VARCHAR 64), `message` (TEXT), `file` (VARCHAR 255 nullable), `location` (VARCHAR 255 nullable), `created_at`.
- **Indices**: Indexes on `job_id`, `project_id`, `change_name`, `status`, `risk`, `created_at`, and `audit_findings.audit_id`.

### 5. Read-Only Snapshot Isolation & Candidate Integrity
- **Decision**: Extend `ReviewerViewManager` and `CandidateIntegrityService` for audit execution:
  - `ReviewerViewManager.create_readonly_view()` creates an OS-level read-only snapshot (`0o444`/`0o555`) and confirms write denial via write probe.
  - Fail-closed symlink check (`scan_candidate_for_symlinks`) blocks snapshot creation if any symlinks are detected.
  - Auditor prompt context compiles git diff against `base_sha`, delta specs, check results, and review findings. The auditor is never given writable access to the candidate worktree.
  - Pre-audit integrity verification validates worktree clean status, candidate HEAD SHA, base SHA, passing checks, and `READY_TO_MERGE` review verdict.
  - Post-audit integrity verification validates that the candidate worktree remains 100% untouched (`git status --porcelain` is empty, HEAD SHA unchanged).

### 6. Execution Pipeline Integration
- **Decision**: In `ExecutionPipelineService`:
  1. After reviewer runner completes with `READY_TO_MERGE`, job status transitions to `AUDIT_RUNNING`.
  2. Pre-audit integrity check verifies worktree and SHA binding.
  3. OS-level read-only snapshot is prepared and `DeepSeekAuditorRunner` is invoked.
  4. Post-audit integrity check asserts zero worktree mutations.
  5. Audit record and structured findings are persisted to PostgreSQL in a single transaction.
  6. Metric facts (`audit_duration_ms`, `total_duration_ms`) are recorded.
  7. Risk gating evaluates outcome: `low`/`medium` transitions job to `READY_TO_MERGE`; `high`/`critical` transitions job to `AUDIT_BLOCKED`.
  8. If complementary review concluded with `CHANGES_REQUIRED`, audit is bypassed and job terminates at `CHANGES_REQUIRED`.

### 7. API and CLI Observability with Secret Redaction
- **Decision**:
  - API endpoint `GET /jobs/{job_id}/audit` returns audit status, risk rating, summary narrative, candidate SHA binding, and structured findings list.
  - `GET /jobs/{job_id}` includes `audit_status` and `audit_risk`.
  - CLI command `minime jobs audit <job_id>` renders a formatted table of findings with risk ratings and summary.
  - `SecretRedactor` masks `DEEPSEEK_API_KEY` and host credentials from all persisted logs, traces, events, and API/CLI views.

## Risks / Trade-offs

- **[Risk] DeepSeek API network latency, timeout, or rate limiting**
  - *Mitigation*: Bounded async HTTP timeout (default 60s); clean transitions to `AUDIT_TIMED_OUT` or `AUDIT_FAILED` with structured error logging without crashing daemon.
- **[Risk] Auditor returns multiple or loose JSON blocks in conversational text**
  - *Mitigation*: `AuditResultParser` strictly permits only a single wrapping markdown code block; multiple JSON blocks or embedded fragments fail closed.
- **[Risk] Sensitive API credentials leaked in database logs or traces**
  - *Mitigation*: `SecretRedactor` filters `DEEPSEEK_API_KEY` and sensitive tokens before writing to `job_logs`, `events`, or audit records.

## Migration Plan

1. Apply Alembic migration `004_deepseek_audit.py` (revising `003_review_pipeline`) creating `audits` and `audit_findings` tables.
2. Rollback strategy: Alembic `downgrade -1` drops `audit_findings` and `audits` tables cleanly.
