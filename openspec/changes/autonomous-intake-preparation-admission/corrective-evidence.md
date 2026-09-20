# Admission policy corrective evidence

Fixed the project creation API to forward all three admission policy settings.
ProjectService and API request models now reject invalid boolean flags and
non-positive or non-integer concurrency limits before changing project state.
Defaults remain true, true, and 1. Null/omitted update fields preserve existing values.

Verification:
- pytest -q tests/test_project_admission_policy_validation.py tests/test_autonomous_intake_admission.py tests/test_project_registry.py --basetemp=.test-tmp/policy-final: 33 passed.
- Ruff checks on both modified source files and the new test file: passed.
- git diff --check: passed.

New tests exercise API request models and the creation handler directly, including
persistence of explicit settings and rejection before mutation. HTTP TestClient
execution stalled and was interrupted. These checks do not establish live
PostgreSQL, PWA/TUI, or full end-to-end acceptance. Independent review, audit, and
applicable human validation remain outstanding. Existing task checkboxes were
not newly certified by this corrective pass.
