## Why

Mini Me has orchestration components, but it has not yet demonstrated the product outcome promised by MM-R01: a real coding agent applying a READY OpenSpec change through its installed native workflow, producing verified code, receiving independent review, and publishing a human-mergeable PR. A bounded, authorized fixture repository will prove that vertical outcome while preserving N01 and the existing repository, provider, cost, and human-approval boundaries.

## What Changes

- Establish one end-to-end agent-led delivery path with independently configured provider/model/effort profiles for planning, execution, tests, and verification. Codex and AGY are primary providers selected by validated stage profiles and may safely hand off compatible work. DeepSeek Direct is the independent reviewer for separate read-only CONTRACT REVIEW and code REVIEW stages, using its own official API/account and explicit capacity/budget authority. OpenRouter is exceptional quota rescue for previously started work only when both primary providers are blocked by quota; it is never a reviewer or a route to start new READY work.
- Select the least-cost configured profile that meets documented complexity/risk and native-workflow requirements; validate provider/model/effort against the exact installed CLI/version. Premium models and maximum effort are not defaults. Escalation requires objective evidence, a recorded rationale, finite bounds, and explicit budget authorization. R01 adds only static stage profiles and validation through existing authorities; dynamic optimization is deferred.
- Keep local AI optional and non-blocking for preliminary complexity classification, context preparation/reduction, extraction, labeling, and auxiliary tasks only; it cannot diagnose failures, implement authoritatively, review security, or make binding decisions.
- Require pre-inference validation of durable repository/worktree identity, installed CLI and workflow compatibility, authentication/capacity signals, scope, and authorization; deny safely without consuming inference when a prerequisite fails. For Antigravity capacity, specify the real non-inferential headless `/usage` schema (`num_turns: 0`, `total_tokens: 0`, Gemini model buckets), require that missing or incomplete `/usage` data never equates to zero consumption, demote `statusLine` to non-authoritative telemetry, and enforce mandatory regressions for incomplete, forged, stale, unknown-provenance, and valid signals.
- Capture verifiable workflow/tool-use and candidate evidence rather than treating prompts, transcripts, mocks, or `openspec validate` as proof that an agent applied OpenSpec.
- Verifiably exclude compiler and runtime artifacts (`__pycache__`, `*.pyc`, `*.pyo`, `.pytest_cache`) from candidate commits, manifests, and published PRs, enforcing clean worktrees and isolated check execution environments.
- Preserve the same Run/Job/worktree and evidence across interruption; keep CONTRACT REVIEW distinct from final code REVIEW; require DeepSeek reviewer independence from substantive authors and retain the human merge gate. Neither review authorizes APPLY, product decisions, or merge. Existing audit output is never converted into review approval.
- Enforce an exhaustive 14-requirement traceability matrix (`requisito → entradas válidas e inválidas → resultado esperado → componente responsable → prueba → evidencia`) and complete adversarial test contracts across all 8 critical surfaces: admission, preflight/capacity, OpenSpec apply execution, worktrees, candidate integrity, recovery, independent review, PR delivery, and N01 preservation.
- Inventory and safely retire only replaced, reachable prompt-emulation paths in this Change after real parity E2E; preserve legitimate orchestration, OpenSpec validation, historical records, and unrelated generators/closure behavior.
- Prove the complete value in an isolated authorized GitHub fixture and perform functional post-deployment verification. Keep scheduler production admission disabled until its separate authorization and release preconditions are satisfied.

## Capabilities

### New Capabilities

- `real-openspec-agent-execution`: Secure, durable orchestration of a real agent's native OpenSpec implementation workflow through independently reviewed, checked, human-gated PR delivery.

### Modified Capabilities

- `autonomous-change-orchestration`: define profile-selected Codex/AGY planning and execution with durable handoff, separate DeepSeek Direct contract and code review stages, OpenRouter quota-only in-flight rescue, and the human merge gate.
- `complementary-reviewer-policy`: preserve candidate-bound independence and mixed-authorship disclosure; define DeepSeek Direct as the read-only reviewer for separate contract and code stages with separate evidence and budget authorization, without converting audit evidence or allowing review to authorize APPLY or merge.

## Impact

- Likely code surfaces to inspect and reuse: `execution_pipeline.py`, `orchestration_service.py`, `implementer_runner.py`, `openspec_tasks.py`, the OpenSpec adapter, provider health/capacity, worktree/repository guards, check/review and PR services. The preliminary census is in `docs/agent-capabilities/R01_IMPLEMENTATION_STARTER.md`; the design must verify callers and actual installed workflows before choosing changes or removals.
- Adds integrated behavior and tests across durable orchestration, agent CLI/workflow evidence, checks, candidate identity, reviewer independence, GitHub PR delivery, and recovery. Any schema change must use Alembic and be justified by a demonstrated evidence gap.
- Uses an isolated disposable, explicitly authorized GitHub test repository for the real E2E; no N01 implementation or state mutation, production scheduler activation, unapproved paid fallback, provider self-review, or auto-merge is authorized.
- The outcome is backend/operator-facing; no new UI is intended. If implementation changes an existing operator-facing UI, its human-validation scenarios must be added before implementation.
- Dependencies: secure baseline and validated project/repository binding; compatible installed stage workflows and supported model/effort profiles; authorized fixture credentials; fresh capacity and account identity for each selected stage; and durable budget authorization/reservation bound to provider, account, model, stage, Run/Job, billing origin, verified cost basis, and limit. DeepSeek uses only its direct account authority. Missing reviewer, capacity, pricing, billing-origin, or budget evidence leaves work preserved and waiting. This planning authorization does not authorize a paid call.
- Out of scope: GitHub Issue-to-proposal intake (R02), full post-merge sync/archive and closure (R04), adaptive/dynamic routing optimization or platform work beyond static stage profiles, generic skill frameworks, dashboard redesign, N01 recovery/implementation, automatic scheduler enablement, and any merge/deployment without the required human authorization.
