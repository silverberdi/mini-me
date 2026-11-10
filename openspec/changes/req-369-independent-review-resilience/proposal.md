## Why

During independent code review of large candidates, the reviewer model (such as DeepSeek) can exhaust its fixed completion token ceiling (4,096 tokens) while performing file-by-file narrative commentary. Because the review prompt previously positioned the structured JSON verdict block at the end of the response, token cutoffs resulted in truncated output lacking any parseable verdict. Furthermore, inclusion of non-code artifacts like `package-lock.json` and stale local Git tracking branches inflated diffs past context boundaries. This change hardens the independent review protocol by placing the structured verdict first, filtering non-code diff noise, and recording raw diagnostic payloads upon parsing failures.

## What Changes

- **Verdict-First Review Protocol**: Update code and proposal review prompts to strictly mandate that the JSON verdict block (`{"verdict": ..., "summary": ..., "findings": [...]}`) be emitted immediately as the very first line of output, before any narrative remarks.
- **Diff Noise Filtering**: Exclude lockfiles (`package-lock.json`, `poetry.lock`, `pnpm-lock.yaml`, `yarn.lock`) from code review diff generation to protect the model's context token window.
- **Merge-Base Sincronization**: Anchor candidate diff computations to the remote immutable ancestor (`git merge-base origin/main HEAD` or resolved remote base branch) to avoid inflating diffs with historical commits from stale local branches.
- **Failure Telemetry & Observability**: Persist the raw response prefix and suffix (first/last 500 characters) in `stop_details` and log streams when `MalformedReviewOutputError` occurs, enabling immediate operator diagnosis without speculative patching.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `reviewer-execution-contract`: Requires that independent reviewer prompt compositions instruct verdict-first JSON emission, lockfile exclusion from review diffs, and remote merge-base alignment.
- `structured-review-verdict`: Expands failure handling to capture and durably persist diagnostic fragments (prefix/suffix) of unparseable reviewer output for immediate UI and operational observability.

## Impact

- Modifies `src/minime/services/orchestration_coordinator.py` (`_run_code_review`, `_run_propose_review`, diff generation, and review error handling).
- Improves stability and token efficiency for all high-complexity changes reviewed by external LLMs via `opencode` or direct APIs.
- No breaking schema changes to database tables; persists diagnostics within existing `stop_details` JSON columns.
