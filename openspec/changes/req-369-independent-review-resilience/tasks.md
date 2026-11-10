## 1. Reviewer Prompt & Diff Hygiene

- [x] 1.1 Invert prompt composition in `src/minime/services/orchestration_coordinator.py` (`_run_code_review` and `_run_propose_review`) to mandate Verdict-First structured JSON as the immediate first line of output before narrative notes.
- [x] 1.2 Add pathspec exclusions in `_run_code_review` git diff extraction to filter out lockfiles (`package-lock.json`, `poetry.lock`, `pnpm-lock.yaml`, `yarn.lock`).
- [x] 1.3 Ensure `_run_code_review` diff base resolves against the remote ancestor commit (`merge-base`) when `base_sha` is `"main"`.

## 2. Failure Diagnostic Observability

- [x] 2.1 Update `_run_code_review` and review error handlers to capture raw response prefix and suffix (first/last 500 characters) upon `MalformedReviewOutputError` and persist them under `stop_details["code_review"]["raw_diagnostic"]`.
- [x] 2.2 Surface `raw_diagnostic` in the review pause message and log stream so operators see the exact failure pattern without server-side shell access.

## 3. Test Verification & Regression Protection

- [x] 3.1 Add unit tests proving that responses with verdict-first JSON followed by truncated text parse successfully.
- [x] 3.2 Add unit tests verifying that lockfiles are excluded from review diff commands.
- [x] 3.3 Add unit tests verifying that `raw_diagnostic` is captured and attached to `stop_details` when the reviewer emits an unparseable response.
- [x] 3.4 Execute full test suite `pytest tests/` ensuring 100% green without regressions.
