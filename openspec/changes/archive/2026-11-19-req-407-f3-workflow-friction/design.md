## Context

See `proposal.md` for motivation and `specs/` for the required behavior. On the current `main` candidate, feasibility validation is centralized in `ProposalFeasibilityEvaluator`; Apply execution evidence is represented in the collected capability set, but `validate_report` currently requires both `profile:execution` and `workflow:execution:apply` in the task's own reference list. `_assess_complexity` validates one structured report and routes blockers to the existing `proposal_feasibility` gate. The gate's native Update dispatch recognizes an option by its literal `OpenSpec Update` wording, while agent-provided resolution options can replace the fallback options.

DOC_CLOSING dispatches the installed Sync and Archive agent workflows. The provider resolver uses `.agents/skills/openspec-archive-change/SKILL.md` for Codex, `.agent/skills/openspec-archive-change/SKILL.md` as the OpenCode fallback, and `.agent/workflows/opsx-archive.md` for Antigravity. These entry points currently include free-text delta/main-spec comparison and manual directory movement even though the installed OpenSpec CLI provides `openspec archive -y`. The `minime request run` CLI currently invokes the coordinator directly and has no response argument; the web request path already records gate responses as durable `OperatorActionRecord` actions with gate/response fingerprints and idempotent re-entry.

No OpenSpec change is active on the `main` base used for this proposal. The implementation must preserve the single active Change per project, exact candidate identity, native workflow ownership, current human authorization boundaries, and fail-closed handling of unverified evidence.

## Goals / Non-Goals

**Goals:**

- Remove only the redundant task-level profile reference while continuing to verify the configured execution profile and the actual installed Apply workflow.
- Retry correctable feasibility report defects at most twice, on the same observed candidate and capability snapshot, before opening the existing gate.
- Make native OpenSpec Update consistently selectable from the feasibility gate without allowing it to waive blockers.
- Use the OpenSpec CLI as the sole archive operation after verified Sync; preserve observable CLI diagnostics and archive evidence.
- Provide an operator CLI response using the same durable gate-response authority as the web path, with idempotent behavior and no new persistence table.

**Non-Goals:**

- Relaxing real capability, credential, preview, external participant, or stage-required evidence; retries must not convert an unknown or missing fact into a pass.
- Changing provider selection, spend policy, retry limits for Apply, candidate/worktree identity, gate authorization semantics, PR merge policy, or ticket order.
- Implementing OpenSpec semantics in Python, adding a custom spec merger/archive mover, adding a new database state machine/table, or deploying the application.
- Adding general CLI access to PostgreSQL or arbitrary Run mutation; the new argument answers only the current gate of the project's uniquely identified active Run.

## Decisions

1. **Treat verified native Apply workflow evidence as the execution capability; retain configuration checks.**
   Reuse the existing capability collection and project profile resolution. For an Apply task, require the verified configured execution/implementer profile and `workflow:execution:apply` availability from the collected evidence, but do not require the report to repeat the same configured profile as a task reference. Validate any additional references normally. Unknown references, unavailable workflow files, or missing configured profile remain blockers. This is narrower than accepting arbitrary actor prose and avoids coupling feasibility to redundant LLM output.

   **Alternative considered:** accept any task-level `profile:execution` or workflow string without checking project/worktree configuration. Rejected because textual claims are not capability evidence and would violate fail-closed behavior.

2. **Classify existing validator diagnostics before retrying; do not add a second evaluator.**
   Extend the current feasibility validation result just enough to identify objective, correctable report defects (schema shape, task/scenario coverage or mapping, and stage/dependency ordering) separately from verified-evidence blockers and invocation failures. When only correctable report defects remain, call the already configured thinking role again with the exact diagnostics, the same candidate SHA, task/scenario inventory, and capability snapshot. Permit two corrective calls after the initial evaluation. Record each call with existing complexity/attempt evidence and stop on a passing report, a real evidence blocker, an invocation error, or the retry bound. Do not retry validation CLI failure, provider failure, security failure, or missing evidence as if it were a formatting problem.

   **Alternative considered:** open a human gate on the first invalid structured report. Rejected because it recreates the correctable dead end described by the Issue. **Alternative considered:** repeat every blocked assessment until it passes. Rejected because it could burn quota, conceal genuine dependencies, or loop without progress.

