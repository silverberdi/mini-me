## 1. Domain Models & Enums

- [ ] 1.1 Add audit lifecycle enums (`AuditStatus` with `AUDIT_PENDING`, `AUDIT_RUNNING`, `AUDIT_COMPLETED`, `AUDIT_BLOCKED`, `AUDIT_FAILED`, `AUDIT_TIMED_OUT`; `AuditRiskLevel` with `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`; `AuditFindingSeverity` with `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), job status `AUDIT_BLOCKED`, and event types (`JOB_AUDIT_RUNNING`, `JOB_AUDIT_COMPLETED`, `JOB_AUDIT_BLOCKED`, `JOB_AUDIT_FAILED`, `AUDIT_TIMEOUT`, `AUDIT_MALFORMED_OUTPUT`, `UNAUTHORIZED_AUDITOR_MUTATION`) to `src/minime/domain/enums.py`
- [ ] 1.2 Define Pydantic domain models (`AuditResult`, `AuditFinding`, `AuditRecord`) conforming to `schemas/audit-result.schema.json` in `src/minime/domain/models.py`

## 2. Database Persistence & Alembic Migration

- [ ] 2.1 Add `AuditModel` and `AuditFindingModel` to `src/minime/db/models.py` with foreign keys to `jobs.id` and `projects.id`
- [ ] 2.2 Create versioned Alembic migration `004_deepseek_audit.py` with `down_revision = "003_review_pipeline"` creating `audits` and `audit_findings` tables in PostgreSQL
- [ ] 2.3 Add repository methods in `src/minime/db/repository.py` for creating audit records, persisting structured findings, updating status/risk/summary, and querying audit history

## 3. DeepSeek Direct Auditor Client & Contract

- [ ] 3.1 Implement `DeepSeekAuditorRunner` in `src/minime/services/deepseek_auditor_runner.py` with direct HTTP API invocation, `DEEPSEEK_API_KEY` credential loading, timeout handling, secret redaction, and strict assertions rejecting OpenRouter proxying or provider substitution
- [ ] 3.2 Implement audit prompt builder formatting candidate git diff against `base_sha`, OpenSpec specs/tasks, check run outputs, and complementary review verdict (`READY_TO_MERGE`) with findings
- [ ] 3.3 Implement `AuditResultParser` in `src/minime/services/audit_verdict_parser.py` validating responses strictly against `schemas/audit-result.schema.json` with fail-closed single-payload enforcement, single markdown code block stripping, and rejection of multiple/ambiguous JSON objects

## 4. Candidate Integrity & Read-Only Snapshot Boundary

- [ ] 4.1 Implement `verify_pre_audit` in `src/minime/services/candidate_integrity.py` ensuring candidate worktree clean status, candidate/base SHA consistency, passing checks, and preceding review verdict of `READY_TO_MERGE`
- [ ] 4.2 Implement read-only audit snapshot creation via `ReviewerViewManager` with symlink fail-closed scanning (`scan_candidate_for_symlinks`) and OS-level write permission removal (`0o444`/`0o555`)
- [ ] 4.3 Implement `verify_post_audit` in `src/minime/services/candidate_integrity.py` asserting zero worktree mutations or untracked changes after audit execution

## 5. Execution Pipeline Integration & Risk Gating

- [ ] 5.1 Integrate DeepSeek audit execution step into `ExecutionPipelineService` running strictly after complementary review produces `READY_TO_MERGE` (bypassing audit on `CHANGES_REQUIRED` or review failures)
- [ ] 5.2 Implement deterministic audit risk gating in `ExecutionPipelineService`: `low`/`medium` risk with no high/critical findings transitions job to `READY_TO_MERGE`; `high`/`critical` risk or high/critical findings transitions job to `AUDIT_BLOCKED`
- [ ] 5.3 Record audit timing metric `audit_duration_ms` in `metric_facts` and transition job atomically with lifecycle events

## 6. API and CLI Observability

- [ ] 6.1 Add `GET /jobs/{job_id}/audit` endpoint and update job detail responses in `src/minime/api/routes.py` with secret redaction
- [ ] 6.2 Add CLI command `minime jobs audit <job_id>` in `src/minime/cli/main.py` displaying audit status, risk rating, summary, and structured findings table

## 7. Verification & Tests

- [ ] 7.1 Add unit tests for `DeepSeekAuditorRunner`, direct endpoint enforcement, credential isolation, and prompt generation
- [ ] 7.2 Add unit tests for `AuditResultParser` verifying schema compliance, single-payload fail-closed validation, markdown fence stripping, and rejection of multiple/malformed JSON outputs
- [ ] 7.3 Add repository and migration tests for Alembic migration `004_deepseek_audit` and `audits`/`audit_findings` models
- [ ] 7.4 Add integration tests for `ExecutionPipelineService` covering successful audit (`low`/`medium` -> `READY_TO_MERGE`), blocked audit (`high`/`critical` -> `AUDIT_BLOCKED`), audit timeout, schema violation failure, symlink rejection, and auditor mutation detection
