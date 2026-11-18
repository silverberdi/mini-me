## Why

When proposal review exhausts its attempts, the current human gate retains structured reviewer findings but its generated option can still be the generic “Pedir corrección y nueva revisión.” Selecting it does not give the author agent the concrete correction directive the reviewer supplied, so the operator has to rewrite that guidance and the resumed Propose can remain ambiguous.

## What Changes

- Build the system-generated correction suggestion from the `expected_correction` values of all substantive findings in the current exhausted proposal-review gate.
- Put the complete generated directive into the operator clarification when that suggestion is selected; preserve the existing native gate response path and gate identity.
- Resume native OpenSpec Propose with that accepted correction context on the same Run and Change, then require the configured independent reviewer to review the revised proposal again.
- When findings lack sufficient correction detail, do not invent instructions; retain the evidence and offer free-text input instead of a misleading generic correction suggestion.

## Capabilities

### New Capabilities

### Modified Capabilities

- `openspec-native-propose`: generated correction guidance for exhausted independent proposal review is complete, evidence-derived, and reaches the resumed native Propose invocation while remaining subject to another independent review.

## Impact

The existing proposal-review escalation and response path in `orchestration_coordinator.py`, the current human-gate payload/projection and its Trabajo actual response UI, plus focused tests for directive composition, selection, and native Propose continuation. The existing continuity contract remains responsible for recording and replaying the accepted response. No new endpoint, provider, workflow, retry policy, review bypass, or durable task-state model is introduced.
