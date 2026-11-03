## Why

The independent code reviewer currently receives only the first 4,000 characters of the candidate diff and a generic review request. This can hide relevant changes and encourage repeated, non-blocking findings; the proposal-review fix in PR #255 provides the established convergence pattern to apply here.

## What Changes

- Include the complete candidate diff in the existing code-review prompt.
- Direct the reviewer to report only substantive correctness, security, or scope defects, with explicit BLOCKER, MAJOR, and MINOR meanings.
- Tell the reviewer not to re-flag requirements already covered or request wording or formatting changes.
- Preserve the existing read-only reviewer invocation, verdict schema, and native workflow behavior.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-native-apply-and-verify`: clarify convergence criteria for independent implementation code review.

## Impact

- `src/minime/services/orchestration_coordinator.py`: the prompt and diff content assembled by `_run_code_review`.
- Focused tests for the code-review prompt, including complete diff delivery and convergence guidance.
- No API, dependency, OpenSpec workflow invocation, or other pipeline-stage changes.
