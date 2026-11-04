## Why

Apply/Verify currently invokes `pytest -q` for the whole repository. Unrelated pre-existing failures can therefore block an otherwise valid change, and every retry pays the cost of running the same unrelated tests. Issue #264 asks mini me to run the tests connected to the candidate change while preserving observable test evidence.

## What Changes

- Replace whole-suite execution in `_run_automated_tests` with test selection derived from candidate files changed by the OpenSpec change and the change's own tests.
- Define and document a bounded test-to-code mapping, including its fallback and limits, so selection is relevant without expanding to the complete suite.
- Build direct-import mappings in one pass over test files using an inverse module-to-tests index, avoiding repeated AST parsing as changed modules grow.
- Preserve the exact selected command, exit status, and runner output as coordinator-observed evidence.
- Keep full-suite execution in the project's CI/CD before merge, outside mini me.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-apply-and-verify`: require change-scoped automated test selection and observable command/result evidence during Apply/Verify instead of requiring the complete project suite.

## Impact

- `src/minime/services/orchestration_coordinator.py`, specifically `_run_automated_tests` and its existing call path.
- Focused coordinator tests covering selection, scope isolation, and captured evidence.
- The `openspec-native-apply-and-verify` delta spec. No CI/CD implementation or other stage changes are included.