3. **Keep the native Update option stable and separate from free-form advice.**
   Reuse the existing feasibility gate payload and `_selected_feasibility_update_option` dispatch. Ensure the canonical system-generated option recognized by that handler is always present, preserving agent suggestions as additional advice. Selecting it authorizes only native OpenSpec Update on the same Run/Change; strict validation and a fresh evidence-bound feasibility assessment remain mandatory. An evidence option continues to require observed evidence and does not dispatch Update.

   **Alternative considered:** infer that arbitrary free text means “Update.” Rejected because it can accidentally grant a different action or bypass operator intent.

4. **Replace archive's manual equivalence-and-move steps with native CLI execution.**
   Keep Sync and Archive as the thinking agent's installed official workflows. After the existing stage has observed successful Sync for the same Change/worktree, update each provider-resolved Archive instruction entry point to run `openspec archive -y <change-name>` and use its exit code plus existing artifact observation for completion. Remove only the free-text paragraph-equivalence gate and manual `mkdir`/`mv` archive substitute. If Sync was not observed as successful, retain the existing native Sync recovery path; if the CLI fails or the archive is ambiguous, preserve the worktree/Change and surface actual diagnostics.

   **Alternative considered:** add Python content normalization, Markdown merging, or filesystem movement to the coordinator. Rejected because it would emulate OpenSpec and add a second source of archive semantics. **Alternative considered:** accept an agent narrative without running the CLI. Rejected because narrative is not observable archive evidence.

5. **Share gate-response acceptance between CLI and web using existing durable action records.**
   Add `--response` to `minime request run` while preserving the current no-argument request-run behavior. Extract only the web route's gate-response acceptance/idempotency logic into a small shared application operation that both interfaces call; leave orchestration and state transitions in the existing coordinator. The operation resolves exactly one active Run and its current gate, binds the response to that gate fingerprint, persists the existing `RESOLVE_GATE` action, redacts the stored response, and uses the existing deterministic idempotency behavior when no explicit key is supplied. On duplicate submission return the prior result; on absent, stale, or ambiguous gate, fail without scheduling work. No new table or alternate CLI-only authorization rule is introduced.

   **Alternative considered:** copy the web route logic into the CLI or call `execute_project_request` with unverified free text. Rejected because either duplicates authority/idempotency rules or bypasses the durable operator action path. The shared operation retains the web flow as the single behavioral authority.

## Risks / Trade-offs

- [Retry calls consume configured thinking-provider capacity] → Limit correction to two calls, reuse normal capacity/spend preflight, and do not retry provider/CLI failures or genuine missing evidence.
- [A validator classification could mislabel an evidence defect as correctable] → Derive classifications from existing structured validator checks, keep unknown/unavailable evidence in a separate non-retryable category, and test both positive correction and negative fail-closed cases.
- [Native Archive behavior or installed CLI syntax can vary by version] → Use the repository's verified installed CLI version and exact `-y` option; test against a temporary OpenSpec fixture and keep the Change untouched when CLI output is nonzero or ambiguous.
- [CLI gate responses may be replayed or target a gate that changed after lookup] → Bind the durable action to Run and gate fingerprints, use the existing transaction/idempotency behavior, and reject stale state before scheduling.
- [Archive skill change could drift from upstream OpenSpec guidance] → Keep the edit limited to invoking the native CLI and observing its result; do not add custom artifact generation, spec merging, or archive logic.

## Migration Plan

No database migration is expected; use the existing `OperatorActionRecord` and attempt evidence. Apply the code and installed-skill changes together in this Change, run focused and adjacent tests plus a local OpenSpec CLI archive fixture, then verify the actual changed integration boundaries before Verify/PR. Use existing provider capacity and authorization rules; do not add a general monitoring or evidence layer for individual OpenSpec steps. If implementation is reverted, restore the prior skill and command behavior with the same Change history preserved; no production deployment or data rewrite is part of this plan.

## Open Questions

None that change the stated behavior or implementation boundary. The correction limit is two retries after the initial feasibility evaluation, matching the Issue's explicit maximum of two retries.
