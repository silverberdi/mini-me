## Context

See `proposal.md` for motivation. Currently, `NativeOrchestrationCoordinator._run_code_review` and `_run_propose_review` generate review prompts that place schema hints and output requests at the bottom of the prompt after the diff. When reviewing changes with 2,000+ lines or multiple files, LLMs exhaust their output token quota (e.g. 4,096 tokens on DeepSeek) while emitting preliminary file-by-file commentary, resulting in truncated responses without any JSON verdict block. Furthermore, raw diffs generated with `git diff HEAD~1..HEAD` indiscriminately include large package lockfiles (`package-lock.json`), and local tracking branches that are behind remote branches cause diff accumulation.

## Goals / Non-Goals

**Goals:**
- Guarantee structured verdict receipt in the first ~200 output tokens by mandating Verdict-First JSON formatting.
- Bound review diff payloads by omitting non-code lockfiles and binary noise.
- Ensure the diff base resolves cleanly against the remote tracking base commit (`merge-base`).
- Capture diagnostic raw snippets in `stop_details` and logs on parser failure for transparent operator visibility.

**Non-Goals:**
- Modifying the underlying LLM provider APIs or increasing provider output token ceilings.
- Altering the semantic verdict schema (`READY_TO_MERGE`, `CHANGES_REQUIRED`, findings attributes).
- Changing the primary implementer workflow or test execution mechanisms.

## Decisions

### Decision 1: Verdict-First Prompt Composition
- **Choice**: The review prompt explicitly orders: *"Emite tu veredicto JSON INMEDIATAMENTE como tu primera línea de salida: `{"verdict": ..., "summary": ..., "findings": [...]}`. Si agregas análisis o notas, hazlo DESPUÉS del bloque JSON."*
- **Rationale**: Output tokens are generated sequentially. Placing the structured verdict at the start guarantees that even if a model exceeds its token limit or truncates midway through later commentary, the critical structured payload is already fully transmitted and parseable.
- **Alternatives considered**:
  - *Hard character cap in prompt ("no más de 4000 caracteres")*: Rejected; LLMs generate token-by-token and do not count downstream characters, ignoring negative length constraints when faced with complex multi-file diffs.
  - *Two-step review (summary first, verdict later)*: Rejected; adds unnecessary latency, round-trips, and cost.

### Decision 2: Diff Lockfile and Noise Filtering
- **Choice**: Pass pathspec exclusions to git diff in `_run_code_review`:
  `git diff <base>..<candidate> -- . ":!package-lock.json" ":!poetry.lock" ":!pnpm-lock.yaml" ":!yarn.lock"`
- **Rationale**: Lockfiles contain thousands of lines of machine-generated dependency hashes and metadata. They consume tens of thousands of prompt tokens without offering substantive logic for review.
- **Alternatives considered**:
  - *Diffing only files listed in git status*: More brittle than pathspec exclusion; pathspec exclusion directly leverages git's native filtering without extra subprocess calls.

### Decision 3: Remote Ancestor Base Resolution
- **Choice**: In `_run_code_review`, compute the diff base using `git merge-base origin/<base_branch> HEAD` or against the authoritative remote base SHA persisted in `run.base_sha`.
- **Rationale**: Prevents accidental inclusion of historical commits when local branches have not been fast-forwarded following GitHub PR merges.

### Decision 4: Failure Diagnostic Capture in `stop_details`
- **Choice**: When `parse_review_verdict` raises `MalformedReviewOutputError`, capture `raw_output[:500]` and `raw_output[-500:]` and attach them to `stop_details["code_review"]["raw_diagnostic"]`.
- **Rationale**: Surfaces immediately in the PWA dashboard and logs whether the response was cut off, empty, or contained invalid syntax, eliminating blind debugging.

## Risks / Trade-offs

- **[Risk]** Reviewer model might ignore Verdict-First and still output narrative text first.
  - **Mitigation**: `parse_review_verdict` already extracts fenced JSON code blocks (` ```json { ... } ``` `) anywhere in the text; Verdict-First simply ensures the block appears within the first 1,000 tokens rather than after token 4,096.
- **[Risk]** Excluded lockfiles might conceal security-sensitive dependency modifications.
  - **Mitigation**: Dependency additions remain fully observable in `package.json` / `pyproject.toml`, which are never excluded. Automated security audits and dependency bots handle lockfile vulnerability scanning.
