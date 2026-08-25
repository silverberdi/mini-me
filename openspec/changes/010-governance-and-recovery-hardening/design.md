## Context

See `proposal.md` for motivation and background context. Changes 001–009 established the complete architectural foundation, job execution pipeline, complementary review, DeepSeek Direct audit, provider resilience, OpenRouter drain fallback, continuation governance, autonomous orchestration coordinator, and GitHub App runtime integration. During operational hardening of changes 007, 008, and 009, eight specific hardening items were identified across governance, recovery, schema safety, test isolation, and presentation.

This change is intentionally the first change designed to be executed via mini me's autonomous orchestration pipeline (`minime orchestrate start`) after manual proposal, project binding, and Definition of Ready preparation.

## Goals / Non-Goals

**Goals:**
- Implement durable mixed-authorship tracking on Review domain models, database models, reviewer prompt payload, and review evidence presentation, evaluated strictly against surviving contributions in the CURRENT frozen candidate generation/SHA.
- Implement manifest-, contract-, and tree-backed missing-file finding validation to eliminate false blockers from guessed/hallucinated filenames or unchanged base repository files.
- Normalize transient provider outcomes (`TRANSIENT_ERROR`, connection drop, 502/503/504) into `ExecutionOutcome.ENVIRONMENT_UNAVAILABLE` and `ContinuationDecision.WAIT_EXTERNAL` in `OrchestrationStopOutcome.WAITING_EXTERNAL`, without incrementing retry or reassignment counters, preserving RUN/DRAIN/WAIT policy.
- Provide deterministic, collision-free logical transition keys for RESUME events and stage transitions (`{run_id}:RESUME:{resumable_stage}:{current_generation}`).
- Validate physical PostgreSQL schema invariants (both table existence and required column existence derived from authoritative SQLAlchemy metadata, specifically including `reviews.is_mixed_authorship`) before admitting orchestration runs, preventing false-head admission.
- Enforce strict test isolation preventing test suites and runtime candidate checks from inheriting canonical database credentials or executing destructive queries against operational databases directly at the `ChecksRunner` execution boundary.
- Fix the CLI crash in `minime providers health` when resolving reset hints by reading from durable capacity window records.
- Strip inherited Git trace environment variables before authenticated Git subprocesses, and resolve the unused `verify_repository` surface in favor of authoritative Issue binding verification.
- Make all autonomous execution readiness prerequisites explicit before initiating `orchestrate start`.

**Non-Goals:**
- No new provider integrations.
- No redesign of provider scheduling or capacity windows.
- No modifications to OpenRouter drain fallback policy.
- No automated GitHub merge or PR merge automation.
- No automated deployment or rollback execution.
- No UI feature work or Textual TUI changes.
- No automatic database repair (database repair remains an explicit operator command).
- No creation of additional PostgreSQL services or instances.
- No modifications to archived changes 001–009.

## Decisions

### Decision 1: Mixed-Authorship Bound to Surviving Current Candidate Material

- **Context**: When executor reassignment occurs (e.g. Codex initiates implementation, Antigravity completes continuation or remediation), the complementary reviewer (Antigravity) may review a candidate partially authored by itself. However, if an earlier attempt's modifications were completely discarded or overwritten, flagging mixed authorship would be a false positive.
- **Choice**:
  1. Add `is_mixed_authorship: bool = False` to `Review` domain model, `ReviewModel` database entity, and `reviews` PostgreSQL table via Alembic migration `009_governance_hardening`.
  2. In `AuthorshipService` and `ReviewerContract`, evaluate author contributions specifically for changes that survive in the CURRENT frozen candidate generation (bound to `candidate_sha` and `candidate_generation`).
  3. If surviving contributions from the assigned reviewer exist in the candidate tree/diff, set `is_mixed_authorship = True`, persist the determination with the Review record, and inject an explicit mixed-authorship disclosure into the reviewer prompt payload.
  4. If the reviewer only authored discarded historical attempts with no surviving modifications in the current candidate, set `is_mixed_authorship = False`.
  5. The reviewer remains complementary but is explicitly marked as non-independent in the review record and evidence logs when `is_mixed_authorship = True`. DeepSeek Direct remains the authoritative independent auditor in all cases.
