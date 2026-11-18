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
- Configured thinking workflow for a correctable feasibility report: **NOT VERIFIED**. Read-only inspection found no project rows and no provider-health/capacity rows in `minime_test`; therefore there is no persisted thinking profile or observable capacity decision to use. The local Codex CLI reports an authenticated session, but that alone does not establish a Mini Me project profile or its capacity/spending authorization. No profile was invented and no provider call was dispatched.

Task 5.2 remains open until that configured workflow can be exercised under the project's existing provider-capacity and authorization rules.
