## Why

During the end-to-end autonomous validation of R01 (`parse-normalized-tags`), mini me successfully delivered a complete lifecycle from canonical intake through to GitHub Draft PR #4 stopped at `READY_FOR_HUMAN_MERGE`. However, that real operational run exposed critical efficiency, resilience, and operational bottlenecks:

1. **Massive Token Bloat in CODE_REVIEW (~100k input tokens)**: `DeepSeekCodeReviewService._read_exact_candidate` serialized all 55 tracked repository files into the review payload—including ~373 KB of static OpenSpec agent workflow manuals—when the actual code diff and tests were under 5 KB (~1,500 tokens).
2. **Fragility to Transient Socket Disconnections (3+ hours of idle wait)**: A connection drop (`read tcp ... connection reset by peer`) during an SSE stream halted the execution loop until manual operator retry, exposing the lack of transport-level retry with backoff and durable independence from interactive supervisory sessions.
3. **Absence of an Intelligent Progress Watchdog**: The system lacks an activity and progress watchdog capable of distinguishing legitimate extended reasoning or test execution from silent hung processes or repetitive loop stagnation, while rigid timeouts risk aborting complex implementations prematurely.
4. **Sub-optimal First-Pass Implementer Convergence (4 attempts for a simple change)**: The native apply dispatch did not enforce atomic delivery (code, tests, checks, tasks) on the first pass, requiring avoidable reconciliation cycles.
5. **Coarse Operational Telemetry**: Metrics do not yet isolate waiting, inference, active work, recovery overhead, and orchestrator transitions with granular accounting.

This change delivers a hardened, context-efficient, and resilient runtime evolution that eliminates redundant context and repetitive cycles, tolerates network interruptions, detects genuine stalls, and tracks fine-grained operational metrics while strictly preserving all existing lifecycle, safety, candidate integrity, and human-merge guarantees.

## What Changes

- **Context-Efficient Independent Code Review**: Evolve `DeepSeekCodeReviewService` and `_read_exact_candidate` to build the review payload from the candidate's exact git diff against `base_sha`, accompanied by the full content of only modified, newly created, and deleted files, along with the active change specifications. Maintain full-tree candidate identity and manifest hash verification in the database. Ensure security-relevant directories (`.agent/`, `.agents/`, `.openspec/`, permissions, configuration) are dynamically included whenever modified by the candidate.
- **Durable Network Resilience & Session Independence**: Introduce a resilient HTTP/SSE transport wrapper with exponential backoff, jitter, and `Retry-After` adherence for transient errors (connection drops, 429, 502/503/504). Distinguish pre-send failures from uncertain post-send outcomes; never re-dispatch uncertain inferences without prior durable reconciliation. Decouple daemon orchestration execution from the interactive lifecycle of supervisory sessions, preserving progress across disconnection.
- **Intelligent Progress & Loop Watchdog**: Replace blind wall-clock timeouts with a multi-signal activity watchdog (`RUNNING → SUSPECTED_STALL → STALLED → RECOVERY`). Monitor tool invocations, stdout/stderr activity, and disk mutations to detect frozen sub-processes, while detecting infinite loops via repetitive blocker fingerprints and zero-diff streaks. Allow extended reasoning when legitimate forward progress is observed.
- **Atomic First-Pass Implementer Convergence**: Update native OpenSpec apply dispatch instructions in `native_openspec_apply.py` to establish a clear contract: functional implementation, test suite authoring, deterministic test execution, and `tasks.md` checkbox updates in a single pass. Provide precise, evidence-based correction prompts for subsequent attempts without discarding valid progress.
- **Granular Operational Observability & Performance Accounting**: Record structured, stage-by-stage operational metrics (admission, contract review, apply execution, test checks, code review, candidate freeze, PR publishing) capturing active duration, wait duration, transport delays, token usage, and remediation causes, persisted durably without external UI dependencies.

## Capabilities

### New Capabilities

- `durable-network-resilience`: Transport-level resilient HTTP/SSE retries with exponential backoff, jitter, and Retry-After adherence, combined with orchestrator session independence ensuring continuous execution across supervisor disconnection.
- `intelligent-progress-and-loop-watchdog`: Multi-signal activity and progress watchdog distinguishing legitimate extended execution from hung processes, repetitive loops, and unrecoverable failures.
- `operational-observability-and-performance-accounting`: Granular backend accounting of duration, token consumption, transport stalls, and attempt attribution across all orchestration stages.

### Modified Capabilities

- `reviewer-execution-contract`: Context-efficient review payload construction based on exact candidate diff and affected files, maintaining full manifest integrity verification and ensuring security-critical policy changes are never omitted.
- `primary-implementer-execution`: Unified first-pass implementation directives (code, tests, checks, tasks) in native apply dispatch and structured recovery feedback preserving valid incremental progress.

## Impact

- **Affected Code**: `src/minime/services/deepseek_code_review_service.py`, `src/minime/adapters/provider_adapter.py`, `src/minime/services/implementer_runner.py`, `src/minime/services/native_openspec_apply.py`, `src/minime/services/execution_pipeline.py`, `src/minime/services/orchestration_service.py`, `src/minime/services/continuation_engine.py`, and operational telemetry tables/events.
- **APIs & Dependencies**: No new external cloud dependencies. Uses standard `asyncio` subprocess monitoring, `httpx` transport hooks / backoff logic, and existing PostgreSQL event logging.
- **Security & Integrity**: Full candidate manifest hash (`manifest_hash`) remains strictly computed over the entire candidate repository tree. Review payload reduction is strictly presentation-level for the external LLM auditor.
- **Budget & Ledger**: Idempotency keys protect all retried requests against duplicate budget ledger entries or duplicate reservations. Uncertain outcomes are preserved as unresolved exposure.
- **Scope Boundaries**: Backend and daemon runtime only. No changes to PWA/SPA UI, no production scheduler activation, no N01 modification, and no bypass of mandatory human merge.
