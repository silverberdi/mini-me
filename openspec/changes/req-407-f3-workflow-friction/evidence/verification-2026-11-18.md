# Issue 407 verification evidence — 2026-11-18

## Candidate and scope

- Implementation candidate: `db6d7324526f1f04c5883e035c707d0be5e661ac`.
- Base: `9bc975cdcb9b7726170fad3e701603b781591296`.
- Verification ran from the dedicated Issue 407 worktree. The main checkout was not modified.

## Task 5.1 — focused and adjacent checks

- `PYTHONPATH=src pytest -q tests/test_f3_fail_closed_contracts.py tests/test_operator_gate_response_cli.py tests/test_two_phase_pr_and_closure.py tests/test_native_propose_lifecycle.py`: **89 passed, 3 failed**.
- The three failures were rerun at base `9bc975c` and reproduced there unchanged:
  - `test_verify_requires_native_final_response_channel`: legacy assertion expects `True`, while the current API returns `VerifyOutcome(status="COMPLETE", ...)`.
  - `test_apply_and_sync_fail_closed_on_agent_error`: test invokes durable DOC_CLOSING dispatch without the required durable stage context.
  - `test_explore_checkpoint_survives_reentry_without_paid_repeat`: fixture re-entry is rejected as an active/ambiguous stage invocation.
- `tests/test_human_gate_current_payload_postgres_e2e.py` against the server's disposable `minime_test` database through SSH: **5 passed**, one Starlette/httpx deprecation warning. The test cleans up its project/run/action rows.
- Ruff on changed Python files: **4 findings remain**. The same findings appear at base: unused `BudgetService` import in `api/app.py`, and in the autonomous CLI path an unsorted import block, unused `BudgetService`, and undefined `Any`. The candidate removes a separate unused `BudgetService` import from `request_run_cmd`; no assertions or lint rules were weakened.
- No mypy/pyright/type-check command is configured in `pyproject.toml` or the repository CI workflow. `python3 -m py_compile` passed for every changed Python file.
- `openspec validate req-407-f3-workflow-friction --strict --no-interactive`: **PASS**.
- `git diff --check 9bc975cdcb9b7726170fad3e701603b781591296..db6d7324526f1f04c5883e035c707d0be5e661ac`: **PASS**.

The three pytest failures and four remaining Ruff findings are recorded, not waived; the pytest failures were confirmed on the base candidate.

## Task 5.2 — real integration boundaries

- CLI gate response through PostgreSQL `OperatorActionRecord`: **PASS**, 5/5 tests on `minime_test`. This includes durable completion, replay idempotency, and prevention of duplicate dispatch; no persistent test rows remained.
- Native OpenSpec Archive CLI on an isolated fixture whose main spec already contained the synchronized requirement: `openspec validate --strict` **PASS**; `openspec archive -y issue-407-archive-fixture` exited **0**, reported “Specs already in sync,” removed the active Change, and created the dated archive. A separate invalid-spec fixture exited nonzero and preserved the active Change.
- Configured thinking workflow for a correctable feasibility report: **EXERCISED** using the persisted Mini Me `thinking` profile (`codex`, `gpt-5.6-luna`, `medium`) and the existing `CapacityLifecycleService`; its read-only preflight returned `RUN` and admission allowed. No scheduler, Run, or production row was changed. The real `CliAgentRunner` invoked the installed native Codex Propose skill for isolated fixture SHA `e49985329d79b016485f52f934ee4f2d3f43e070`, with the correctable diagnostic that task IDs did not cover native tasks. The structured response validated (`status=VALID`), and the task/scenario mapping blocker disappeared. The evaluator still returned `feasibility_status=BLOCKED` because the report introduced an unmet preview precondition, for which the fixture had no candidate-matched preview. That is a genuine unavailable capability, so fail-closed behavior was correct; no second corrective call was made. Structured response SHA-256: `0b160e237ba217e666d87e5762b791552924fc70277b761cb278f42267d946c0`.
- Two earlier real assessments on the full Issue 407 Change also remained blocked by unavailable preview evidence; one used Boxio's persisted thinking profile, and one used Mini Me's. They are not represented as successful corrections. The isolated fixture above tests only the correctable mapping boundary and keeps its genuine preview blocker visible.
- `minime_test` had no configured projects/provider-health rows before the PostgreSQL test; the test inserted and removed its own rows. Read-only post-test counts were `projects=0`, `operator_actions=0`, `runs=0`. The configured-thinking call used the existing Mini Me profile and live read-only capacity preflight because the disposable test database has no project profile.

Task 5.2 is complete: all three integration boundaries were exercised with their real authorities, including the configured thinking profile and real capacity preflight. The thinking assessment's evidence blocker remains recorded as its result; completion of this verification task does not claim the synthetic fixture was executable or create a preview.
