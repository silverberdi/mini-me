## Context

See `proposal.md` and the binding MM-R01 contract in `docs/backlog/MM-R01.md`. The preliminary code census confirms that `ExecutionPipelineService` currently builds prompt context and coordinates implementation/check/review/audit stages; `CliImplementerRunner` transports a prompt to a configured CLI; `OpenSpecAdapter` invokes the OpenSpec executable for validation/discovery; `WorktreeManager` already owns governed worktrees; and orchestration/PR services own durable stages and GitHub effects. The OpenSpec apply skill exists agent-side. These facts identify inspection points, not proof that any current path is safe to remove or that installed provider CLIs load the workflow.

The new capability composes the existing contracts in `primary-implementer-execution`, `reviewer-execution-contract`, `openspec-readiness`, `candidate-evidence-integrity`, `pr-preparation-and-recovery`, repository binding, durable saga, and checks. It does not replace their authorities. Canonical policy in `docs/CANONICAL_DECISIONS.md` supersedes older OpenSpec requirements that make DeepSeek a universal routine audit; this change carries focused deltas to orchestration and reviewer policy rather than silently preserving a contradictory gate.

## Goals / Non-Goals

**Goals:**

- Deliver the R01 vertical capability and evidence for R01-S01–S07 and R01-E01–E07 from an authorized, disposable GitHub fixture through a real Draft PR and functional post-deployment check.
- Keep security, identity, permission, quota, durable-state, worktree, check, review, PR, and human-merge authority in existing mini me services.
- Make actual native agent workflow execution independently observable, with exact provider/workflow/tool version, change, worktree, attempt, candidate SHA, and redacted outcome evidence.
- Preserve N01 and all historical durable and filesystem evidence; use N01 only for a read-only before/after preservation comparison.
- Complete a Removal Ledger and remove only proven-replaced reachable implementation-prompt emulation in the same Change, after successful real-path parity and with E2E rerun after removal.

**Non-Goals:**

- Reimplement OpenSpec `propose`, `apply`, `verify`, `sync`, or `archive` semantics in Python, templates, or generic prompts.
- Replace OpenSpec parsing/readiness, worktree/GitHub/PostgreSQL/claim/check/review/PR authorities, or create a generic plugin, capability, or workflow engine.
- Implement N01, GitHub Issue-to-proposal intake (R02), post-merge closure (R04), dynamic routing, dashboard redesign, OpenRouter drain, or automatic production scheduler activation.
- Make routine DeepSeek auditing mandatory or let any auditor replace the distinct authoritative reviewer.

## Decisions

1. **Stage dispatch stays in the existing orchestration pipeline; workflow semantics stay with the installed agent.** Inspect the actual execution entry point and configured CLI profiles for each supported provider. The pipeline will dispatch a bounded request naming the exact OpenSpec change and native stage workflow; the provider-side installed skill/workflow performs the cognitive `apply`. The OpenSpec CLI remains a structural/readiness validator. Prefer extending existing runner invocation data only if the code census proves it necessary; do not add a second runner abstraction or assume Codex and Antigravity use the same command syntax.

2. **Preflight and workspace authority precede provider invocation.** Reuse durable Project/repository/Issue/change binding, current base observation, WorktreeManager and ManagedWorkspaceGuard, installed-workflow/tool discovery, and provider auth/capacity signals. A no-go or unknown prerequisite returns a structured refusal/wait before inference and before external mutation. Worktree path is supplied only by validated durable ownership. No Issue title, transcript, or agent-selected path grants authority.

3. **Evidence requires independent observation.** Reuse existing attempt, event, candidate-manifest, check, review, and external-action persistence where it provides the required evidence. Persist only demonstrated gaps through existing PostgreSQL repositories and use Alembic if a schema addition is necessary. Corroborate native workflow use with process/tool traces plus artifact/diff and candidate observations; transcript assertions alone are insufficient. Bind check/review/PR evidence to exact candidate SHA, base SHA, generation and repository identity. Unknown external outcomes are observed/reconciled before retry.

4. **Candidate progression requires checks and an eligible independent reviewer.** Run configured deterministic checks and installed OpenSpec verification where supported against the frozen candidate. Reuse the existing reviewer authority and enforce identity independence against surviving candidate authorship. If reviewer capacity or compatible workflow is unavailable, preserve candidate and wait; do not self-review. Additional audit is a separate gate only when policy or explicit human authorization requires it. Do not silently spend DeepSeek/OpenRouter budget or allow an audit to stand in for a reviewer.

5. **PR delivery reuses the existing durable GitHub path and stops at the human gate.** Reconcile the candidate branch and Draft PR through existing action reservation/observation semantics; the remote PR head must equal the audited/otherwise authorized current candidate SHA and reference the exact Issue and change. Human merge remains mandatory. No archive, automatic merge, production deploy, or closure is folded into this implementation stage.

