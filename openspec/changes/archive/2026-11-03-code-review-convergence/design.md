## Context

See `proposal.md` for motivation. The current `_run_code_review` obtains the candidate diff through the existing Git call, truncates it to 4,000 characters, and constructs a generic prompt. `_run_proposal_review` already demonstrates the complete-artifact and convergence wording to reuse. The code-review runner call and structured verdict hint are separate from prompt content and remain unchanged.

## Goals / Non-Goals

**Goals:**
- Give the independent reviewer the complete candidate diff.
- Apply the proposal-review fix's substantive focus and explicit severity guidance to the code-review prompt.
- Add focused tests that protect complete diff delivery and convergence wording without changing dispatch behavior.

**Non-Goals:**
- Change OpenSpec workflow semantics, reviewer invocation, role/provider selection, verdict schema, or review routing.
- Modify proposal review, Apply, human payloads, DOC_CLOSING/Archive, or any other stage.
- Add diff summarization, chunking, token-budget policy, or a new reviewer abstraction.

## Decisions

1. **Use the full diff string in the existing prompt.** Remove the 4,000-character slice instead of raising the limit. Raising a limit would continue hiding part of a candidate diff. Chunking or summarization would add a second review path outside this issue.
2. **Reuse the established convergence language.** Keep the prompt read-only and retain the existing verdict schema hint. Add substance-only scope, BLOCKER/MAJOR/MINOR meanings, and instructions against re-flagging covered requirements or requesting wording/formatting changes, following `_run_proposal_review` and PR #255.
3. **Keep the native reviewer invocation intact.** Do not change the runner call, configured reviewer identity, candidate SHA recording, parsing, or stage transitions; the change concerns only prompt content.
4. **Test the prompt at its boundary.** Focused tests should exercise `_run_code_review` with a diff longer than 4,000 characters, assert the tail reaches the reviewer, assert convergence/severity guidance, and verify the existing reviewer role and invocation remain in use.

## Risks / Trade-offs

- [Risk] A complete diff creates a larger reviewer prompt and may approach a provider's context limit → Keep the behavior to the requested complete diff and rely on existing provider execution/error handling; do not silently truncate or add a separate fallback policy in this Change.

## Migration Plan

No data or API migration is required. Update the prompt assembly and focused tests; rollback by reverting this Change's code commit.
