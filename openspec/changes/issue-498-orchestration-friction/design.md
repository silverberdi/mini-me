## Context

See `proposal.md` for the observed friction. The current implementation already has native OpenSpec workflows, durable stage invocation guards, human-gate response paths, provider-specific prompt transport, reviewer isolation, and typed GitHub operations. The design reuses those paths; it does not add a workflow engine, recovery subsystem, or new persistent state.

## Goals / Non-Goals

**Goals:**

- Make stage completion depend on observable process, CLI, and artifact evidence instead of exact natural-language completion tokens.
- Ensure every nonterminal hold is understandable and has an existing authorized path to continue when one exists.
- Make review remediation and merge retry safe, bounded, and tied to authoritative candidate/PR state.
- Keep reviewer coverage of changed source while avoiding unnecessary process-argument and provider-context failures.

**Non-Goals:**

- Reimplementing OpenSpec or changing its official workflows.
- Automatically answering genuine human questions, approving proposals, overriding branch protection, or changing candidate identity.
- Changing autonomy/time dashboard metrics covered by Issue #489.
- Adding a new persisted state machine, queue, provider, deployment step, or general-purpose retry framework.

## Decisions

1. **Use native execution evidence, not a success phrase.** For Explore, rely on the configured workflow invocation's successful process result and nonempty observable output; preserve an explicit human question/options when present. A failed process, missing output, or unclear unresolved decision remains a concrete hold with a reason. For Propose, validate the canonical artifacts and strict OpenSpec CLI result. Do not accept narrative or a model-authored token as a substitute for these checks. This removes the exact `READY_TO_PROPOSE` / `MINIME_WORKFLOW_RESULT` dependency without weakening real artifact validation. An alternative was to broaden the set of accepted magic strings; that would keep the same brittle protocol.

2. **Route prerequisite failures through the existing gate contract.** When the coordinator cannot dispatch because authorization is missing, expose the prerequisite and the existing operator action through the current gate/API/UI flow. Never expose internal authorization material as a credential and never create an action that grants itself authority. If the workflow has no safe operator action, report that concrete fact and preserve the Run. This reuses existing gate response and authorization handling rather than adding a parallel control surface.

3. **Treat review corrections as stage-entry evidence.** Reuse the existing stage invocation guard and Apply retry history, allowing a new Apply invocation when an observed review result routes the same candidate to remediation. Keep corrections distinct from Apply partial-work recovery context. Revalidate candidate identity and retain current retry, budget, regression, and unresolved-human-gate checks. Do not reset history or loosen generic stage re-entry rules.

4. **Reduce reviewer payload by evidence, not broad path guesses.** First use the configured prompt transport so a large prompt is not placed in argv. Exclude lockfiles, binary bodies, and outputs only when repository configuration or file metadata establishes that they are generated/non-reviewable. Keep authored source and project assets represented. If provider context limits still apply, partition the relevant changed files using the existing reviewer invocation path; do not silently truncate. Record which evidence was supplied so a partial review is not reported as complete. An unverified fixed-size cutoff or broad exclusion of `static/` was rejected because it could hide authored assets.

5. **Retry HTTP 405 only after authoritative read-back.** After a 405, read the same PR from GitHub. Retry with a small bounded backoff only while GitHub reports mergeability as unknown/transient; stop immediately for conflict, branch-protection denial, failed checks, or other permanent rejection. Preserve typed error details. Do not assume every 405 is transient or turn retry into a policy bypass.

6. **Keep scope in the existing capabilities.** Update the existing OpenSpec requirements for proposal, recovery, Apply, review, and merge behavior. Do not create a new capability solely to house orchestration guardrails, and do not add a database migration unless implementation evidence shows the existing records cannot represent the required action/result.

7. **Separate candidate Verify from deployed-Run acceptance.** Before merge, run the applicable automated checks against the committed candidate SHA and report any skipped target or unavailable external behavior precisely. Do not call synthetic fixtures real E2E. Observe a real Run only after the merged release is deployed; keep that operational acceptance pending until its Run and stage evidence are collected, and complete it before documentary closure or closing Issue #498. This follow-up does not introduce deployment responsibility into mini me.

## Risks / Trade-offs

- [A successful Explore process may still return too little useful content] → Require nonempty output and preserve unresolved questions; distinguish this from Propose artifact completion, which remains subject to strict CLI validation.
- [A gate may reveal an internal blocker] → Present only the actionable reason and authorized response, never secret/token material or a way to bypass authorization.
- [Review partitioning can weaken cross-file reasoning] → Keep all review-relevant changed-file evidence, make partitions attributable, and require the reviewer to consider the candidate as one change before approving.
- [GitHub may continue returning 405 after mergeability is known] → Bound retries and retain the final read-back plus typed rejection for operator visibility.
- [A real Run cannot exercise the merged candidate before deployment] → Keep pre-merge Verify limited to candidate-bound automated evidence and leave deployed-Run acceptance explicitly pending until the release is available.
