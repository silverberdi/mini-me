# Tasks: Provider Execution Safety Stabilization

Instructions: treat `specs/provider-capacity-tracking/spec.md`, `specs/openrouter-drain-fallback/spec.md`, `specs/agent-execution-outcome-governance/spec.md`, `specs/primary-implementer-execution/spec.md`, and `specs/reviewer-execution-contract/spec.md` as behavioral authority. Scope is limited to this change only. Do NOT implement `ai-provider-model-capability-selection`, OpenCode integration, telemetry-based routing, or scheduler restart policy.

## Task 1 - Test-first regression tests reproducing the confirmed defects
- [x] Write a failing test proving the unknown-reset probe storm: with a provider `EXHAUSTED` and `capacity_reset_at = null`, running 100 consecutive scheduler tick/probe cycles must NOT produce one probe per cycle; this FAILS against current behavior (unknown reset is treated as immediately probe-eligible).
- [x] Write a failing test proving OpenRouter implementer fallback fabricates no candidate: with a successful OpenRouter text response and no repository-editing harness, no `candidate_impl.py`, no candidate commit, and no success/progress lifecycle event may be produced; this FAILS against current behavior (fake candidate is created and committed).
- Completion signal: both tests run red against current production code, then are made green by Tasks 2-5.

## Task 2 - Readiness/capacity separation and non-inference readiness (D1, D2)
- [x] Split the adapter probe contract on `ProviderAdapterInterface`: `check_cli_present()`, `check_auth_ready()`, and an expensive-classified `probe_availability()`.
- [x] Codex adapter: executable-missing returns a deterministic local failure with no inference probe; investigate and prove (or document the absence of) a non-inference auth command on the installed CLI before wiring `check_auth_ready`.
- [x] Keep Antigravity `agy models` readiness non-inference; do not reclassify it as an expensive probe.
- [x] Health service reflects truthful `misconfigured`/`unreachable` and `auth_required` outcomes without dispatching inference probes.
- Completion signal: unit tests for executable-missing, auth-unavailable, and quota-free readiness pass (acceptance scenarios 7 and 8).

## Task 3 - Deterministic cooldown/backoff for availability probes (D3, D4)
- [x] Replace the unknown-reset `is_reset_elapsed = True` behavior in `ProviderHealthService.check_and_probe_provider` with the D3 eligibility rules.
- [x] Persist probe-attempt state (`last_probe_at`, `consecutive_probe_failures`) via a versioned Alembic migration and wire it through the UoW repositories.
- [x] Add explicit per-provider `probe:` configuration with the documented defaults (`cooldown_seconds`, `backoff_base_seconds`, `backoff_max_seconds`, `max_per_hour`) and wire into config load/validation.
- [x] Ensure `probe_unavailable_providers()` invoked every scheduler tick is a no-op while cooldown/backoff holds.
- Completion signal: tests pass for known-future-reset (no probe before window), unknown-reset (bounded, no storm), 100 scheduler cycles within bound, failed probe delays the next probe, and successful probe resets backoff (acceptance scenarios 1, 2, 3, 5, 6, 18).

## Task 4 - Expensive probe governance and observability
- [x] Classify inference-consuming probes as expensive and rate-limit them with the cooldown/backoff and `max_per_hour` rolling window.
- [x] Persist an observable probe event (provider, kind=`expensive`, timestamp, outcome) on every expensive probe execution.
- [x] Assert probes never decrement implementation retry budgets and never create Runs/Jobs.
- Completion signal: tests for expensive-probe classification, rate-limit, observability, and no retry-budget consumption pass (acceptance scenarios 4 and 18).

## Task 5 - Remove OpenRouter fake candidate; truthful governed outcome (D5, D6)
- [x] Remove the placeholder `candidate_impl.py` create/commit in the OpenRouter success branch of `src/minime/services/execution_pipeline.py`.
- [x] When no real repository-editing harness exists, return a truthful governed outcome (`EVIDENCE_INSUFFICIENT`/`PROVIDER_FAILURE`), settle the reservation as unresolved/refunded, and persist no progress event.
- [x] Confirm no execution path creates a candidate without real repository materialization (candidate truth invariant).
- Completion signal: the Task 1 OpenRouter regression test is green; acceptance scenarios 14, 15, and 20 pass. `MockImplementerRunner` is unchanged unless a specific regression test requires a justified test-only adjustment.

## Task 6 - Headless CLI compatibility proving (D7)
- [x] Add deterministic proving tests (skip when the CLI is absent; fail fast when an installed CLI rejects a configured flag) for the Codex implementer, Codex reviewer, Antigravity implementer, and Antigravity reviewer invocations.
- [x] Add preflight validation so unsupported/deprecated CLI flags fail before a full attempt is consumed.
- Completion signal: proving tests pass or skip per CLI availability, and preflight tests assert no full-attempt consumption (acceptance scenarios 9, 10, 11, 12, 13).

## Task 7 - Process safety proving (D8)
- [x] Add deterministic tests proving implementer timeout terminates the process group (SIGTERM then SIGKILL) with a truthful timeout result.
- [x] Add deterministic tests proving cancellation leaves no orphan subprocesses.
- Completion signal: timeout and cancellation tests pass (acceptance scenarios 16 and 17).