- **Alternatives Considered**:
  - *Flag mixed authorship whenever reassignment occurred on the job*: Rejected because discarded attempts do not influence the candidate code under review and create false positive disclosure.
  - *Disallow reassignment to complementary reviewer*: Rejected because in a two-primary setup (Codex/Antigravity), disallowing reassignment would prematurely escalate to human intervention when continuation is possible.

### Decision 2: Candidate Tree & Contract Authority for Missing-File Validation

- **Context**: LLM reviewers sometimes assert `CHANGES_REQUIRED` with severity `BLOCKER` claiming that a convention-based or imagined file (e.g., `scheduler_service.py`) is "missing", even when the capability is implemented in an alternative declared module (e.g., `capacity_lifecycle_service.py`) or the file was never specified in OpenSpec. Additionally, a required file that existed in the base branch and remains unchanged does not appear in the base..candidate diff and must not be falsely flagged as missing.
- **Choice**:
  1. In `BlockerValidationService` and review verdict handling in `execution_pipeline.py`, cross-check any missing-file blocker finding against:
     - Explicit OpenSpec tasks and specification requirements;
     - The frozen `CandidateManifest`;
     - The authoritative candidate tree at the exact `candidate_sha`;
     - The `base_sha..candidate_sha` diff as supporting evidence.
  2. A missing-file finding is validated as a legitimate `REAL_BLOCKER` ONLY when:
     - The artifact is explicitly required by OpenSpec tasks or specifications; AND
     - The file is absent from the authoritative candidate tree at `candidate_sha`.
  3. If the file exists in the candidate tree (even if absent from the diff because it was unchanged from base), the claim is rejected.
  4. If the claimed missing file is a guessed, non-contractual name and the candidate passes configured deterministic checks, the finding is classified as a `FALSE_BLOCKER` / non-blocking remark and does not block review completion.
- **Alternatives Considered**:
  - *Rely solely on git diff*: Rejected because unchanged files from base branch do not appear in diffs and would trigger false missing-file claims.
  - *Accept all reviewer findings unconditionally*: Rejected because hallucinated file claims cause false remediation loops.

### Decision 3: Deterministic Transient Provider Error State Machine

- **Context**: In 007 outcome governance, `ProviderResultClass.TRANSIENT_ERROR` was mapped to `ExecutionOutcome.PROVIDER_FAILURE`. This caused active jobs to transition directly to `FAILED` or trigger excessive reassignments on transient network blips.
- **Choice**:
  1. Define explicit canonical mapping:
     - Input result: `ProviderResultClass.TRANSIENT_ERROR` (network connection reset, timeout, DNS resolution failure, HTTP 502/503/504).
     - Mapped outcome: `ExecutionOutcome.ENVIRONMENT_UNAVAILABLE`.
     - Continuation decision: `ContinuationDecision.WAIT_EXTERNAL`.
     - Orchestration outcome: `OrchestrationStopOutcome.WAITING_EXTERNAL`.
  2. On transient provider errors, the coordinator preserves the in-flight attempt context, resumable stage, and handoff.
  3. `corrective_retries_count` and `reassignment_count` are NOT incremented for transient infrastructure errors.
  4. The run resumes cleanly from its resumable checkpoint when connectivity is restored via `orchestration_service.resume()` or daemon startup recovery.
- **Alternatives Considered**:
  - *Map transient error to PROVIDER_FAILURE*: Rejected because provider failure consumes reassignment quotas and leads to unnecessary human escalation.
  - *Create a new scheduler state*: Rejected because existing `WAIT_EXTERNAL` / `ENVIRONMENT_UNAVAILABLE` enums already represent non-provider external/transient waiting semantics accurately.

### Decision 4: Deterministic Logical Idempotency Key for RESUME Events

- **Context**: In `orchestration_service.py`, `resume()` generated stage events using `transition_key=f"{run.run_id}:RESUME:{utc_now().isoformat()}"`. This generated non-idempotent event records on repeated reconciliation calls.
- **Choice**:
  1. Replace timestamp-based key generation with deterministic logical transition keys: `transition_key=f"{run.run_id}:RESUME:{run.resumable_stage.value}:{run.current_generation}"`.
  2. On repeated daemon startup reconciliation or operator `orchestrate resume` calls where no stage transition has occurred, the coordinator checks if a resume event with the logical key already exists and avoids duplicate stage event insertions.
