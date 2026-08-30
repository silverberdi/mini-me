## Why

Prior changes (007, 008, and 009) established autonomous change orchestration, continuation governance, and GitHub App runtime integration. However, operational checks and edge-case validations surfaced specific governance, recovery, schema safety, and presentation defects—including undisclosed mixed authorship during reassigned reviews, unverified reviewer missing-file blockers, transient provider outcomes mapped to terminal failures, timestamp-derived RESUME event jitter, alembic-only schema checks that miss absent tables or columns, candidate checks inheriting canonical database credentials at runtime, CLI crashes on provider health queries, and ambient Git trace variable credential exposure. Change 010 hardens these surfaces as the final prerequisite before mini me begins self-hosting change implementation through its autonomous orchestration pipeline.

## What Changes

- **Mixed-Authorship Review Disclosure for Current Candidate**: When executor reassignment occurs, evaluate whether the assigned reviewer authored material that survives in the CURRENT frozen candidate generation/SHA. If surviving contributions exist, the Review record, reviewer prompt payload, and review presentation must explicitly disclose mixed authorship (`is_mixed_authorship = True`), maintaining complementary review while clarifying non-independence ahead of mandatory DeepSeek Direct audit. Earlier attempts whose contributions were discarded do not trigger mixed authorship.
- **Manifest- & Tree-Backed Missing-File Finding Validation**: Cross-check reviewer claims of missing files against OpenSpec requirements, the frozen candidate manifest, and the authoritative candidate tree at the exact candidate SHA (with base..candidate diff as supporting context). A file present in base that remains unchanged is verified as present; guessed or convention-based filenames cannot block by themselves, while genuine candidate omissions still fail normally.
- **Deterministic Transient Provider Error Normalization**: Map transient network, timeout, connection reset, and HTTP 502/503/504 errors (`ProviderResultClass.TRANSIENT_ERROR`) to `ExecutionOutcome.ENVIRONMENT_UNAVAILABLE` and `ContinuationDecision.WAIT_EXTERNAL`, stopping the run in `OrchestrationStopOutcome.WAITING_EXTERNAL` without incrementing corrective retry or reassignment counters, preserving RUN/DRAIN/WAIT policy.
- **RESUME Observability Idempotency**: Replace timestamp-derived RESUME event and transition keys with deterministic logical idempotency keys (`{run_id}:RESUME:{resumable_stage}:{current_generation}`) so repeated restarts or reconciliations do not produce duplicate logical evidence.
- **Physical PostgreSQL Schema Integrity Before Admission**: Verify physical database schema invariants (actual table existence and required columns derived from authoritative SQLAlchemy metadata, specifically including `reviews.is_mixed_authorship`) in addition to `alembic_version` head before admitting an orchestration run, failing closed with `SCHEMA_INVARIANT_VIOLATION` if the head exists without required tables or columns, without performing automatic database repairs.
- **Runtime Canonical Database Isolation for Candidate Checks**: Enforce database protection directly within mini me's production `ChecksRunner` by sanitizing candidate subprocess environments (purging `MINIME_DATABASE_URL` and `MINIME_EXPECTED_DATABASE` by default). Destructive or PostgreSQL-specific checks must declare structured disposable-DB intent and exact expected database identity, failing closed if pointing to canonical `minime`, if expected DB is missing, or if actual != expected. Test fixtures in `tests/conftest.py` remain as defense in depth.
- **Provider Health CLI Presentation Defect Fix**: Fix the CLI crash in `minime providers health` by joining `ProviderHealth` with its latest `CapacityWindow` rather than reading non-existent model attributes, without modifying underlying scheduling semantics.
- **GitHub App Residual Hardening**: Remove the redundant standalone `verify_repository` API call in favor of authoritative Issue remote verification (`validate_issue_binding`), and sanitize subprocess environments by stripping inherited Git trace variables (`GIT_TRACE`, `GIT_TRACE_PACKET`, `GIT_TRACE_CURL`, `GIT_CURL_VERBOSE`, `GIT_TRANSPORT_TRACE`) before authenticated Git executions to prevent Authorization header exposure.
- **Autonomous Execution Readiness Contract**: Establish explicit readiness prerequisites (active project, durable binding to the GitHub Issue bound to this change, remote Issue verification, physical schema preflight, non-empty checks, available primary capacity, and healthy GitHub App) before initiating `minime orchestrate start`.

## Capabilities

### New Capabilities
*(None)*

### Modified Capabilities
- `complementary-reviewer-policy`: Enforce explicit mixed-authorship disclosure bound to surviving contributions in the current candidate generation in Review records, reviewer prompts, and evidence surfaces when reassignment has occurred.
- `structured-review-verdict`: Require reviewer missing-file blocker claims to be cross-checked against OpenSpec contracts, frozen candidate manifest, and the exact candidate tree.
- `agent-execution-outcome-governance`: Normalize transient provider errors to `ENVIRONMENT_UNAVAILABLE` and `WAIT_EXTERNAL` waiting outcomes without consuming retry ceilings.
- `autonomous-change-orchestration`: Ensure RESUME stage transitions and events use deterministic, timestamp-free logical idempotency keys.
- `postgres-durable-state`: Mandate physical schema table and column invariant validation before admission, and enforce canonical database isolation against destructive candidate tests.
- `deterministic-checks-runner`: Sanitize candidate check subprocess environments, purging canonical database credentials and validating structured disposable database intent fail-closed.
- `status-observability`: Provide crash-free provider health status presentation via `minime providers health` with accurate reset windows resolved from capacity window records.
- `github-app-runtime-identity`: Strip inherited Git trace environment variables before authenticated Git operations and eliminate redundant repository verification.

## Impact

- **Services & Governance**: `authorship_service.py`, `reviewer_contract.py`, `execution_pipeline.py`, `orchestration_service.py`, `outcome_governance.py`, `blocker_validation.py`, `restart_recovery_service.py`, `provider_health_service.py`, `readiness_service.py`, and `checks_runner.py` updated with deterministic hardening.
- **Database & Persistence**: `Review` domain model and `ReviewModel` database entity gain explicit `is_mixed_authorship` tracking; Alembic database revision `009_governance_hardening` added (chained from `008_autonomous_orchestration`). Note: `009` is the database revision sequence; the OpenSpec change number is `010`.
- **Runtime Checks Execution**: `ChecksRunner` sanitizes subprocess environment by default and enforces disposable PostgreSQL database verification.
- **Adapters & Subprocesses**: `src/minime/adapters/github.py` sanitizes subprocess environment variables against trace leaks; redundant `verify_repository` removed or aligned to `validate_issue_binding`.
- **API & CLI**: `minime providers health` and orchestration status endpoints present robust, uncorrupted diagnostic and health payloads.