## Task 8 - Coherence, strict validation, and scope guardrails
- [x] `openspec validate provider-execution-safety-stabilization --strict --type change` passes.
- [x] Focused pytest suite passes and ruff is clean.
- [x] Confirm no production code outside this change was modified, the production scheduler remains disabled/inactive, and no OpenCode/selector/registry/telemetry/routing scope leaked in.
- Completion signal: strict validation PASS plus the focused test suite is green.

## Operational proving guardrails (not code tasks)
- Production `minime-scheduler` remains disabled/inactive during implementation and deployment proving (acceptance scenario 19); it is re-enabled only after post-merge proving completes and the operator explicitly decides.
- No deploy and no OpenSpec apply/sync/archive are run during this preparation stage.

## Execution evidence
- Core defect RED evidence (pre-implementation): tests/test_provider_execution_safety_regressions.py::test_unknown_reset_codex_probe_storm_is_bounded_across_scheduler_cycles measured 100 Codex probes across 100 scheduler cycles against pre-TG3 code (captured in the TG2 close-out run and the TG3 pre-work state).
- Granular TG3 tests in tests/test_probe_cooldown_backoff.py were added and validated GREEN (8 passed), but their individual RED-before-code executions were NOT captured because implementation landed in the same pass. No retrospective RED evidence was fabricated.

## Task 6 proving evidence
- Codex implementer profile (codex exec - --approve-for-me --ephemeral) proven headless and mutating only a disposable fixture via one bounded real execution (exit 0; marker.txt created). One model-backed execution consumed quota.
- Codex reviewer profile corrected to codex review - (codex-cli 0.147.0 has no --ask-for-approval; codex review is the non-interactive read-only reviewer). Proven headless and non-mutating via one bounded real execution (exit 0; git clean; no file created).
- Antigravity flag-level preflight evidence recorded (implementer and reviewer profiles accepted via agy --help).
- AG implementer behavioral proving EXECUTED 2026-09-16T15:07:24Z–15:10:35Z (agy 1.1.27, model: gemini-3.6-flash-medium, --mode accept-edits --dangerously-skip-permissions --print-timeout 10m, worktree: proving/ag-implementer-behavioral-D7 at /private/tmp/mini-me-ag-impl-proving-fixture, base SHA: a17840f1477bd29e762053747ee13f1a6f703642). Result: PASS — AG implementer produced candidate commit d898071d39a46d2e28115d74c4568763a04cc075 with material assignment-relevant docstring mutation in src/minime/domain/interfaces.py. Evidence durable at brain/f5ba3355-ab1b-4044-a09b-01df9d092cea/ag_implementer_proving_evidence.md.
- AG reviewer behavioral proving EXECUTED 2026-09-16T15:13:49Z–15:14:29Z (agy 1.1.27, reviewer model: gpt-oss-120b-medium, distinct from implementer model gemini-3.6-flash-medium, worktree: proving/ag-implementer-behavioral-D7 at /private/tmp/mini-me-ag-impl-proving-fixture). Result: PASS — AG reviewer evaluated candidate SHA d898071d39a46d2e28115d74c4568763a04cc075, returned verdict ACCEPTABLE, and left worktree, HEAD SHA, index, and files 100% clean and unmutated. Evidence durable at brain/f5ba3355-ab1b-4044-a09b-01df9d092cea/ag_reviewer_proving_evidence.md.

## Corrective review evidence (independent audit)
- Independent Codex audit returned NEEDS_FIXES with findings A-H. Eight task leaves were truthfully reopened ([x] -> [ ]): first-probe cooldown (A), robust max_per_hour (B), per-provider probe config (C), OpenRouter candidate_sha (D), OpenRouter outcome semantics (E), preflight retry/health semantics (F), cancellation cleanup (G), AG behavioral proving (H).
- No retrospective evidence fabricated; the reopened leaves are re-addressed in this corrective APPLY pass with test-first regressions.
- Resolution: A (first-probe cooldown anchored to exhaustion baseline) resolved — test_probe_cooldown_backoff.py::test_unknown_reset_first_probe_respects_cooldown. B (durable per-provider rolling max_per_hour counter + provider-scoped lock + bounded suppression evidence) resolved — test_probe_governance.py (unrelated-events displacement, concurrent bound, bounded suppression). C (explicit per-provider probe YAML + bounds validation + per-provider selection) resolved — tests/test_probe_config.py. D (candidate_sha only on COMPLETED) resolved — test_provider_execution_safety_regressions.py. E (no-harness -> EVIDENCE_INSUFFICIENT, not WAITING_CAPACITY) resolved — test_provider_execution_safety_regressions.py + test_scheduler_drain_fallback.py. F (preflight -> NEEDS_HUMAN, no retry budget, no health degradation, both roles) resolved — tests/test_preflight_retry_and_health.py. G (bounded cancellation-protected cleanup before CancelledError propagates) resolved — tests/test_process_safety.py. H (Antigravity behavioral proving) RESOLVED — AG implementer proving (gemini-3.6-flash-medium, candidate SHA d898071d39a46d2e28115d74c4568763a04cc075, PASS) and AG reviewer proving (gpt-oss-120b-medium, candidate SHA d898071d39a46d2e28115d74c4568763a04cc075, verdict ACCEPTABLE, non-mutation PASS) both completed successfully.