6. **Fixture is the product acceptance boundary; N01 is a protected invariant.** Use one small explicitly authorized disposable GitHub repository with a real failing behavior test and an already READY change whose specs were authored through the agent-side OpenSpec proposal workflow. Run one bounded authorized real implementation, deterministic checks, a distinct review, and a real Draft PR. Record separate TECHNICAL_PASS, E2E_PASS and DEPLOYED_VERIFIED evidence. If inference, reviewer capacity, credentials or deployment authorization is absent, report the relevant stage NOT_VERIFIED/WAITING and do not claim complete delivery. Capture N01 read-only identity/evidence before and after; never dispatch N01 or modify its records/worktree.

7. **Removal is proof-gated and same-change.** Inventory current prompt builders, callers, runner profiles, fixtures, tests, configuration, and dynamically selected paths. Classify every affected behavior REUSE/MODIFY/REPLACE/REMOVE/RETAIN-WITH-REASON. Retire only reachable code-authoring prompt paths that the native workflow has replaced, after a real E2E proves parity. Migrate callers and valuable tests/docs, then rerun focused checks, E2E, security denials and interruption recovery after removal. Retain `OpenSpecTaskTracker`, OpenSpec validation, deterministic orchestration and other code with justified consumers; do not remove semantic proposal generation from `OpenSpecGenerator`/intake (R02) or sync/archive behavior (R04).

8. **No speculative schema or deployment migration.** First use existing durable attempt/event/candidate/check/review/external-action records. Any field not representable must be justified by the traceability/evidence contract and added with a backward-compatible Alembic migration. Deploy only through the authorized target process after human merge; rollback restores the prior application artifact without deleting evidence or reverting external PR state. Keep production scheduler disabled until a separate release authorization and safety preconditions are satisfied.

9. **Resolve active-change and PR #152 interactions before apply, not by mutation.** Inspect active OpenSpec directories and the current N01/PR #152 state as read-only inputs. R01 uses a disposable fixture, not N01, and does not assume PR #152 is merged or authoritative. If existing active work conflicts with the single-change execution policy or blocks a safe baseline, stop before apply and request a human sequencing decision; do not archive, rewrite, or silently supersede those changes.

## Risks / Trade-offs

- **Installed provider workflow syntax or tool-use evidence differs by version** → resolve CLI/workflow names and versions in preflight and exercise each supported path; block unsupported or unobservable invocations.
- **Existing prompt path contains non-OpenSpec orchestration still needed for recovery or evidence** → use call-site/runtime census and ledger; remove only the semantic code-authoring portion after parity E2E and preserve safety coordination.
- **Native workflow execution can modify out-of-scope paths** → worktree confinement, path/diff checks, manifest review and fail-closed candidate validation; no PR on mismatch.
- **Provider auth/capacity or independent reviewer unavailable** → bounded preflight and wait while preserving the same Run/Job/worktree; do not consume paid fallback without explicit authority or claim E2E completion.
- **A real GitHub fixture or post-deployment target is not available** → mark the relevant E2E stage NOT_VERIFIED and block DONE; mocks/unit tests cannot substitute for product acceptance.
- **Legacy OpenSpec audit requirements conflict with canonical provider policy** → update only the affected orchestration/reviewer requirement deltas in this Change and preserve explicit policy-required audit behavior and candidate binding.
- **R01 activity overlaps currently unarchived changes or N01 recovery** → read-only reconciliation before apply; fixture isolation and no N01 mutations; seek sequencing authority if the conflict is material.

## Migration Plan

1. Before apply, verify branch/base, canonical remote and managed binding; inspect active changes, PR #140/#152, installed OpenSpec/provider workflows, relevant call graph and test fixtures. No production inference or mutation is part of this inspection.
2. Implement only the approved R01 specs, extending existing authorities and adding an Alembic migration only if a proven evidence gap requires one. Maintain backward-compatible readers and preserve all existing Run/Job/attempt/saga/worktree history.
3. Prove preflight denials and recovery first in isolated tests. Execute authorized stage E2E against the disposable GitHub fixture with explicit provider budget and separate reviewer; publish a Draft PR only after exact candidate/check/review evidence is verified.
4. Execute the Removal Ledger after real-path parity: migrate consumers, remove superseded reachable prompt emulation, then rerun affected unit/integration, denial, interruption, stage E2E and full fixture delivery tests.
5. Merge remains human-controlled. Deploy only after authorization, run functional post-deployment fixture acceptance bound to deployed SHA/digest, and preserve rollback/evidence. If a stage cannot execute safely, stop with WAITING/BLOCKED and retain artifacts.

## Open Questions

- None for the contract. The exact CLI workflow names, versions, invocation options, fixture repository identity, bounded inference budget, and deployment target are environment facts/authorizations to be resolved by preflight; their absence blocks execution rather than changing this design.
