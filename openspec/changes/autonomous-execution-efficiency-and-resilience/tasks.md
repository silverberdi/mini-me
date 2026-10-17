## 1. Context-Efficient Independent Code Review

- [ ] 1.1 Evolve `DeepSeekCodeReviewService._read_exact_candidate` to build review files payload from candidate `git diff` against `base_sha` and full content of only modified/added/deleted files and active change specs.
- [ ] 1.2 Implement unconditional inclusion logic for security-critical paths (`.agent/`, `.agents/`, `.openspec/`, permissions, configuration) whenever touched by the candidate.
- [ ] 1.3 Preserve full-tree candidate identity, manifest generation, and `manifest_hash` database verification in `CandidateManifestService`.
- [ ] 1.4 Add unit tests verifying review payload exclusion of unchanged static documentation files and prompt token reduction under 5,000 tokens for standard fixtures.
- [ ] 1.5 Add adversarial tests ensuring modified security policies or instructions in `.agent/` are never omitted from review payloads.

## 2. Durable Network Resilience & Session Independence

- [ ] 2.1 Implement resilient HTTP/SSE transport wrapper with exponential backoff, random jitter, and `Retry-After` adherence in provider adapters.
- [ ] 2.2 Classify retriable transport errors (`ConnectionResetError`, socket disconnects, 429, 502/503/504) versus non-retriable client errors (400, 401, 403, invalid JSON schema).
- [ ] 2.3 Implement pre-send versus post-send outcome classification, preserving uncertain in-flight requests as `UNKNOWN` exposure without duplicate billing dispatch.
- [ ] 2.4 Verify daemon orchestration runs execute independently of supervisory terminal/client connections and survive disconnects cleanly.
- [ ] 2.5 Add unit and integration tests simulating transport socket drops and verifying automatic retry recovery and ledger idempotency.

## 3. Intelligent Progress & Loop Watchdog

- [ ] 3.1 Implement multi-signal activity tracker in `ImplementerRunner` observing subprocess stdout/stderr, tool calls, and filesystem write events.
- [ ] 3.2 Implement watchdog state machine progression (`RUNNING → SUSPECTED_STALL → STALLED → RECOVERY`) with non-destructive process polling.
- [ ] 3.3 Implement loop and stagnation detection tracking `same_blocker_fingerprint_streak >= 3` and zero-diff file edits across sub-iterations.
- [ ] 3.4 Implement clean subprocess group termination (SIGTERM/SIGKILL) and diagnostic logging on confirmed deadlocks.
- [ ] 3.5 Add tests verifying complex active long-running tasks are protected while true hung processes and repetitive loops are terminated.

## 4. First-Pass Implementer Convergence

- [ ] 4.1 Update native OpenSpec apply prompt harness in `native_openspec_apply.py` to enforce atomic delivery (code, tests, checks, tasks) in a single pass.
- [ ] 4.2 Enforce task completion validation in `VerifyGate` and `LightweightReconciliationService` rejecting checkbox-only updates lacking functional code evidence.
- [ ] 4.3 Implement structured, evidence-based retry prompts for partial progress that retain valid code and highlight specific test/task gaps.
- [ ] 4.4 Add tests validating rejection of checkbox-only pseudocode implementations and verifying targeted remediation dispatch.

## 5. Operational Observability & Performance Accounting

- [ ] 5.1 Add discrete stage duration tracking (admission, contract review, apply, checks, code review, freeze, PR preparation) to orchestration events.
- [ ] 5.2 Attribute prompt tokens, completion tokens, costs, and transport retry counts per Run, Job, and Attempt in `budget_ledger` and `evidence_diagnostics`.
- [ ] 5.3 Implement structured duration breakdown reporting separating active compute from provider wait and transport delays without UI dependencies.
- [ ] 5.4 Add tests verifying operational metrics calculation and strict secret redaction in all telemetry records.

## 6. End-to-End Integration & OpenSpec Validation

- [ ] 6.1 Execute strict OpenSpec validation (`openspec validate --strict autonomous-execution-efficiency-and-resilience`).
- [ ] 6.2 Execute targeted pytest suite and Ruff lint checks across all modified and newly created modules.
- [ ] 6.3 Verify regression baseline against disposable PostgreSQL and candidate freeze integrity.
