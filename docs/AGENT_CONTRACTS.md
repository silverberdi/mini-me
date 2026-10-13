# Agent Role Contracts

## OpenSpec proposer / updater / implementer / verifier (Codex or Antigravity)
Receives authoritative Business Intent, accepted backlog ficha, active OpenSpec artifacts, exact workspace, project policy, tools/skills/hooks/harnesses, deterministic checks and prior findings. The **agent runs installed native OpenSpec workflows** (tool-specific propose/update/continue/apply/verify/sync/archive); the mini me daemon never recreates their semantic work. The agent must stay in scope, modify only assigned worktree, preserve unrelated code and return tool-invocation evidence and artifact/candidate/check identities. Material ambiguities are escalated before editing.

## Complementary reviewer (Antigravity or Codex)
Starts read-only. Receives same OpenSpec change, candidate diff and check evidence. Evaluates spec compliance, correctness, regression risk, tests, security and maintainability. It does not silently become implementer.

Normalized review shape is defined in `schemas/reviewer-result.schema.json`.

## DeepSeek Direct optional authorized analyst
Available **only as operator-authorized compatible fallback after dual-primary capacity exhaustion**, read-only unless an approved future agent-with-tools contract exists; no mandatory post-review audit. Focus: acceptance mismatch, edge cases, security/privacy, idempotency/concurrency and missing tests. Never proxied through OpenRouter. Schema: `schemas/audit-result.schema.json` when this optional role is used.

## OpenRouter authorized fallback executor
May finish eligible in-flight work only after both primaries cannot serve the stage, explicit operator authorization, budget allowance, and proof the runner can actually invoke tools/workflows and write within the sandbox. API text generation alone is not OpenSpec implementation. It may not cause admission of a new READY change.

## OpenRouter drain reviewer
May authoritatively review in DRAIN only when its model identity differs from the latest substantive implementer model for the candidate. If distinct review capacity is unavailable, wait rather than self-review.

## Qwen local helper
Advisory/mechanical only. Cannot satisfy review, audit, security, budget or human gates.

## Delivery evidence
No agent may self-certify E2E or deploy success. The harness verifies real OpenSpec workflow usage, diff/tests/review/candidate PR and behavior postdeploy, with actor/model/tool/version/skill hashes. Unit/integration PASS is not product completion.

## Human
Durable authority for final approval, UI validation judgment, merge, product/spec ambiguity, sensitive findings, policy overrides, budget increases and rollback authorization.
