## Context

See `proposal.md` for motivation. The current feasibility stage check emits a blocker whenever `preconditions[*].evidence_refs` is empty. `CliAgentRunner.run` requests a structured completion handoff for `sync` and `archive`, and only parses that handoff when it was required. DOC_CLOSING separately dispatches native Sync and Archive; Archive currently receives a prompt to archive after Sync but does not direct the official CLI to skip its second spec update. `_run_sync_and_archive` commits OpenSpec paths after archive, while `_ensure_doc_closing_sync_archive` returns immediately for an already-complete archive without checking pending OpenSpec changes.

The installed OpenSpec Archive CLI supports `--yes` and `--skip-specs`. The installed Sync skill is agent-driven and edits main specs; mini me must continue to delegate both workflows rather than perform a semantic merge itself.

## Goals / Non-Goals

**Goals:**

- Remove a blocker that is produced solely by an empty stage evidence list, while keeping unknown or unverified concrete references and required capabilities fail-closed.
- Let Sync and Archive complete from process and filesystem evidence without requiring a model-authored completion phrase; preserve actionable native human handoffs.
- Keep the contract's native Sync-then-Archive sequence and prevent Archive from applying delta specs a second time.
- Ensure archived OpenSpec artifacts and synchronized specs are committed on the documentation branch before PR2 progression, including re-entry after archive.

**Non-Goals:**

- Change the OpenSpec CLI, installed skills, workflow ownership, or artifact semantics.
- Add database tables, lifecycle states, a semantic Markdown validator, a custom Sync/Archive implementation, or a manual archive/move path.
- Change PR merge policy, deployment responsibility, or the required evidence for Apply and Verify.

## Decisions

### 1. Empty stage references are not a dependency proof or blocker

In the stage-specific blocker check, skip a precondition whose `evidence_refs` is empty. It contributes no verifiable reference and therefore must not independently stop that transition. Continue evaluating every required stage capability and every non-empty reference; unknown, absent, or unverified concrete evidence remains blocking. Do not infer that an external dependency was satisfied from an empty list, and do not change the initial assessment's checks for missing structured task assessments or required pre-Apply evidence.

This keeps the correction local to the spurious stage blocker and avoids adding a new field or state. Adding a dependency classifier or a second feasibility engine was rejected as unnecessary. The existing validated task assessment remains the authority for whether a dependency is actually declared.

### 2. Make completion handoff optional only for Sync and Archive

Remove `sync` and `archive` from the set of workflows that must return `MINIME_WORKFLOW_RESULT: COMPLETE`. Preserve the mandatory handoff for `propose` and `continue`; do not alter Apply or Verify result rules. For Sync/Archive, stage success requires an exit code of zero, no timeout/preflight/environment error, and observable operation effects in the documentation worktree. It must not depend on final-response prose being non-empty or on a completion token.

Keep parsing a valid `HUMAN_REQUIRED` result when one is emitted, even when completion reporting is optional; the coordinator must still persist and display that current question and options instead of treating the operation as successful. Do not let an optional `COMPLETE`/`INCOMPLETE` report override failed process or artifact evidence.

For Sync, use the agent invocation result together with observed changes to the main OpenSpec specs in the same documentation worktree; if no Sync effect is observable and the specs are not already represented in the candidate, do not advance to Archive. The native Sync skill remains responsible for merging the delta semantics. Do not implement a second Python text merger or paragraph-equivalence checker.

### 3. Keep two native operations; skip spec application only in Archive

Retain the existing Sync then Archive workflow order. After Sync is observed successful, pass the official native Archive command `openspec archive --yes --skip-specs <change-name>` through the installed Archive workflow. This avoids replaying deltas while preserving OpenSpec ownership. A single Archive invocation that also syncs was rejected because it would remove the contract's separate native Sync stage.

Archive success requires process success and a factual postcondition: the active Change is absent, exactly one matching archive exists with required artifacts, and corresponding main spec files are present. Continue to use the existing read-only OpenSpec state observer; do not accept the agent's narrative as a substitute.

### 4. Commit observed OpenSpec state before PR2 progression

Move the commit guarantee to the DOC_CLOSING boundary so it covers both a freshly completed archive and an already-complete archive on re-entry. Before returning success, inspect the documentation worktree's Git state. If OpenSpec paths are pending, stage only `openspec/` and commit them; if unrelated paths are already staged, stop rather than include them in this commit. Verify the resulting Git head and that no OpenSpec changes remain uncommitted before advancing.

If the archive and synchronized specs are already in the current commit with no pending OpenSpec changes, proceed without an empty commit. Commit/push and branch identity remain within the existing documentation worktree and Git ownership rules; no new durable state is needed.

## Risks / Trade-offs

- [A malformed assessment could omit a real later-stage reference] → Keep non-empty unknown references and required capabilities fail-closed, and limit the empty-list rule to the stage transition check covered by the Issue.
- [A successful agent process could produce no Sync effect] → Require observable main-spec effect or verified already-synced state before Archive; process success or final prose alone is insufficient.
- [A legitimate native human handoff could be lost when completion tokens become optional] → Continue parsing and routing valid `HUMAN_REQUIRED` handoffs independently from the requirement to report `COMPLETE`.
- [Unrelated staged files could be committed with the archive] → Detect staged paths outside `openspec/` and stop before creating the documentation commit.

## Migration Plan

No database migration or deployment procedure is required. The code change follows the existing deployment pipeline. Rollback is the normal application rollback; already-created documentation commits remain on their Git branch and are not rewritten.