- **Alternatives Considered**:
  - *Keep timestamp keys and suppress unique constraint*: Rejected because event logs should represent meaningful state transitions rather than duplicate polling artifacts.

### Decision 5: Physical PostgreSQL Schema Invariant Verification (Tables & Required Columns)

- **Context**: `alembic_version` can indicate `head` (e.g. if migrations were marked applied or stamped) even if physical application tables or specific required columns were dropped or uninitialized.
- **Choice**:
  1. Implement `verify_physical_schema_invariants(engine)` in `minime.db.session` and invoke it during admission preflight in `readiness_service.py` and `orchestration_service.admit_change()`.
  2. The verification derives required tables and columns directly from authoritative SQLAlchemy metadata (`Base.metadata`), checking PostgreSQL catalog / `information_schema`.
  3. Specifically verifies:
     - `alembic_version` matches the expected head revision (`009_governance_hardening`).
     - All core application tables physically exist (`projects`, `project_bindings`, `changes`, `jobs`, `job_attempts`, `reviews`, `review_findings`, `audits`, `audit_findings`, `orchestration_runs`, etc.).
     - All required columns physically exist on their respective tables, specifically including `reviews.is_mixed_authorship` and `jobs.is_mixed_authorship`.
  4. If any required table or column is missing, admission fails closed immediately with a structured diagnostic error (`SCHEMA_INVARIANT_VIOLATION`), refusing orchestration run admission.
  5. Automatic database repair (running `alembic upgrade head` or `create_all`) is strictly prohibited during runtime admission; schema remediation remains an explicit operator action.
- **Alternatives Considered**:
  - *Run alembic upgrade head automatically on admission*: Rejected because running automated DDL during production/canonical admission violates canonical safety rules.

### Decision 6: Runtime Canonical Database Isolation at ChecksRunner

- **Context**: If candidate check commands or test suites execute with inherited environment variables, a check subprocess could inadvertently target or mutate the canonical operational PostgreSQL database (`minime`). Placing safety checks only in `tests/conftest.py` leaves production checks vulnerable.
- **Choice**:
  1. In `ChecksRunner.run()`, sanitize the execution environment for all candidate check subprocesses:
     - Purge `MINIME_DATABASE_URL` and `MINIME_EXPECTED_DATABASE` by default.
  2. If a check requires PostgreSQL access (e.g. database migration or concurrency tests), the check configuration must declare structured disposable-DB intent:
     ```yaml
     name: pg-integration-tests
     command: pytest tests/test_pg_integration.py
     disposable_postgres: true
     expected_database: minime_010_verify
     ```
  3. `ChecksRunner` validates that:
     - `MINIME_DATABASE_URL` does NOT point to the canonical database (`minime`).
     - `expected_database` is explicitly defined.
     - The database name in `MINIME_DATABASE_URL` strictly equals `expected_database`.
  4. If the check targets `minime`, if `expected_database` is missing, or if actual database != expected database, `ChecksRunner` fails closed immediately with exit code 126 and an `EvidenceDiagnostic` failure before spawning the subprocess.
  5. `tests/conftest.py` fixtures enforce the same disposable-DB checks as defense in depth.
- **Alternatives Considered**:
  - *Rely solely on pytest conftest*: Rejected because arbitrary shell checks configured in projects bypass pytest fixtures.

### Decision 7: Provider Health Reset Time Presentation via Capacity Window Association

- **Context**: In `src/minime/cli/main.py`, `providers_health_cmd` (`minime providers health`) attempted to read `h.capacity_reset_at` and `h.retry_after_seconds` directly from `ProviderHealth` domain objects, causing `AttributeError` because those attributes exist on `CapacityWindow`.
- **Choice**:
  1. In `ProviderHealthService.list_all_health_with_capacity()`, join `ProviderHealth` with `CapacityWindowRepository.get_latest_for_provider(provider)`.
  2. In `cli/main.py` for command `minime providers health`, read `capacity_reset_at` and `retry_after_seconds` from the associated capacity window.
  3. Preserve all underlying provider health and capacity tracking semantics.
