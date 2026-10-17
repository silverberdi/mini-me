## Context

The R01 autonomous validation on `parse-normalized-tags` proved that mini me can coordinate the complete development lifecycle (Intake → Admission → CONTRACT REVIEW → Native APPLY → Deterministic Checks → CODE REVIEW → Freezing → Draft PR #4 → READY_FOR_HUMAN_MERGE) without human intervention in implementation.

However, the real runtime execution revealed that:
1. `DeepSeekCodeReviewService._read_exact_candidate` in [src/minime/services/deepseek_code_review_service.py](file:///Users/silveriobernal/Documents/Code/Development/mini-me/src/minime/services/deepseek_code_review_service.py#L604-L636) iterated through all tracked files in `manifest.tracked_files`. In a repository with OpenSpec agent tooling (`.agent/`, `.agents/`), 373 KB (over 100k tokens) of static instruction markdown was uploaded to the DeepSeek Direct API for every review invocation, incurring unnecessary latency and risk of exceeding context windows.
2. A transient socket reset (`read tcp ... connection reset by peer`) during an SSE stream paused the execution loop for 3 hours awaiting manual operator recovery. The daemon lacked a transport-level retry layer with exponential backoff and was coupled to the supervisor terminal session.
3. The execution pipeline relies on rigid time limits or basic streaks without an activity-aware watchdog to distinguish between an implementer actively computing or running tests vs. a deadlocked process or repetitive loop.
4. The implementer required 4 attempts because native apply dispatch did not enforce a single-pass contract (code, tests, checks, tasks) and initial prompts lacked clear evidence expectations.
5. Telemetry lacked granular attribution of stage durations, waiting times, and transport stalls.

## Goals / Non-Goals

**Goals:**
- Reduce input tokens for `CODE_REVIEW` by >90% (to <5,000 tokens for standard changes) while maintaining strict candidate manifest hash validation in PostgreSQL and full visibility into modified security, policy, or configuration files.
- Introduce an HTTP/SSE transport wrapper with exponential backoff, jitter, and Retry-After adherence, classifying retriable vs. non-retriable failures and preserving uncertain post-send outcomes.
- Decouple daemon orchestration execution from supervisory terminal sessions so runs continue reliably across operator disconnects.
- Implement an activity and loop watchdog (`RUNNING → SUSPECTED_STALL → STALLED → RECOVERY`) based on multi-signal heartbeats (I/O, tool calls, worktree mutations) that protects long-running tasks while aborting confirmed deadlocks or repetitive loops.
- Deliver an atomic first-pass apply prompt harness that instructs the implementer to deliver code, tests, checks, and task checkoffs in a single pass, with evidence-based retry feedback on partial progress.
- Record structured operational metrics capturing stage durations, transport pauses, and token usage.

**Non-Goals:**
- No changes to PWA/SPA UI or frontend components.
- No alteration of provider hierarchy (Codex/Antigravity as primaries, DeepSeek Direct as independent reviewer, OpenRouter as quota rescue only).
- No automatic merge; human merge remains mandatory in MVP.
- No activation of the production scheduler or modification of production environments (N01).
- No rewrite of the core state machine; changes build directly on existing models, tables, and services.

## Decisions

### Decision 1: Selective Diff-Based Review Payload while Preserving Full-Tree Manifest Hashing
- **Approach**: In `DeepSeekCodeReviewService._read_exact_candidate`, compute the candidate manifest over the entire repository tree as required for immutable integrity (`manifest_hash` in PostgreSQL), but construct the JSON `files` payload sent to the LLM reviewer selectively:
  - Include the complete `git diff` between `base_sha` and `candidate_sha`.
  - Include the full content of only modified, newly added, and deleted files.
  - Include the active OpenSpec change specifications (`openspec/changes/<change>/`).
  - Dynamically include any files modified in `.agent/`, `.agents/`, `.openspec/`, permissions, or configuration paths to guarantee that security or workflow alterations are never hidden from the reviewer.
- **Alternatives Considered**:
  - *Diff-only payload*: Omits full context of new/modified files, impairing static analysis by the LLM.
  - *Hard exclusion of `.agent/`*: Dangerous, because an adversarial or buggy candidate modifying agent instructions or security policies would evade review.
  - *Status quo (full tree upload)*: Wastes 100k tokens per review and risks context window exhaustion.

### Decision 2: Transport-Level Exponential Backoff with Pre-Send vs. Post-Send Distinction
- **Approach**: Wrap provider client calls (DeepSeek Direct, Google Cloud Code PA, OpenAI) with a resilient transport handler:
  - Automatically retry pre-send connection drops, socket resets, and transient HTTP status codes (429, 502, 503, 504) with exponential backoff (e.g. 1s, 2s, 4s, 8s + random jitter) respecting `Retry-After`.
  - Distinguish pre-send transport failures (safe to retry) from post-send uncertain outcomes. If a request was transmitted and the socket dropped during response streaming without receipt of a terminal payload, do NOT blind-retry. Preserve the reservation as `UNKNOWN`/`AMBIGUOUS` and require reconciliation to prevent duplicate billing and side effects.
  - Permanent client errors (400, 401, 403, invalid response JSON) fail immediately without retry.
- **Alternatives Considered**:
  - *Blind automatic retry for all errors*: Violates economic policy and can cause duplicate charges on paid providers.
  - *Manual intervention on every network blip*: Caused the 3-hour delay during R01.

### Decision 3: Progress Watchdog (Heartbeat + Loop Streak) over Blind Wall-Clock Timeout
- **Approach**: In `ImplementerRunner` and `DarwinSandbox`, replace rigid timeouts with a stateful watchdog:
  - Track `last_activity_at` via child process stdout/stderr emissions, tool execution events, and filesystem write timestamps in the candidate worktree.
  - If inactive for 3 minutes, transition to `SUSPECTED_STALL` and perform non-destructive diagnostic polling (checking whether worker threads are actively consuming CPU).
  - If inactive for 5 minutes with zero CPU/IO activity, mark `STALLED` and cleanly terminate the process group with diagnostic `WATCHDOG_HANG_TERMINATED`.
  - If repetitive failure fingerprints occur (`same_blocker_fingerprint_streak >= 3`) or files are modified without net diff progress, trigger loop diversion.
  - If an implementer is actively running a 15-minute test suite and producing output or disk writes, the watchdog resets its timer and allows it to proceed.
- **Alternatives Considered**:
  - *Fixed 10-minute timeout*: Terminates legitimate complex tasks prematurely.
  - *No timeout*: Risks indefinite hangs if a sub-process deadlocks on an unhandled socket or lock.

### Decision 4: Unified Atomic Apply Prompt Harness & Evidence-Targeted Remediation Feedback
- **Approach**: In `src/minime/services/native_openspec_apply.py`:
  - Provide an explicit execution directive in the initial dispatch: *"In this single execution pass, you must: (1) implement functional code in src/, (2) write comprehensive tests in tests/, (3) run pytest and verify exit code 0, and (4) update tasks.md marking completed tasks [x]."*.
  - Enforce that task checkoffs in `tasks.md` are rejected by `VerifyGate` and `LightweightReconciliationService` if not accompanied by functional code changes.
  - On retry, provide structured feedback indicating exact missing pieces (e.g., "Code implemented and passing tests, but task 1.2 in tasks.md is unchecked" or "Tests failed with exit code 1: <trace>").
- **Alternatives Considered**:
  - *Generic re-prompts*: Wasted 4 attempts during R01.

### Decision 5: Operational Performance Accounting via Existing PostgreSQL Models
- **Approach**: Leverage `orchestration_stage_events`, `job_attempts`, and `evidence_diagnostics` to store structured timing metrics:
  - Record `stage_duration_ms`, `active_compute_ms`, `wait_duration_ms`, and `transport_retry_count`.
  - Link token consumption (`prompt_tokens`, `completion_tokens`, `amount_usd`) explicitly to run, job, and stage.
- **Alternatives Considered**:
  - *External monitoring infrastructure (Prometheus/Grafana)*: Unnecessary operational overhead for personal single-installation orchestrator.

## Risks / Trade-offs

- **[Risk] Reviewer misses context from unmodified related files** → *Mitigation*: The candidate git diff highlights all changes; all modified/new files are sent in full; active change specs define behavioral requirements; and if the candidate modifies any configuration or policy file, it is automatically included.
- **[Risk] Post-send network drop leaves reservation unresolved** → *Mitigation*: Existing budget ledger preserves exposure as `UNRESOLVED` rather than creating duplicate charges, maintaining economic policy integrity.
- **[Risk] Watchdog misidentifies slow CPU-bound compilation as a hang** → *Mitigation*: The watchdog checks process CPU consumption before transitioning from `SUSPECTED_STALL` to `STALLED`.

## Migration Plan

1. Implement selective review payload in `DeepSeekCodeReviewService` and verify unit tests with simulated full repositories.
2. Implement resilient HTTP transport wrapper in provider adapters with mock connection reset tests.
3. Integrate progress watchdog into `ImplementerRunner` with synthetic hang and long-process tests.
4. Update native apply dispatch templates in `native_openspec_apply.py` and test convergence.
5. Verify end-to-end integration with strict OpenSpec validation and disposable PostgreSQL tests.
6. Rollback strategy: Purely code-level changes; standard git revert restores previous behavior if regressions occur.
