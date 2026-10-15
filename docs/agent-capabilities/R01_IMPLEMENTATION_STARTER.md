# MM-R01 — Starting Package for Stage-Oriented OpenSpec Execution (reviewable v1)

**Target Change:** `real-openspec-agent-execution` | **Status:** predesigned backlog input, not an active OpenSpec Change. This document shortens agent planning: **the agent must still inspect code and build the final `proposal/design/specs/tasks` using the installed OpenSpec propose workflow**, not copy this as executable code. No agent inference or deployment authorized merely because this file exists.

## 0. Read in strict order

1. `AGENTS.md`, `docs/BUSINESS_INTENT.md`, `docs/CANONICAL_DECISIONS.md`, `docs/PRODUCT.md`, `docs/ENGINEERING_DISCIPLINE.md`.
2. `docs/CHANGE_DELIVERY_CONTRACT.md`, `docs/DOR_DOD.md`, `docs/ARCHITECTURE.md`, `docs/PROVIDER_POLICY.md`, `docs/AGENT_CONTRACTS.md`.
3. `docs/backlog/MM-R01.md`: its **R01-S01–S07** and **R01-E01–E07** are binding minimum scope.
4. `docs/agent-capabilities/V1_MANIFEST.md`, `HOOK_CONTRACTS.md`, `HARNESS_CONTRACT.md`, `RETIREMENT_MAP.md`.
5. Actual repo code, OpenSpec installed skills/workflows, existing tests, and PR [#140](https://github.com/silverberdi/mini-me/pull/140) and PR [#152](https://github.com/silverberdi/mini-me/pull/152) **as reference only**; neither is assumed merged.

## 1. Fixed product decision (no reinterpretation allowed)

- mini me is the **orchestrator**. It never writes implementation code or semantically authors `proposal/design/specs/tasks`; Codex/Antigravity run **native agent-side OpenSpec**.
- R01 starts from a **valid existing READY** OpenSpec Change in an **isolated disposable fixture repository**, not from new GitHub intake or N01 replacement. First real functionality: create a code change from OpenSpec with a real coding agent, pass tests, secure independent review, and issue a real GitHub PR.
- The specific shell executable for OpenSpec is `openspec`; `$openspec-apply-change` for Codex and `/opsx-apply` for the other compatible agent are **agent workflows**, not shell executables. Resolve installed names/versions at preflight. The agent side implements and uses tools; mini me dispatches and verifies.
- Human merge approval remains mandatory. Never use DeepSeek or OpenRouter silently. No auto-start production scheduler. No changes to N01's Run/Job/attempts/worktree for the fixture.
- All specs necessary for R01's own deployed value belong **inside R01**: preflight, native workflow dispatch, candidate, tests, review, PR, safety, quota, stage E2E, postdeploy E2E, and code retirement. Do not defer an essential piece to R02–R10.
- **R01 stage ownership:** Codex PLAN; DeepSeek Direct preferred for read-only CONTRACT REVIEW only when model/workflow compatibility, fresh capacity, and explicit provider/stage/budget authorization are proven, otherwise AGY; AGY APPLY and implementation tests; Codex VERIFY/E2E; final REVIEW follows the independent candidate-review policy. Contract review cannot authorize APPLY, final review, product decisions, or merge.
- Configure provider, model, and effort independently per stage. Validate each tuple against the exact installed CLI/version and its supported model, effort, role, and workflow capabilities; never infer CLI support. Start with the least-cost configured profile meeting documented complexity/risk and workflow requirements. Premium models/max effort are not defaults; escalation requires objective evidence, recorded rationale, finite bounds, and explicit budget authority. R01 needs static per-stage profiles and validation through existing config/adapter/capacity/budget authorities, not a second selector or dynamic optimizer.
- Local AI is optional/non-blocking for preliminary complexity classification, context preparation/reduction, extraction, labeling, and auxiliary tasks only. It cannot diagnose failures, implement authoritatively, review security, or make binding decisions; absence or failure never blocks the pipeline.

## 2. Existing code surfaces to inspect and decision to make

| Inspect | Why / expected ownership | Change policy |
|---|---|---|
| `src/minime/services/execution_pipeline.py` | Contains prompts to agent implementers and stage/check coordination | Replace only code-authoring **prompt-emulation** with real agent-side OpenSpec workflow invocation. Preserve legitimate orchestration/error normalization. |
| `src/minime/services/implementer_runner.py` | CLI dispatch, result/handoff semantics and bounds | Reuse runner tooling; add stage/workflow request only if required; no new generic runner framework. |
| `src/minime/services/orchestration_service.py` | Stage orchestration, review, PR gates, provider policy | Reuse durable stage flow; inspect its hardcoded DeepSeek audit gate and reconcile with current authorization. Do not hollow out enforcement. |
| `src/minime/services/openspec_tasks.py` | OpenSpec task extraction/prompt context | Retain OpenSpec parsing and readiness if useful; retire obsolete code-writing prompt route after parity. |
| `src/minime/adapters/openspec.py` | Real OpenSpec CLI validations | Reuse, don't reimplement validation. |
| `src/minime/services/workspace_guard.py` and Git/worktree managers | Managed-root identity, isolation | Preserve strict fail-closed security, symlink/remote/base SHA preflight. |
| `src/minime/services/provider_health_service.py` | Quota/auth/retry signals | Integrate stage preflight; do not claim exact remaining tokens when unknown. |
| `src/minime/services/post_merge_service.py` / `openspec_sync.py` | Closure/sync/archives | **Do not refactor in R01** unless required by R01 E2E; removal belongs mainly to R04. |
| `src/minime/services/openspec_generator.py`, `intake_service.py` | Deterministic OpenSpec proposals | **Do not delete yet in R01**; replacement belongs to R02 with E2E and migration. |
| `.agent/workflows/opsx-apply.md`, `.agents/skills/openspec-apply-change/SKILL.md` | Installed official OpenSpec apply behavior | Dispatch according to **actual installed provider skill**; do not duplicate workflow logic in mini me Python. |
| `tests/test_execution_pipeline.py`, `tests/test_worktree_and_runner.py`, `tests/test_stage_c_isolation.py`, `tests/test_n01_durable_continue_postgres.py` | Existing unit/integration/regression safety | Reuse useful tests but real agent/PR E2E is a **new, separate proof**. Never weaken N01 preservation assertions for convenience. |

The above are **inspection targets**, not confirmation that a module has no other consumers. Enumerate callers/DI/jobs/config/schemas, complete Removal Ledger and choose smallest safe integration. No architecture or refactoring for its own sake.

## 3. Planned stage interface and evidence contract

Use `docs/agent-capabilities/HARNESS_CONTRACT.md` for fields and classifications. R01 must establish at least:

- `admit_work_item(project_id, change_slug)` or existing equivalent: explicit **durable validated binding**, reserved claim, exact worktree, auth/quota/tool preflight, no speculative new job.
- Stage request = `(project, change, run, job, attempt, generation, stage, configured provider/model/effort, installed-workflow, skill hashes, scope, policy snapshot, capacity/budget authorization, idempotency key)`.
- R01 flow assignment = Codex PLAN → authorized read-only CONTRACT REVIEW (DeepSeek preferred, AGY alternative) → AGY native OpenSpec APPLY → AGY implementation TEST → Codex read-only VERIFY/E2E → final independent REVIEW under the unchanged final-review policy. If Codex verification changes candidate content, that content is attributed as authorship and requires a new frozen candidate/independence evaluation; verifier claims never self-authorize review.
- Agent invocation = selected CLI **actually loads** the installed native workflow for its assigned stage and edits only the worktree when write authority is granted. mini me must observe side effect/tool evidence; do not accept transcript-only claims.
- Stage output = normalized result class + concrete diff/SHA/tests/artifacts + events/cost/capacity and tool trace; mark UNKNOWN/WAITING rather than fabricated SUCCESS.
- Verification = project checks + native agent-side `verify` when installed + stage E2E; select distinct reviewer/model for authoritative review. A review on a code snapshot requires frozen candidate SHA.
- Publication = Draft PR real with candidate SHA, Issue/OpenSpec binding and evidence. No auto-merge.
- Human/operator state = original Run/Job/worktree restored after crash if safe, not duplicated.

Use **existing** providers/worktree/saga/PR services. Only add new classes/schema/migrations where code census establishes necessity. Decide exact function signatures in `design.md` after inspecting code, not in a free-form prompt.

## 4. Real fixture E2E — minimum deterministic specification

Fixture design to materialize within R01:
1. A small **authorized GitHub test repository** with actual working-tree remote, README, `AGENTS.md`, OpenSpec config, a minimal app/function (e.g. `normalize_label`) and a real failing behavior test, with a branch-protection-compatible PR path.
2. A Change already created with **agent-side OpenSpec** and specs including successful behavior, invalid input/rejection and regression criteria; DoR READY, explicit owner and repo binding.
3. A bounded authorized sequence using fresh stage-specific preflight: Codex PLAN, approved read-only CONTRACT REVIEW (DeepSeek only under explicit budget/provider authorization, else AGY), one AGY APPLY, AGY implementation tests, Codex VERIFY/E2E, and independent final review under current policy. Capture CLI exit, native workflow/tool trace, `openspec status`/validation, actual source modification, checks, model/effort capability proof, and candidate identity.
4. A distinct final reviewer. If no eligible reviewer exists, **stop at `AWAITING_INDEPENDENT_REVIEW` or equivalent** with code safely preserved; do not fabricate independent acceptance. Contract-review evidence is not final code-review evidence. No self-review.
5. After genuine reviewer acceptance and final checks, publish a **Draft** PR with exact candidate and evidence. Human merge remains manual.
6. R01-E03: assert missing native skill/auth, stale provider health, remote mismatch, symlink escape **block before paid inference**.
7. R01-E04/E06: assert interrupted attempt and N01 data survive with same IDs/WT and no duplicate effects. R01-E07: verify behavior via actual deployed API/CLI and fixture delivery, not just process health.

**Gates and result honesty:** unit/integration ≠ agent E2E ≠ postdeploy. If current provider availability cannot satisfy independent review, R01 may advance to code candidate **but not falsely claim the entire Change delivered**.

## 5. Retirement ledger explicitly required inside R01

- INVENTORY: old implementation-prompt builder, text-only pretend execution path, fake tool-use proofs, duplicated workflow dispatchers, their callers/fixtures.
- MIGRATE: stage dispatch + agent handoffs, reviewer/check integration, docs and test cases.
- REMOVE: old reachable routes **only after** native agent/OpenSpec parity E2E; E2E again after removal.
- RETAIN-WITH-REASON: legitimate task parser/adapters/workflow evidence that remain useful. No obsolete active dispatch paths and no hidden fallback to raw generic implementation prompts.
- OUTSIDE SCOPE: semantic `OpenSpecGenerator` (R02) and `OpenSpecSyncService` (R04), unless proven to block the minimal E2E; keep history/migrations.

## 6. Engineering/quality gates and expected artifacts

`proposal.md`: one coherent user value, before/after, boundaries, R01 S/E traceability.
`design.md`: call graph and ownership; native CLI/skill invocation; actual retry/claim capacity flow; candidate, review, PR and N01 compatibility; explicit Remove Ledger; rollout/fault injections.
`specs/`: enough specs for all R01-S01…S07 (no missing E0x) with Given/When/Then.
`tasks.md`: ordered code/integration + focused checks + actual E2E by stage + negative fault-injection + retirement + post-retirement regression + real postdeploy acceptance and source evidence.
`verify`: present coherent/pass/fail/blocked report, *never* accept task checkbox, static existence or fake runner as real E2E.

Use the approved per-stage role assignment above; historical availability does not establish current capability or authorize a call. Finish planning before provider execution. No DeepSeek call is allowed by this document alone; CONTRACT REVIEW still requires fresh explicit per-run stage/provider/budget authorization.