- **Alternatives Considered**:
  - *Duplicate capacity fields on ProviderHealth table*: Rejected because `CapacityWindow` is already the authoritative historical and active record of quota exhaustion windows.

### Decision 8: Ephemeral Subprocess Environment Sanitization for Authenticated Git

- **Context**: If the host environment has Git trace variables enabled (`GIT_TRACE`, `GIT_TRACE_PACKET`, `GIT_TRACE_CURL`, `GIT_CURL_VERBOSE`, `GIT_TRANSPORT_TRACE`), Git prints full HTTP request headers—including `Authorization: Basic <base64-token>`—to standard error or trace streams. Furthermore, `verify_repository` in `src/minime/adapters/github.py` was unused in runtime flows.
- **Choice**:
  1. In `GitHubAdapter._run_git()`, construct a sanitized subprocess environment that explicitly strips `GIT_TRACE`, `GIT_TRACE_PACKET`, `GIT_TRACE_CURL`, `GIT_CURL_VERBOSE`, and `GIT_TRANSPORT_TRACE`.
  2. Remove or streamline the redundant standalone `verify_repository` method, relying on `validate_issue_binding` which already performs authoritative repository validation via remote GitHub Issue inspection without making redundant API calls.
- **Alternatives Considered**:
  - *Rely only on output redaction*: Rejected because preventing secrets from appearing in trace streams at the subprocess boundary is more secure.

## Data Model & Alembic Migration Plan

Add Alembic migration `009_governance_hardening.py` chained from `008_autonomous_orchestration`:
- Add column `is_mixed_authorship` (`Boolean`, `nullable=False`, `server_default=false`) to `reviews` table.
- Down revision: `008_autonomous_orchestration`.
- Alembic revision sequence identifier: `009_governance_hardening` (satisfies `alembic_version` varchar(32) limit). Note: `009` is the database migration sequence; the OpenSpec change number is `010`.
- Upgrades and downgrades are tested against disposable test databases.

## Risks / Trade-offs

- **[Risk]** Physical schema check adds a brief query on startup/admission.
  → **Mitigation**: Inspection runs a single lightweight SQL query against PostgreSQL table and column metadata before admitting a run.
- **[Risk]** Test safety guard blocks tests if developer forgets to set `MINIME_EXPECTED_DATABASE`.
  → **Mitigation**: Clear diagnostic error message in `ChecksRunner` and pytest fixture explaining exact required environment variables.
- **[Risk]** Reviewer missing-file validation could override a valid finding if OpenSpec tasks were underspecified.
  → **Mitigation**: Any file explicitly listed in OpenSpec tasks or specifications remains strictly required; only unreferenced/guessed names are validated against existing alternatives.
- **[Risk]** Git trace variable stripping might impede low-level Git debugging during development.
  → **Mitigation**: Trace variables are stripped only for authenticated subprocesses containing credential injection (`http.extraHeader`).

## Migration Plan

1. Create and apply Alembic migration `009_governance_hardening.py` on the disposable test database.
2. Verify all deterministic checks and unit/integration test suites pass.
3. Rollback strategy: `alembic downgrade -1` removes the `is_mixed_authorship` column cleanly.

## Autonomous Orchestration Execution Plan

This change is explicitly prepared as the first change to be executed via mini me's autonomous orchestration pipeline:
1. Operator creates durable ProjectBinding (`project_id ↔ silverberdi/mini-me ↔ the durable GitHub Issue bound to 010-governance-and-recovery-hardening ↔ 010-governance-and-recovery-hardening`).
2. Operator evaluates Definition of Ready (`minime readiness evaluate`), verifying:
   - Project registration is active;
   - Durable binding exists;
   - Remote GitHub Issue verification succeeds;
   - Physical schema preflight (tables + columns) succeeds;
   - Deterministic project checks are non-empty;
   - Primary implementer/reviewer capacity is available;
   - GitHub App runtime authority is healthy.
3. Operator initiates autonomous orchestration (`minime orchestrate start -p <project_id> -c 010-governance-and-recovery-hardening`).
4. mini me coordinates implementation, candidate freeze, complementary review, DeepSeek Direct audit, branch push, and PR preparation autonomously to the `READY_FOR_HUMAN_MERGE` gate.
