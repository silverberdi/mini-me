## Why

In Multiplo Issue #4 independent code review, the DeepSeek reviewer produced a valid, substantive `CHANGES_REQUIRED` JSON verdict containing CSS code blocks and braces within finding fields (`violated_requirement`). However, `review_verdict_parser.py` utilized a regex (`\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}`) supporting at most one level of nesting, which mistakenly partitioned the JSON text when encountering CSS braces (`{ display: flex; }`), dropping the root `"verdict"` and failing with `invalid_response: No structured verdict payload found in reviewer output`.

Now that lockfile filtering and verdict-first prompt order guarantee complete, non-truncated JSON output from DeepSeek, the parser must use Python's standard library `json.JSONDecoder().raw_decode` to robustly extract root verdict payloads of arbitrary nesting depth, escaped quotes, and embedded curly braces without false syntax rejections.

## What Changes

- Modify `src/minime/services/review_verdict_parser.py` to extract candidate JSON payloads using `json.JSONDecoder().raw_decode` from both fenced codeblocks and raw text boundaries, eliminating the single-nesting regex limitation.
- Ensure that JSON payloads containing nested objects, arrays, and string literals with curly braces (`{ ... }`) are parsed faithfully as authoritative `ReviewVerdictPayload`.
- Preserve strict ambiguity checking and fail-closed safety: if no valid verdict payload exists or conflicting verdicts are present, raise `MalformedReviewOutputError`.

## Capabilities

### Modified Capabilities
- `structured-review-verdict`: The parser MUST robustly extract root review verdicts containing arbitrary nesting depth, multiline arrays, and nested braces within string literals.

## Impact

- `src/minime/services/review_verdict_parser.py`: Implementation of `parse_review_verdict`.
- `tests/test_review_verdict_parser.py`: Comprehensive regression tests with CSS code literals, multiple findings, and markdown narrative suffixes.
