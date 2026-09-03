# Tasks: 018.2 — Autonomous End-to-End Execution

- [x] 1. Archive 018.1 change and synchronize delta specs to main specs <!-- id: 18.2.1 -->
  - Verify 018.1 archived under `openspec/changes/archive/2026-09-02-018.1-provider-efficiency-reviewer-independence-hardening/`.
  - Verify delta specs copied to `openspec/specs/`.

- [x] 2. Synchronize physical schema invariant preflight with Alembic head 016 <!-- id: 18.2.2 -->
  - Update `verify_physical_schema_invariants` in `src/minime/db/session.py` to `016_provider_efficiency_telemetry`.
  - Update schema integrity unit test in `tests/test_schema_integrity.py`.

- [x] 3. Enhance execution pipeline remediation context formatting <!-- id: 18.2.3 -->
  - Propagate review findings, audit findings, and check failure snippets into `ExecutionPipelineService` prompt context.
  - Verify structured findings are rendered cleanly in corrective prompts.

- [x] 4. Harden autonomous driver and state machine transitions <!-- id: 18.2.4 -->
  - Verify all 15 stages progress autonomously without manual supervisor intervention.
  - Verify remediation re-entry paths (`CHECKS_FAILED`, `REVIEW_REMEDIATION`, `AUDIT_REMEDIATION`).
  - Verify terminal stop at `READY_FOR_HUMAN_MERGE`.

- [x] 5. Verify and clean up test suite and linting <!-- id: 18.2.5 -->
  - Fix unused imports in tests and ensure `ruff check .` passes cleanly with 0 errors.
  - Run full test suite with `pytest` and verify all tests pass.

- [x] 6. Bootstrap 018.2 GitHub Issue and Project Item <!-- id: 18.2.6 -->
  - Create Issue for 018.2 on `silverberdi/mini-me`.
  - Add Issue to GitHub Project #2.
  - Verify DoR via `ReadinessService`.

- [ ] 7. Perform independent complementary review and DeepSeek audit on 018.2 <!-- id: 18.2.7 -->
  - Perform complementary review against OpenSpec contract.
  - Perform DeepSeek Direct audit on frozen candidate.
  - Create PR and perform pre-authorized merge.

- [ ] 8. Execute real bounded autonomous proving run <!-- id: 18.2.8 -->
  - Bootstrap a real bounded work item (GitHub Issue + Project item + OpenSpec + binding + READY).
  - Run `mini me` autonomously to execute the complete pipeline to `READY_FOR_HUMAN_MERGE`.
  - Verify all 8 hard efficiency gates and self-hosting >= 75%.
