## 1. Domain Models & Database Migration

- [ ] 1.1 Add `is_mixed_authorship: bool = False` to `Review` domain model in `src/minime/domain/models.py` and `ReviewModel` in `src/minime/db/models.py`.
- [ ] 1.2 Create Alembic migration `009_governance_hardening.py` in `alembic/versions/` (down revision `008_autonomous_orchestration`, with revision identifier within 32 chars) adding `is_mixed_authorship` column to `reviews` table.
- [ ] 1.3 Update repository mapping in `src/minime/db/repository.py` (`PostgresReviewRepository` and `InMemoryReviewRepository`) to persist and retrieve `is_mixed_authorship`.

## 2. Review Governance & Missing-File Validation

- [ ] 2.1 Update `AuthorshipService` and `build_reviewer_prompt` in `src/minime/services/reviewer_contract.py` to evaluate whether the assigned reviewer authored surviving contributions in the CURRENT frozen candidate generation/SHA; if so, set `is_mixed_authorship = True` and inject explicit disclosure into the reviewer prompt payload; if the reviewer only authored discarded historical attempts, set `is_mixed_authorship = False`.
- [ ] 2.2 Update review execution in `src/minime/services/execution_pipeline.py` and `orchestration_service.py` to persist `is_mixed_authorship` flag and contribution evidence on the `Review` record.
- [ ] 2.3 Update `BlockerValidationService` in `src/minime/services/blocker_validation.py` and review verdict handling in `execution_pipeline.py` to cross-check reviewer missing-file blocker claims against explicit OpenSpec tasks/specs, the frozen `CandidateManifest`, the authoritative candidate tree at `candidate_sha`, and base..candidate diff, rejecting hallucinated/non-contractual names as false blockers while preserving real omissions.

## 3. Recovery & Provider Outcome Normalization

- [ ] 3.1 Update `OutcomeGovernanceService.classify_outcome` in `src/minime/services/outcome_governance.py` to map `ProviderResultClass.TRANSIENT_ERROR` (network errors, timeouts, connection resets, 502/503/504) deterministically to `ExecutionOutcome.ENVIRONMENT_UNAVAILABLE`.
- [ ] 3.2 Update `ContinuationEngine` in `src/minime/services/continuation_engine.py` to map `ExecutionOutcome.ENVIRONMENT_UNAVAILABLE` to `ContinuationDecision.WAIT_EXTERNAL`, and update `OrchestrationService` to transition to `OrchestrationStopOutcome.WAITING_EXTERNAL` without incrementing `corrective_retries_count` or `reassignment_count`.

## 4. RESUME Observability Idempotency

- [ ] 4.1 Update `OrchestrationService.resume()` in `src/minime/services/orchestration_service.py` to construct deterministic logical transition keys `{run_id}:RESUME:{resumable_stage}:{current_generation}` without timestamp jitter.
- [ ] 4.2 Ensure stage event recording checks for existing identical resume transition keys to prevent duplicate logical stage events during repeated restart/reconciliation cycles.

## 5. Physical PostgreSQL Schema Integrity & Test Safety

- [ ] 5.1 Implement `verify_physical_schema_invariants(engine)` in `src/minime/db/session.py` to inspect actual PostgreSQL physical tables AND required columns derived from authoritative SQLAlchemy metadata (`Base.metadata`), explicitly verifying `reviews.is_mixed_authorship`.
- [ ] 5.2 Integrate physical schema verification into `admit_change()` in `orchestration_service.py` and `readiness_service.py`, failing closed with structured error `SCHEMA_INVARIANT_VIOLATION` if `alembic_version` is at head but application tables or required columns are missing, without automatic repair.
- [ ] 5.3 Update `ChecksRunner.run()` in `src/minime/services/checks_runner.py` to sanitize subprocess environment by removing `MINIME_DATABASE_URL` and `MINIME_EXPECTED_DATABASE` by default; for checks declaring disposable PostgreSQL intent (`disposable_postgres: true`), validate that target DB != `minime`, expected DB is non-empty, and actual DB == expected DB, failing closed before subprocess execution if invalid.
- [ ] 5.4 Maintain disposable test database validation in `tests/conftest.py` as defense in depth.

## 6. Provider Health CLI Presentation & GitHub App Hardening

- [ ] 6.1 Fix `providers_health_cmd` (`minime providers health`) in `src/minime/cli/main.py` and `ProviderHealthService` in `src/minime/services/provider_health_service.py` to resolve capacity reset timestamps and retry-after durations from `CapacityWindowRepository` without attribute errors.
- [ ] 6.2 Update `GitHubAdapter._run_git()` in `src/minime/adapters/github.py` to strip ambient Git trace environment variables (`GIT_TRACE`, `GIT_TRACE_PACKET`, `GIT_TRACE_CURL`, `GIT_CURL_VERBOSE`, `GIT_TRANSPORT_TRACE`) before authenticated Git subprocess execution.
- [ ] 6.3 Remove redundant standalone `verify_repository` API calls across the runtime, ensuring repository proof is derived authoritatively from `validate_issue_binding`.

## 7. Verification & Regression Testing

- [ ] 7.1 Add unit tests in `tests/test_mixed_authorship_review.py` verifying:
  - Reviewer authored surviving candidate material -> `is_mixed_authorship = True`
  - Reviewer had earlier discarded attempt only -> `is_mixed_authorship = False`
  - No reassignment -> `is_mixed_authorship = False`
- [ ] 7.2 Add unit tests in `tests/test_missing_file_validation.py` verifying:
  - Required unchanged base file present in candidate tree -> no false blocker
  - Explicitly required file absent from candidate tree -> valid blocker
  - Guessed/convention-based filename absent -> false blocker
- [ ] 7.3 Add unit tests in `tests/test_transient_provider_outcome.py` verifying:
  - `ProviderResultClass.TRANSIENT_ERROR` maps to `ExecutionOutcome.ENVIRONMENT_UNAVAILABLE`
  - Continuation engine maps to `ContinuationDecision.WAIT_EXTERNAL` and `OrchestrationStopOutcome.WAITING_EXTERNAL`
  - Corrective retry and reassignment counters are NOT incremented
- [ ] 7.4 Add unit tests in `tests/test_resume_idempotency.py` verifying deterministic RESUME transition key idempotency across repeated restarts without duplicate events.
- [ ] 7.5 Add integration tests in `tests/test_schema_integrity.py` verifying:
  - Migration head + missing table -> fails admission with `SCHEMA_INVARIANT_VIOLATION`
  - Migration head + missing required column -> fails admission with `SCHEMA_INVARIANT_VIOLATION`
  - Valid physical schema -> passes preflight
- [ ] 7.6 Add regression tests in `tests/test_checks_runner_db_safety.py` verifying:
  - Production `ChecksRunner` sanitizes candidate check environment by default
  - Check targeting canonical `minime` DB fails closed immediately
  - Check with mismatched expected DB name fails closed immediately
  - Verified disposable DB check executes successfully
- [ ] 7.7 Add CLI tests in `tests/test_provider_health_cli.py` verifying `minime providers health` displays reset hints cleanly from capacity windows without crashing.
- [ ] 7.8 Add unit tests in `tests/test_git_trace_sanitization.py` verifying Git trace variable sanitization before authenticated Git subprocesses.
- [ ] 7.9 Run full deterministic test suite with pytest against disposable database (`minime_010_verify`) and ensure all checks pass.
