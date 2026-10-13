## Why

Mini Me has orchestration components, but it has not yet demonstrated the product outcome promised by MM-R01: a real coding agent applying a READY OpenSpec change through its installed native workflow, producing verified code, receiving independent review, and publishing a human-mergeable PR. A bounded, authorized fixture repository will prove that vertical outcome while preserving N01 and the existing repository, provider, cost, and human-approval boundaries.

## What Changes

- Establish one end-to-end agent-led delivery path from an explicitly bound READY change through preflight, native agent-side OpenSpec `apply`, candidate/check evidence, independent review, and a real Draft PR.
- Require pre-inference validation of durable repository/worktree identity, installed CLI and workflow compatibility, authentication/capacity signals, scope, and authorization; deny safely without consuming inference when a prerequisite fails.
- Capture verifiable workflow/tool-use and candidate evidence rather than treating prompts, transcripts, mocks, or `openspec validate` as proof that an agent applied OpenSpec.
- Preserve the same Run/Job/worktree and evidence across interruption; require a reviewer distinct from the substantive implementer and retain the human merge gate.
- Inventory and safely retire only replaced, reachable prompt-emulation paths in this Change after real parity E2E; preserve legitimate orchestration, OpenSpec validation, historical records, and unrelated generators/closure behavior.
- Prove the complete value in an isolated authorized GitHub fixture and perform functional post-deployment verification. Keep scheduler production admission disabled until its separate authorization and release preconditions are satisfied.

## Capabilities

### New Capabilities

- `real-openspec-agent-execution`: Secure, durable orchestration of a real agent's native OpenSpec implementation workflow through independently reviewed, checked, human-gated PR delivery.

### Modified Capabilities

- `autonomous-change-orchestration`: align the candidate-to-human-gate contract with current canonical policy: independent primary-agent review is the normal quality gate; DeepSeek Direct is not a mandatory routine audit and may be used only as an explicitly authorized compatible fallback when both primaries cannot serve the stage.
- `complementary-reviewer-policy`: preserve reviewer/model independence and mixed-authorship disclosure without making DeepSeek Direct a universal mandatory final audit boundary.

## Impact

- Likely code surfaces to inspect and reuse: `execution_pipeline.py`, `orchestration_service.py`, `implementer_runner.py`, `openspec_tasks.py`, the OpenSpec adapter, provider health/capacity, worktree/repository guards, check/review and PR services. The preliminary census is in `docs/agent-capabilities/R01_IMPLEMENTATION_STARTER.md`; the design must verify callers and actual installed workflows before choosing changes or removals.
- Adds integrated behavior and tests across durable orchestration, agent CLI/workflow evidence, checks, candidate identity, reviewer independence, GitHub PR delivery, and recovery. Any schema change must use Alembic and be justified by a demonstrated evidence gap.
- Uses an isolated disposable, explicitly authorized GitHub test repository for the real E2E; no N01 implementation or state mutation, production scheduler activation, unapproved paid fallback, provider self-review, or auto-merge is authorized.
- The outcome is backend/operator-facing; no new UI is intended. If implementation changes an existing operator-facing UI, its human-validation scenarios must be added before implementation.
- Dependencies: secure baseline and validated project/repository binding; compatible installed Codex/Antigravity native OpenSpec workflows; authorized fixture credentials and bounded inference capacity; complementary reviewer availability. Missing provider capacity leaves work preserved and waiting, not falsely accepted.
- Out of scope: GitHub Issue-to-proposal intake (R02), full post-merge sync/archive and closure (R04), dynamic routing/platform work, generic skill frameworks, dashboard redesign, N01 recovery/implementation, automatic scheduler enablement, and any merge/deployment without the required human authorization.
